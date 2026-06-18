from django.test import SimpleTestCase
from unfold.widgets import UnfoldAdminColorInputWidget

from qrcodes.admin import QrCodeAdminForm
from qrcodes.forms import QrCodeForm


class QrCodeFormWidgetTest(SimpleTestCase):
    def test_admin_form_uses_unfold_color_picker_widgets(self):
        form = QrCodeAdminForm()

        self.assertIsInstance(form.fields["foreground_color"].widget, UnfoldAdminColorInputWidget)
        self.assertIsInstance(form.fields["background_color"].widget, UnfoldAdminColorInputWidget)

    def test_frontend_form_uses_html_color_inputs(self):
        form = QrCodeForm()

        self.assertEqual(form.fields["foreground_color"].widget.input_type, "color")
        self.assertEqual(form.fields["background_color"].widget.input_type, "color")
