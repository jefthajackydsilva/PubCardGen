"""Congregation totals expressed as extra S-21 cards, one per reporting category."""

from __future__ import annotations

from .models import MONTHS, Card, MonthlyReport, Publisher, serves_as_pioneer

PIONEERS = "Regular and Special Pioneers and Field Missionaries"
AUXILIARY = "Auxiliary Pioneers"
PUBLISHERS = "All Other Publishers"

# Numbered so the three files sort into reading order in the output folder.
_STEMS = {
    PIONEERS: "Summary 1 - Pioneers",
    AUXILIARY: "Summary 2 - Auxiliary Pioneers",
    PUBLISHERS: "Summary 3 - All Other Publishers",
}


def category(publisher: Publisher, report: MonthlyReport) -> str:
    """Bucket by how the person served that month, falling back to their PubInfo standing."""
    if report.status == "AP":
        return AUXILIARY
    return PIONEERS if serves_as_pioneer(publisher, report) else PUBLISHERS


def build(cards: list[Card], service_year: str) -> list[tuple[str, Card]]:
    tallies: dict[str, dict[str, list[float]]] = {
        label: {month: [0, 0, 0.0] for month in MONTHS} for label in _STEMS
    }

    for card in cards:
        for month, report in card.reports.items():
            if report.is_empty:
                continue
            tally = tallies[category(card.publisher, report)][month]
            tally[0] += 1
            tally[1] += report.bible_studies or 0
            tally[2] += report.hours or 0

    summaries = []
    for label, stem in _STEMS.items():
        reports = {}
        for month in MONTHS:
            count, studies, hours = tallies[label][month]
            if not count:
                continue
            reports[month] = MonthlyReport(
                month=month,
                name=label,
                bible_studies=int(studies),
                hours=hours or None,
                remarks=f"{int(count)} reporting",
            )
        summaries.append(
            (stem, Card(publisher=Publisher(name=label), service_year=service_year, reports=reports))
        )
    return summaries
