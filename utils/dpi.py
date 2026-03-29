"""
DPI Scaling Utility
===================
Windows allows users to set display scaling (100 %, 125 %, 150 %, 200 %, …).
The AI agent captures screenshots at physical resolution, resizes them to a
fixed size (e.g. 1280×720) for the model, then receives coordinates back in
that screenshot space.  PyAutoGUI click() on a DPI-aware process expects
*physical* pixel coordinates.

The correct conversion is therefore:

    physical_x = gemini_x * (physical_screen_width  / screenshot_width)
    physical_y = gemini_y * (physical_screen_height / screenshot_height)

NOT the raw DPI ratio (which only equals the correct factor when the
screenshot happens to be the same size as the logical screen).

Strategy
--------
1. Mark the process as DPI-aware (call once, as early as possible) so that
   all Windows API calls and PyAutoGUI return/expect physical pixels.
2. Query the physical screen dimensions via GetSystemMetrics.
3. Divide by the Gemini screenshot dimensions to get the true scale factors.
4. Multiply every model-returned [x, y] by those factors before clicking.
"""

import platform

# ── safe import: only Windows has ctypes.windll ───────────────────────────────
if platform.system() == "Windows":
    import ctypes
    import ctypes.wintypes
else:
    ctypes = None  # type: ignore


def ensure_dpi_aware() -> None:
    """
    Mark this process as per-monitor DPI-aware so that:
      - GetSystemMetrics returns physical pixel dimensions.
      - PyAutoGUI screenshots are captured at physical resolution.
      - PyAutoGUI click coordinates are interpreted as physical pixels.

    Safe to call multiple times; subsequent calls are no-ops.
    """
    if platform.system() != "Windows" or ctypes is None:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()   # fallback for older Windows
        except Exception:
            pass


def _get_windows_dpi_scale(screenshot_w: int = 1280,
                            screenshot_h: int = 720) -> tuple[float, float]:
    """
    Return (scale_x, scale_y) that maps Gemini screenshot coordinates to
    physical screen pixels on the primary monitor.

    Calls ensure_dpi_aware() first so that GetSystemMetrics returns the true
    physical resolution rather than the scaled logical resolution.
    """
    ensure_dpi_aware()

    # Read physical screen dimensions (SM_CXSCREEN=0, SM_CYSCREEN=1).
    # After SetProcessDpiAwareness these return physical pixels, e.g. 1920×1080.
    user32 = ctypes.windll.user32
    screen_w: int = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h: int = user32.GetSystemMetrics(1)  # SM_CYSCREEN

    if screen_w <= 0 or screen_h <= 0:
        return 1.0, 1.0

    # Scale = physical screen size / Gemini screenshot size
    # e.g. 1920/1280 = 1.5, not 1.25 (which is the DPI ratio -- a different thing)
    scale_x = screen_w / screenshot_w
    scale_y = screen_h / screenshot_h
    return scale_x, scale_y


def get_dpi_scale(screenshot_w: int = 1280,
                  screenshot_h: int = 720) -> tuple[float, float]:
    """
    Return (scale_x, scale_y) mapping Gemini screenshot coordinates to
    physical screen pixels.

    Parameters
    ----------
    screenshot_w, screenshot_h : dimensions of the image sent to the model
                                  (must match Eyes.resize_w / resize_h)

    On non-Windows systems always returns (1.0, 1.0).
    """
    if platform.system() != "Windows" or ctypes is None:
        return 1.0, 1.0
    try:
        return _get_windows_dpi_scale(screenshot_w, screenshot_h)
    except Exception:
        return 1.0, 1.0


def scale_point(x: float, y: float,
                scale_x: float, scale_y: float) -> tuple[int, int]:
    """
    Convert a screenshot-space coordinate to a physical pixel coordinate
    suitable for PyAutoGUI.

    Parameters
    ----------
    x, y    : coordinate returned by the model (screenshot space)
    scale_x : horizontal scale  (physical_screen_width  / screenshot_width)
    scale_y : vertical scale    (physical_screen_height / screenshot_height)

    Returns
    -------
    (physical_x, physical_y) as integers
    """
    return int(round(x * scale_x)), int(round(y * scale_y))
