"""
Hands Module — OS-Level Mouse & Keyboard Control
=================================================
Wraps PyAutoGUI with:
  - Automatic DPI coordinate scaling (logical → physical pixels)
  - Human-like random micro-delays to avoid bot-detection
  - Structured result strings for the ReAct history log
"""

import logging
import time
import random
from typing import Any

import pyautogui

from utils.dpi import get_dpi_scale, scale_point

logger = logging.getLogger(__name__)

# Disable PyAutoGUI's fail-safe (we manage our own kill switch)
pyautogui.FAILSAFE = False


class Hands:
    def __init__(self, pause_s: float = 0.3, typing_interval: float = 0.04) -> None:
        pyautogui.PAUSE = pause_s
        self._typing_interval = typing_interval
        self._scale_x, self._scale_y = get_dpi_scale()
        logger.info(
            "🖱  DPI scale detected: x=%.2f  y=%.2f", self._scale_x, self._scale_y
        )

    # ── coordinate helpers ────────────────────────────────────────────────────

    def _to_physical(self, lx: float, ly: float) -> tuple[int, int]:
        """Convert logical screenshot coordinates to physical screen pixels."""
        return scale_point(lx, ly, self._scale_x, self._scale_y)

    def _jitter(self, x: int, y: int, radius: int = 2) -> tuple[int, int]:
        """Add tiny random offset to simulate non-robotic movement."""
        return (
            x + random.randint(-radius, radius),
            y + random.randint(-radius, radius),
        )

    # ── actions ───────────────────────────────────────────────────────────────

    def click(self, lx: float, ly: float) -> str:
        px, py = self._jitter(*self._to_physical(lx, ly))
        pyautogui.moveTo(px, py, duration=0.15 + random.random() * 0.1)
        pyautogui.click(px, py)
        logger.info("🖱  click   logical=(%.0f, %.0f) → physical=(%d, %d)", lx, ly, px, py)
        return f"clicked ({px}, {py})"

    def double_click(self, lx: float, ly: float) -> str:
        px, py = self._to_physical(lx, ly)
        pyautogui.doubleClick(px, py)
        logger.info("🖱  dblclick physical=(%d, %d)", px, py)
        return f"double-clicked ({px}, {py})"

    def right_click(self, lx: float, ly: float) -> str:
        px, py = self._to_physical(lx, ly)
        pyautogui.rightClick(px, py)
        logger.info("🖱  rclick  physical=(%d, %d)", px, py)
        return f"right-clicked ({px}, {py})"

    def type_text(self, text: str) -> str:
        pyautogui.write(text, interval=self._typing_interval)
        logger.info("⌨️  type   %r", text[:60] + ("…" if len(text) > 60 else ""))
        return f"typed {len(text)} chars"

    def hotkey(self, combo: str) -> str:
        """
        Accept combos like "ctrl+c", "alt+F4", "win+d".
        """
        keys = [k.strip() for k in combo.lower().split("+")]
        pyautogui.hotkey(*keys)
        logger.info("⌨️  hotkey  %s", combo)
        return f"pressed {combo}"

    def scroll(self, lx: float, ly: float,
               direction: str = "down", amount: int = 3) -> str:
        px, py = self._to_physical(lx, ly)
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks, x=px, y=py)
        logger.info("🖱  scroll  %s ×%d @ (%d, %d)", direction, amount, px, py)
        return f"scrolled {direction} ×{amount}"

    def drag(self, lx1: float, ly1: float,
             lx2: float, ly2: float, duration: float = 0.4) -> str:
        x1, y1 = self._to_physical(lx1, ly1)
        x2, y2 = self._to_physical(lx2, ly2)
        pyautogui.moveTo(x1, y1, duration=0.1)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")
        logger.info("🖱  drag   (%d, %d) → (%d, %d)", x1, y1, x2, y2)
        return f"dragged ({x1},{y1}) → ({x2},{y2})"

    def wait(self, seconds: float = 1.5) -> str:
        time.sleep(seconds)
        logger.info("⏳ wait %.1fs", seconds)
        return f"waited {seconds}s"

    # ── dispatch ──────────────────────────────────────────────────────────────

    def execute(self, command: dict[str, Any]) -> str:
        """
        Route a Gemini-returned command dict to the right method.
        Returns a human-readable result string for the history log.
        """
        action = command.get("action", "")
        point  = command.get("point", [0, 0])
        lx = float(point[0]) if len(point) > 0 else 0.0
        ly = float(point[1]) if len(point) > 1 else 0.0

        match action:
            case "click":
                return self.click(lx, ly)
            case "double_click":
                return self.double_click(lx, ly)
            case "right_click":
                return self.right_click(lx, ly)
            case "type":
                return self.type_text(command.get("text", ""))
            case "hotkey":
                return self.hotkey(command.get("text", ""))
            case "scroll":
                return self.scroll(
                    lx, ly,
                    direction=command.get("direction", "down"),
                    amount=int(command.get("scroll_amount", 3)),
                )
            case "wait":
                return self.wait(command.get("seconds", 1.5))
            case _:
                return f"[hands] unknown action: {action}"
