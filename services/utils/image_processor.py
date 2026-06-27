"""
Image Processing Service
Downloads images, resizes to WordPress featured image dimensions (1200x630),
and applies branded overlay using Pillow.

Overlay spec:
- Transparent black gradient at bottom
- Article title (max 2 lines)
- Modern font
- Company logo at bottom-right corner
- Save as WebP
"""

import io
import os
import textwrap
import uuid
from pathlib import Path
from typing import Optional

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from core.config import settings
from core.exceptions import ImageProcessingError
from core.models import ImageResult, ProcessedImage

logger = structlog.get_logger(__name__)

# Target dimensions for WordPress featured image
TARGET_WIDTH = settings.THUMBNAIL_WIDTH   # 1200
TARGET_HEIGHT = settings.THUMBNAIL_HEIGHT  # 630

# Overlay styling
GRADIENT_HEIGHT_RATIO = 0.45   # Gradient covers bottom 45% of image
GRADIENT_OPACITY_TOP = 0       # Transparent at top of gradient
GRADIENT_OPACITY_BOTTOM = 200  # ~80% opacity at bottom
TITLE_FONT_SIZE = 42
TITLE_MAX_CHARS_PER_LINE = 38
TITLE_MAX_LINES = 2
TITLE_PADDING_BOTTOM = 30
TITLE_PADDING_SIDE = 40
LOGO_PADDING = 20
LOGO_MAX_SIZE = (120, 60)


class ImageProcessor:
    """
    Handles image download, resize, overlay application, and WebP export.
    """

    def __init__(
        self,
        temp_dir: str = settings.TEMP_DIR,
        logo_path: str = settings.COMPANY_LOGO_PATH,
        default_thumbnail_path: str = settings.DEFAULT_THUMBNAIL_PATH,
    ):
        self._temp_dir = Path(temp_dir)
        self._logo_path = Path(logo_path)
        self._default_thumbnail = Path(default_thumbnail_path)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def process(
        self,
        image_source: Optional[ImageResult],
        article_title: str,
    ) -> ProcessedImage:
        """
        Main processing pipeline:
        1. Download image (or use default)
        2. Resize to 1200x630
        3. Apply gradient overlay with title
        4. Add company logo
        5. Save as WebP
        """
        output_path = self._temp_dir / f"{uuid.uuid4().hex}.webp"

        try:
            # Step 1: Load image
            img = await self._load_image(image_source)

            # Step 2: Resize/crop to target dimensions
            img = self._resize_crop(img, TARGET_WIDTH, TARGET_HEIGHT)

            # Step 3: Apply gradient overlay
            img = self._apply_gradient_overlay(img)

            # Step 4: Draw title text
            img = self._draw_title(img, article_title)

            # Step 5: Add logo
            img = self._add_logo(img)

            # Step 6: Save as WebP
            img.save(str(output_path), "WEBP", quality=85, method=6)
            size_bytes = output_path.stat().st_size

            processed = ProcessedImage(
                local_path=str(output_path),
                width=TARGET_WIDTH,
                height=TARGET_HEIGHT,
                format="webp",
                size_bytes=size_bytes,
                source=image_source.source if image_source else "default",
            )

            logger.info(
                "Image processed",
                path=str(output_path),
                size_kb=size_bytes // 1024,
                source=processed.source,
            )
            return processed

        except Exception as e:
            raise ImageProcessingError(f"Image processing failed: {e}") from e

    async def _load_image(self, image_source: Optional[ImageResult]) -> Image.Image:
        """Download and load image from URL, or use default thumbnail."""
        if image_source and image_source.url:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(
                        image_source.url, follow_redirects=True
                    )
                    response.raise_for_status()
                    return Image.open(io.BytesIO(response.content)).convert("RGB")
            except Exception as e:
                logger.warning(
                    "Failed to download image, using default",
                    url=image_source.url[:80],
                    error=str(e),
                )

        # Fallback to default thumbnail
        return self._load_default_thumbnail()

    def _load_default_thumbnail(self) -> Image.Image:
        """Load default thumbnail, or create a solid color placeholder."""
        if self._default_thumbnail.exists():
            return Image.open(str(self._default_thumbnail)).convert("RGB")

        logger.warning(
            "Default thumbnail not found, creating placeholder",
            path=str(self._default_thumbnail),
        )
        # Create a simple gradient placeholder
        img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (30, 60, 90))
        return img

    def _resize_crop(self, img: Image.Image, width: int, height: int) -> Image.Image:
        """
        Resize and center-crop image to exact dimensions.
        Maintains aspect ratio during resize, then crops to fit.
        """
        original_ratio = img.width / img.height
        target_ratio = width / height

        if original_ratio > target_ratio:
            # Image is wider - scale by height, crop width
            new_height = height
            new_width = int(height * original_ratio)
        else:
            # Image is taller - scale by width, crop height
            new_width = width
            new_height = int(width / original_ratio)

        img = img.resize((new_width, new_height), Image.LANCZOS)

        # Center crop
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        img = img.crop((left, top, left + width, top + height))

        return img

    def _apply_gradient_overlay(self, img: Image.Image) -> Image.Image:
        """Apply a smooth black gradient overlay at the bottom of the image."""
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        gradient_start_y = int(img.height * (1 - GRADIENT_HEIGHT_RATIO))

        for y in range(gradient_start_y, img.height):
            # Linear interpolation of opacity
            progress = (y - gradient_start_y) / (img.height - gradient_start_y)
            alpha = int(GRADIENT_OPACITY_TOP + progress * (GRADIENT_OPACITY_BOTTOM - GRADIENT_OPACITY_TOP))
            draw.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))

        # Composite overlay onto RGB image
        img_rgba = img.convert("RGBA")
        img_rgba = Image.alpha_composite(img_rgba, overlay)
        return img_rgba.convert("RGB")

    def _draw_title(self, img: Image.Image, title: str) -> Image.Image:
        """Draw article title at the bottom of the image."""
        draw = ImageDraw.Draw(img)
        font = self._get_font(TITLE_FONT_SIZE)

        # Wrap title to max 2 lines
        wrapped = textwrap.wrap(title, width=TITLE_MAX_CHARS_PER_LINE)
        wrapped = wrapped[:TITLE_MAX_LINES]

        if not wrapped:
            return img

        # Calculate text block height
        line_height = TITLE_FONT_SIZE + 8
        total_height = len(wrapped) * line_height

        # Position: bottom of image with padding
        y_start = img.height - TITLE_PADDING_BOTTOM - total_height

        for i, line in enumerate(wrapped):
            y = y_start + i * line_height
            x = TITLE_PADDING_SIDE

            # Draw shadow for readability
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 180))
            # Draw main text
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

        return img

    def _add_logo(self, img: Image.Image) -> Image.Image:
        """Add company logo to bottom-right corner."""
        if not self._logo_path.exists():
            logger.debug("Logo file not found, skipping", path=str(self._logo_path))
            return img

        try:
            logo = Image.open(str(self._logo_path)).convert("RGBA")

            # Resize logo to fit max size while maintaining aspect ratio
            logo.thumbnail(LOGO_MAX_SIZE, Image.LANCZOS)

            # Position: bottom-right corner with padding
            x = img.width - logo.width - LOGO_PADDING
            y = img.height - logo.height - LOGO_PADDING

            # Paste logo with transparency mask
            img_rgba = img.convert("RGBA")
            img_rgba.paste(logo, (x, y), logo)
            return img_rgba.convert("RGB")

        except Exception as e:
            logger.warning("Failed to add logo, skipping", error=str(e))
            return img

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Load a font, falling back to default if not found."""
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\calibrib.ttf",
        ]

        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue

        logger.warning("No system font found, using default bitmap font")
        return ImageFont.load_default()

    def cleanup(self, path: str) -> None:
        """Remove temporary file after upload."""
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.debug("Temp file cleaned up", path=path)
        except Exception as e:
            logger.warning("Failed to cleanup temp file", path=path, error=str(e))
