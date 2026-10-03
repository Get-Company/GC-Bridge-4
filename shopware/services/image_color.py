from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageCms
from loguru import logger

from core.services import BaseService


class ImageColorProfileService(BaseService):
    """Prepare web images without changing their source files."""

    max_download_bytes = 64 * 1024 * 1024
    supported_formats = {"JPEG", "PNG", "WEBP", "TIFF"}

    @lru_cache(maxsize=16)
    def prepare_upload(self, *, source_url: str) -> bytes:
        if urlsplit(source_url).scheme not in {"http", "https"}:
            raise ValueError("Bildquelle muss eine HTTP- oder HTTPS-URL sein.")
        with requests.get(source_url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > self.max_download_bytes:
                    raise ValueError("Bildquelle überschreitet das Download-Limit von 64 MiB.")
        return self.normalize(bytes(data))

    def normalize(self, content: bytes) -> bytes:
        # SVG and other non-raster assets retain their original bytes.
        if content.lstrip().startswith((b"<svg", b"<?xml")):
            return content
        with Image.open(BytesIO(content)) as image:
            profile_bytes = image.info.get("icc_profile")
            if image.format not in self.supported_formats:
                if profile_bytes:
                    raise ValueError(f"Farbprofil-Konvertierung für {image.format} nicht unterstützt.")
                return content
            if not profile_bytes and image.mode != "CMYK":
                return content
            if getattr(image, "n_frames", 1) > 1:
                raise ValueError("Bilder mit mehreren Frames und Farbprofil benötigen eine separate Konvertierung.")

            target_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            if profile_bytes:
                source_profile = ImageCms.ImageCmsProfile(BytesIO(profile_bytes))
                has_alpha = image.mode in {"RGBA", "LA", "PA", "RGBa", "La"} or "transparency" in image.info
                alpha = image.convert("RGBA").getchannel("A") if has_alpha else None
                source = image
                if image.mode in {"P", "RGBA", "PA", "RGBa"}:
                    source = image.convert("RGB")
                elif image.mode in {"LA", "La"}:
                    source = image.convert("L")
                converted = ImageCms.profileToProfile(
                    source,
                    source_profile,
                    target_profile,
                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode="RGB",
                )
                if alpha is not None:
                    converted.putalpha(alpha)
                logger.info("Bildprofil nach sRGB konvertiert: {}", ImageCms.getProfileDescription(source_profile).strip())
            else:
                logger.warning("CMYK-Bild ohne ICC-Profil: konventionelle RGB-Konvertierung verwendet.")
                converted = image.convert("RGB")

            options = {"icc_profile": target_profile.tobytes()}
            if image.info.get("exif"):
                options["exif"] = image.info["exif"]
            if image.info.get("dpi"):
                options["dpi"] = image.info["dpi"]
            if image.format == "JPEG":
                options.update(quality=95, subsampling=0)
            elif image.format == "WEBP":
                options["lossless"] = True
            output = BytesIO()
            converted.save(output, format=image.format, **options)
            return output.getvalue()
