"""
D-Bus client for communicating with the ByteCLI service daemon.

Wraps the session-bus proxy for ``com.bytecli.Service`` and exposes typed
helper methods for every D-Bus method / signal defined by the service.
All calls are asynchronous-safe when used from a GLib main loop.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from gi.repository import Gio, GLib

from bytecli.constants import DBUS_BUS_NAME, DBUS_INTERFACE, DBUS_OBJECT_PATH

logger = logging.getLogger(__name__)


class DBusClient:
    """Thin wrapper around the session-bus proxy for the ByteCLI service."""

    def __init__(self) -> None:
        self._proxy: Optional[Gio.DBusProxy] = None
        self._connection: Optional[Gio.DBusConnection] = None
        self._signal_subscriptions: list[int] = []

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Create a synchronous D-Bus proxy.  Returns True on success."""
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._proxy = Gio.DBusProxy.new_sync(
                self._connection,
                Gio.DBusProxyFlags.NONE,
                None,
                DBUS_BUS_NAME,
                DBUS_OBJECT_PATH,
                DBUS_INTERFACE,
                None,
            )
            logger.info("D-Bus proxy created for %s", DBUS_BUS_NAME)
            return True
        except GLib.Error as exc:
            logger.error("Failed to connect to D-Bus service: %s", exc.message)
            return False

    def disconnect(self) -> None:
        """Unsubscribe from all signals and release the proxy."""
        if self._connection is not None:
            for sub_id in self._signal_subscriptions:
                self._connection.signal_unsubscribe(sub_id)
            self._signal_subscriptions.clear()
        self._proxy = None
        self._connection = None

    @property
    def is_connected(self) -> bool:
        return self._proxy is not None

    # ------------------------------------------------------------------
    # Signal subscriptions
    # ------------------------------------------------------------------

    def subscribe_signal(
        self,
        signal_name: str,
        callback: Callable[..., None],
    ) -> None:
        """Subscribe to a D-Bus signal on the service interface.

        *callback* receives ``(connection, sender, path, iface, signal, params)``.
        """
        if self._connection is None:
            logger.warning("Cannot subscribe to signal '%s': not connected.", signal_name)
            return

        sub_id = self._connection.signal_subscribe(
            DBUS_BUS_NAME,
            DBUS_INTERFACE,
            signal_name,
            DBUS_OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            callback,
        )
        self._signal_subscriptions.append(sub_id)
        logger.debug("Subscribed to D-Bus signal '%s' (id=%d)", signal_name, sub_id)

    # ------------------------------------------------------------------
    # Method calls (synchronous convenience wrappers)
    # ------------------------------------------------------------------

    def _call_sync(
        self,
        method: str,
        parameters: Optional[GLib.Variant] = None,
    ) -> Optional[GLib.Variant]:
        """Call a D-Bus method synchronously and return the result."""
        if self._proxy is None:
            logger.error("D-Bus proxy not available for method '%s'.", method)
            return None
        try:
            result = self._proxy.call_sync(
                method,
                parameters,
                Gio.DBusCallFlags.NONE,
                5000,  # 5 s timeout
                None,
            )
            return result
        except GLib.Error as exc:
            logger.error("D-Bus call '%s' failed: %s", method, exc.message)
            return None

    def _call_async(
        self,
        method: str,
        parameters: Optional[GLib.Variant] = None,
        callback: Optional[Callable] = None,
    ) -> None:
        """Call a D-Bus method asynchronously."""
        if self._proxy is None:
            logger.error("D-Bus proxy not available for async method '%s'.", method)
            return

        def _on_done(proxy: Gio.DBusProxy, result: Gio.AsyncResult) -> None:
            try:
                res = proxy.call_finish(result)
                if callback:
                    callback(res)
            except GLib.Error as exc:
                logger.error("Async D-Bus call '%s' failed: %s", method, exc.message)
                if callback:
                    callback(None)

        self._proxy.call(
            method,
            parameters,
            Gio.DBusCallFlags.NONE,
            30000,
            None,
            _on_done,
        )

    # --- Service lifecycle -----------------------------------------------

    def start_service(self, callback: Optional[Callable] = None) -> None:
        self._call_async("Start", callback=callback)

    def stop_service(self, callback: Optional[Callable] = None) -> None:
        self._call_async("Stop", callback=callback)

    def restart_service(self, callback: Optional[Callable] = None) -> None:
        self._call_async("Restart", callback=callback)

    def get_status(self) -> Optional[str]:
        result = self._call_sync("GetStatus")
        if result:
            return result.unpack()[0] if result.n_children() > 0 else None
        return None

    # --- Configuration ---------------------------------------------------

    def get_config(self) -> Optional[dict]:
        result = self._call_sync("GetConfig")
        if result is None:
            return None
        try:
            import json
            raw = result.unpack()[0] if result.n_children() > 0 else result.unpack()
            if isinstance(raw, str):
                return json.loads(raw)
            return dict(raw)
        except Exception as exc:
            logger.error("Failed to unpack GetConfig result: %s", exc)
            return None

    def save_config(self, config: dict, callback: Optional[Callable] = None) -> None:
        import json
        params = GLib.Variant("(s)", (json.dumps(config),))
        self._call_async("SaveConfig", parameters=params, callback=callback)

    # --- Model -----------------------------------------------------------

    def switch_model(self, model_name: str, callback: Optional[Callable] = None) -> None:
        params = GLib.Variant("(s)", (model_name,))
        self._call_async("SwitchModel", parameters=params, callback=callback)

    # --- Audio -----------------------------------------------------------

    def get_audio_devices(self) -> Optional[list]:
        result = self._call_sync("GetAudioDevices")
        if result is None:
            return None
        try:
            raw = result.unpack()
            if isinstance(raw, tuple) and len(raw) == 1:
                raw = raw[0]
            return list(raw)
        except Exception as exc:
            logger.error("Failed to unpack GetAudioDevices result: %s", exc)
            return None

    # --- History ---------------------------------------------------------

    def get_history(self) -> Optional[list]:
        result = self._call_sync("GetHistory")
        if result is None:
            return None
        try:
            import json
            raw = result.unpack()[0] if result.n_children() > 0 else result.unpack()
            if isinstance(raw, str):
                return json.loads(raw)
            return list(raw)
        except Exception as exc:
            logger.error("Failed to unpack GetHistory result: %s", exc)
            return None

    # --- Indicator -------------------------------------------------------

    def refresh_indicator(self, callback: Optional[Callable] = None) -> None:
        self._call_async("RefreshIndicator", callback=callback)
