"""
DPI Scaling Utility
===================
Windows allows users to set display scaling (100 %, 125 %, 150 %, 200 %, …).
PIL screenshots are captured at *logical* resolution; PyAutoGUI clicks at
*physical* pixels.  Without correction every coordinate returned by Gemini
will be wrong on HiDPI / scaled displays.

Strategy
--------
1. Mark the process as DPI-aware so GetSystemMetrics returns physical pixels.
2. Compute scale = physical_width / logical_width.
3. Multiply every Gemini-returned [x, y] by that scale before clicking.
"""

import platform
import sys

# ── safe import: only Windows has ctypes.windll ───────────────────────────────
if platform.system() == "Windows":
    import ctypes
    import ctypes.wintypes
else:
    ctypes = None  # type: ignore


def _get_windows_dpi_scale() -> tuple[float, float]:
    """Return (scale_x, scale_y) for the primary monitor on Windows."""
    # Mark process as per-monitor DPI aware so subsequent calls are accurate
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()   # fallback for older Windows
        except Exception:
            pass

    # Read the actual DPI of the primary display via GDI
    # LOGPIXELSX = 88, LOGPIXELSY = 90 — dots-per-logical-inch reported by GDI
    # At 100 % scaling this is 96 dpi; at 125 % → 120; at 150 % → 144; etc.
    user32 = ctypes.windll.user32
    gdi32  = ctypes.windll.gdi32
    hdc    = user32.GetDC(None)
    dpi_x: int = gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
    dpi_y: int = gdi32.GetDeviceCaps(hdc, 90)   # LOGPIXELSY
    user32.ReleaseDC(None, hdc)

    if dpi_x <= 0 or dpi_y <= 0:
        return 1.0, 1.0

    # 96 DPI == 100 % scale (Windows baseline)
    scale_x = dpi_x / 96.0
    scale_y = dpi_y / 96.0
    return scale_x, scale_y


def get_dpi_scale() -> tuple[float, float]:
    """
    Return (scale_x, scale_y).
    On non-Windows systems, always returns (1.0, 1.0).
    """
    if platform.system() != "Windows" or ctypes is None:
        return 1.0, 1.0
    try:
        return _get_windows_dpi_scale()
    except Exception:
        return 1.0, 1.0


def scale_point(x: float, y: float,
                scale_x: float, scale_y: float) -> tuple[int, int]:
    """
    Convert a logical (screenshot-space) coordinate to a physical pixel
    coordinate suitable for PyAutoGUI.

    Parameters
    ----------
    x, y    : coordinate returned by Gemini (logical pixels, screenshot space)
    scale_x : horizontal DPI scale factor
    scale_y : vertical DPI scale factor

    Returns
    -------
    (physical_x, physical_y) as integers
    """
    return int(round(x * scale_x)), int(round(y * scale_y))
