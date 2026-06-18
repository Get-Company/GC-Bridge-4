from django import forms

from qrcodes.models import QrCode


class QrCodeForm(forms.ModelForm):
    class Meta:
        model = QrCode
        fields = (
            "title",
            "target_url",
            "description",
            "center_mode",
            "center_image",
            "center_text",
            "center_scale_percent",
            "foreground_color",
            "background_color",
            "is_active",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "foreground_color": forms.TextInput(attrs={"type": "color"}),
            "background_color": forms.TextInput(attrs={"type": "color"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        center_mode = cleaned_data.get("center_mode")
        center_image = cleaned_data.get("center_image")
        center_text = (cleaned_data.get("center_text") or "").strip()

        if center_mode == QrCode.CenterMode.IMAGE and not center_image and not self.instance.center_image:
            self.add_error("center_image", "Bitte ein Bild fuer die QR-Code-Mitte hochladen.")
        if center_mode == QrCode.CenterMode.TEXT and not center_text:
            self.add_error("center_text", "Bitte einen Text fuer die QR-Code-Mitte eingeben.")
        return cleaned_data
