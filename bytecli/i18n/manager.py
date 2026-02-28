"""
I18nManager -- lightweight internationalisation for ByteCLI.

Loads flat JSON string tables keyed by dot-notation (e.g. "panel.title")
and performs variable interpolation via str.format_map().

Usage:
    from bytecli.i18n import i18n

    i18n.load("en")
    print(i18n.t("server.running", model="tiny"))   # "Running (tiny)"
    i18n.switch("zh")                                # notifies all callbacks
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Directory that contains the locale JSON files (en.json, zh.json, ...).
_LOCALE_DIR: str = os.path.dirname(os.path.abspath(__file__))

# Supported language codes -- kept in sync with the JSON files shipped in
# the package.  Used for validation only; an unsupported code falls back
# to English.
_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "zh"})

_DEFAULT_LANGUAGE: str = "en"


class I18nManager:
    """Simple, GObject-free internationalisation manager.

    * Singleton semantics are achieved by the module-level ``i18n`` instance.
    * Language-change listeners are plain callables stored in a list.
    """

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._current_language: str = _DEFAULT_LANGUAGE
        self._callbacks: list[Callable[[str], Any]] = []
        # Eagerly load the default language so ``t()`` always works.
        self.load(_DEFAULT_LANGUAGE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_language(self) -> str:
        """Return the language code that is currently active."""
        return self._current_language

    def load(self, lang: str) -> None:
        """Load the string table for *lang* from the package's i18n directory.

        Falls back to English when *lang* is unknown or the file cannot be
        read.  The operation is intentionally synchronous and expected to
        complete well within 100 ms (a single small JSON parse).
        """
        if lang not in _SUPPORTED_LANGUAGES:
            logger.warning(
                "Unsupported language '%s'; falling back to '%s'.",
                lang,
                _DEFAULT_LANGUAGE,
            )
            lang = _DEFAULT_LANGUAGE

        locale_path = os.path.join(_LOCALE_DIR, f"{lang}.json")

        try:
            with open(locale_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            logger.error("Locale file not found: %s", locale_path)
            if lang != _DEFAULT_LANGUAGE:
                self.load(_DEFAULT_LANGUAGE)
            return
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load locale file %s: %s", locale_path, exc)
            if lang != _DEFAULT_LANGUAGE:
                self.load(_DEFAULT_LANGUAGE)
            return

        if not isinstance(data, dict):
            logger.error("Locale file %s does not contain a JSON object.", locale_path)
            if lang != _DEFAULT_LANGUAGE:
                self.load(_DEFAULT_LANGUAGE)
            return

        self._strings = {str(k): str(v) for k, v in data.items()}
        self._current_language = lang
        logger.debug("Loaded %d strings for locale '%s'.", len(self._strings), lang)

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key*, interpolating ``{name}`` placeholders with *kwargs*.

        Returns the raw *key* if no translation is found, so missing strings
        are immediately visible in the UI during development.
        """
        template = self._strings.get(key)
        if template is None:
            logger.debug("Missing i18n key: '%s' (lang=%s)", key, self._current_language)
            return key

        if kwargs:
            try:
                return template.format_map(kwargs)
            except KeyError as exc:
                logger.warning(
                    "Missing interpolation variable %s for key '%s'.",
                    exc,
                    key,
                )
                return template

        return template

    def switch(self, lang: str) -> None:
        """Load a new language and notify all registered callbacks.

        If the requested language is the same as the current one, this is a
        no-op.
        """
        if lang == self._current_language:
            return

        previous = self._current_language
        self.load(lang)

        # Only fire callbacks if the language actually changed.
        if self._current_language != previous:
            for callback in self._callbacks:
                try:
                    callback(self._current_language)
                except Exception:
                    logger.exception(
                        "Language-change callback %r raised an exception.",
                        callback,
                    )

    def on_language_changed(self, callback: Callable[[str], Any]) -> None:
        """Register *callback* to be called when the language changes.

        The callback receives the new language code as its sole argument.
        Duplicate registrations are silently ignored.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_language_changed(self, callback: Callable[[str], Any]) -> None:
        """Unregister a previously registered language-change callback.

        Silently ignores callbacks that were never registered.
        """
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
i18n = I18nManager()
