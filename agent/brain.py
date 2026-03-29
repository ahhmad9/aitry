import os  
"""
Brain Module — Gemini Multimodal Reasoning Engine
==================================================
Sends a screenshot + task context to Gemini and receives a structured
JSON command back.

Command Schema (what Gemini must return)
-----------------------------------------
{
  "thought":      "...internal reasoning...",
  "action":       "click" | "double_click" | "right_click" | "type" |
                  "hotkey" | "scroll" | "screenshot_only" |
                  "terminal" | "browser_navigate" | "browser_type" |
                  "browser_click" | "wait" | "done",
  "point":        [x, y],          # for click/scroll actions (screenshot coords)
  "text":         "...",           # for type / hotkey / browser actions
  "command":      "...",           # for terminal action
  "url":          "...",           # for browser_navigate
  "direction":    "up" | "down",   # for scroll
  "scroll_amount":3,               # scroll clicks
  "reason":       "...",           # human-readable justification
  "is_complete":  false            # true when the whole task is done
}
"""

import base64
import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

from agent.eyes import ScreenCapture

logger = logging.getLogger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are an autonomous computer agent that controls a Windows desktop and browser.
You receive a screenshot and a task.  You must return ONLY a single JSON object
(no markdown fences, no extra text) describing the NEXT atomic action.

AUTONOMOUS BEHAVIOUR RULES:
1. Analyse the full screenshot carefully before deciding on an action.
2. Break complex tasks into small, sequential steps and work through them
   methodically — do not try to complete everything in one action.
3. UNEXPECTED UI ELEMENTS (pop-ups, ads, cookie banners, permission dialogs,
   notification prompts, login walls, etc.):
   - Detect them immediately by looking for modal overlays, banner bars, or
     anything that blocks your primary task.
   - Dismiss them as quickly as possible: click the ✕ / "Close" / "Dismiss" /
     "No thanks" / "Accept" / "Got it" button, press Escape, or use
     hotkey "alt+f4" if nothing else works.
   - After dismissing, use screenshot_only to confirm the element is gone
     before resuming your main task.
4. ERROR RECOVERY: if an action does not produce the expected result (e.g. a
   click missed, a page did not load, text was not typed), take a fresh
   screenshot_only, re-assess, and try an alternative approach rather than
   repeating the same action.
5. SCROLLING: if the content you need is not visible, scroll down (or up) in
   small increments and re-check with screenshot_only after each scroll.
6. WAITING: after navigating to a URL or clicking a button that triggers a
   page load, use "wait" to give the page time to render before proceeding.
7. Never give up before max_iterations — always try a recovery action.

Available actions:
  click           – left-click at point [x, y]
  double_click    – double-click at [x, y]
  right_click     – right-click at [x, y]
  type            – type the string in "text" (keyboard input)
  hotkey          – press key combination in "text" (e.g. "ctrl+c")
  scroll          – scroll at [x, y] in "direction" by "scroll_amount" clicks
  screenshot_only – take a fresh screenshot and reason again (no UI action)
  terminal        – run shell command in "command" field
  browser_open    – launch Chrome, optionally at "url"
  browser_navigate– focus Chrome address bar and go to "url"
  browser_new_tab – open a new Chrome tab (Ctrl+T)
  browser_reload  – reload current Chrome page (F5)
  browser_type    – type "text" into the currently focused Chrome field
  browser_click   – hint only; use a normal "click" action with screen coords instead
  wait            – sleep briefly (use when waiting for something to load)
  done            – task is fully complete; set is_complete: true

Coordinate rules:
- [x, y] are in the SCREENSHOT coordinate space (0..1280, 0..720).
- Click the CENTER of target elements.
- If unsure of coordinates, choose screenshot_only to re-examine.

Return exactly this JSON structure:
{
  "thought": "...",
  "action": "...",
  "point": [x, y],
  "text": "...",
  "command": "...",
  "url": "...",
  "direction": "down",
  "scroll_amount": 3,
  "reason": "...",
  "is_complete": false
}
Omit fields that are not needed for the chosen action (except thought, action,
reason, and is_complete which are always required).
""".strip()


class Brain:
    def __init__(self, api_key: str, model_name: str,
                 max_tokens: int = 2048, temperature: float = 0.1) -> None:
        

        # Point to your service account JSON file in the root folder
        # (Adjust the path if it's not in the exact same directory you run the script from)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"

        # Initialize the client for Vertex AI
        self._client = genai.Client(
            vertexai=True,
            project="YOUR_GOOGLE_CLOUD_PROJECT_ID",  # Replace with your actual project ID
            location="us-central1"  # Replace with your region if different
        )
        self._model = model_name
        self._max_tokens = max_tokens
        self._temperature = temperature

    # ── public ────────────────────────────────────────────────────────────────

    def reason(
        self,
        capture: ScreenCapture,
        task: str,
        history: list[dict[str, Any]],
        context_paths: list[str] | None = None,
        context_scope: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Send screenshot + task + history to Gemini; return parsed JSON command.
        Raises ValueError if the model returns malformed JSON.
        """
        history_text = self._format_history(history)

        # Build context block from GUI-supplied paths and scope
        context_block = ""
        if context_paths:
            paths_fmt = "\n".join(f"  - {p}" for p in context_paths)
            context_block += f"\nRELEVANT LOCATIONS (prefer working in these paths):\n{paths_fmt}\n"
        if context_scope:
            scope_fmt = ", ".join(context_scope)
            context_block += f"\nENABLED SCOPES (only use these capabilities): {scope_fmt}\n"

        user_text = (
            f"TASK: {task}\n"
            f"{context_block}\n"
            f"PREVIOUS ACTIONS (most recent last):\n{history_text}\n\n"
            "Examine the screenshot and return the next JSON action."
        )

        contents = [
            types.Part.from_bytes(
                data=_b64_to_bytes(capture.b64_jpeg),
                mime_type="image/jpeg",
            ),
            types.Part.from_text(text=user_text),
        ]

        logger.debug("🧠 Sending to Gemini (%s)…", self._model)

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True,
                ),
            ),
        )

        raw_text = response.text.strip()
        logger.debug("🧠 Gemini raw response:\n%s", raw_text)
        return self._parse_json(raw_text)

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        if not history:
            return "(none)"
        lines = []
        for i, entry in enumerate(history[-10:], 1):   # last 10 actions only
            action = entry.get("action", "?")
            reason = entry.get("reason", "")
            result = entry.get("result", "")
            lines.append(f"  {i}. [{action}] {reason}  →  {result}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        # Strip markdown fences if the model slips them in
        cleaned = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Gemini returned non-JSON output: {exc}\nRaw:\n{raw}"
            ) from exc


def _b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64)
