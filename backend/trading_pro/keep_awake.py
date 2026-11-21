"""Keep Windows from falling asleep while the agents work (or while a position needs following).

Uses the same call as video players: ``SetThreadExecutionState``. Nothing in the system settings is changed; the
request disappears when the program stops. It only prevents *idle* sleep: choosing Sleep by hand, closing a laptop
lid (unless Windows is set to do nothing) or running out of battery still suspends the computer, and a suspended
computer runs nothing. The call applies to the thread that makes it, so the pilot's own thread must make it.
"""
from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001  # the system must not go to sleep; the screen is still allowed to turn off


def _windows_setter():
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32.SetThreadExecutionState
    except Exception:  # noqa: BLE001 - never let a power request break the pilot
        return None


class KeepAwake:
    def __init__(self, setter=None):
        self._setter = setter if setter is not None else _windows_setter()
        self.holding = False

    @property
    def available(self) -> bool:
        return self._setter is not None

    def set(self, needed: bool) -> bool:
        """Request (or release) the 'do not sleep' state; returns whether sleep is currently being prevented."""
        if self._setter is None:
            return False
        try:
            self._setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED if needed else ES_CONTINUOUS)
            self.holding = bool(needed)
        except Exception:  # noqa: BLE001
            self.holding = False
        return self.holding
