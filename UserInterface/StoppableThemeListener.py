"""Cancellable system theme polling for qfluentwidgets."""
import darkdetect
from qfluentwidgets import SystemThemeListener


class StoppableThemeListener(SystemThemeListener):
    """Poll the system theme without blocking thread interruption."""

    _POLL_INTERVAL_MS = 50
    _POLLS_PER_SECOND = 20

    def run(self):
        last_theme = None
        while not self.isInterruptionRequested():
            try:
                detected = darkdetect.theme()
            except Exception:
                detected = None
            if self.isInterruptionRequested():
                return
            theme = detected.strip().lower() if isinstance(detected, str) else None
            if theme in {'light', 'dark'} and theme != last_theme:
                last_theme = theme
                self._onThemeChanged(theme)
            for _ in range(self._POLLS_PER_SECOND):
                if self.isInterruptionRequested():
                    return
                self.msleep(self._POLL_INTERVAL_MS)
