"""
Comprehensive stability test suite for ByteCLI.

Covers unit tests for all core managers, state machine, i18n, PID management,
model switcher, recording FSM, and corner cases.  All heavy dependencies
(Whisper, PyTorch, GTK, D-Bus) are mocked so these tests run on any machine
with Python 3.10+ and pytest.

Run:
    python -m pytest tests/test_stability.py -v
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import uuid
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Ensure the package is importable without GTK / D-Bus / Whisper installed.
# We mock the gi module at the top level for tests that import GTK-dependent
# code indirectly.
# ---------------------------------------------------------------------------

# ===================================================================
# 1. ConfigManager tests
# ===================================================================

from bytecli.service.config_manager import ConfigManager
from bytecli.constants import DEFAULT_CONFIG, WHISPER_MODELS


class TestConfigManager:
    """Unit tests for ConfigManager load / save / validate cycle."""

    def _make_manager(self, tmp_path: str) -> ConfigManager:
        config_file = os.path.join(tmp_path, "config.json")
        return ConfigManager(config_file=config_file)

    def test_load_creates_default_when_missing(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        config = mgr.load()
        assert config["model"] == DEFAULT_CONFIG["model"]
        assert config["device"] == DEFAULT_CONFIG["device"]
        assert os.path.isfile(mgr.config_file)

    def test_save_and_reload(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        custom = copy.deepcopy(DEFAULT_CONFIG)
        custom["model"] = "tiny"
        custom["language"] = "zh"
        mgr.save(custom)

        mgr2 = self._make_manager(str(tmp_path))
        reloaded = mgr2.load()
        assert reloaded["model"] == "tiny"
        assert reloaded["language"] == "zh"

    def test_corrupt_file_recovery(self, tmp_path):
        config_file = os.path.join(str(tmp_path), "config.json")
        with open(config_file, "w") as f:
            f.write("NOT VALID JSON {{{")

        mgr = ConfigManager(config_file=config_file)
        config = mgr.load()
        # Should fall back to defaults.
        assert config["model"] == DEFAULT_CONFIG["model"]
        # Backup should exist.
        assert os.path.isfile(config_file + ".bak")

    def test_validate_valid_config(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        errors = mgr.validate(copy.deepcopy(DEFAULT_CONFIG))
        assert errors == []

    def test_validate_invalid_model(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["model"] = "nonexistent"
        errors = mgr.validate(bad)
        assert "model" in errors

    def test_validate_invalid_device(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["device"] = "tpu"
        errors = mgr.validate(bad)
        assert "device" in errors

    def test_validate_invalid_language(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["language"] = "fr"
        errors = mgr.validate(bad)
        assert "language" in errors

    def test_validate_invalid_auto_start(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["auto_start"] = "yes"
        errors = mgr.validate(bad)
        assert "auto_start" in errors

    def test_validate_invalid_hotkey(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["hotkey"] = {"keys": ["A"]}  # Too few keys
        errors = mgr.validate(bad)
        assert "hotkey.keys" in errors

    def test_validate_history_max_entries_boundary(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)

        bad["history_max_entries"] = 0
        errors = mgr.validate(bad)
        assert "history_max_entries" in errors

        bad["history_max_entries"] = 501
        errors = mgr.validate(bad)
        assert "history_max_entries" in errors

        bad["history_max_entries"] = 1
        errors = mgr.validate(bad)
        assert "history_max_entries" not in errors

        bad["history_max_entries"] = 500
        errors = mgr.validate(bad)
        assert "history_max_entries" not in errors

    def test_validate_empty_audio_input(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["audio_input"] = ""
        errors = mgr.validate(bad)
        assert "audio_input" in errors

    def test_atomic_write_survives_read(self, tmp_path):
        """Verify that the file written is valid JSON after save."""
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.save(DEFAULT_CONFIG)

        with open(mgr.config_file, "r") as f:
            data = json.load(f)
        assert data["model"] == DEFAULT_CONFIG["model"]

    def test_load_merges_new_keys(self, tmp_path):
        """Config file missing a key should get the default value."""
        config_file = os.path.join(str(tmp_path), "config.json")
        partial = {"model": "tiny", "device": "cpu", "audio_input": "auto",
                    "hotkey": {"keys": ["Ctrl", "Alt", "V"]},
                    "language": "en", "auto_start": False}
        # Missing: history_max_entries
        with open(config_file, "w") as f:
            json.dump(partial, f)

        mgr = ConfigManager(config_file=config_file)
        config = mgr.load()
        assert "history_max_entries" in config
        assert config["history_max_entries"] == DEFAULT_CONFIG["history_max_entries"]

    def test_get_default_config_returns_deep_copy(self):
        c1 = ConfigManager.get_default_config()
        c2 = ConfigManager.get_default_config()
        c1["model"] = "medium"
        assert c2["model"] == DEFAULT_CONFIG["model"]


# ===================================================================
# 2. HistoryManager tests
# ===================================================================

from bytecli.service.history_manager import HistoryManager


class TestHistoryManager:
    """Unit tests for HistoryManager add/get/persist cycle."""

    def _make_manager(self, tmp_path: str, max_entries: int = 50) -> HistoryManager:
        history_file = os.path.join(tmp_path, "history.json")
        return HistoryManager(history_file=history_file, max_entries=max_entries)

    def test_add_and_get(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.add("hello world", "tiny", 1500)
        entries = mgr.get_recent(10)
        assert len(entries) == 1
        assert entries[0]["text"] == "hello world"
        assert entries[0]["model"] == "tiny"
        assert entries[0]["duration_ms"] == 1500

    def test_fifo_eviction(self, tmp_path):
        mgr = self._make_manager(str(tmp_path), max_entries=3)
        mgr.load()
        for i in range(5):
            mgr.add(f"entry_{i}", "small", 100)
        entries = mgr.entries
        assert len(entries) == 3
        # Oldest entries should be evicted.
        texts = [e["text"] for e in entries]
        assert "entry_0" not in texts
        assert "entry_1" not in texts
        assert "entry_4" in texts

    def test_persist_and_reload(self, tmp_path):
        path = str(tmp_path)
        mgr = self._make_manager(path)
        mgr.load()
        mgr.add("test1", "small", 200)
        mgr.add("test2", "medium", 300)

        mgr2 = self._make_manager(path)
        mgr2.load()
        assert len(mgr2.entries) == 2

    def test_corrupt_file_recovery(self, tmp_path):
        history_file = os.path.join(str(tmp_path), "history.json")
        with open(history_file, "w") as f:
            f.write("CORRUPT DATA!!!")

        mgr = HistoryManager(history_file=history_file)
        mgr.load()
        assert len(mgr.entries) == 0
        assert os.path.isfile(history_file + ".bak")

    def test_empty_history(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        assert mgr.entries == []
        assert mgr.get_recent(5) == []
        assert mgr.get_all() == []

    def test_get_all_format(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.add("hello", "tiny", 100)
        result = mgr.get_all()
        assert len(result) == 1
        text, timestamp, entry_id = result[0]
        assert text == "hello"
        assert isinstance(timestamp, str)
        assert isinstance(entry_id, str)

    def test_get_recent_order(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.add("first", "tiny", 100)
        mgr.add("second", "tiny", 100)
        mgr.add("third", "tiny", 100)
        recent = mgr.get_recent(2)
        assert len(recent) == 2
        assert recent[0]["text"] == "third"  # newest first
        assert recent[1]["text"] == "second"

    def test_max_entries_setter(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.max_entries = 0
        assert mgr.max_entries == 1  # Clamped to minimum
        mgr.max_entries = 999
        assert mgr.max_entries == 500  # Clamped to maximum
        mgr.max_entries = 100
        assert mgr.max_entries == 100

    def test_entries_returns_deep_copy(self, tmp_path):
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.add("test", "tiny", 100)
        entries = mgr.entries
        entries[0]["text"] = "MODIFIED"
        assert mgr.entries[0]["text"] == "test"

    def test_atomic_write(self, tmp_path):
        """Verify the history file is valid JSON after persist."""
        mgr = self._make_manager(str(tmp_path))
        mgr.load()
        mgr.add("test", "tiny", 100)

        history_file = os.path.join(str(tmp_path), "history.json")
        with open(history_file, "r") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1


# ===================================================================
# 3. ServiceStateMachine tests
# ===================================================================

from bytecli.service.state_machine import (
    ServiceStateMachine,
    ServiceState,
    ServiceEvent,
)


class TestServiceStateMachine:
    """Unit tests for the service lifecycle state machine."""

    def test_initial_state(self):
        sm = ServiceStateMachine()
        assert sm.state is ServiceState.STOPPED

    def test_valid_start_sequence(self):
        sm = ServiceStateMachine()
        assert sm.dispatch(ServiceEvent.EVT_START) is True
        assert sm.state is ServiceState.STARTING
        assert sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS) is True
        assert sm.state is ServiceState.RUNNING

    def test_stop_sequence(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        assert sm.dispatch(ServiceEvent.EVT_STOP) is True
        assert sm.state is ServiceState.STOPPING
        assert sm.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE) is True
        assert sm.state is ServiceState.STOPPED

    def test_restart_sequence(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        assert sm.dispatch(ServiceEvent.EVT_RESTART) is True
        assert sm.state is ServiceState.RESTARTING
        assert sm.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE) is True
        assert sm.state is ServiceState.STARTING

    def test_init_fail_goes_to_failed(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        assert sm.dispatch(ServiceEvent.EVT_INIT_FAIL) is True
        assert sm.state is ServiceState.FAILED

    def test_crash_from_running(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        assert sm.dispatch(ServiceEvent.EVT_CRASH) is True
        assert sm.state is ServiceState.FAILED

    def test_restart_from_failed(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_FAIL)
        assert sm.state is ServiceState.FAILED
        assert sm.dispatch(ServiceEvent.EVT_RESTART) is True
        assert sm.state is ServiceState.RESTARTING

    def test_illegal_transition_returns_false(self):
        sm = ServiceStateMachine()
        # Cannot stop from STOPPED.
        assert sm.dispatch(ServiceEvent.EVT_STOP) is False
        assert sm.state is ServiceState.STOPPED

    def test_illegal_transition_preserves_state(self):
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        # Cannot start from RUNNING.
        assert sm.dispatch(ServiceEvent.EVT_START) is False
        assert sm.state is ServiceState.RUNNING

    def test_callback_fires_on_transition(self):
        records = []
        sm = ServiceStateMachine(
            on_state_change=lambda old, new: records.append((old, new))
        )
        sm.dispatch(ServiceEvent.EVT_START)
        assert len(records) == 1
        assert records[0] == (ServiceState.STOPPED, ServiceState.STARTING)

    def test_callback_error_does_not_corrupt_state(self):
        def bad_callback(old, new):
            raise ValueError("boom")

        sm = ServiceStateMachine(on_state_change=bad_callback)
        sm.dispatch(ServiceEvent.EVT_START)
        assert sm.state is ServiceState.STARTING

    def test_all_transitions_from_table(self):
        """Verify every defined transition works."""
        from bytecli.service.state_machine import _TRANSITIONS

        for (start_state, event), end_state in _TRANSITIONS.items():
            sm = ServiceStateMachine()
            sm._state = start_state
            result = sm.dispatch(event)
            assert result is True, f"{start_state} + {event} should be valid"
            assert sm.state is end_state


# ===================================================================
# 4. I18nManager tests
# ===================================================================

from bytecli.i18n.manager import I18nManager


class TestI18nManager:
    """Unit tests for the I18n translation manager."""

    def test_default_language_is_english(self):
        mgr = I18nManager()
        assert mgr.current_language == "en"

    def test_missing_key_returns_fallback(self):
        mgr = I18nManager()
        result = mgr.t("nonexistent.key", fallback="My Fallback")
        assert result == "My Fallback"

    def test_missing_key_returns_key_when_no_fallback(self):
        mgr = I18nManager()
        result = mgr.t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_variable_interpolation(self):
        mgr = I18nManager()
        # Manually set a string with interpolation.
        mgr._strings["test.hello"] = "Hello {name}!"
        result = mgr.t("test.hello", name="World")
        assert result == "Hello World!"

    def test_missing_interpolation_variable(self):
        mgr = I18nManager()
        mgr._strings["test.key"] = "Hello {missing_var}!"
        result = mgr.t("test.key")
        # Should return the template without crashing.
        assert result == "Hello {missing_var}!"

    def test_switch_language(self):
        mgr = I18nManager()
        mgr.switch("zh")
        assert mgr.current_language == "zh"

    def test_switch_to_same_language_is_noop(self):
        mgr = I18nManager()
        callback = MagicMock()
        mgr.on_language_changed(callback)
        mgr.switch("en")  # Already en
        callback.assert_not_called()

    def test_language_change_callback(self):
        mgr = I18nManager()
        callback = MagicMock()
        mgr.on_language_changed(callback)
        mgr.switch("zh")
        callback.assert_called_once_with("zh")

    def test_remove_callback(self):
        mgr = I18nManager()
        callback = MagicMock()
        mgr.on_language_changed(callback)
        mgr.remove_language_changed(callback)
        mgr.switch("zh")
        callback.assert_not_called()

    def test_remove_nonexistent_callback(self):
        mgr = I18nManager()
        mgr.remove_language_changed(lambda x: None)  # Should not raise.

    def test_unsupported_language_falls_back(self):
        mgr = I18nManager()
        mgr.load("fr")  # Not supported
        assert mgr.current_language == "en"

    def test_corrupt_locale_file(self, tmp_path):
        mgr = I18nManager()
        # Temporarily override the locale dir.
        import bytecli.i18n.manager as m
        old_dir = m._LOCALE_DIR
        m._LOCALE_DIR = str(tmp_path)

        corrupt_file = os.path.join(str(tmp_path), "en.json")
        with open(corrupt_file, "w") as f:
            f.write("NOT JSON")

        mgr.load("en")
        # Should have empty strings but not crash.
        m._LOCALE_DIR = old_dir

    def test_duplicate_callback_registration(self):
        mgr = I18nManager()
        callback = MagicMock()
        mgr.on_language_changed(callback)
        mgr.on_language_changed(callback)  # Duplicate
        mgr.switch("zh")
        # Should only be called once.
        callback.assert_called_once()

    def test_callback_error_does_not_prevent_others(self):
        mgr = I18nManager()

        def bad_callback(lang):
            raise RuntimeError("boom")

        good_callback = MagicMock()
        mgr.on_language_changed(bad_callback)
        mgr.on_language_changed(good_callback)
        mgr.switch("zh")
        good_callback.assert_called_once_with("zh")


# ===================================================================
# 5. PidManager tests
# ===================================================================

from bytecli.service.pid_manager import PidManager


class TestPidManager:
    """Unit tests for PID file management."""

    def test_write_and_check(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        PidManager.check_and_write(pid_file)
        assert os.path.isfile(pid_file)
        with open(pid_file) as f:
            assert int(f.read().strip()) == os.getpid()

    def test_cleanup_removes_own_pid(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
        PidManager.cleanup(pid_file)
        assert not os.path.isfile(pid_file)

    def test_cleanup_preserves_other_pid(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        with open(pid_file, "w") as f:
            f.write("99999999")  # Very unlikely to be a real PID
        PidManager.cleanup(pid_file)
        assert os.path.isfile(pid_file)

    def test_stale_pid_detected(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        with open(pid_file, "w") as f:
            f.write("99999999")  # Dead PID
        # Should not raise (stale PID should be cleaned).
        PidManager.check_and_write(pid_file)

    def test_is_running_no_file(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "nonexistent.pid")
        assert PidManager.is_running(pid_file) is False

    def test_is_running_corrupt_file(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        with open(pid_file, "w") as f:
            f.write("not_a_number")
        assert PidManager.is_running(pid_file) is False

    def test_own_pid_not_considered_running(self, tmp_path):
        """os.execv restart scenario: same PID should not block."""
        pid_file = os.path.join(str(tmp_path), "test.pid")
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
        assert PidManager.is_running(pid_file) is False

    def test_double_check_and_write_same_process(self, tmp_path):
        pid_file = os.path.join(str(tmp_path), "test.pid")
        PidManager.check_and_write(pid_file)
        # Same PID should be allowed (self-restart scenario).
        PidManager.check_and_write(pid_file)


# ===================================================================
# 6. ModelSwitcher tests
# ===================================================================

from bytecli.service.model_switcher import ModelSwitcher, ModelSwitchState


class TestModelSwitcher:
    """Unit tests for the async model switcher."""

    def _make_engine_mock(self):
        engine = MagicMock()
        engine.current_model = "small"
        engine.current_device = "cpu"
        engine.load_model = MagicMock()
        engine.unload_model = MagicMock()
        return engine

    def test_switch_model_success(self):
        engine = self._make_engine_mock()
        switcher = ModelSwitcher(engine)
        results = []

        def callback(state, msg):
            results.append((state, msg))

        assert switcher.switch_model("tiny", callback) is True

        # Wait for the background thread to finish.
        time.sleep(0.5)

        assert switcher.state is ModelSwitchState.IDLE
        states = [r[0] for r in results]
        assert "switching" in states
        assert "success" in states

    def test_switch_model_debounce(self):
        engine = self._make_engine_mock()
        # Make load_model block so the first switch is still in progress.
        engine.load_model = MagicMock(side_effect=lambda *a: time.sleep(1))
        switcher = ModelSwitcher(engine)
        callback = MagicMock()

        assert switcher.switch_model("tiny", callback) is True
        assert switcher.switch_model("medium", callback) is False

        # Wait for the first to finish.
        time.sleep(1.5)

    def test_switch_model_failure_and_rollback(self):
        engine = self._make_engine_mock()
        engine.unload_model = MagicMock()
        call_count = [0]

        def load_side_effect(model, device):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("CUDA OOM")
            # Rollback load succeeds.

        engine.load_model = MagicMock(side_effect=load_side_effect)
        switcher = ModelSwitcher(engine)
        results = []

        def callback(state, msg):
            results.append((state, msg))

        switcher.switch_model("medium", callback)
        time.sleep(0.5)

        assert switcher.state is ModelSwitchState.IDLE
        states = [r[0] for r in results]
        assert "failed" in states

    def test_switch_device_success(self):
        engine = self._make_engine_mock()
        switcher = ModelSwitcher(engine)
        results = []

        def callback(state, msg):
            results.append((state, msg))

        assert switcher.switch_device("gpu", callback) is True
        time.sleep(0.5)

        states = [r[0] for r in results]
        assert "success" in states

    def test_double_finish_guard(self):
        """Timeout + worker race: both call _finish, should not double-fire."""
        engine = self._make_engine_mock()
        # Make load_model slow enough that we can test the guard.
        engine.load_model = MagicMock(side_effect=lambda *a: time.sleep(0.2))
        switcher = ModelSwitcher(engine)
        results = []

        def callback(state, msg):
            results.append((state, msg))

        switcher.switch_model("tiny", callback)

        # Manually call _finish to simulate a timeout racing with the worker.
        time.sleep(0.1)
        switcher._finish(callback, "failed", "timeout")

        time.sleep(0.5)

        # The worker's _finish should see IDLE and return early.
        # Only switching + failed should be in results (no double success).
        final_states = [r[0] for r in results if r[0] != "switching"]
        assert len(final_states) == 1  # Either failed or success, not both.


# ===================================================================
# 7. RecordingFSM tests
# ===================================================================

from bytecli.service.recording_fsm import RecordingFSM, RecordingState


class TestRecordingFSM:
    """Unit tests for the recording finite state machine."""

    def _make_fsm(self):
        audio = MagicMock()
        engine = MagicMock()
        history = MagicMock()
        sig_started = MagicMock()
        sig_stopped = MagicMock()
        config_mgr = MagicMock()
        config_mgr.config = {"audio_input": "auto"}

        # Make stop_recording return a numpy-like array.
        import numpy as np
        audio.stop_recording.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        audio.start_recording.return_value = None

        engine.transcribe.return_value = "hello world"
        engine.current_model = "small"

        fsm = RecordingFSM(
            audio_manager=audio,
            whisper_engine=engine,
            history_manager=history,
            dbus_recording_started_signal=sig_started,
            dbus_recording_stopped_signal=sig_stopped,
            config_manager=config_mgr,
        )
        return fsm, audio, engine, history, sig_started, sig_stopped

    def test_initial_state(self):
        fsm, *_ = self._make_fsm()
        assert fsm.state is RecordingState.IDLE

    def test_toggle_starts_recording(self):
        fsm, audio, *_ = self._make_fsm()
        fsm.on_hotkey_toggle()
        assert fsm.state is RecordingState.RECORDING
        audio.start_recording.assert_called_once()

    def test_toggle_during_recording_stops_and_transcribes(self):
        fsm, audio, engine, *_ = self._make_fsm()
        fsm.on_hotkey_toggle()  # Start
        assert fsm.state is RecordingState.RECORDING

        # Wait slightly longer than MIN_RECORDING_DURATION.
        time.sleep(0.4)
        fsm.on_hotkey_toggle()  # Stop

        # Should be TRANSCRIBING (submitted to thread pool).
        assert fsm.state is RecordingState.TRANSCRIBING

    def test_short_press_discarded(self):
        fsm, audio, engine, *_ = self._make_fsm()
        fsm.on_hotkey_toggle()  # Start
        # Immediately toggle (< 0.3s).
        fsm.on_hotkey_toggle()  # Stop
        # Should go back to IDLE (too short).
        assert fsm.state is RecordingState.IDLE

    def test_toggle_during_transcribing_ignored(self):
        fsm, *_ = self._make_fsm()
        fsm._state = RecordingState.TRANSCRIBING
        fsm.on_hotkey_toggle()
        assert fsm.state is RecordingState.TRANSCRIBING

    def test_start_recording_failure(self):
        fsm, audio, *_ = self._make_fsm()
        audio.start_recording.side_effect = RuntimeError("No device")
        fsm.on_hotkey_toggle()
        assert fsm.state is RecordingState.IDLE

    def test_empty_audio_buffer(self):
        import numpy as np
        fsm, audio, engine, history, _, sig_stopped = self._make_fsm()
        audio.stop_recording.return_value = np.array([], dtype=np.float32)

        fsm.on_hotkey_toggle()  # Start
        time.sleep(0.4)
        fsm.on_hotkey_toggle()  # Stop

        assert fsm.state is RecordingState.IDLE
        sig_stopped.assert_called_once_with("")

    def test_shutdown(self):
        fsm, *_ = self._make_fsm()
        fsm.shutdown()
        # Should not raise.

    def test_recording_started_signal_failure(self):
        fsm, audio, engine, history, sig_started, sig_stopped = self._make_fsm()
        sig_started.side_effect = RuntimeError("D-Bus error")
        # Should not crash.
        fsm.on_hotkey_toggle()
        assert fsm.state is RecordingState.RECORDING


# ===================================================================
# 8. WhisperEngine tests (mocked)
# ===================================================================

class TestWhisperEngine:
    """Unit tests for WhisperEngine lifecycle (Whisper/torch mocked)."""

    def test_initial_state(self):
        from bytecli.service.whisper_engine import WhisperEngine
        engine = WhisperEngine()
        assert engine.is_loaded is False
        assert engine.current_model is None
        assert engine.current_device is None

    def test_transcribe_without_model_raises(self):
        from bytecli.service.whisper_engine import WhisperEngine
        import numpy as np
        engine = WhisperEngine()
        with pytest.raises(RuntimeError, match="No Whisper model"):
            engine.transcribe(np.zeros(16000, dtype=np.float32))

    def test_unload_when_not_loaded(self):
        from bytecli.service.whisper_engine import WhisperEngine
        engine = WhisperEngine()
        engine.unload_model()  # Should not raise.

    def test_load_and_unload(self):
        from bytecli.service.whisper_engine import WhisperEngine
        mock_whisper = MagicMock()
        mock_model = MagicMock()
        mock_whisper.load_model.return_value = mock_model

        import sys
        sys.modules["whisper"] = mock_whisper
        try:
            engine = WhisperEngine()
            engine.load_model("tiny", "cpu")
            assert engine.is_loaded is True
            assert engine.current_model == "tiny"
            assert engine.current_device == "cpu"

            engine.unload_model()
            assert engine.is_loaded is False
            assert engine.current_model is None
        finally:
            del sys.modules["whisper"]

    def test_load_model_failure(self):
        from bytecli.service.whisper_engine import WhisperEngine
        mock_whisper = MagicMock()
        mock_whisper.load_model.side_effect = Exception("download failed")

        engine = WhisperEngine()
        import sys
        sys.modules["whisper"] = mock_whisper
        try:
            with pytest.raises(RuntimeError, match="Failed to load"):
                engine.load_model("tiny", "cpu")
        finally:
            del sys.modules["whisper"]

    def test_collapse_repeats(self):
        from bytecli.service.whisper_engine import _collapse_repeats
        assert _collapse_repeats("我我我我我我我我") == "我我我"
        assert _collapse_repeats("hello") == "hello"
        assert _collapse_repeats("") == ""
        assert _collapse_repeats("aaa") == "aaa"  # Exactly 3 is OK
        assert _collapse_repeats("aaaa") == "aaa"  # 4 collapses to 3


# ===================================================================
# 9. D-Bus service input validation tests
# ===================================================================

class TestDBusServiceValidation:
    """Test that D-Bus SwitchModel/SwitchDevice validate inputs."""

    def _make_service(self):
        bus_name = MagicMock()
        config = MagicMock()
        state = MagicMock()
        engine = MagicMock()
        audio = MagicMock()
        hotkey = MagicMock()
        history = MagicMock()
        switcher = MagicMock()
        switcher.switch_model.return_value = True
        switcher.switch_device.return_value = True

        # We need to mock dbus.service.Object to avoid needing a real bus.
        with patch("dbus.service.Object.__init__", return_value=None):
            from bytecli.service.dbus_service import ByteCLIDBusService
            svc = ByteCLIDBusService(
                bus_name=bus_name,
                config_manager=config,
                state_machine=state,
                whisper_engine=engine,
                audio_manager=audio,
                hotkey_manager=hotkey,
                history_manager=history,
                model_switcher=switcher,
            )
        return svc, switcher

    def test_switch_model_valid(self):
        svc, switcher = self._make_service()
        result = svc.SwitchModel("tiny")
        assert result is True
        switcher.switch_model.assert_called_once()

    def test_switch_model_invalid(self):
        svc, switcher = self._make_service()
        result = svc.SwitchModel("huge")
        assert result is False
        switcher.switch_model.assert_not_called()

    def test_switch_device_valid_gpu(self):
        svc, switcher = self._make_service()
        result = svc.SwitchDevice("gpu")
        assert result is True

    def test_switch_device_valid_cpu(self):
        svc, switcher = self._make_service()
        result = svc.SwitchDevice("cpu")
        assert result is True

    def test_switch_device_invalid(self):
        svc, switcher = self._make_service()
        result = svc.SwitchDevice("tpu")
        assert result is False
        switcher.switch_device.assert_not_called()


# ===================================================================
# 10. Corner case tests
# ===================================================================

class TestCornerCases:
    """Tests for edge cases and error scenarios."""

    def test_concurrent_model_switches(self):
        """Fire 3 switches simultaneously — only the first should proceed."""
        engine = MagicMock()
        engine.current_model = "small"
        engine.current_device = "cpu"
        engine.load_model = MagicMock(side_effect=lambda *a: time.sleep(0.5))
        engine.unload_model = MagicMock()

        switcher = ModelSwitcher(engine)
        callback = MagicMock()

        results = []
        results.append(switcher.switch_model("tiny", callback))
        results.append(switcher.switch_model("medium", callback))
        results.append(switcher.switch_model("small", callback))

        assert results[0] is True
        assert results[1] is False
        assert results[2] is False

        time.sleep(1.0)

    def test_config_file_deleted_mid_run(self, tmp_path):
        """Deleting the config file should not crash -- re-save works."""
        config_file = os.path.join(str(tmp_path), "config.json")
        mgr = ConfigManager(config_file=config_file)
        mgr.load()

        # Delete the file.
        os.unlink(config_file)
        assert not os.path.isfile(config_file)

        # Save should recreate it.
        mgr.save(DEFAULT_CONFIG)
        assert os.path.isfile(config_file)

    def test_history_corruption_recovery(self, tmp_path):
        """Corrupt history file should be backed up and cleared."""
        history_file = os.path.join(str(tmp_path), "history.json")

        # Write some valid entries first.
        mgr = HistoryManager(history_file=history_file)
        mgr.load()
        mgr.add("test1", "tiny", 100)
        mgr.add("test2", "small", 200)
        assert len(mgr.entries) == 2

        # Corrupt the file.
        with open(history_file, "w") as f:
            f.write("CORRUPTED!!!!")

        # Reload — should detect corruption and reset.
        mgr2 = HistoryManager(history_file=history_file)
        mgr2.load()
        assert len(mgr2.entries) == 0
        assert os.path.isfile(history_file + ".bak")

    def test_rapid_fsm_toggles(self):
        """10 rapid toggles should not crash the FSM."""
        audio = MagicMock()
        engine = MagicMock()
        history = MagicMock()
        sig_started = MagicMock()
        sig_stopped = MagicMock()
        config_mgr = MagicMock()
        config_mgr.config = {"audio_input": "auto"}

        import numpy as np
        audio.stop_recording.return_value = np.zeros(100, dtype=np.float32)
        engine.transcribe.return_value = "test"
        engine.current_model = "small"

        fsm = RecordingFSM(
            audio_manager=audio,
            whisper_engine=engine,
            history_manager=history,
            dbus_recording_started_signal=sig_started,
            dbus_recording_stopped_signal=sig_stopped,
            config_manager=config_mgr,
        )

        for _ in range(10):
            fsm.on_hotkey_toggle()

        # Should still be in a valid state.
        assert fsm.state in (
            RecordingState.IDLE,
            RecordingState.RECORDING,
            RecordingState.TRANSCRIBING,
        )
        fsm.shutdown()

    def test_state_machine_full_cycle(self):
        """Run through STOPPED->STARTING->RUNNING->STOPPING->STOPPED."""
        sm = ServiceStateMachine()
        assert sm.state is ServiceState.STOPPED

        sm.dispatch(ServiceEvent.EVT_START)
        assert sm.state is ServiceState.STARTING

        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        assert sm.state is ServiceState.RUNNING

        sm.dispatch(ServiceEvent.EVT_STOP)
        assert sm.state is ServiceState.STOPPING

        sm.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE)
        assert sm.state is ServiceState.STOPPED

    def test_state_machine_crash_restart_cycle(self):
        """RUNNING -> FAILED -> RESTARTING -> STARTING."""
        sm = ServiceStateMachine()
        sm.dispatch(ServiceEvent.EVT_START)
        sm.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        sm.dispatch(ServiceEvent.EVT_CRASH)
        assert sm.state is ServiceState.FAILED

        sm.dispatch(ServiceEvent.EVT_RESTART)
        assert sm.state is ServiceState.RESTARTING

        sm.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE)
        assert sm.state is ServiceState.STARTING

    def test_config_validation_all_wrong_types(self, tmp_path):
        """Every field with a wrong type should be caught."""
        mgr = ConfigManager(config_file=os.path.join(str(tmp_path), "c.json"))
        bad = {
            "model": 123,
            "device": None,
            "audio_input": 0,
            "hotkey": "not a dict",
            "language": True,
            "auto_start": "yes",
            "history_max_entries": "fifty",
        }
        errors = mgr.validate(bad)
        assert len(errors) >= 6  # All fields should be invalid

    def test_i18n_fallback_parameter(self):
        """Verify that fallback= is properly used by i18n.t()."""
        from bytecli.i18n import i18n
        # Use a key that definitely doesn't exist.
        result = i18n.t("this.key.absolutely.does.not.exist", fallback="Fallback Text")
        assert result == "Fallback Text"

    def test_history_add_preserves_entry_fields(self, tmp_path):
        """Each history entry should have id, text, timestamp, model, duration_ms."""
        mgr = HistoryManager(
            history_file=os.path.join(str(tmp_path), "h.json"),
            max_entries=10,
        )
        mgr.load()
        mgr.add("test text", "medium", 5000)

        entry = mgr.entries[0]
        assert "id" in entry
        assert "text" in entry
        assert "timestamp" in entry
        assert "model" in entry
        assert "duration_ms" in entry
        # Validate UUID format.
        uuid.UUID(entry["id"])  # Should not raise.

    def test_model_switcher_rollback_on_load_failure(self):
        """If the new model fails to load, rollback should reload the old one."""
        engine = MagicMock()
        engine.current_model = "small"
        engine.current_device = "cpu"
        call_count = [0]

        def load_side_effect(model, device):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("load failed")

        engine.load_model = MagicMock(side_effect=load_side_effect)
        switcher = ModelSwitcher(engine)
        results = []

        switcher.switch_model("tiny", lambda s, m: results.append(s))
        time.sleep(0.5)

        # Should have attempted rollback (2 load_model calls: new + rollback).
        assert engine.load_model.call_count == 2
        # Rollback call should be with the old model.
        rollback_call = engine.load_model.call_args_list[1]
        assert rollback_call[0] == ("small", "cpu")

    def test_pid_file_permissions(self, tmp_path):
        """PID file should be writable by current user."""
        pid_file = os.path.join(str(tmp_path), "test.pid")
        PidManager.check_and_write(pid_file)
        assert os.access(pid_file, os.R_OK | os.W_OK)
