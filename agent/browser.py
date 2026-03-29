"""
Browser Module — Chrome via PyAutoGUI (Screen Control)
=======================================================
Controls Google Chrome directly through screen clicks and keyboard input,
exactly like the agent controls any other window.

No Playwright. No browser-use. No Chromium download.
Works with your real installed Chrome on Windows.

How it works:
  - open_chrome     → launches chrome.exe via subprocess
  - browser_navigate→ focuses Chrome address bar (Ctrl+L), types URL, Enter
  - browser_click   → passthrough (Gemini uses screen coords via normal click)
  - browser_type    → types into whatever Chrome field is focused
  - close()         → no-op (Chrome stays open, user manages it)
"""

import asyncio
import logging
import os
import subprocess

import pyautogui

logger = logging.getLogger(__name__)

# Common Chrome install paths on Windows
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\{username}\AppData\Local\Google\Chrome\Application\chrome.exe",
]


def _find_chrome() -> str | None:
    """Return the first Chrome executable that exists on this machine."""
    username = os.environ.get("USERNAME", "")
    for path in _CHROME_PATHS:
        expanded = path.format(username=username)
        if os.path.exists(expanded):
            return expanded
    return None


class BrowserController:
    """
    Controls Chrome through PyAutoGUI screen actions.
    All real clicking is done by Gemini returning 'click' commands with
    screen coordinates — this module handles URL navigation and keyboard ops.
    """

    def __init__(
        self,
        gemini_api_key: str = "",   # API-compat, unused
        model_name: str = "",       # API-compat, unused
        headless: bool = False,     # ignored, Chrome is always visible
        timeout_s: int = 30,
    ) -> None:
        self._timeout_s = timeout_s

    # ── public ────────────────────────────────────────────────────────────────

    async def open_chrome(self, url: str = "about:blank") -> str:
        """Launch Chrome, optionally at a URL."""
        chrome = _find_chrome()
        try:
            if chrome:
                subprocess.Popen([chrome, url])
            else:
                # Shell fallback — works if Chrome is in PATH
                subprocess.Popen(f'start chrome "{url}"', shell=True)
            await asyncio.sleep(2.5)
            logger.info("🌐 Chrome launched → %s", url)
            return f"Chrome opened at {url}"
        except Exception as exc:
            logger.error("🌐 Chrome launch failed: %s", exc)
            return f"[error] Could not launch Chrome: {exc}"

    async def navigate(self, url: str) -> str:
        """
        Navigate Chrome to a URL using the keyboard address bar shortcut.
        Assumes Chrome already has focus (Gemini clicks on it first).
        """
        if not url:
            return "[error] No URL provided"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            pyautogui.hotkey("ctrl", "l")        # focus address bar
            await asyncio.sleep(0.35)
            pyautogui.hotkey("ctrl", "a")         # select all
            await asyncio.sleep(0.1)
            pyautogui.write(url, interval=0.03)
            await asyncio.sleep(0.1)
            pyautogui.press("enter")
            await asyncio.sleep(1.8)              # let page start loading
            logger.info("🌐 Navigated → %s", url)
            return f"Navigated to {url}"
        except Exception as exc:
            logger.error("🌐 navigate error: %s", exc)
            return f"[error] {exc}"

    async def click_element(self, description: str) -> str:
        """
        Screen-control mode: element clicks use Gemini's visual coordinates
        via the normal 'click' action. This is just a logged passthrough.
        """
        logger.info("🌐 browser_click → Gemini will click by screen coords: %s", description)
        return f"browser_click delegated to screen vision: {description}"

    async def type_in_browser(self, text: str) -> str:
        """Type into the currently focused Chrome field."""
        try:
            pyautogui.write(text, interval=0.04)
            logger.info("🌐 Typed: %r", text[:60])
            return f"typed: {text[:60]}"
        except Exception as exc:
            return f"[error] {exc}"

    async def new_tab(self) -> str:
        pyautogui.hotkey("ctrl", "t")
        await asyncio.sleep(0.5)
        return "new tab opened"

    async def close_tab(self) -> str:
        pyautogui.hotkey("ctrl", "w")
        await asyncio.sleep(0.3)
        return "tab closed"

    async def reload(self) -> str:
        pyautogui.press("f5")
        await asyncio.sleep(1.2)
        return "page reloaded"

    async def close(self) -> None:
        """No-op — we never force-close the user's Chrome."""
        pass
