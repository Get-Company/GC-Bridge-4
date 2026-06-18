from __future__ import annotations

import base64
import html
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from core.services import BaseService
from qrcodes.models import QrCode


@dataclass(frozen=True)
class QrExport:
    content: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class QrCenterGeometry:
    module_count: int
    target_modules: int
    cutout_modules: frozenset[tuple[int, int]]

    @property
    def target_side_ratio(self) -> float:
        return self.target_modules / self.module_count


class QrCodeRenderService(BaseService):
    model = QrCode

    RASTER_SIZES = {
        "small": 512,
        "medium": 1024,
        "large": 2048,
    }
    PDF_QR_SIDE_POINTS = {
        "small": 260,
        "medium": 360,
        "large": 460,
    }
    FORMATS = {"png", "jpg", "svg", "pdf"}

    def build_export(self, qr_code: QrCode, file_format: str, size_key: str) -> QrExport:
        file_format = file_format.lower()
        size_key = size_key.lower()
        if file_format not in self.FORMATS:
            raise ValueError("Dieses Dateiformat wird nicht unterstuetzt.")
        if size_key not in self.RASTER_SIZES:
            raise ValueError("Diese Aufloesung wird nicht unterstuetzt.")

        if file_format == "svg":
            content = self.render_svg(qr_code, self.RASTER_SIZES[size_key])
            content_type = "image/svg+xml"
            extension = "svg"
        elif file_format == "pdf":
            content = self.render_pdf(qr_code, size_key)
            content_type = "application/pdf"
            extension = "pdf"
        else:
            content = self.render_raster(qr_code, file_format, self.RASTER_SIZES[size_key])
            content_type = "image/png" if file_format == "png" else "image/jpeg"
            extension = file_format

        return QrExport(
            content=content,
            content_type=content_type,
            filename=f"{self._filename_base(qr_code)}-{size_key}.{extension}",
        )

    def render_raster(self, qr_code: QrCode, file_format: str, pixel_size: int) -> bytes:
        image = self._build_base_pil(qr_code).convert("RGBA")
        image = image.resize((pixel_size, pixel_size), Image.Resampling.NEAREST)
        self._apply_center_content(image, qr_code)

        output = BytesIO()
        if file_format == "jpg":
            image.convert("RGB").save(output, format="JPEG", quality=94, optimize=True)
        else:
            image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def render_svg(self, qr_code: QrCode, pixel_size: int = 1024) -> bytes:
        qr = self._build_qr(qr_code)
        matrix = qr.get_matrix()
        module_count = len(matrix)
        module_size = 10
        side = module_count * module_size
        fill = html.escape(qr_code.foreground_color, quote=True)
        background = html.escape(qr_code.background_color, quote=True)
        paths = []
        for y, row in enumerate(matrix):
            for x, enabled in enumerate(row):
                if enabled:
                    paths.append(f"M{x * module_size},{y * module_size}h{module_size}v{module_size}h-{module_size}z")

        center_markup = self._build_svg_center_markup(qr_code, side, module_size, module_count)
        path_data = "".join(paths)
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" width="{pixel_size}" height="{pixel_size}">'
            f'<rect width="100%" height="100%" fill="{background}"/>'
            f'<path fill="{fill}" d="{path_data}"/>'
            f"{center_markup}"
            "</svg>"
        )
        return svg.encode("utf-8")

    def render_pdf(self, qr_code: QrCode, size_key: str) -> bytes:
        raster = self.render_raster(qr_code, "png", self.RASTER_SIZES[size_key])
        page_width, page_height = A4
        qr_side = self.PDF_QR_SIDE_POINTS[size_key]
        x = (page_width - qr_side) / 2
        y = (page_height - qr_side) / 2

        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=A4)
        pdf.drawImage(ImageReader(BytesIO(raster)), x, y, width=qr_side, height=qr_side, mask="auto")
        pdf.showPage()
        pdf.save()
        return output.getvalue()

    def _build_qr(self, qr_code: QrCode) -> qrcode.QRCode:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_H,
            box_size=18,
            border=4,
        )
        qr.add_data(qr_code.target_url)
        qr.make(fit=True)
        return qr

    def _build_base_pil(self, qr_code: QrCode) -> Image.Image:
        qr = self._build_qr(qr_code)
        return qr.make_image(
            fill_color=qr_code.foreground_color,
            back_color=qr_code.background_color,
        ).convert("RGBA")

    def _apply_center_content(self, image: Image.Image, qr_code: QrCode) -> None:
        if qr_code.center_mode == QrCode.CenterMode.NONE:
            return
        if qr_code.center_mode == QrCode.CenterMode.IMAGE and not qr_code.center_image:
            return
        if qr_code.center_mode == QrCode.CenterMode.TEXT and not qr_code.center_text.strip():
            return

        module_count = len(self._build_qr(qr_code).get_matrix())
        geometry = self._build_center_geometry(module_count, qr_code.center_scale_percent)
        self._clear_raster_modules(image, qr_code.background_color, geometry)
        target_side = int(image.width * geometry.target_side_ratio)


        if qr_code.center_mode == QrCode.CenterMode.IMAGE:
            center = self._load_center_image(qr_code, target_side)
            image.alpha_composite(center, ((image.width - center.width) // 2, (image.height - center.height) // 2))
            return

        self._draw_center_text(image, qr_code.center_text.strip(), target_side, qr_code.foreground_color)

    def _load_center_image(self, qr_code: QrCode, target_side: int) -> Image.Image:
        with qr_code.center_image.open("rb") as image_file:
            center = Image.open(image_file).convert("RGBA")
            center.thumbnail((target_side, target_side), Image.Resampling.LANCZOS)
        return center

    def _draw_center_text(self, image: Image.Image, text: str, max_side: int, fill: str) -> None:
        draw = ImageDraw.Draw(image)
        font = self._fit_font(draw, text, max_side)
        text_box = draw.textbbox((0, 0), text, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        x = (image.width - text_width) / 2
        y = (image.height - text_height) / 2 - text_box[1]
        draw.text((x, y), text, font=font, fill=fill)

    def _build_svg_center_markup(self, qr_code: QrCode, side: int, module_size: int, module_count: int) -> str:
        if qr_code.center_mode == QrCode.CenterMode.NONE:
            return ""
        if qr_code.center_mode == QrCode.CenterMode.IMAGE and not qr_code.center_image:
            return ""
        if qr_code.center_mode == QrCode.CenterMode.TEXT and not qr_code.center_text.strip():
            return ""

        geometry = self._build_center_geometry(module_count, qr_code.center_scale_percent)
        target_side = side * geometry.target_side_ratio
        background = html.escape(qr_code.background_color, quote=True)
        foreground = html.escape(qr_code.foreground_color, quote=True)
        module_markup = (
            f'<rect x="{x * module_size}" y="{y * module_size}" width="{module_size}" height="{module_size}" fill="{background}"/>'
            for x, y in sorted(geometry.cutout_modules, key=lambda item: (item[1], item[0]))
        )
        markup = ["".join(module_markup)]

        if qr_code.center_mode == QrCode.CenterMode.IMAGE:
            mime_type = self._image_mime_type(qr_code.center_image.name)
            with qr_code.center_image.open("rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode("ascii")
            image_x = (side - target_side) / 2
            image_y = (side - target_side) / 2
            markup.append(
                f'<image x="{image_x:.2f}" y="{image_y:.2f}" width="{target_side:.2f}" height="{target_side:.2f}" '
                f'preserveAspectRatio="xMidYMid meet" href="data:{mime_type};base64,{encoded}"/>'
            )
            return "".join(markup)

        text = html.escape(qr_code.center_text.strip())
        font_size = max(12, target_side * 0.34)
        markup.append(
            f'<text x="{side / 2:.2f}" y="{side / 2:.2f}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="Arial, sans-serif" font-weight="700" font-size="{font_size:.2f}" fill="{foreground}">{text}</text>'
        )
        return "".join(markup)

    def _build_center_geometry(self, module_count: int, scale_percent: int) -> QrCenterGeometry:
        target_modules = max(3, math.ceil(module_count * (scale_percent / 100)))
        if target_modules % 2 == 0:
            target_modules += 1

        padding_modules = max(2, math.ceil(target_modules * 0.22))
        cutout_side = min(module_count - 8, target_modules + (padding_modules * 2))
        if cutout_side % 2 == 0:
            cutout_side += 1

        start = (module_count - cutout_side) // 2
        end = start + cutout_side
        radius = max(2.0, cutout_side * 0.24)
        inner_left = start + radius
        inner_right = end - radius
        inner_top = start + radius
        inner_bottom = end - radius

        modules: set[tuple[int, int]] = set()
        for y in range(start, end):
            for x in range(start, end):
                center_x = x + 0.5
                center_y = y + 0.5
                nearest_x = min(max(center_x, inner_left), inner_right)
                nearest_y = min(max(center_y, inner_top), inner_bottom)
                if (center_x - nearest_x) ** 2 + (center_y - nearest_y) ** 2 <= radius**2:
                    modules.add((x, y))

        return QrCenterGeometry(
            module_count=module_count,
            target_modules=target_modules,
            cutout_modules=frozenset(modules),
        )

    def _clear_raster_modules(self, image: Image.Image, fill: str, geometry: QrCenterGeometry) -> None:
        draw = ImageDraw.Draw(image)
        for x, y in geometry.cutout_modules:
            left = round((x / geometry.module_count) * image.width)
            top = round((y / geometry.module_count) * image.height)
            right = round(((x + 1) / geometry.module_count) * image.width)
            bottom = round(((y + 1) / geometry.module_count) * image.height)
            draw.rectangle((left, top, right - 1, bottom - 1), fill=fill)

    def _fit_font(self, draw: ImageDraw.ImageDraw, text: str, max_side: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_path = self._font_path()
        for size in range(max_side, 11, -2):
            font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
            text_box = draw.textbbox((0, 0), text, font=font)
            if text_box[2] - text_box[0] <= max_side and text_box[3] - text_box[1] <= max_side * 0.7:
                return font
        return ImageFont.truetype(font_path, 12) if font_path else ImageFont.load_default()

    def _font_path(self) -> str | None:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        )
        return next((path for path in candidates if Path(path).exists()), None)

    def _image_mime_type(self, name: str) -> str:
        extension = Path(name).suffix.lower()
        if extension in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if extension == ".webp":
            return "image/webp"
        return "image/png"

    def _filename_base(self, qr_code: QrCode) -> str:
        from django.utils.text import slugify

        return slugify(qr_code.title) or f"qr-code-{qr_code.pk or 'export'}"
