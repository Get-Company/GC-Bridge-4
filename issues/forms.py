from pathlib import Path

from django import forms
from PIL import Image, UnidentifiedImageError


MAX_CHAT_IMAGES = 5
MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024
CHAT_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
CHAT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class IssueChatForm(forms.Form):
    body = forms.CharField(required=False, strip=True, max_length=5000)

    def __init__(self, *args, uploads=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.uploads = list(uploads)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("body") and not self.uploads:
            raise forms.ValidationError("Bitte eine Nachricht schreiben oder einen Screenshot auswählen.")
        if len(self.uploads) > MAX_CHAT_IMAGES:
            raise forms.ValidationError(f"Pro Nachricht sind höchstens {MAX_CHAT_IMAGES} Bilder erlaubt.")
        for upload in self.uploads:
            if upload.size > MAX_CHAT_IMAGE_BYTES:
                raise forms.ValidationError("Ein Screenshot darf höchstens 10 MB groß sein.")
            if Path(upload.name).suffix.lower() not in CHAT_IMAGE_EXTENSIONS:
                raise forms.ValidationError("Erlaubt sind PNG-, JPEG-, WebP- und GIF-Bilder.")
            try:
                with Image.open(upload) as image:
                    if image.format not in CHAT_IMAGE_FORMATS:
                        raise forms.ValidationError("Die Datei ist kein unterstütztes Bild.")
                    image.verify()
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise forms.ValidationError("Die Datei ist kein gültiges Bild.") from exc
            finally:
                upload.seek(0)
        return cleaned
