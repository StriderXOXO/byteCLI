"""
Whisper speech-recognition engine wrapper.

Loads / unloads OpenAI Whisper models and performs thread-safe transcription
of 16 kHz float32 numpy audio arrays.  Supports progress-reporting during
first-run model downloads.
"""

from __future__ import annotations

import gc
import hashlib
import logging
import os
import threading
import urllib.request
from typing import Callable, Optional

import numpy as np

from bytecli.constants import MODEL_DIR, WHISPER_MODELS

logger = logging.getLogger(__name__)

# Whisper model download URLs (from openai/whisper source).
_WHISPER_MODEL_URLS: dict[str, str] = {
    "tiny": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
    "base": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
    "small": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
    "medium": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
}

# Expected SHA256 hashes (from openai/whisper source).
_WHISPER_MODEL_HASHES: dict[str, str] = {
    "tiny": "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
    "base": "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
    "small": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
    "medium": "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1",
}


class WhisperEngine:
    """Manages the lifecycle of an OpenAI Whisper model instance."""

    def __init__(self) -> None:
        self._model = None
        self._current_model: Optional[str] = None
        self._current_device: Optional[str] = None
        self._lock = threading.Lock()
        self._loading = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def current_model(self) -> Optional[str]:
        return self._current_model

    @property
    def current_device(self) -> Optional[str]:
        return self._current_device

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self, model_name: str, device: str = "cpu") -> None:
        """Load a Whisper model onto *device*.

        Parameters
        ----------
        model_name:
            One of ``"tiny"``, ``"small"``, ``"medium"``.
        device:
            ``"cpu"`` or ``"cuda"`` / ``"gpu"``.

        Raises
        ------
        RuntimeError
            If the model cannot be loaded (OOM, missing files, etc.).
        """
        import os
        os.makedirs(MODEL_DIR, exist_ok=True)

        # Normalise the device identifier for PyTorch.
        torch_device = "cuda" if device == "gpu" else device

        logger.info(
            "Loading Whisper model '%s' on device '%s' ...",
            model_name,
            torch_device,
        )

        try:
            import whisper  # type: ignore[import-untyped]

            model = whisper.load_model(
                model_name,
                device=torch_device,
                download_root=MODEL_DIR,
            )
        except torch_cuda_oom_error():
            logger.error(
                "Out of GPU memory while loading model '%s'. "
                "Try a smaller model or switch to CPU.",
                model_name,
            )
            raise RuntimeError(
                f"GPU out of memory loading model '{model_name}'."
            )
        except FileNotFoundError as exc:
            logger.error("Model file not found: %s", exc)
            raise RuntimeError(f"Model file not found: {exc}") from exc
        except Exception as exc:
            logger.error("Failed to load model '%s': %s", model_name, exc)
            raise RuntimeError(
                f"Failed to load model '{model_name}': {exc}"
            ) from exc

        self._model = model
        self._current_model = model_name
        self._current_device = device
        logger.info("Model '%s' loaded successfully on '%s'.", model_name, device)

    def _model_file_exists(self, model_name: str) -> bool:
        """Check if the model file is already downloaded."""
        model_path = os.path.join(MODEL_DIR, f"{model_name}.pt")
        return os.path.isfile(model_path)

    def _download_model_file(
        self,
        model_name: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """Pre-download the model file with progress reporting.

        Parameters
        ----------
        model_name:
            One of ``"tiny"``, ``"small"``, ``"medium"``.
        progress_callback:
            Called with (percent: int, message: str) during download.
        """
        if model_name not in _WHISPER_MODEL_URLS:
            return  # Unknown model — let whisper.load_model handle it.

        model_path = os.path.join(MODEL_DIR, f"{model_name}.pt")
        if os.path.isfile(model_path):
            logger.debug("Model file already exists: %s", model_path)
            return

        os.makedirs(MODEL_DIR, exist_ok=True)

        url = _WHISPER_MODEL_URLS[model_name]
        model_info = WHISPER_MODELS.get(model_name, {})
        size_str = model_info.get("size", "unknown size")

        if progress_callback:
            progress_callback(0, f"Downloading {model_name} model ({size_str})...")

        logger.info("Downloading model '%s' from %s ...", model_name, url)

        tmp_path = model_path + ".part"
        try:
            response = urllib.request.urlopen(url)
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MB chunks

            sha256 = hashlib.sha256()

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
                    downloaded += len(chunk)

                    if total_size > 0 and progress_callback:
                        percent = min(int(downloaded * 100 / total_size), 99)
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        progress_callback(
                            percent,
                            f"Downloading... {mb_done:.0f}/{mb_total:.0f} MB",
                        )

            # Verify hash if available.
            expected_hash = _WHISPER_MODEL_HASHES.get(model_name)
            if expected_hash and sha256.hexdigest() != expected_hash:
                os.remove(tmp_path)
                raise RuntimeError(
                    f"Model hash mismatch for '{model_name}'. "
                    "Download may be corrupted."
                )

            os.rename(tmp_path, model_path)
            logger.info("Model '%s' downloaded to %s", model_name, model_path)

            if progress_callback:
                progress_callback(100, "Download complete. Loading model...")

        except Exception as exc:
            # Clean up partial download.
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            logger.error("Model download failed: %s", exc)
            raise

    def load_model_async(
        self,
        model_name: str,
        device: str = "cpu",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        done_callback: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """Load a Whisper model in a background thread with progress reporting.

        Parameters
        ----------
        model_name:
            One of ``"tiny"``, ``"small"``, ``"medium"``.
        device:
            ``"cpu"`` or ``"cuda"`` / ``"gpu"``.
        progress_callback:
            Called with (percent: int, message: str) during download/load.
        done_callback:
            Called with (success: bool, message: str) when loading finishes.
        """
        self._loading = True

        def _worker():
            try:
                # Step 1: Download model file with progress (if needed).
                needs_download = not self._model_file_exists(model_name)
                if needs_download:
                    self._download_model_file(model_name, progress_callback)
                elif progress_callback:
                    progress_callback(100, "Loading model...")

                # Step 2: Load the model (this is fast if already downloaded).
                self.load_model(model_name, device)

                self._loading = False
                if done_callback:
                    done_callback(True, "Model loaded successfully.")
            except Exception as exc:
                self._loading = False
                logger.error("Async model load failed: %s", exc)
                if done_callback:
                    done_callback(False, str(exc))

        thread = threading.Thread(target=_worker, daemon=True, name="model-loader")
        thread.start()

    def unload_model(self) -> None:
        """Release the current model and reclaim memory."""
        if self._model is None:
            return

        logger.info("Unloading model '%s' ...", self._current_model)
        del self._model
        self._model = None
        self._current_model = None
        self._current_device = None

        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.debug("Model unloaded and memory released.")

    def transcribe(self, audio_data_np: np.ndarray) -> str:
        """Transcribe a float32 16 kHz numpy array to text.

        Parameters
        ----------
        audio_data_np:
            1-D float32 numpy array at 16 kHz sample rate.

        Returns
        -------
        str
            Transcription text (empty string if no speech is detected).
        """
        if self._model is None:
            raise RuntimeError("No Whisper model is loaded.")

        with self._lock:
            duration_s = len(audio_data_np) / 16000.0
            logger.debug("Transcribing audio (%.2f s) ...", duration_s)

            use_fp16 = self._current_device != "cpu"

            # Do NOT set language= — keep it auto so mixed
            # Chinese/English input is transcribed correctly.
            # The initial_prompt stabilises the decoder and prevents
            # the CJK repetition hallucination bug.
            try:
                result = self._model.transcribe(
                    audio_data_np,
                    fp16=use_fp16,
                    initial_prompt=_INITIAL_PROMPT,
                    condition_on_previous_text=False,
                    compression_ratio_threshold=1.8,
                    no_speech_threshold=0.6,
                    temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                )
            except Exception as exc:
                logger.error("Transcription failed: %s", exc)
                raise RuntimeError(f"Transcription failed: {exc}") from exc

        text: str = result.get("text", "").strip()

        # Guard against residual repetition (e.g. "我我我我我").
        text = _collapse_repeats(text)

        logger.debug("Transcription result: %r", text)
        return text

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_cuda_available() -> bool:
        """Return ``True`` if a CUDA-capable GPU is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# Bilingual initial prompt – primes the Whisper decoder to expect mixed
# Chinese/English input and produce coherent text.  This is the primary
# defence against the CJK repetition hallucination bug while keeping
# language=auto so mixed-language speech works correctly.
# ---------------------------------------------------------------------------

_INITIAL_PROMPT = (
    "以下是普通话和英语的语音转录，可能包含中英文混合内容。"
    "This is a multilingual voice transcription that may contain "
    "both Chinese and English."
)


# ---------------------------------------------------------------------------
# Internal helper – match CUDA OOM errors across PyTorch versions.
# ---------------------------------------------------------------------------

def _collapse_repeats(text: str, max_repeat: int = 3) -> str:
    """Collapse runs of repeated characters or words.

    Chinese repetition bug produces strings like "我我我我我我".
    This collapses any character or word repeated more than *max_repeat*
    consecutive times down to *max_repeat* occurrences.
    """
    import re

    # Collapse repeated single characters (catches CJK repetition).
    text = re.sub(r"(.)\1{" + str(max_repeat) + r",}", r"\1" * max_repeat, text)

    # Collapse repeated words/tokens (e.g. "hello hello hello hello").
    text = re.sub(
        r"\b(\w+)(?:\s+\1){" + str(max_repeat) + r",}",
        lambda m: (m.group(1) + " ") * max_repeat + m.group(1),
        text,
    )

    return text.strip()


def torch_cuda_oom_error() -> type:
    """Return the CUDA OOM exception class, or a dummy that never matches."""
    try:
        import torch
        return torch.cuda.OutOfMemoryError
    except (ImportError, AttributeError):
        # PyTorch < 1.13 or not installed – return a class that will
        # never be raised so the ``except`` clause is a no-op.
        return type("_NeverRaised", (Exception,), {})
