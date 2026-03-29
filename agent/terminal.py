"""
Terminal Module — GodMode Shell Access
======================================
Executes PowerShell or CMD commands and returns their stdout/stderr.
Captures output as UTF-8 text; enforces a configurable timeout.

Security note: This module gives the agent full shell access.
Run only in isolated/trusted environments.
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

# Maximum characters of output returned to the brain (keeps history compact)
MAX_OUTPUT_CHARS = 2000


class Terminal:
    def __init__(self, shell: str = "powershell", timeout_s: int = 30) -> None:
        self._timeout = timeout_s
        if shell == "powershell":
            # -NoProfile -NonInteractive: faster startup
            self._prefix = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
            ]
        else:
            self._prefix = ["cmd", "/c"]

    # ── public ────────────────────────────────────────────────────────────────

    def run(self, command: str) -> str:
        """
        Execute `command` in the configured shell.
        Returns a single string: stdout + stderr (truncated if too long).
        """
        full_cmd = self._prefix + [command]
        logger.info("💻 terminal: %s", command)

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            output = output.strip()

            if result.returncode != 0:
                logger.warning(
                    "💻 exit code %d for command: %s", result.returncode, command
                )
                output = f"[exit {result.returncode}]\n{output}"

            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n…[truncated]"

            logger.debug("💻 output:\n%s", output)
            return output or "(no output)"

        except subprocess.TimeoutExpired:
            msg = f"[timeout after {self._timeout}s] Command: {command}"
            logger.error(msg)
            return msg

        except FileNotFoundError:
            msg = f"[error] Shell not found. Tried: {self._prefix[0]}"
            logger.error(msg)
            return msg

        except Exception as exc:
            msg = f"[error] {exc}"
            logger.error("💻 unexpected error: %s", exc, exc_info=True)
            return msg
