"""
Generates a photo-card by embedding a news image and Bengali headline
into the standard template at assets/photo_card_template.png.

Detected template zones (940 × 788 px):
  Image slot  : x=0–940, y=79–510  (940 × 432 px, full-width, no padding)
  Headline box: x=0–940, y=513–591 (red placeholder text lives here)
"""

from __future__ import annotations

import io
import os

import requests
from PIL import Image, ImageDraw, ImageFont

_TEMPLATE   = os.path.join(os.path.dirname(__file__), "..", "assets", "photo_card_template.png")
_FONT_BOLD  = "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf"
_FONT_REG   = "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"

# Exact pixel zones derived from programmatic analysis of the template
_IMG_X1, _IMG_Y1, _IMG_X2, _IMG_Y2       = 0, 79, 940, 510   # news photo slot
# Full band between the two horizontal separator lines (y=511 and y=684)
_HDR_X1, _HDR_Y1, _HDR_X2, _HDR_Y2      = 0, 513, 940, 683  # headline clear + draw area (170 px)
_HEADLINE_COLOR = (232, 2, 18)   # matches template red  (#E80212)
_HEADLINE_CLEAR = (5, 5, 5)      # near-black to erase placeholder text


class PhotoCardGenerator:
    """
    Usage:
        gen = PhotoCardGenerator()
        gen.generate("https://…/photo.jpg", "বাংলা শিরোনাম এখানে", "output.png")
    """

    def __init__(
        self,
        template_path: str = _TEMPLATE,
        font_path: str = _FONT_BOLD,
        max_font_size: int = 38,
        min_font_size: int = 10,
    ):
        self.template_path = os.path.normpath(template_path)
        self.font_path = font_path
        self.max_font_size = max_font_size
        self.min_font_size = min_font_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_bytes(self, image_url: str, headline: str) -> bytes:
        """Return the finished card as PNG bytes (no disk I/O)."""
        card = Image.open(self.template_path).convert("RGBA")
        news_img = self._fetch_and_cover_crop(image_url, _IMG_X2 - _IMG_X1, _IMG_Y2 - _IMG_Y1)
        card.paste(news_img.convert("RGBA"), (_IMG_X1, _IMG_Y1))
        self._draw_headline(ImageDraw.Draw(card), headline)
        buf = io.BytesIO()
        card.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def generate(self, image_url: str, headline: str, output_path: str) -> str:
        """Save finished card to output_path and return it."""
        with open(output_path, "wb") as f:
            f.write(self.generate_bytes(image_url, headline))
        return output_path

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------

    def _fetch_and_cover_crop(self, url: str, target_w: int, target_h: int) -> Image.Image:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        return self._cover_crop(img, target_w, target_h)

    @staticmethod
    def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        src_w, src_h = img.size
        scale = max(target_w / src_w, target_h / src_h)
        new_w, new_h = int(src_w * scale), int(src_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top  = (new_h - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))

    # ------------------------------------------------------------------
    # Headline rendering
    # ------------------------------------------------------------------

    def _draw_headline(self, draw: ImageDraw.ImageDraw, text: str) -> None:
        box_w = _HDR_X2 - _HDR_X1   # 940
        box_h = _HDR_Y2 - _HDR_Y1   # 170

        draw.rectangle([_HDR_X1, _HDR_Y1, _HDR_X2, _HDR_Y2], fill=_HEADLINE_CLEAR)

        font, lines = self._fit_text(text, box_w, box_h)
        line_height = self._line_height(font)
        total_h     = len(lines) * line_height
        y           = _HDR_Y1 + (box_h - total_h) // 2   # vertically centred

        for line in lines:
            w = draw.textbbox((0, 0), line, font=font)[2]
            draw.text((_HDR_X1 + (box_w - w) // 2, y), line, font=font, fill=_HEADLINE_COLOR)
            y += line_height

    def _fit_text(self, text: str, box_w: int, box_h: int):
        """
        ≤2 words → single line at fs=68, shrink only if text wider than box.
        ≥3 words → balanced 2-line split at fs=56.
                   If any line still exceeds box_w, fall back to greedy wrap
                   and shrink font until height fits.
        """
        words = text.split()

        if len(words) <= 3:
            for fs in range(68, self.min_font_size - 1, -1):
                font = ImageFont.truetype(self.font_path, fs)
                if self._measure(text, font) <= box_w:
                    return font, [text]
            font = ImageFont.truetype(self.font_path, self.min_font_size)
            return font, [text]

        # Balanced 2-line at fs=56
        font  = ImageFont.truetype(self.font_path, 56)
        lines = self._balanced_split(words, font, box_w)
        if lines and self._line_height(font) * 2 <= box_h:
            return font, lines

        # Fallback: greedy wrap, shrink from fs=56 until height fits
        for fs in range(56, self.min_font_size - 1, -1):
            font  = ImageFont.truetype(self.font_path, fs)
            lines = self._wrap_text(text, font, box_w)
            if self._line_height(font) * len(lines) <= box_h:
                return font, lines

        font = ImageFont.truetype(self.font_path, self.min_font_size)
        return font, self._wrap_text(text, font, box_w)

    @staticmethod
    def _balanced_split(words: list[str], font: ImageFont.FreeTypeFont, box_w: int) -> list[str] | None:
        """Split at the word boundary that minimises |width(l1) − width(l2)|.
        Returns None if no valid split exists within box_w."""
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        best_lines, best_diff = None, float("inf")
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            w1 = dummy.textbbox((0, 0), l1, font=font)[2]
            w2 = dummy.textbbox((0, 0), l2, font=font)[2]
            if w1 <= box_w and w2 <= box_w:
                diff = abs(w1 - w2)
                if diff < best_diff:
                    best_diff, best_lines = diff, [l1, l2]
        return best_lines

    @staticmethod
    def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
        """Greedy word-wrap within max_w pixels."""
        dummy, words, lines, cur = ImageDraw.Draw(Image.new("RGB", (1, 1))), text.split(), [], ""
        for word in words:
            candidate = (cur + " " + word).strip()
            if dummy.textbbox((0, 0), candidate, font=font)[2] <= max_w:
                cur = candidate
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines or [text]

    @staticmethod
    def _measure(text: str, font: ImageFont.FreeTypeFont) -> int:
        return ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)[2]

    @staticmethod
    def _line_height(font: ImageFont.FreeTypeFont) -> int:
        ascent, descent = font.getmetrics()
        return ascent + descent
