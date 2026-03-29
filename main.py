"""
Overlord Agent — Entry Point
============================
Usage:
    python main.py "open Chrome and search for Python docs"
    python main.py   # will prompt for a task interactively

Kill switch:
    Move the mouse to the TOP-LEFT CORNER of the screen at any time to
    immediately abort the agent.

Environment variables:
    GEMINI_API_KEY   (required)
"""

import asyncio
import logging
import sys
import os

# ── ensure project root is on path ────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from agent.react_loop import ReActLoop
from utils.kill_switch import KillSwitch, AgentAborted
from utils.logger import get_logger

logger = get_logger("overlord")


def _banner() -> None:
    print("""
╔══════════════════════════════════════════════════════════╗
║          OVERLORD AGENT  —  Gemini Vision + ReAct        ║
║  Kill switch: move mouse to TOP-LEFT corner to abort     ║
╚══════════════════════════════════════════════════════════╝
""")


async def _run(task: str) -> None:
    config = Config()

    kill_switch = KillSwitch(
        margin_px=config.kill_switch_margin_px,
        poll_s=config.kill_switch_poll_s,
    )
    kill_switch.start()

    loop = ReActLoop(config, kill_switch)

    try:
        result = await loop.run(task)
        logger.info("🏁 Final result: %s", result)
        print(f"\n✅ {result}")
    except AgentAborted as exc:
        logger.warning("🛑 %s", exc)
        print(f"\n🛑 Agent aborted: {exc}")
    except KeyboardInterrupt:
        logger.warning("⚠️  Ctrl-C received — shutting down")
        print("\n⚠️  Interrupted.")
    except Exception as exc:
        logger.critical("💥 Unhandled error: %s", exc, exc_info=True)
        print(f"\n💥 Fatal error: {exc}")
    finally:
        kill_switch.stop()


def main() -> None:
    _banner()

    # Task from CLI args or interactive prompt
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = input("🎯 Enter task: ").strip()
        if not task:
            print("No task provided. Exiting.")
            return

    print(f"🚀 Starting agent for task: {task!r}\n")

    # Validate API key early
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY environment variable is not set.")
        sys.exit(1)

    asyncio.run(_run(task))


if __name__ == "__main__":
    main()
