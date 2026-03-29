"""
Eyes Module
===========
Responsible for:
  - Capturing the full primary-monitor screenshot via PIL
  - Optionally resizing it before sending to Gemini (reduces token cost)
  - Encoding it as base64 JPEG for the Gemini vision payload
  - Annotating coordinates (debug overlay) for developer inspection
"""

import base64
import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw
import pyautogui

logger = logging.getLogger(__name__)


@dataclass
class ScreenCapture:
    image: Image.Image          # PIL image (logical resolution)
    width: int
    height: int
    b64_jpeg: str               # base64-encoded JPEG for Gemini


class Eyes:
    def __init__(
        self,
        resize_w: int = 1280,
        resize_h: int = 720,
        jpeg_quality: int = 85,
    ) -> None:
        self.resize_w = resize_w
        self.resize_h = resize_h
        self.jpeg_quality = jpeg_quality

    # ── public ────────────────────────────────────────────────────────────────

    def capture(self) -> ScreenCapture:
        """Take a full-screen screenshot and return a ScreenCapture object."""
        # pyautogui.screenshot() returns a PIL Image at logical resolution
        raw: Image.Image = pyautogui.screenshot()
        original_w, original_h = raw.size

        # Resize for Gemini (lower tokens, faster inference)
        resized = raw.resize((self.resize_w, self.resize_h), Image.LANCZOS)

        b64 = self._encode_jpeg(resized, self.jpeg_quality)
        logger.debug(
            "📸 Screenshot %dx%d → resized %dx%d (%.1f KB)",
            original_w, original_h,
            self.resize_w, self.resize_h,
            len(b64) * 3 / 4 / 1024,
        )
        return ScreenCapture(
            image=resized,
            width=self.resize_w,
            height=self.resize_h,
            b64_jpeg=b64,
        )

    def annotate_point(self, capture: ScreenCapture, x: int, y: int,
                       label: str = "") -> Image.Image:
        """Draw a crosshair on the capture for debug visualization."""
        img = capture.image.copy()
        draw = ImageDraw.Draw(img)
        r = 10
        draw.ellipse([x - r, y - r, x + r, y + r], outline="red", width=2)
        draw.line([x - r * 2, y, x + r * 2, y], fill="red", width=1)
        draw.line([x, y - r * 2, x, y + r * 2], fill="red", width=1)
        if label:
            draw.text((x + r + 2, y - r), label, fill="red")
        return img

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _encode_jpeg(image: Image.Image, quality: int) -> str:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
