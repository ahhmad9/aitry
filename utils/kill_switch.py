"""
Kill Switch
===========
Runs in a daemon thread.  If the user moves the mouse to the top-left corner
of the screen (within `margin` pixels of 0, 0) the agent is aborted
immediately — no waiting for the current iteration to finish.

Usage
-----
    ks = KillSwitch(margin_px=5, poll_s=0.2)
    ks.start()
    ...
    if ks.triggered:
        raise AgentAborted("Kill switch activated")
    ...
    ks.stop()
"""

import threading
import time
import logging

import pyautogui

logger = logging.getLogger(__name__)


class AgentAborted(Exception):
    """Raised when the kill switch is triggered."""


class KillSwitch:
    def __init__(self, margin_px: int = 5, poll_s: float = 0.2) -> None:
        self.margin_px = margin_px
        self.poll_s = poll_s
        self.triggered = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._monitor, daemon=True,
                                        name="KillSwitchMonitor")

    # ── public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        logger.info(
            "🛡  Kill switch active — move mouse to top-left corner to abort."
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def check(self) -> None:
        """Call inside the ReAct loop; raises AgentAborted if triggered."""
        if self.triggered:
            raise AgentAborted(
                "Kill switch triggered: mouse moved to top-left corner."
            )

    # ── private ───────────────────────────────────────────────────────────────

    def _monitor(self) -> None:
        while not self._stop_event.is_set():
            try:
                x, y = pyautogui.position()
                if x <= self.margin_px and y <= self.margin_px:
                    self.triggered = True
                    logger.warning(
                        "🚨 KILL SWITCH ACTIVATED — mouse at (%d, %d)", x, y
                    )
                    return
            except Exception:
                pass
            time.sleep(self.poll_s)
