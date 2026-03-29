"""
Overlord Agent — GUI
====================
Industrial command-center. Tabs: Setup | Settings | Agent
Dark charcoal + amber accent. Monospace live log.

New in this version
-------------------
• Compact sidebar mode — when agent runs, window collapses to a 300px strip
  pinned to the right edge of the screen (always-on-top) so you can see your
  desktop while the agent works.
• Cursor-drift detection — if you move the mouse between iterations the agent
  logs a warning and notes it in history so the brain can compensate.
• Task verification — after the agent signals "done" it takes one more
  screenshot and asks Gemini to confirm the task is actually complete.
• Settings tab — set your screen resolution and DPI scale from the GUI; values
  are saved to settings.json so you never need to edit Python files.
"""

import asyncio
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
from typing import Optional

import customtkinter as ctk

# ── project path ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# ── theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── palette ───────────────────────────────────────────────────────────────────
BG_BASE    = "#0e0e0f"
BG_PANEL   = "#161618"
BG_CARD    = "#1c1c1f"
BG_INPUT   = "#111113"
AMBER      = "#f59e0b"
AMBER_DIM  = "#92610a"
AMBER_GLOW = "#fbbf24"
RED        = "#ef4444"
GREEN      = "#22c55e"
MUTED      = "#52525b"
TEXT_PRI   = "#f4f4f5"
TEXT_SEC   = "#a1a1aa"
MONO_FONT  = ("Consolas", 11)
UI_FONT    = ("Segoe UI", 11)

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    existing = load_settings()
    existing.update(data)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(existing, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  Logging bridge
# ─────────────────────────────────────────────────────────────────────────────

class QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._q = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put_nowait(("log", record.levelno, self.format(record)))


# ─────────────────────────────────────────────────────────────────────────────
#  Custom Widgets
# ─────────────────────────────────────────────────────────────────────────────

class StatusLED(ctk.CTkCanvas):
    STATES = {
        "idle":     ("#52525b", False),
        "running":  ("#22c55e", True),
        "thinking": ("#f59e0b", True),
        "error":    ("#ef4444", False),
        "done":     ("#22c55e", False),
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=14, height=14,
                         bg=BG_BASE, highlightthickness=0, **kwargs)
        self._state = "idle"
        self._phase = 0
        self._dot = self.create_oval(2, 2, 12, 12, fill=MUTED, outline="")
        self._animate()

    def set_state(self, state: str) -> None:
        self._state = state
        color, _ = self.STATES.get(state, (MUTED, False))
        self.itemconfig(self._dot, fill=color)

    def _animate(self) -> None:
        color, pulse = self.STATES.get(self._state, (MUTED, False))
        if pulse:
            import math
            self._phase = (self._phase + 8) % 360
            t = (math.sin(math.radians(self._phase)) + 1) / 2
            r1, g1, b1 = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            r = int(r1 * t + 14 * (1 - t))
            g = int(g1 * t + 14 * (1 - t))
            b = int(b1 * t + 15 * (1 - t))
            self.itemconfig(self._dot, fill=f"#{r:02x}{g:02x}{b:02x}")
        self.after(40, self._animate)


class SectionHeader(ctk.CTkLabel):
    def __init__(self, parent, text: str, **kwargs):
        super().__init__(parent, text=text.upper(),
                         font=("Segoe UI", 9, "bold"), text_color=AMBER, **kwargs)


class PathRow(ctk.CTkFrame):
    def __init__(self, parent, path: str, on_remove, **kwargs):
        super().__init__(parent, fg_color=BG_INPUT, corner_radius=6, **kwargs)
        self.path = path
        ctk.CTkLabel(self, text="📁", font=("Segoe UI", 12),
                     text_color=AMBER, width=24).pack(side="left", padx=(8, 4), pady=6)
        ctk.CTkLabel(self, text=path, font=("Consolas", 10),
                     text_color=TEXT_SEC, anchor="w").pack(side="left", fill="x",
                                                            expand=True, pady=6)
        ctk.CTkButton(self, text="✕", width=26, height=22,
                      font=("Segoe UI", 10), fg_color="transparent",
                      hover_color="#3f1212", text_color=RED, corner_radius=4,
                      command=lambda: on_remove(self)).pack(side="right", padx=6, pady=4)


def _sep(parent):
    ctk.CTkFrame(parent, fg_color=BG_CARD, height=1).pack(fill="x", padx=16, pady=2)


# ─────────────────────────────────────────────────────────────────────────────
#  SETUP TAB
# ─────────────────────────────────────────────────────────────────────────────

PACKAGES = [
    ("google-genai",    "Google Gemini AI SDK"),
    ("Pillow",          "Image capture & processing"),
    ("opencv-python",   "Computer vision"),
    ("pyautogui",       "Screen & keyboard control"),
    ("customtkinter",   "Modern GUI toolkit"),
    ("google-auth",     "Vertex AI service account auth"),
]


class SetupTab(ctk.CTkFrame):
    def __init__(self, parent, on_ready_callback, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_ready = on_ready_callback
        self._check_queue: queue.Queue = queue.Queue()
        self._pkg_rows: dict[str, dict] = {}
        self._build()
        self._check_installed()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        hdr.pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(hdr, text="⚙  Environment Setup",
                     font=("Segoe UI Black", 14), text_color=AMBER).pack(
            anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(hdr,
                     text="Install all required packages with one click.",
                     font=("Segoe UI", 10), text_color=TEXT_SEC,
                     wraplength=600, justify="left").pack(
            anchor="w", padx=20, pady=(0, 14))

        pkg_card = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        pkg_card.pack(fill="x", padx=20, pady=8)
        SectionHeader(pkg_card, "Required Packages").pack(anchor="w", padx=16, pady=(12, 8))

        for pkg, desc in PACKAGES:
            row = ctk.CTkFrame(pkg_card, fg_color=BG_CARD, corner_radius=8)
            row.pack(fill="x", padx=16, pady=3)
            status_lbl = ctk.CTkLabel(row, text="⟳", width=28,
                                      font=("Segoe UI", 13), text_color=MUTED)
            status_lbl.pack(side="left", padx=(10, 6), pady=8)
            ctk.CTkLabel(row, text=pkg, font=("Consolas", 11),
                         text_color=TEXT_PRI, width=160, anchor="w").pack(side="left", pady=8)
            ctk.CTkLabel(row, text=desc, font=("Segoe UI", 10),
                         text_color=TEXT_SEC, anchor="w").pack(side="left", fill="x", expand=True, pady=8)
            self._pkg_rows[pkg] = {"row": row, "status": status_lbl}

        chrome_card = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        chrome_card.pack(fill="x", padx=20, pady=8)
        SectionHeader(chrome_card, "Browser").pack(anchor="w", padx=16, pady=(12, 8))
        chrome_row = ctk.CTkFrame(chrome_card, fg_color=BG_CARD, corner_radius=8)
        chrome_row.pack(fill="x", padx=16, pady=(3, 14))
        self._chrome_status = ctk.CTkLabel(chrome_row, text="⟳", width=28,
                                           font=("Segoe UI", 13), text_color=MUTED)
        self._chrome_status.pack(side="left", padx=(10, 6), pady=8)
        ctk.CTkLabel(chrome_row, text="Google Chrome", font=("Consolas", 11),
                     text_color=TEXT_PRI, width=160, anchor="w").pack(side="left", pady=8)
        self._chrome_path_lbl = ctk.CTkLabel(chrome_row, text="Checking...",
                                              font=("Segoe UI", 10), text_color=TEXT_SEC, anchor="w")
        self._chrome_path_lbl.pack(side="left", fill="x", expand=True, pady=8)

        log_card = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        log_card.pack(fill="both", expand=True, padx=20, pady=8)
        SectionHeader(log_card, "Install Log").pack(anchor="w", padx=16, pady=(12, 4))
        self._log = ctk.CTkTextbox(log_card, font=MONO_FONT, fg_color=BG_INPUT,
                                   border_color=AMBER_DIM, border_width=1,
                                   text_color="#d4d4d4", corner_radius=8,
                                   scrollbar_button_color=AMBER_DIM)
        self._log.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self._log.configure(state="disabled")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        self._install_btn = ctk.CTkButton(
            btn_row, text="⬇  Install All Packages", width=200, height=38,
            font=("Segoe UI", 11, "bold"), fg_color=AMBER, hover_color=AMBER_GLOW,
            text_color=BG_BASE, corner_radius=8, command=self._install_all)
        self._install_btn.pack(side="left", padx=(0, 10))
        self._ready_btn = ctk.CTkButton(
            btn_row, text="✓  Go to Agent →", width=160, height=38,
            font=("Segoe UI", 11, "bold"), fg_color=BG_CARD, hover_color="#2a2a2e",
            text_color=MUTED, corner_radius=8, state="disabled", command=self._on_ready)
        self._ready_btn.pack(side="left")
        self._poll_check_queue()

    def _check_installed(self) -> None:
        def worker():
            import importlib
            pkg_map = {
                "google-genai": "google.genai", "Pillow": "PIL",
                "opencv-python": "cv2", "pyautogui": "pyautogui",
                "customtkinter": "customtkinter", "google-auth": "google.auth",
            }
            for pkg, desc in PACKAGES:
                mod = pkg_map.get(pkg, pkg)
                try:
                    importlib.import_module(mod)
                    self._check_queue.put_nowait(("pkg", pkg, "ok"))
                except ImportError:
                    self._check_queue.put_nowait(("pkg", pkg, "missing"))
            try:
                from agent.browser import _find_chrome
                chrome = _find_chrome()
            except Exception:
                chrome = None
            self._check_queue.put_nowait(("chrome", chrome or "", ""))
            self._check_queue.put_nowait(("check_done", "", ""))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_check_queue(self) -> None:
        try:
            while True:
                kind, name, status = self._check_queue.get_nowait()
                if kind == "pkg":
                    self._set_pkg_status(name, status)
                elif kind == "chrome":
                    self._set_chrome_status(name)
                elif kind == "log":
                    self._append_log(status)
                elif kind == "install_done":
                    self._on_install_done()
                elif kind == "check_done":
                    self._check_ready()
        except queue.Empty:
            pass
        self.after(100, self._poll_check_queue)

    def _set_pkg_status(self, pkg: str, status: str) -> None:
        row = self._pkg_rows.get(pkg)
        if not row:
            return
        lbl = row["status"]
        if status == "ok":
            lbl.configure(text="✓", text_color=GREEN)
        else:
            lbl.configure(text="✗", text_color=RED)

    def _set_chrome_status(self, path: str) -> None:
        if path:
            self._chrome_status.configure(text="✓", text_color=GREEN)
            self._chrome_path_lbl.configure(text=path, text_color=GREEN)
        else:
            self._chrome_status.configure(text="✗", text_color=RED)
            self._chrome_path_lbl.configure(
                text="Not found — download from google.com/chrome", text_color=RED)

    def _check_ready(self) -> None:
        all_ok = all(
            self._pkg_rows[pkg]["status"].cget("text") == "✓"
            for pkg, _ in PACKAGES
        )
        if all_ok:
            self._ready_btn.configure(state="normal", text_color=TEXT_PRI,
                                      fg_color=GREEN, hover_color="#16a34a",
                                      text_color_disabled=BG_BASE)
            self._append_log("✅ All packages installed. Ready to run!")

    def _install_all(self) -> None:
        self._install_btn.configure(state="disabled", text="Installing…")
        self._append_log("Starting installation…\n")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self) -> None:
        req = os.path.join(os.path.dirname(__file__), "requirements.txt")
        cmd = [sys.executable, "-m", "pip", "install", "-r", req, "--upgrade"]
        self._append_log(f"Running: {' '.join(cmd)}\n")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            for line in proc.stdout:
                self._check_queue.put_nowait(("log", "", line.rstrip()))
            proc.wait()
            if proc.returncode == 0:
                self._check_queue.put_nowait(("log", "", "\n✅ Installation complete!"))
            else:
                self._check_queue.put_nowait(("log", "", f"\n❌ pip exited with code {proc.returncode}"))
        except Exception as exc:
            self._check_queue.put_nowait(("log", "", f"\n❌ Error: {exc}"))
        self._check_queue.put_nowait(("install_done", "", ""))

    def _on_install_done(self) -> None:
        self._install_btn.configure(state="normal", text="⬇  Install All Packages")
        self._check_installed()

    def _append_log(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.configure(state="disabled")
        self._log.see("end")


# ─────────────────────────────────────────────────────────────────────────────
#  SETTINGS TAB
# ─────────────────────────────────────────────────────────────────────────────

class SettingsTab(ctk.CTkFrame):
    """
    GUI settings for display calibration and agent behaviour.
    Values are saved to settings.json and loaded by Config on next run.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._saved_lbl = None
        self._build()
        self._load()

    def _build(self) -> None:
        # ── Display calibration ───────────────────────────────────────────────
        disp = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        disp.pack(fill="x", padx=20, pady=(20, 8))

        ctk.CTkLabel(disp, text="🖥  Display Calibration",
                     font=("Segoe UI Black", 14), text_color=AMBER).pack(
            anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(disp,
                     text="Set your exact screen resolution and Windows display scale.\n"
                          "These values fix cursor click accuracy — especially on HiDPI displays.",
                     font=("Segoe UI", 10), text_color=TEXT_SEC,
                     wraplength=660, justify="left").pack(anchor="w", padx=20, pady=(0, 14))

        grid = ctk.CTkFrame(disp, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(0, 18))
        grid.grid_columnconfigure((0, 2, 4), weight=0)
        grid.grid_columnconfigure((1, 3, 5), weight=1)

        # Resolution
        ctk.CTkLabel(grid, text="Screen Width (px)", font=("Segoe UI", 10),
                     text_color=TEXT_SEC).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        self._res_w = ctk.CTkEntry(grid, width=100, font=MONO_FONT, fg_color=BG_INPUT,
                                   border_color=AMBER_DIM, text_color=TEXT_PRI, corner_radius=6)
        self._res_w.grid(row=0, column=1, sticky="w", padx=(0, 24), pady=6)

        ctk.CTkLabel(grid, text="Screen Height (px)", font=("Segoe UI", 10),
                     text_color=TEXT_SEC).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=6)
        self._res_h = ctk.CTkEntry(grid, width=100, font=MONO_FONT, fg_color=BG_INPUT,
                                   border_color=AMBER_DIM, text_color=TEXT_PRI, corner_radius=6)
        self._res_h.grid(row=0, column=3, sticky="w", padx=(0, 24), pady=6)

        # Scale
        ctk.CTkLabel(grid, text="Display Scale (%)", font=("Segoe UI", 10),
                     text_color=TEXT_SEC).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        self._scale_entry = ctk.CTkEntry(grid, width=100, font=MONO_FONT, fg_color=BG_INPUT,
                                          border_color=AMBER_DIM, text_color=TEXT_PRI,
                                          corner_radius=6, placeholder_text="e.g. 125")
        self._scale_entry.grid(row=1, column=1, sticky="w", padx=(0, 24), pady=6)

        ctk.CTkLabel(grid, text="(0 = auto-detect)", font=("Segoe UI", 9),
                     text_color=MUTED).grid(row=1, column=2, sticky="w", pady=6)

        # Common presets
        presets_f = ctk.CTkFrame(disp, fg_color=BG_CARD, corner_radius=8)
        presets_f.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkLabel(presets_f, text="Quick presets:", font=("Segoe UI", 9),
                     text_color=MUTED).pack(side="left", padx=(12, 8), pady=8)
        for label, w, h, s in [
            ("1920×1080 @ 100%", 1920, 1080, 100),
            ("1920×1080 @ 125%", 1920, 1080, 125),
            ("1920×1080 @ 150%", 1920, 1080, 150),
            ("2560×1440 @ 125%", 2560, 1440, 125),
            ("3840×2160 @ 150%", 3840, 2160, 150),
        ]:
            ctk.CTkButton(presets_f, text=label, width=160, height=26,
                          font=("Segoe UI", 9), fg_color=BG_INPUT,
                          hover_color=AMBER_DIM, text_color=TEXT_SEC, corner_radius=4,
                          command=lambda _w=w, _h=h, _s=s: self._apply_preset(_w, _h, _s)
                          ).pack(side="left", padx=4, pady=6)

        # ── Agent behaviour ───────────────────────────────────────────────────
        behav = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        behav.pack(fill="x", padx=20, pady=8)

        ctk.CTkLabel(behav, text="🤖  Agent Behaviour",
                     font=("Segoe UI Black", 14), text_color=AMBER).pack(
            anchor="w", padx=20, pady=(14, 2))

        bg = ctk.CTkFrame(behav, fg_color="transparent")
        bg.pack(fill="x", padx=20, pady=(4, 18))
        bg.grid_columnconfigure((0, 2), weight=0)
        bg.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(bg, text="Max Iterations", font=("Segoe UI", 10),
                     text_color=TEXT_SEC).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        self._max_iter = ctk.CTkEntry(bg, width=80, font=MONO_FONT, fg_color=BG_INPUT,
                                      border_color=AMBER_DIM, text_color=TEXT_PRI, corner_radius=6)
        self._max_iter.grid(row=0, column=1, sticky="w", padx=(0, 24), pady=6)

        ctk.CTkLabel(bg, text="Loop Delay (s)", font=("Segoe UI", 10),
                     text_color=TEXT_SEC).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=6)
        self._loop_delay = ctk.CTkEntry(bg, width=80, font=MONO_FONT, fg_color=BG_INPUT,
                                        border_color=AMBER_DIM, text_color=TEXT_PRI, corner_radius=6)
        self._loop_delay.grid(row=0, column=3, sticky="w", pady=6)

        # Checkboxes
        chk_f = ctk.CTkFrame(behav, fg_color="transparent")
        chk_f.pack(fill="x", padx=20, pady=(0, 18))
        self._cursor_protect = tk.BooleanVar(value=True)
        self._task_verify    = tk.BooleanVar(value=True)
        self._compact_mode   = tk.BooleanVar(value=True)
        for var, label, hint in [
            (self._cursor_protect, "Cursor drift detection",
             "Warn in log if mouse is moved during agent operation"),
            (self._task_verify,    "Task verification screenshot",
             "After agent signals done, take a final screenshot to confirm"),
            (self._compact_mode,   "Compact sidebar while running",
             "Collapse GUI to a side strip so the desktop is visible"),
        ]:
            row = ctk.CTkFrame(chk_f, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkCheckBox(row, text=label, variable=var,
                            font=("Segoe UI", 10), text_color=TEXT_PRI,
                            fg_color=AMBER, hover_color=AMBER_DIM,
                            checkmark_color=BG_BASE, corner_radius=4).pack(side="left")
            ctk.CTkLabel(row, text=hint, font=("Segoe UI", 9),
                         text_color=MUTED).pack(side="left", padx=12)

        # ── Save ─────────────────────────────────────────────────────────────
        save_row = ctk.CTkFrame(self, fg_color="transparent")
        save_row.pack(fill="x", padx=20, pady=(4, 20))

        ctk.CTkButton(save_row, text="💾  Save Settings", width=160, height=38,
                      font=("Segoe UI", 11, "bold"), fg_color=AMBER, hover_color=AMBER_GLOW,
                      text_color=BG_BASE, corner_radius=8, command=self._save).pack(side="left")

        self._saved_lbl = ctk.CTkLabel(save_row, text="", font=("Segoe UI", 10),
                                        text_color=GREEN)
        self._saved_lbl.pack(side="left", padx=16)

    def _apply_preset(self, w: int, h: int, s: int) -> None:
        self._res_w.delete(0, "end"); self._res_w.insert(0, str(w))
        self._res_h.delete(0, "end"); self._res_h.insert(0, str(h))
        self._scale_entry.delete(0, "end"); self._scale_entry.insert(0, str(s))

    def _load(self) -> None:
        s = load_settings()
        if "screen_width"  in s: self._res_w.insert(0, str(s["screen_width"]))
        if "screen_height" in s: self._res_h.insert(0, str(s["screen_height"]))
        if "screen_scale_pct" in s: self._scale_entry.insert(0, str(s["screen_scale_pct"]))
        if "max_iterations"   in s: self._max_iter.insert(0, str(s["max_iterations"]))
        if "loop_delay_s"     in s: self._loop_delay.insert(0, str(s["loop_delay_s"]))
        self._cursor_protect.set(s.get("cursor_protect", True))
        self._task_verify.set(s.get("task_verify", True))
        self._compact_mode.set(s.get("compact_mode", True))

    def _save(self) -> None:
        data = {}
        try: data["screen_width"] = int(self._res_w.get())
        except ValueError: pass
        try: data["screen_height"] = int(self._res_h.get())
        except ValueError: pass
        try: data["screen_scale_pct"] = int(self._scale_entry.get())
        except ValueError: pass
        try: data["max_iterations"] = int(self._max_iter.get())
        except ValueError: pass
        try: data["loop_delay_s"] = float(self._loop_delay.get())
        except ValueError: pass
        data["cursor_protect"] = self._cursor_protect.get()
        data["task_verify"]    = self._task_verify.get()
        data["compact_mode"]   = self._compact_mode.get()
        save_settings(data)
        if self._saved_lbl:
            self._saved_lbl.configure(text="✓ Saved!")
            self.after(2500, lambda: self._saved_lbl.configure(text=""))

    def get_flags(self) -> dict:
        return {
            "cursor_protect": self._cursor_protect.get(),
            "task_verify":    self._task_verify.get(),
            "compact_mode":   self._compact_mode.get(),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  AGENT TAB
# ─────────────────────────────────────────────────────────────────────────────

class AgentTab(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._log_queue: queue.Queue = queue.Queue()
        self._agent_thread: Optional[threading.Thread] = None
        self._kill_switch = None
        self._stop_event = threading.Event()
        self._path_rows: list[PathRow] = []
        self._iteration = 0
        self._max_iter = 50
        self._action_count = 0
        self._on_start_cb = None   # set by OverlordGUI for compact mode
        self._on_done_cb  = None

        self._setup_logging()
        self._build()
        self._poll_log_queue()

    def _setup_logging(self) -> None:
        handler = QueueHandler(self._log_queue)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.handlers = [h for h in root.handlers if isinstance(h, QueueHandler)]
        root.addHandler(handler)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=4, minsize=340)
        self.grid_columnconfigure(1, weight=6)
        self.grid_rowconfigure(0, weight=1)
        self._build_left()
        self._build_right()
        self._build_bottom()

    def _build_left(self) -> None:
        panel = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(4, 8), pady=(8, 0))
        panel.grid_rowconfigure(2, weight=1)

        SectionHeader(panel, "Task Prompt").pack(anchor="w", padx=16, pady=(14, 4))
        self._task_box = ctk.CTkTextbox(
            panel, height=110, font=UI_FONT, fg_color=BG_INPUT,
            border_color=AMBER_DIM, border_width=1, text_color=TEXT_PRI,
            corner_radius=8, wrap="word", scrollbar_button_color=AMBER_DIM)
        self._task_box.pack(fill="x", padx=16, pady=(0, 2))
        self._task_box.insert("0.0", "Open Chrome, search for Python docs, and screenshot the result")
        self._char_lbl = ctk.CTkLabel(panel, text="", font=("Segoe UI", 9), text_color=MUTED)
        self._char_lbl.pack(anchor="e", padx=18, pady=(0, 6))
        self._task_box.bind("<KeyRelease>", self._update_chars)

        _sep(panel)

        SectionHeader(panel, "Context Scope").pack(anchor="w", padx=16, pady=(10, 6))
        sf = ctk.CTkFrame(panel, fg_color="transparent")
        sf.pack(fill="x", padx=16, pady=(0, 4))
        self._scope_vars = {}
        scopes = [
            ("desktop_gui", "🖥  Desktop GUI",  True),
            ("browser",     "🌐  Chrome",        True),
            ("terminal",    "💻  Terminal",      True),
            ("file_system", "📂  File System",   True),
        ]
        for i, (key, label, default) in enumerate(scopes):
            var = tk.BooleanVar(value=default)
            self._scope_vars[key] = var
            ctk.CTkCheckBox(sf, text=label, variable=var,
                            font=("Segoe UI", 10), text_color=TEXT_SEC,
                            fg_color=AMBER, hover_color=AMBER_DIM,
                            checkmark_color=BG_BASE, corner_radius=4
                            ).grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=3)

        _sep(panel)

        lhdr = ctk.CTkFrame(panel, fg_color="transparent")
        lhdr.pack(fill="x", padx=16, pady=(10, 4))
        SectionHeader(lhdr, "Locations & Directories").pack(side="left")
        self._loc_badge = ctk.CTkLabel(lhdr, text="0", font=("Segoe UI", 9, "bold"),
                                       text_color=AMBER_GLOW, fg_color=AMBER_DIM,
                                       corner_radius=10, width=20, height=18)
        self._loc_badge.pack(side="left", padx=6)

        self._path_list = ctk.CTkScrollableFrame(
            panel, fg_color=BG_INPUT, corner_radius=8, scrollbar_button_color=AMBER_DIM)
        self._path_list.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        add_f = ctk.CTkFrame(panel, fg_color="transparent")
        add_f.pack(fill="x", padx=16, pady=(0, 14))
        self._path_entry = ctk.CTkEntry(
            add_f, placeholder_text="C:\\path\\to\\directory",
            font=("Consolas", 10), fg_color=BG_INPUT,
            border_color=MUTED, text_color=TEXT_PRI, corner_radius=6)
        self._path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(add_f, text="Browse", width=70, height=32,
                      font=("Segoe UI", 10), fg_color=BG_CARD,
                      hover_color="#2a2a2e", text_color=TEXT_SEC,
                      corner_radius=6, command=self._browse).pack(side="left", padx=(0, 4))
        ctk.CTkButton(add_f, text="+ Add", width=60, height=32,
                      font=("Segoe UI", 10, "bold"), fg_color=AMBER_DIM, hover_color=AMBER,
                      text_color=BG_BASE, corner_radius=6, command=self._add_from_entry).pack(side="left")

    def _build_right(self) -> None:
        panel = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=(8, 0))
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        stats = ctk.CTkFrame(panel, fg_color=BG_CARD, corner_radius=8)
        stats.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        defs = [
            ("ITERATION", "0 / 50", "_iter_lbl"),
            ("ACTIONS",   "0",      "_act_lbl"),
            ("LAST ACTION", "—",    "_last_lbl"),
        ]
        for i, (title, init, attr) in enumerate(defs):
            f = ctk.CTkFrame(stats, fg_color="transparent")
            f.pack(side="left", expand=True, fill="x", padx=16, pady=8)
            ctk.CTkLabel(f, text=title, font=("Segoe UI", 8), text_color=MUTED).pack(anchor="w")
            lbl = ctk.CTkLabel(f, text=init, font=("Segoe UI", 11, "bold"), text_color=AMBER_GLOW)
            lbl.pack(anchor="w")
            setattr(self, attr, lbl)
            if i < len(defs) - 1:
                ctk.CTkFrame(stats, fg_color=BG_INPUT, width=1, height=40).pack(side="left")

        lhdr = ctk.CTkFrame(panel, fg_color="transparent")
        lhdr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 4))
        SectionHeader(lhdr, "Live Log").pack(side="left")
        self._autoscroll = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(lhdr, text="Auto-scroll", variable=self._autoscroll,
                        font=("Segoe UI", 9), text_color=MUTED,
                        fg_color=AMBER, hover_color=AMBER_DIM,
                        checkmark_color=BG_BASE, corner_radius=4,
                        width=16, height=16).pack(side="right")

        self._log_box = ctk.CTkTextbox(
            panel, font=MONO_FONT, fg_color=BG_INPUT,
            border_color=AMBER_DIM, border_width=1,
            text_color="#d4d4d4", corner_radius=8,
            scrollbar_button_color=AMBER_DIM, wrap="none")
        self._log_box.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 14))
        self._log_box.configure(state="disabled")
        tb = self._log_box._textbox
        tb.tag_config("DEBUG",   foreground="#52525b")
        tb.tag_config("INFO",    foreground="#d4d4d4")
        tb.tag_config("WARNING", foreground="#f59e0b")
        tb.tag_config("ERROR",   foreground="#ef4444")
        tb.tag_config("TS",      foreground="#3f3f46")
        tb.tag_config("VERIFY",  foreground="#22c55e")

    def _build_bottom(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=60)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bar.pack_propagate(False)

        bf = ctk.CTkFrame(bar, fg_color="transparent")
        bf.pack(side="left", padx=16, pady=12)

        self._run_btn = ctk.CTkButton(
            bf, text="▶  RUN TASK", width=140, height=36,
            font=("Segoe UI", 11, "bold"), fg_color=AMBER, hover_color=AMBER_GLOW,
            text_color=BG_BASE, corner_radius=8, command=self._start)
        self._run_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            bf, text="■  STOP", width=90, height=36,
            font=("Segoe UI", 11, "bold"), fg_color=BG_CARD, hover_color="#3f1212",
            text_color=RED, corner_radius=8, border_width=1, border_color="#3f1212",
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            bf, text="✕  Clear Log", width=100, height=36,
            font=("Segoe UI", 10), fg_color="transparent",
            hover_color=BG_CARD, text_color=MUTED, corner_radius=8,
            command=self._clear_log).pack(side="left")

        pf = ctk.CTkFrame(bar, fg_color="transparent")
        pf.pack(side="right", padx=16, pady=12)
        self._prog_lbl = ctk.CTkLabel(pf, text="0%", font=("Segoe UI", 9), text_color=MUTED)
        self._prog_lbl.pack()
        self._progress = ctk.CTkProgressBar(pf, width=180, fg_color=BG_CARD,
                                             progress_color=AMBER, corner_radius=4)
        self._progress.pack()
        self._progress.set(0)

    # ── log polling ───────────────────────────────────────────────────────────

    def _poll_log_queue(self) -> None:
        try:
            while True:
                kind, level, msg = self._log_queue.get_nowait()
                if kind == "log":
                    self._append_log(level, msg)
                elif kind == "iteration":
                    self._on_iteration(level)
                elif kind == "action":
                    self._last_lbl.configure(text=msg[:22])
        except queue.Empty:
            pass
        self.after(80, self._poll_log_queue)

    def _append_log(self, level: int, msg: str) -> None:
        import logging as _l
        tag = _l.getLevelName(level)
        self._log_box.configure(state="normal")
        tb = self._log_box._textbox
        parts = msg.split("  ", 2)
        if len(parts) == 3:
            ts, lvl, body = parts
            tb.insert("end", ts + "  ", "TS")
            tb.insert("end", f"{lvl:<5}  ", tag)
            tb.insert("end", body + "\n", tag)
        else:
            tb.insert("end", msg + "\n", tag)
        self._log_box.configure(state="disabled")
        if self._autoscroll.get():
            self._log_box._textbox.see("end")

    # ── paths ─────────────────────────────────────────────────────────────────

    def _add_path(self, path: str) -> None:
        path = path.strip()
        if not path or path in [r.path for r in self._path_rows]:
            return
        row = PathRow(self._path_list, path, on_remove=self._remove_row)
        row.pack(fill="x", pady=2)
        self._path_rows.append(row)
        self._loc_badge.configure(text=str(len(self._path_rows)))

    def _remove_row(self, row: PathRow) -> None:
        row.pack_forget(); row.destroy()
        self._path_rows = [r for r in self._path_rows if r.winfo_exists()]
        self._loc_badge.configure(text=str(len(self._path_rows)))

    def _add_from_entry(self) -> None:
        self._add_path(self._path_entry.get()); self._path_entry.delete(0, "end")

    def _browse(self) -> None:
        p = filedialog.askdirectory(title="Select Directory")
        if p:
            self._add_path(p)

    # ── agent control ─────────────────────────────────────────────────────────

    def start_with_key(self, api_key: str) -> None:
        self._api_key = api_key
        self._start()

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def _start(self) -> None:
        from config import Config as _Cfg
        _use_vertex = _Cfg().use_vertex

        api_key = getattr(self, "_api_key", "")
        if not _use_vertex and not api_key:
            self._append_log(40, "00:00:00  ERROR  No API key — enter it in the top bar")
            return
        task = self._task_box.get("0.0", "end").strip()
        if not task:
            return
        active_scope = [k for k, v in self._scope_vars.items() if v.get()]
        paths = [r.path for r in self._path_rows if r.winfo_exists()]

        self._iteration = 0; self._action_count = 0
        self._progress.set(0); self._prog_lbl.configure(text="0%")
        self._iter_lbl.configure(text=f"0 / {self._max_iter}")
        self._act_lbl.configure(text="0")
        self._run_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")

        if api_key:
            os.environ["GEMINI_API_KEY"] = api_key

        # Notify parent for compact mode
        if self._on_start_cb:
            self._on_start_cb(task)

        self._stop_event.clear()
        self._agent_thread = threading.Thread(
            target=self._run_thread,
            args=(task, api_key, active_scope, paths),
            daemon=True)
        self._agent_thread.start()

    def _stop(self) -> None:
        self._stop_event.set()
        if self._kill_switch:
            self._kill_switch.triggered = True
        self._run_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")

    def _run_thread(self, task, api_key, scope, paths) -> None:
        try:
            from config import Config
            from utils.kill_switch import KillSwitch, AgentAborted

            cfg = Config()
            cfg.gemini_api_key = api_key
            cfg.context_paths  = paths
            cfg.context_scope  = scope
            self._max_iter     = cfg.max_iterations

            # Read behaviour flags from settings
            s = load_settings()
            flags = {
                "cursor_protect": s.get("cursor_protect", True),
                "task_verify":    s.get("task_verify", True),
            }

            ks = KillSwitch(margin_px=cfg.kill_switch_margin_px,
                            poll_s=cfg.kill_switch_poll_s)
            self._kill_switch = ks

            loop = _InstrumentedLoop(cfg, ks, self._log_queue, self._stop_event, flags)
            ks.start()
            asyncio.run(loop.run(task))
        except Exception as exc:
            logging.critical("💥 %s", exc, exc_info=True)
        finally:
            if self._kill_switch:
                self._kill_switch.stop()
            self.after(0, self._on_agent_done)

    def _on_agent_done(self) -> None:
        self._run_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        if self._on_done_cb:
            self._on_done_cb()

    def _on_iteration(self, i: int) -> None:
        self._iteration = i
        frac = i / self._max_iter
        self._progress.set(frac)
        self._prog_lbl.configure(text=f"{int(frac * 100)}%")
        self._iter_lbl.configure(text=f"{i} / {self._max_iter}")
        self._action_count += 1
        self._act_lbl.configure(text=str(self._action_count))

    def _update_chars(self, _=None) -> None:
        n = len(self._task_box.get("0.0", "end").strip())
        self._char_lbl.configure(text=f"{n} chars")

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("0.0", "end")
        self._log_box.configure(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
#  Instrumented ReAct Loop
# ─────────────────────────────────────────────────────────────────────────────

class _InstrumentedLoop:
    """Thin wrapper around ReActLoop that feeds events to the GUI queue."""

    def __init__(self, config, kill_switch, gui_queue: queue.Queue,
                 stop_event: threading.Event, flags: dict) -> None:
        from agent.react_loop import ReActLoop
        self._inner = ReActLoop(config, kill_switch)
        self._gui_q = gui_queue
        self._stop  = stop_event
        self._cfg   = config
        self._ks    = kill_switch
        self._flags = flags
        self._inner_obj = self._inner

    async def run(self, task: str) -> str:
        import logging
        import pyautogui
        from utils.kill_switch import AgentAborted
        logger = logging.getLogger("overlord")
        logger.info("=" * 55)
        logger.info("🎯 TASK: %s", task)
        logger.info("=" * 55)

        obj = self._inner_obj
        iteration   = 0
        fail_streak = 0
        last_cursor = None      # track cursor between iterations

        try:
            while iteration < self._cfg.max_iterations:
                if self._stop.is_set():
                    raise AgentAborted("Stop button pressed")

                iteration += 1
                self._gui_q.put_nowait(("iteration", iteration, ""))
                logger.info("── Iteration %d / %d ──", iteration, self._cfg.max_iterations)

                self._ks.check()

                # ── Cursor drift detection ─────────────────────────────────
                if self._flags.get("cursor_protect") and last_cursor is not None:
                    try:
                        cur = pyautogui.position()
                        dx = abs(cur.x - last_cursor[0])
                        dy = abs(cur.y - last_cursor[1])
                        if dx > 40 or dy > 40:
                            logger.warning(
                                "⚠️  Cursor drifted — expected (%d,%d) found (%d,%d)."
                                " Did you move the mouse? Agent will compensate.",
                                last_cursor[0], last_cursor[1], cur.x, cur.y)
                            obj._history.append({
                                "action": "system_note",
                                "reason": f"User moved cursor from {last_cursor} to ({cur.x},{cur.y})",
                                "result": "cursor drift detected"
                            })
                    except Exception:
                        pass

                # ── Screenshot ────────────────────────────────────────────
                try:
                    capture = obj._eyes.capture()
                except Exception as exc:
                    logger.error("👁 Screenshot failed: %s", exc)
                    fail_streak += 1
                    if fail_streak >= self._cfg.retry_on_fail:
                        return "ABORTED: screenshot failed"
                    await asyncio.sleep(self._cfg.loop_delay_s)
                    continue

                # ── Brain ─────────────────────────────────────────────────
                try:
                    command = obj._brain.reason(
                        capture, task, obj._history,
                        context_paths=self._cfg.context_paths,
                        context_scope=self._cfg.context_scope,
                    )
                except ValueError as exc:
                    logger.warning("🧠 JSON error: %s", exc)
                    fail_streak += 1
                    if fail_streak >= self._cfg.retry_on_fail:
                        return "ABORTED: bad JSON"
                    await asyncio.sleep(self._cfg.loop_delay_s)
                    continue

                action = command.get("action", "unknown")
                reason = command.get("reason", "")
                thought = command.get("thought", "")
                self._gui_q.put_nowait(("action", 0, action))
                logger.info("🧠 action=%s  %s", action, reason)
                if thought:
                    logger.debug("💭 %s", thought)

                # ── Dispatch ──────────────────────────────────────────────
                try:
                    result = await obj._dispatch(command)
                    fail_streak = 0
                except AgentAborted:
                    raise
                except Exception as exc:
                    result = f"[error] {exc}"
                    fail_streak += 1
                    logger.error("❌ streak=%d: %s", fail_streak, exc, exc_info=True)
                    if fail_streak >= self._cfg.retry_on_fail:
                        return "ABORTED: too many failures"

                logger.info("✅ %s", result)
                obj._history.append({"action": action, "reason": reason, "result": result})

                # Record cursor after action for drift detection next iteration
                try:
                    pos = pyautogui.position()
                    last_cursor = (pos.x, pos.y)
                except Exception:
                    last_cursor = None

                # ── Task complete? ─────────────────────────────────────────
                if command.get("is_complete", False) or action == "done":
                    logger.info("🏁 Agent signalled task complete.")

                    # ── Verification screenshot ────────────────────────────
                    if self._flags.get("task_verify"):
                        logger.info("🔍 Running verification screenshot…")
                        try:
                            verify_capture = obj._eyes.capture()
                            verified, v_reason = obj._brain.verify(verify_capture, task)
                            if verified:
                                logger.info(
                                    "✅ VERIFIED: Task confirmed complete. %s", v_reason)
                            else:
                                logger.warning(
                                    "⚠️  VERIFICATION FAILED: %s — continuing to fix…", v_reason)
                                # Don't return; inject a note and keep going
                                obj._history.append({
                                    "action": "verification_failed",
                                    "reason": v_reason,
                                    "result": "task not visually confirmed — retry"
                                })
                                await asyncio.sleep(self._cfg.loop_delay_s)
                                continue
                        except Exception as ve:
                            logger.warning("🔍 Verification error (skipping): %s", ve)

                    return f"DONE: {reason or result}"

                await asyncio.sleep(self._cfg.loop_delay_s)

            return f"STOPPED: max_iterations={self._cfg.max_iterations}"

        finally:
            await obj._browser.close()


# ─────────────────────────────────────────────────────────────────────────────
#  COMPACT SIDEBAR  (shown while agent is running)
# ─────────────────────────────────────────────────────────────────────────────

class CompactSidebar(ctk.CTkToplevel):
    """
    A narrow always-on-top sidebar that shows agent status while
    the main window is hidden, so the desktop is fully visible.
    """

    def __init__(self, master, task: str, stop_callback, led_source) -> None:
        super().__init__(master)
        self.overrideredirect(True)          # no window chrome
        self.attributes("-topmost", True)
        self.configure(fg_color=BG_PANEL)
        self.resizable(False, False)

        self._stop_cb = stop_callback
        self._led_src = led_source           # AgentTab reference for stats

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = 290
        self.geometry(f"{w}x{sh}+{sw - w}+0")

        self._build(task)
        self._poll()

    def _build(self, task: str) -> None:
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self._led = StatusLED(hdr)
        self._led.pack(side="left", padx=(12, 6), pady=15)
        ctk.CTkLabel(hdr, text="OVERLORD", font=("Segoe UI Black", 12),
                     text_color=AMBER).pack(side="left")
        ctk.CTkLabel(hdr, text=" AGENT", font=("Segoe UI", 12),
                     text_color=TEXT_SEC).pack(side="left")

        # Drag handle (click and drag title bar area to move)
        hdr.bind("<ButtonPress-1>",   self._drag_start)
        hdr.bind("<B1-Motion>",       self._drag_motion)

        # Task
        ctk.CTkFrame(self, fg_color=AMBER_DIM, height=1).pack(fill="x")
        task_f = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        task_f.pack(fill="x")
        ctk.CTkLabel(task_f, text="TASK", font=("Segoe UI", 8, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(task_f, text=task[:120] + ("…" if len(task) > 120 else ""),
                     font=("Segoe UI", 9), text_color=TEXT_SEC,
                     wraplength=260, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        # Stats
        ctk.CTkFrame(self, fg_color=AMBER_DIM, height=1).pack(fill="x")
        stats_f = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        stats_f.pack(fill="x", pady=8)

        for label, attr in [("ITERATION", "_s_iter"), ("ACTIONS", "_s_act"), ("LAST", "_s_last")]:
            row = ctk.CTkFrame(stats_f, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=label, font=("Segoe UI", 8),
                         text_color=MUTED, width=70, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(row, text="—", font=("Consolas", 10, "bold"),
                               text_color=AMBER_GLOW, anchor="w")
            lbl.pack(side="left")
            setattr(self, attr, lbl)

        # Mini log
        ctk.CTkFrame(self, fg_color=AMBER_DIM, height=1).pack(fill="x")
        ctk.CTkLabel(self, text="LIVE LOG", font=("Segoe UI", 8, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=12, pady=(8, 2))
        self._mini_log = ctk.CTkTextbox(self, font=("Consolas", 9), fg_color=BG_INPUT,
                                        text_color="#a1a1aa", corner_radius=6,
                                        wrap="word", border_width=0)
        self._mini_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._mini_log.configure(state="disabled")

        # Stop button
        ctk.CTkFrame(self, fg_color=AMBER_DIM, height=1).pack(fill="x")
        ctk.CTkButton(self, text="■  STOP AGENT", height=44,
                      font=("Segoe UI", 11, "bold"), fg_color="#3f1212",
                      hover_color="#6b1d1d", text_color=RED, corner_radius=0,
                      command=self._stop).pack(fill="x")

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_motion(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def _stop(self) -> None:
        if self._stop_cb:
            self._stop_cb()

    def _poll(self) -> None:
        """Sync stats from the AgentTab."""
        try:
            src = self._led_src
            if src:
                self._s_iter.configure(text=src._iter_lbl.cget("text"))
                self._s_act.configure( text=src._act_lbl.cget("text"))
                self._s_last.configure(text=src._last_lbl.cget("text")[:20])
                is_running = (getattr(src, "_agent_thread", None) and
                              src._agent_thread.is_alive())
                self._led.set_state("running" if is_running else "done")

                # Mirror last log line into mini log
                tb = src._log_box._textbox
                last = tb.get("end-2l", "end-1l").strip()
                if last:
                    self._mini_log.configure(state="normal")
                    cur = self._mini_log.get("0.0", "end").strip()
                    if last not in cur[-200:]:
                        self._mini_log.insert("end", last + "\n")
                        self._mini_log.see("end")
                    self._mini_log.configure(state="disabled")
        except Exception:
            pass
        self.after(300, self._poll)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class OverlordGUI(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Overlord Agent")
        self.geometry("1260x820")
        self.minsize(900, 660)
        self.configure(fg_color=BG_BASE)
        self._compact_sidebar: Optional[CompactSidebar] = None
        self._normal_geometry = "1260x820"
        self._build()

    def _build(self) -> None:
        # ── Top bar ───────────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        logo_f = ctk.CTkFrame(topbar, fg_color="transparent")
        logo_f.pack(side="left", padx=20, fill="y")
        self._led = StatusLED(logo_f)
        self._led.pack(side="left", padx=(0, 10), pady=18)
        ctk.CTkLabel(logo_f, text="OVERLORD", font=("Segoe UI Black", 15),
                     text_color=AMBER).pack(side="left")
        ctk.CTkLabel(logo_f, text=" AGENT", font=("Segoe UI", 15),
                     text_color=TEXT_SEC).pack(side="left")

        right_f = ctk.CTkFrame(topbar, fg_color="transparent")
        right_f.pack(side="right", padx=20, fill="y")

        from config import Config as _Cfg
        if _Cfg().use_vertex:
            ctk.CTkLabel(right_f, text="🔑 Vertex AI  |  my-project-1598000",
                         font=("Segoe UI", 9), text_color=MUTED).pack(
                side="right", pady=16, padx=(8, 0))
            self._api_var = tk.StringVar(value="")
        else:
            ctk.CTkLabel(right_f, text="GEMINI API KEY",
                         font=("Segoe UI", 9), text_color=MUTED).pack(
                side="right", pady=16, padx=(8, 0))
            self._api_var = tk.StringVar(value=os.environ.get("GEMINI_API_KEY", ""))
            ctk.CTkEntry(right_f, textvariable=self._api_var, show="•",
                         width=240, height=30, font=MONO_FONT,
                         fg_color=BG_INPUT, border_color=AMBER_DIM,
                         text_color=TEXT_PRI, corner_radius=6).pack(
                side="right", padx=(0, 6), pady=11)

        ctk.CTkButton(right_f, text="▶ RUN", width=80, height=30,
                      font=("Segoe UI", 10, "bold"), fg_color=AMBER, hover_color=AMBER_GLOW,
                      text_color=BG_BASE, corner_radius=6,
                      command=self._topbar_run).pack(side="right", padx=(0, 12), pady=11)

        # ── Tab view ──────────────────────────────────────────────────────────
        tabview = ctk.CTkTabview(self, fg_color=BG_BASE,
                                 segmented_button_fg_color=BG_PANEL,
                                 segmented_button_selected_color=AMBER,
                                 segmented_button_selected_hover_color=AMBER_GLOW,
                                 segmented_button_unselected_color=BG_PANEL,
                                 segmented_button_unselected_hover_color=BG_CARD,
                                 text_color=TEXT_PRI, text_color_disabled=MUTED)
        tabview.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        tabview.add("⚙  Setup")
        tabview.add("⚡  Settings")
        tabview.add("🤖  Agent")

        self._setup_tab = SetupTab(
            tabview.tab("⚙  Setup"),
            on_ready_callback=lambda: tabview.set("🤖  Agent"))
        self._setup_tab.pack(fill="both", expand=True)

        self._settings_tab = SettingsTab(tabview.tab("⚡  Settings"))
        self._settings_tab.pack(fill="both", expand=True)

        self._agent_tab = AgentTab(tabview.tab("🤖  Agent"))
        self._agent_tab.pack(fill="both", expand=True)

        # Wire compact mode callbacks
        self._agent_tab._on_start_cb = self._enter_compact
        self._agent_tab._on_done_cb  = self._exit_compact

        self._tabview = tabview
        self._agent_tab._led = self._led
        self.after(200, self._sync_led)

    # ── Compact sidebar ───────────────────────────────────────────────────────

    def _enter_compact(self, task: str) -> None:
        s = load_settings()
        if not s.get("compact_mode", True):
            return
        self._normal_geometry = self.geometry()
        self.withdraw()   # hide main window
        self._compact_sidebar = CompactSidebar(
            master=self,
            task=task,
            stop_callback=self._agent_tab._stop,
            led_source=self._agent_tab,
        )

    def _exit_compact(self) -> None:
        if self._compact_sidebar:
            try:
                self._compact_sidebar.destroy()
            except Exception:
                pass
            self._compact_sidebar = None
        self.deiconify()
        self.geometry(self._normal_geometry)
        self.lift()

    # ── LED sync ──────────────────────────────────────────────────────────────

    def _sync_led(self) -> None:
        tab = self._agent_tab
        if getattr(tab, "_agent_thread", None) and tab._agent_thread.is_alive():
            self._led.set_state("running")
        else:
            self._led.set_state("idle")
        self.after(500, self._sync_led)

    def _topbar_run(self) -> None:
        key = self._api_var.get().strip()
        self._agent_tab.set_api_key(key)
        self._agent_tab._start()


if __name__ == "__main__":
    app = OverlordGUI()
    app.mainloop()
