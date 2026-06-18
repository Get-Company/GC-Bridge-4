from django.test import SimpleTestCase
from unfold.widgets import UnfoldAdminColorInputWidget

from qrcodes.admin import QrCodeAdmin, QrCodeAdminForm
from qrcodes.forms import QrCodeForm
from qrcodes.models import QrCode
from qrcodes.services import QrCodeRenderService


class QrCodeFormWidgetTest(SimpleTestCase):
    def test_admin_form_uses_unfold_color_picker_widgets(self):
        form = QrCodeAdminForm()

        self.assertIsInstance(form.fields["foreground_color"].widget, UnfoldAdminColorInputWidget)
        self.assertIsInstance(form.fields["background_color"].widget, UnfoldAdminColorInputWidget)

    def test_frontend_form_uses_html_color_inputs(self):
        form = QrCodeForm()

        self.assertEqual(form.fields["foreground_color"].widget.input_type, "color")
        self.assertEqual(form.fields["background_color"].widget.input_type, "color")

    def test_admin_download_links_render_without_format_error(self):
        qr_code = QrCode(pk=1, title="Test", target_url="https://example.com")
        html = QrCodeAdmin(QrCode, None).download_links(qr_code)

        self.assertIn("/qr-codes/1/download/png/medium/", html)
        self.assertIn(">PDF</a>", html)

    def test_svg_center_background_uses_qr_module_grid(self):
        qr_code = QrCode(
            title="Test",
            target_url="https://example.com",
            center_mode=QrCode.CenterMode.TEXT,
            center_text="GC",
        )
        svg = QrCodeRenderService().render_svg(qr_code).decode("utf-8")

        self.assertNotIn('rx="', svg)
        self.assertGreater(svg.count('fill="#ffffff"'), 20)
