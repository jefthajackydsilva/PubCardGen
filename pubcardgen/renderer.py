"""Stamp card data onto the official S-21 form."""

from __future__ import annotations

import io
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import layout
from .models import MONTHS, Card


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _format_date(value: date | None) -> str:
    return value.strftime(layout.DATE_FORMAT) if value else ""


def _fit(text: str, max_width: float, font: str, size: float, min_size: float) -> tuple[str, float]:
    """Shrink then, as a last resort, truncate text so it fits ``max_width``."""
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.5
    if stringWidth(text, font, size) <= max_width:
        return text, size

    ellipsis = "\u2026"
    while text and stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return text + ellipsis, size


class CardRenderer:
    """Draws card data as an overlay and merges it onto a copy of the template page."""

    def __init__(self, template_path: Path, show_credit_overflow: bool = True) -> None:
        self._template_bytes = Path(template_path).read_bytes()
        self._show_credit_overflow = show_credit_overflow

    def _overlay(self, card: Card) -> PdfReader:
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=(layout.PAGE_WIDTH, layout.PAGE_HEIGHT))
        self._draw_header(pdf, card)
        self._draw_table(pdf, card)
        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        return PdfReader(buffer)

    def _check(
        self, pdf: canvas.Canvas, position: tuple[float, float], box_size: float
    ) -> None:
        x, y = position
        size = box_size * layout.CHECK_SCALE
        pdf.saveState()
        pdf.setLineWidth(size * 0.14)
        pdf.setLineCap(1)
        pdf.setLineJoin(1)
        path = pdf.beginPath()
        path.moveTo(x - 0.40 * size, y + 0.02 * size)
        path.lineTo(x - 0.12 * size, y - 0.30 * size)
        path.lineTo(x + 0.42 * size, y + 0.34 * size)
        pdf.drawPath(path, stroke=1, fill=0)
        pdf.restoreState()

    def _header_check(self, pdf: canvas.Canvas, position: tuple[float, float]) -> None:
        self._check(pdf, position, layout.HEADER_BOX_SIZE)

    def _draw_header(self, pdf: canvas.Canvas, card: Card) -> None:
        publisher = card.publisher

        name, size = _fit(
            publisher.name, layout.NAME_MAX_WIDTH, layout.FONT, layout.BODY_SIZE, 6.0
        )
        pdf.setFont(layout.FONT, size)
        pdf.drawString(layout.NAME_X, layout.NAME_BASELINE, name)

        pdf.setFont(layout.FONT, layout.BODY_SIZE)
        pdf.drawString(layout.DOB_X, layout.DOB_BASELINE, _format_date(publisher.date_of_birth))
        pdf.drawString(
            layout.BAPTISM_X, layout.BAPTISM_BASELINE, _format_date(publisher.date_of_baptism)
        )

        pdf.setFont(layout.FONT, layout.SERVICE_YEAR_SIZE)
        pdf.drawCentredString(
            layout.SERVICE_YEAR_CENTRE_X, layout.SERVICE_YEAR_BASELINE, card.service_year
        )

        if publisher.is_male:
            self._header_check(pdf, layout.CHECK_MALE)
        if publisher.is_female:
            self._header_check(pdf, layout.CHECK_FEMALE)
        if publisher.is_other_sheep:
            self._header_check(pdf, layout.CHECK_OTHER_SHEEP)
        if publisher.is_anointed:
            self._header_check(pdf, layout.CHECK_ANOINTED)
        if publisher.is_elder:
            self._header_check(pdf, layout.CHECK_ELDER)
        if publisher.is_ministerial_servant:
            self._header_check(pdf, layout.CHECK_MINISTERIAL_SERVANT)
        if publisher.is_regular_pioneer:
            self._header_check(pdf, layout.CHECK_REGULAR_PIONEER)
        if publisher.is_special_pioneer:
            self._header_check(pdf, layout.CHECK_SPECIAL_PIONEER)
        if publisher.is_field_missionary:
            self._header_check(pdf, layout.CHECK_FIELD_MISSIONARY)

    def _draw_table(self, pdf: canvas.Canvas, card: Card) -> None:
        for index, month in enumerate(MONTHS):
            report = card.report(month)
            if report is None or report.is_empty:
                continue

            centre = layout.ROW_CENTRES[index]
            text_baseline = layout.baseline(centre, layout.BODY_SIZE)

            if report.shared:
                self._check(pdf, (layout.SHARED_CHECK_X, centre), layout.TABLE_BOX_SIZE)
            if report.status == "AP":
                self._check(pdf, (layout.AUX_PIONEER_CHECK_X, centre), layout.TABLE_BOX_SIZE)

            pdf.setFont(layout.FONT, layout.BODY_SIZE)
            if report.bible_studies is not None:
                pdf.drawCentredString(
                    layout.BIBLE_STUDIES_CENTRE_X, text_baseline, str(report.bible_studies)
                )
            if report.hours is not None:
                pdf.drawCentredString(
                    layout.HOURS_CENTRE_X, text_baseline, _format_number(report.hours)
                )
            if report.remarks:
                remarks, size = _fit(
                    report.remarks,
                    layout.REMARKS_MAX_WIDTH,
                    layout.FONT,
                    layout.REMARKS_SIZE,
                    layout.MIN_REMARKS_SIZE,
                )
                pdf.setFont(layout.FONT, size)
                pdf.drawString(
                    layout.REMARKS_LEFT_X, layout.baseline(centre, size), remarks
                )

        if card.total_hours:
            pdf.setFont(layout.FONT, layout.BODY_SIZE)
            pdf.drawCentredString(
                layout.TOTAL_HOURS_CENTRE_X,
                layout.baseline(layout.TOTAL_ROW_CENTRE, layout.BODY_SIZE),
                _format_number(card.total_hours),
            )

        notes: list[str] = []
        if card.has_credit:
            note = f"Total including credit = {_format_number(card.total_with_credit)}"
            if self._show_credit_overflow:
                note += f"; Credit overflow = {_format_number(card.credit_overflow)}"
            notes.append(note)

        average = card.pioneer_average
        if average is not None:
            months = len(card.pioneer_months)
            notes.append(
                f"Average = {_format_number(round(average, 1))} hrs "
                f"({months} month{'s' if months != 1 else ''})"
            )

        if notes:
            text, size = _fit(
                "; ".join(notes),
                layout.REMARKS_MAX_WIDTH,
                layout.FONT,
                layout.REMARKS_SIZE,
                layout.MIN_REMARKS_SIZE,
            )
            pdf.setFont(layout.FONT, size)
            pdf.drawString(
                layout.REMARKS_LEFT_X,
                layout.baseline(layout.TOTAL_ROW_CENTRE, size),
                text,
            )

    def render(self, card: Card) -> bytes:
        """Return a one page PDF for the card, so it can be reused without re-rendering."""
        template = PdfReader(io.BytesIO(self._template_bytes))
        page = template.pages[0]
        page.merge_page(self._overlay(card).pages[0])

        writer = PdfWriter()
        writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    @staticmethod
    def save(document: bytes, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(document)
        return destination

    @staticmethod
    def merge(documents: Iterable[bytes]) -> bytes:
        writer = PdfWriter()
        for document in documents:
            for page in PdfReader(io.BytesIO(document)).pages:
                writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    @classmethod
    def combine(cls, documents: Iterable[bytes], destination: Path) -> Path:
        return cls.save(cls.merge(documents), destination)
