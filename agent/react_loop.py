"""
ReAct Loop — Reason → Act → Observe → Repeat
=============================================
This is the central orchestrator of the Overlord Agent.

Each iteration:
  1. EYES   → capture screenshot
  2. BRAIN  → send screenshot + task + history to Gemini → get JSON command
  3. HANDS  → execute the command (click / type / scroll / terminal / browser)
  4. LOG    → record action + result to history
  5. CHECK  → kill switch, is_complete flag, error retry counter

The loop continues until:
  - Gemini sets is_complete=true
  - max_iterations is reached
  - The kill switch fires
  - A non-recoverable error occurs
"""

import asyncio
import logging
from typing import Any

from config import Config
from agent.brain import Brain
from agent.eyes import Eyes, ScreenCapture
from agent.hands import Hands
from agent.terminal import Terminal
from agent.browser import BrowserController
from utils.kill_switch import KillSwitch, AgentAborted

logger = logging.getLogger(__name__)


class ReActLoop:
    def __init__(self, config: Config, kill_switch: KillSwitch) -> None:
        self._cfg     = config
        self._ks      = kill_switch

        # ── module instances ──────────────────────────────────────────────────
        self._eyes    = Eyes(
            resize_w=config.screenshot_resize_w,
            resize_h=config.screenshot_resize_h,
            jpeg_quality=config.screenshot_quality,
        )
        self._brain   = Brain(
            api_key=config.gemini_api_key,
            model_name=config.model_name,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        self._hands   = Hands(
            pause_s=config.pyautogui_pause_s,
            typing_interval=config.typing_interval_s,
        )
        self._terminal = Terminal(
            shell=config.shell,
            timeout_s=config.terminal_timeout_s,
        )
        self._browser = BrowserController(
            timeout_s=config.browser_timeout_s,
        )

        self._history: list[dict[str, Any]] = []

    # ── public ────────────────────────────────────────────────────────────────

    async def run(self, task: str) -> str:
        """
        Execute the task.  Returns a final status string.
        """
        logger.info("=" * 60)
        logger.info("🎯 TASK: %s", task)
        logger.info("=" * 60)

        iteration   = 0
        fail_streak = 0                        # consecutive failures
        last_result = "none"

        try:
            while iteration < self._cfg.max_iterations:
                iteration += 1
                logger.info("── Iteration %d / %d ──", iteration, self._cfg.max_iterations)

                # ── 0. Kill switch ─────────────────────────────────────────────
                self._ks.check()

                # ── 1. EYES: capture screenshot ────────────────────────────────
                try:
                    capture: ScreenCapture = self._eyes.capture()
                except Exception as exc:
                    logger.error("👁  Screenshot failed: %s", exc)
                    fail_streak += 1
                    if fail_streak >= self._cfg.retry_on_fail:
                        return f"ABORTED: screenshot failed {fail_streak} times"
                    await asyncio.sleep(self._cfg.loop_delay_s)
                    continue

                # ── 2. BRAIN: reason ───────────────────────────────────────────
                command: dict[str, Any]
                try:
                    command = self._brain.reason(
                        capture, task, self._history,
                        context_paths=self._cfg.context_paths,
                        context_scope=self._cfg.context_scope,
                    )
                except ValueError as exc:
                    logger.warning("🧠 Parse error (retry %d): %s", fail_streak + 1, exc)
                    fail_streak += 1
                    if fail_streak >= self._cfg.retry_on_fail:
                        return f"ABORTED: Gemini returned bad JSON {fail_streak} times"
                    await asyncio.sleep(self._cfg.loop_delay_s)
                    continue

                # ── 3. Log the thought ─────────────────────────────────────────
                action = command.get("action", "unknown")
                thought = command.get("thought", "")
                reason  = command.get("reason", "")
                logger.info("🧠 action=%s  reason=%s", action, reason)
                if thought:
                    logger.debug("🧠 thought: %s", thought)

                # ── 4. HANDS / dispatch ────────────────────────────────────────
                try:
                    result = await self._dispatch(command)
                    fail_streak = 0              # reset on success
                except AgentAborted:
                    raise
                except Exception as exc:
                    result = f"[error] {exc}"
                    fail_streak += 1
                    logger.error("❌ Action failed (streak=%d): %s", fail_streak, exc,
                                 exc_info=True)
                    if fail_streak >= self._cfg.retry_on_fail:
                        logger.error("❌ Too many consecutive failures — aborting")
                        return f"ABORTED after {fail_streak} consecutive failures"

                last_result = result
                logger.info("✅ result: %s", result)

                # ── 5. Record history ──────────────────────────────────────────
                self._history.append({
                    "action":  action,
                    "reason":  reason,
                    "result":  result,
                })

                # ── 6. Check completion ────────────────────────────────────────
                if command.get("is_complete", False) or action == "done":
                    logger.info("🏁 Task marked complete by agent.")
                    return f"DONE: {reason or last_result}"

                # ── 7. Pause before next iteration ────────────────────────────
                await asyncio.sleep(self._cfg.loop_delay_s)

            return f"STOPPED: reached max_iterations={self._cfg.max_iterations}"

        finally:
            # Always close the browser, even on kill-switch abort or crash
            await self._browser.close()

    # ── private dispatch ───────────────────────────────────────────────────────

    async def _dispatch(self, command: dict[str, Any]) -> str:
        """Route command to the correct module."""
        action = command.get("action", "")

        # ── OS / GUI actions ──────────────────────────────────────────────────
        if action in {"click", "double_click", "right_click",
                      "type", "hotkey", "scroll", "wait"}:
            return self._hands.execute(command)

        # ── Screenshot-only (no UI change, re-examine) ─────────────────────
        elif action == "screenshot_only":
            return "re-examined screenshot"

        # ── Terminal ──────────────────────────────────────────────────────────
        elif action == "terminal":
            cmd_str = command.get("command", "")
            if not cmd_str:
                return "[error] terminal action missing 'command' field"
            return self._terminal.run(cmd_str)

        # ── Browser (real Chrome via PyAutoGUI) ──────────────────────────────────────────
        elif action == "browser_open":
            return await self._browser.open_chrome(command.get("url", "about:blank"))

        elif action == "browser_navigate":
            return await self._browser.navigate(command.get("url", ""))

        elif action == "browser_click":
            return await self._browser.click_element(command.get("text", ""))

        elif action == "browser_type":
            return await self._browser.type_in_browser(command.get("text", ""))

        elif action == "browser_new_tab":
            return await self._browser.new_tab()

        elif action == "browser_reload":
            return await self._browser.reload()

        # ── Done sentinel ─────────────────────────────────────────────────────
        elif action == "done":
            return "task complete"

        else:
            logger.warning("⚠️  Unknown action: %s", action)
            return f"[skipped] unknown action: {action}"
