from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from core.admin import BaseAdmin
from hr.admin import TravelExpenseClaimAdmin
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
            "0,350 EUR/km", "86,42 EUR", "Unterschrift",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("Anschrift", text)
        self.assertNotIn("Uhr", text)

    def test_admin_uses_logged_in_user_and_restricts_other_claims(self):
        user = get_user_model()(id=7, username="erika", first_name="Erika", last_name="Müller", is_staff=True)
        request = RequestFactory().get("/admin/hr/travelexpenseclaim/")
        request.user = user
        model_admin = TravelExpenseClaimAdmin(TravelExpenseClaim, AdminSite())
        claim = self.make_claim()

        with patch.object(BaseAdmin, "save_model"):
            model_admin.save_model(request, claim, None, False)
        self.assertEqual(claim.user_id, user.pk)
        self.assertEqual(claim.name, "Erika Müller")

        with patch.object(model_admin, "_can_view_all", return_value=False):
            self.assertTrue(model_admin.has_view_permission(request, claim))
            claim.user_id = 8
            self.assertFalse(model_admin.has_view_permission(request, claim))
            with patch.object(model_admin, "get_object", return_value=claim):
                with self.assertRaises(Http404):
                    model_admin._pdf_response(request, claim.pk)
