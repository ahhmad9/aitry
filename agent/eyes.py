"""
Eyes Module
===========
Responsible for:
  - Capturing the full primary-monitor screenshot via PIL
  - Optionally resizing it before sending to Gemini (reduces token cost)
  - Encoding it as base64 JPEG for the Gemini vision payload
  - Overlaying a numbered coordinate grid (Set-of-Marks) to help the AI
    estimate precise [x, y] click positions
  - Annotating coordinates (debug overlay) for developer inspection
"""

import base64
import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
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

        # Overlay a numbered coordinate grid so the AI can read off precise [x, y]
        annotated = self._draw_grid(resized)

        b64 = self._encode_jpeg(annotated, self.jpeg_quality)
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

    def _draw_grid(self, image: Image.Image, step: int = 100) -> Image.Image:
        """
        Draw a semi-transparent numbered coordinate grid over *image*.

        Lines are drawn every *step* pixels (default 100) along both axes.
        Each intersection is labelled with its "x,y" value so the AI can read
        off precise coordinates without having to guess.

        Parameters
        ----------
        image : PIL Image
            The resized screenshot to annotate (not modified in place).
        step : int
            Pixel interval between grid lines (default 100 px).
        """
        # Work on a copy so the stored ScreenCapture.image stays clean
        img = image.copy().convert("RGBA")
        w, h = img.size

        # Create a transparent overlay for the grid lines
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        line_color = (255, 255, 255, 80)   # white, ~31 % opaque
        text_color = (255, 255, 0, 200)    # yellow, ~78 % opaque
        text_bg    = (0, 0, 0, 140)        # dark background behind labels

        # Try common font names across platforms, fall back to PIL default
        _font_candidates = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                             "LiberationSans-Regular.ttf"]
        font = ImageFont.load_default()
        for _fname in _font_candidates:
            try:
                font = ImageFont.truetype(_fname, 11)
                break
            except (OSError, IOError):
                continue

        # Grid lines start at 'step' so there is no redundant line on the
        # image border (x=0, y=0 are just the edges of the frame).
        x_positions = range(step, w, step)
        y_positions = range(step, h, step)

        # Draw vertical lines
        for x in x_positions:
            draw.line([(x, 0), (x, h)], fill=line_color, width=1)

        # Draw horizontal lines
        for y in y_positions:
            draw.line([(0, y), (w, y)], fill=line_color, width=1)

        # Label every intersection
        for x in x_positions:
            for y in y_positions:
                label = f"{x},{y}"
                bbox = draw.textbbox((x, y), label, font=font)
                pad = 1
                draw.rectangle(
                    [bbox[0] - pad, bbox[1] - pad,
                     bbox[2] + pad, bbox[3] + pad],
                    fill=text_bg,
                )
                draw.text((x, y), label, fill=text_color, font=font)

        # Composite the overlay onto the image
        img = Image.alpha_composite(img, overlay)
        return img.convert("RGB")

    @staticmethod
    def _encode_jpeg(image: Image.Image, quality: int) -> str:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
