import json
import os
from dataclasses import dataclass, field
from typing import List

_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


@dataclass
class Config:
    # ─── Backend selector ─────────────────────────────────────────────────────
    use_vertex: bool = True

    # ─── AI Studio (used when use_vertex=False) ───────────────────────────────
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))

    # ─── Vertex AI (used when use_vertex=True) ────────────────────────────────
    vertex_project: str = "my-project-1598000"
    vertex_location: str = "us-central1"
    vertex_sa_key_path: str = "service_account.json"

    # ─── Model ────────────────────────────────────────────────────────────────
    model_name: str = "gemini-2.5-flash"
    max_tokens: int = 2048
    temperature: float = 0.1

    # ─── ReAct Loop ───────────────────────────────────────────────────────────
    max_iterations: int = 50
    retry_on_fail: int = 3
    loop_delay_s: float = 1.0

    # ─── Screenshot ───────────────────────────────────────────────────────────
    screenshot_quality: int = 85
    screenshot_resize_w: int = 1280
    screenshot_resize_h: int = 720

    # ─── Display (override auto-detection if set in settings.json) ────────────
    # 0 means auto-detect from Windows API
    screen_width: int = 0
    screen_height: int = 0
    screen_scale_pct: int = 0    # e.g. 125 for 125%; 0 = auto

    # ─── Terminal ─────────────────────────────────────────────────────────────
    terminal_timeout_s: int = 30
    shell: str = "powershell"

    # ─── PyAutoGUI ────────────────────────────────────────────────────────────
    pyautogui_pause_s: float = 0.3
    typing_interval_s: float = 0.04

    # ─── Browser ──────────────────────────────────────────────────────────────
    browser_timeout_s: int = 30

    # ─── Kill Switch ──────────────────────────────────────────────────────────
    kill_switch_corner: str = "top-left"
    kill_switch_margin_px: int = 5
    kill_switch_poll_s: float = 0.2

    # ─── Context / Scope ──────────────────────────────────────────────────────
    context_paths: List[str] = field(default_factory=list)
    context_scope: List[str] = field(default_factory=lambda: [
        "desktop_gui", "browser", "terminal", "file_system"
    ])

    def __post_init__(self):
        """Apply overrides from settings.json if present."""
        s = _load_settings()
        overridable = {
            "screen_width", "screen_height", "screen_scale_pct",
            "max_iterations", "loop_delay_s",
        }
        for key in overridable:
            if key in s:
                try:
                    setattr(self, key, type(getattr(self, key))(s[key]))
                except Exception:
                    pass
