from __future__ import annotations

from io import BytesIO
from html import escape
from pathlib import Path

from django.utils import timezone
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.services import BaseService
from hr.models import TravelExpenseClaim


class TravelExpensePdfService(BaseService):
    model = TravelExpenseClaim

    @staticmethod
    def _money(value, digits: int = 2) -> str:
        return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")

    @staticmethod
    def _paragraph(value, style: ParagraphStyle) -> Paragraph:
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)

    def render_pdf(self, claim: TravelExpenseClaim) -> bytes:
        font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
        if "TravelExpenseVera" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("TravelExpenseVera", str(font_dir / "Vera.ttf")))
            pdfmetrics.registerFont(TTFont("TravelExpenseVeraBold", str(font_dir / "VeraBd.ttf")))
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=22 * mm,
            rightMargin=22 * mm,
            topMargin=22 * mm,
            bottomMargin=20 * mm,
            title=f"Reisekostenabrechnung Nr. {claim.number}",
            author="GC-Bridge-4",
        )
        ink = colors.HexColor("#172334")
        muted = colors.HexColor("#5A6675")
        rule = colors.HexColor("#D5DCE5")
        body = ParagraphStyle("body", fontName="TravelExpenseVera", fontSize=10, leading=15, textColor=ink)
        label = ParagraphStyle("label", parent=body, fontSize=8, leading=11, textColor=muted)
        title = ParagraphStyle("title", parent=body, fontName="TravelExpenseVeraBold", fontSize=20, leading=24)
        section = ParagraphStyle("section", parent=body, fontName="TravelExpenseVeraBold", fontSize=11, leading=15)
        bold = ParagraphStyle("bold", parent=body, fontName="TravelExpenseVeraBold")
        small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=12)

        def p(value, style=body):
            return self._paragraph(value, style)

        def detail_row(left_label, left_value, right_label=None, right_value=None):
            cells = [[p(left_label, label), p(right_label, label) if right_label else ""],
                     [p(left_value), p(right_value) if right_label else ""]]
            table = Table(cells, colWidths=[83 * mm, 83 * mm], hAlign="LEFT")
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
            ]))
            return table

        start = timezone.localtime(claim.travel_start) if timezone.is_aware(claim.travel_start) else claim.travel_start
        end = timezone.localtime(claim.travel_end) if timezone.is_aware(claim.travel_end) else claim.travel_end
        story = [
            p("Reisekostenabrechnung", title),
            Spacer(1, 3 * mm),
            p(f"Nr. {claim.number}", bold),
            Spacer(1, 5 * mm),
            HRFlowable(width="100%", thickness=1, color=rule),
            Spacer(1, 5 * mm),
            p("Angaben zur Person", section),
            Spacer(1, 2 * mm),
            detail_row("Name", claim.name, "Anschrift", claim.address),
            Spacer(1, 2 * mm),
            p("Reise", section),
            Spacer(1, 2 * mm),
            detail_row("Datum", claim.travel_date.strftime("%d.%m.%Y"), "Anlass", claim.purpose),
            detail_row("Reisebeginn", start.strftime("%d.%m.%Y, %H:%M Uhr"),
                       "Reiseende", end.strftime("%d.%m.%Y, %H:%M Uhr")),
            detail_row("Fahrzeug", claim.vehicle, "Kennzeichen", claim.license_plate),
            Spacer(1, 2 * mm),
            p("Fahrtkosten", section),
            Spacer(1, 3 * mm),
        ]
        cost_rows = [
            [p("Strecke", label), p("Pauschale", label), p("Fahrtkosten", label), p("Fahrt", label)],
            [p(f"{self._money(claim.distance_km)} km"), p(f"{self._money(claim.rate_per_km, 3)} EUR/km"),
             p(f"{self._money(claim.fare_cost)} EUR"), p("Hin und zurück" if claim.round_trip else "Einfach")],
        ]
        costs = Table(cost_rows, colWidths=[41.5 * mm] * 4, hAlign="LEFT")
        costs.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F5F8")),
            ("BOX", (0, 0), (-1, -1), 0.5, rule),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, rule),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.extend([
            costs,
            Spacer(1, 5 * mm),
            detail_row("Summe der Fahrt", f"{self._money(claim.trip_total)} EUR",
                       "Gesamtsumme", f"{self._money(claim.trip_total)} EUR"),
            Spacer(1, 6 * mm),
            HRFlowable(width="100%", thickness=1, color=rule),
            Spacer(1, 5 * mm),
            detail_row("Ort der Abrechnung", claim.settlement_place,
                       "Datum der Abrechnung", claim.settlement_date.strftime("%d.%m.%Y")),
            Spacer(1, 13 * mm),
            KeepTogether([
                HRFlowable(width=70 * mm, thickness=0.7, color=ink, hAlign="LEFT"),
                Spacer(1, 2 * mm),
                p("Unterschrift", small),
            ]),
        ])
        document.build(story)
        return buffer.getvalue()
