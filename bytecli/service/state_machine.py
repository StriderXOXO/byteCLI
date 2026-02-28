"""
Service lifecycle state machine.

Implements the state / event / transition table defined in PRD section 4.1.
Illegal transitions are silently ignored with a ``logging.warning`` message.
"""

from __future__ import annotations

import enum
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ServiceState(enum.Enum):
    """All possible states of the ByteCLI service daemon."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    RESTARTING = "RESTARTING"
    FAILED = "FAILED"


class ServiceEvent(enum.Enum):
    """All events that can drive state transitions."""

    EVT_START = "EVT_START"
    EVT_STOP = "EVT_STOP"
    EVT_RESTART = "EVT_RESTART"
    EVT_INIT_SUCCESS = "EVT_INIT_SUCCESS"
    EVT_INIT_FAIL = "EVT_INIT_FAIL"
    EVT_INIT_TIMEOUT = "EVT_INIT_TIMEOUT"
    EVT_SHUTDOWN_DONE = "EVT_SHUTDOWN_DONE"
    EVT_SHUTDOWN_TIMEOUT = "EVT_SHUTDOWN_TIMEOUT"
    EVT_CRASH = "EVT_CRASH"


# ---------------------------------------------------------------------------
# Transition table  (current_state, event) -> new_state
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[tuple[ServiceState, ServiceEvent], ServiceState] = {
    # From STOPPED
    (ServiceState.STOPPED, ServiceEvent.EVT_START): ServiceState.STARTING,
    # From STARTING
    (ServiceState.STARTING, ServiceEvent.EVT_INIT_SUCCESS): ServiceState.RUNNING,
    (ServiceState.STARTING, ServiceEvent.EVT_INIT_FAIL): ServiceState.FAILED,
    (ServiceState.STARTING, ServiceEvent.EVT_INIT_TIMEOUT): ServiceState.FAILED,
    # From RUNNING
    (ServiceState.RUNNING, ServiceEvent.EVT_STOP): ServiceState.STOPPING,
    (ServiceState.RUNNING, ServiceEvent.EVT_RESTART): ServiceState.RESTARTING,
    (ServiceState.RUNNING, ServiceEvent.EVT_CRASH): ServiceState.FAILED,
    # From STOPPING
    (ServiceState.STOPPING, ServiceEvent.EVT_SHUTDOWN_DONE): ServiceState.STOPPED,
    (ServiceState.STOPPING, ServiceEvent.EVT_SHUTDOWN_TIMEOUT): ServiceState.STOPPED,
    # From RESTARTING
    (ServiceState.RESTARTING, ServiceEvent.EVT_SHUTDOWN_DONE): ServiceState.STARTING,
    (ServiceState.RESTARTING, ServiceEvent.EVT_SHUTDOWN_TIMEOUT): ServiceState.STARTING,
    # From FAILED
    (ServiceState.FAILED, ServiceEvent.EVT_RESTART): ServiceState.RESTARTING,
    (ServiceState.FAILED, ServiceEvent.EVT_START): ServiceState.STARTING,
}


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class ServiceStateMachine:
    """Deterministic finite state machine for the service lifecycle."""

    def __init__(
        self,
        on_state_change: Optional[Callable[[ServiceState, ServiceState], None]] = None,
    ) -> None:
        self._state: ServiceState = ServiceState.STOPPED
        self._on_state_change = on_state_change

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ServiceState:
        return self._state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, event: ServiceEvent) -> bool:
        """Apply *event* to the current state.

        Returns ``True`` if the transition was legal and the state changed,
        ``False`` otherwise (illegal transitions are silently logged).
        """
        key = (self._state, event)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            logger.warning(
                "Illegal transition: state=%s event=%s – ignored.",
                self._state.value,
                event.value,
            )
            return False

        old_state = self._state
        self._state = new_state
        logger.info(
            "State transition: %s -[%s]-> %s",
            old_state.value,
            event.value,
            new_state.value,
        )

        if self._on_state_change is not None:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                logger.exception("on_state_change callback raised an exception.")

        return True
