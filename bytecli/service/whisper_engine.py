"""
Whisper speech-recognition engine wrapper.

Loads / unloads OpenAI Whisper models and performs thread-safe transcription
of 16 kHz float32 numpy audio arrays.
"""

from __future__ import annotations

import gc
import logging
import threading
from typing import Optional

import numpy as np

from bytecli.constants import MODEL_DIR

logger = logging.getLogger(__name__)


class WhisperEngine:
    """Manages the lifecycle of an OpenAI Whisper model instance."""

    def __init__(self) -> None:
        self._model = None
        self._current_model: Optional[str] = None
        self._current_device: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

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
