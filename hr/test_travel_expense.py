from contextlib import nullcontext
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from core.admin import BaseAdmin
from hr.admin import TravelExpenseClaimAdmin
from hr.forms import TravelExpenseClaimAdminForm
from hr.management.commands.hr_reset_travel_expense_sequence import Command as ResetTravelExpenseSequenceCommand
from hr.models import TravelExpenseClaim
from hr.services.travel_expense_pdf_service import TravelExpensePdfService


class TravelExpenseClaimTest(SimpleTestCase):
    def make_claim(self, *, round_trip=False):
        return TravelExpenseClaim(
            id=42,
            name="Erika Müller",
            travel_date=date(2026, 9, 23),
            travel_start=date(2026, 9, 23),
            travel_end=date(2026, 9, 23),
            purpose="Kundentermin",
            vehicle="Privatwagen",
            license_plate="B-AB 123",
            distance_km=Decimal("123.45"),
            rate_per_km=Decimal("0.350"),
            round_trip=round_trip,
            settlement_place="Berlin",
            settlement_date=date(2026, 9, 23),
        )

    def test_round_trip_doubles_distance_before_rounding(self):
        claim = self.make_claim(round_trip=True)
        self.assertEqual(claim.number, "000042")
        self.assertEqual(claim.fare_cost, Decimal("43.21"))
        self.assertEqual(claim.trip_total, Decimal("86.42"))
        claim.round_trip = False
        self.assertEqual(claim.trip_total, Decimal("43.21"))

    def test_end_before_start_is_invalid(self):
        claim = self.make_claim()
        claim.travel_end = claim.travel_start - timedelta(days=1)
        with self.assertRaises(ValidationError):
            claim.clean()

    def test_dates_default_to_current_day(self):
        before = timezone.localdate()
        claim = TravelExpenseClaim()
        after = timezone.localdate()
        for field in ("travel_date", "travel_start", "travel_end", "settlement_date"):
            self.assertIn(getattr(claim, field), (before, after))

    def test_pdf_is_a4_and_contains_claim_details(self):
        claim = self.make_claim(round_trip=True)
        reader = PdfReader(BytesIO(TravelExpensePdfService().render_pdf(claim)))
        self.assertEqual(len(reader.pages), 1)
        page = reader.pages[0]
        self.assertAlmostEqual(float(page.mediabox.width), A4[0], places=1)
        self.assertAlmostEqual(float(page.mediabox.height), A4[1], places=1)
        text = page.extract_text()
        for expected in (
            "Reisekostenabrechnung", "000042", "Erika Müller", "B-AB 123",
            "0,350 EUR/km", "86,42 EUR",
            "Unterschrift Mitarbeiter", "Unterschrift Geschäftsführung",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("Anschrift", text)
        self.assertNotIn("Auszahlung erfolgt", text)
        self.assertNotIn("Uhr", text)

    def test_pdf_renders_html_description_as_text(self):
        claim = self.make_claim()
        claim.purpose = "<p>Kundentermin &amp; Gespräch</p><p>Weitere Notiz<br>zweite Zeile</p>"
        text = PdfReader(BytesIO(TravelExpensePdfService().render_pdf(claim))).pages[0].extract_text()
        self.assertIn("Kundentermin & Gespräch", text)
        self.assertIn("Weitere Notiz", text)
        self.assertIn("zweite Zeile", text)
        self.assertNotIn("<p>", text)
        self.assertNotIn("&amp;", text)

    @patch("hr.forms.CompanyProfile.objects.filter")
    def test_company_city_is_shown_and_cannot_be_overridden(self, company_filter):
        company_filter.return_value.values_list.return_value.first.return_value = " Berlin "
        form = TravelExpenseClaimAdminForm()
        place = form.fields["settlement_place"]
        self.assertTrue(place.disabled)
        self.assertEqual(place.initial, "Berlin")

        user = get_user_model()(id=7, username="erika", is_staff=True, is_superuser=True)
        request = RequestFactory().post("/admin/hr/travelexpenseclaim/add/")
        request.user = user
        form_class = TravelExpenseClaimAdmin(TravelExpenseClaim, AdminSite()).get_form(request)
        bound = form_class(data={
            "travel_date": "23.09.2026", "travel_start": "23.09.2026", "travel_end": "23.09.2026",
            "purpose": "Kundentermin", "vehicle": "Privatwagen", "license_plate": "B-AB 123",
            "distance_km": "123.45", "rate_per_km": "0.350", "settlement_place": "Falscher Ort",
        })
        self.assertTrue(bound.is_valid(), bound.errors.as_text())
        self.assertEqual(bound.cleaned_data["settlement_place"], "Berlin")

    @patch("hr.forms.CompanyProfile.objects.filter")
    def test_missing_company_city_blocks_new_claim(self, company_filter):
        company_filter.return_value.values_list.return_value.first.return_value = ""
        form = TravelExpenseClaimAdminForm()
        with self.assertRaisesMessage(ValidationError, "Bitte zuerst einen Ort in den Firmendaten hinterlegen"):
            form.clean_settlement_place()

    def test_admin_uses_logged_in_user_and_restricts_other_claims(self):
        user = get_user_model()(id=7, username="erika", first_name="Erika", last_name="Müller", is_staff=True)
        request = RequestFactory().get("/admin/hr/travelexpenseclaim/")
        request.user = user
        model_admin = TravelExpenseClaimAdmin(TravelExpenseClaim, AdminSite())
        claim = self.make_claim()

        with patch.object(BaseAdmin, "save_model"):
            model_admin.save_model(request, claim, SimpleNamespace(company_city="Berlin"), False)
        self.assertEqual(claim.user_id, user.pk)
        self.assertEqual(claim.name, "Erika Müller")
        self.assertEqual(claim.settlement_place, "Berlin")

        with patch.object(model_admin, "_can_view_all", return_value=False):
            self.assertTrue(model_admin.has_view_permission(request, claim))
            self.assertTrue(model_admin.has_change_permission(request, claim))
            claim.user_id = 8
            self.assertFalse(model_admin.has_view_permission(request, claim))
            with patch.object(model_admin, "get_object", return_value=claim):
                with self.assertRaises(Http404):
                    model_admin._pdf_response(request, claim.pk)


class ResetTravelExpenseSequenceTest(SimpleTestCase):
    def test_empty_table_resets_sequence_after_lock(self):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = (False,)
        database = SimpleNamespace(
            vendor="postgresql",
            ops=SimpleNamespace(
                quote_name=lambda value: f'"{value}"',
                sequence_reset_sql=lambda style, models: ["SELECT reset_sequence()"],
            ),
            cursor=lambda: cursor,
        )
        with patch("hr.management.commands.hr_reset_travel_expense_sequence.connection", database), patch(
            "hr.management.commands.hr_reset_travel_expense_sequence.transaction.atomic", return_value=nullcontext()
        ):
            ResetTravelExpenseSequenceCommand(stdout=StringIO()).handle()
        self.assertEqual(cursor.execute.call_args_list, [
            call('LOCK TABLE "hr_travelexpenseclaim" IN ACCESS EXCLUSIVE MODE'),
            call('SELECT EXISTS (SELECT 1 FROM "hr_travelexpenseclaim")'),
            call("SELECT reset_sequence()"),
        ])

    def test_nonempty_table_is_not_reset(self):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = (True,)
        database = SimpleNamespace(
            vendor="postgresql",
            ops=SimpleNamespace(
                quote_name=lambda value: f'"{value}"',
                sequence_reset_sql=lambda style, models: ["SELECT reset_sequence()"],
            ),
            cursor=lambda: cursor,
        )
        with patch("hr.management.commands.hr_reset_travel_expense_sequence.connection", database), patch(
            "hr.management.commands.hr_reset_travel_expense_sequence.transaction.atomic", return_value=nullcontext()
        ):
            with self.assertRaises(CommandError):
                ResetTravelExpenseSequenceCommand(stdout=StringIO()).handle()
        self.assertNotIn(call("SELECT reset_sequence()"), cursor.execute.call_args_list)
