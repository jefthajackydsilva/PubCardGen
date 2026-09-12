"""Command line entry point: python -m pubcardgen"""

from __future__ import annotations

import argparse
import calendar
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from . import excel_reader, summary
from .models import FULL_TIME_STATUSES, MONTHS, Card, Publisher
from .renderer import CardRenderer

# done, total, label. A total of zero means the length is not known yet.
ProgressCallback = Callable[[int, int, str], None]

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|]+')
UNGROUPED = "Ungrouped"
BY_GROUP_TREE = "By group"
FILING_TREE = "By filing order"
PIONEER_SECTION = "1 - Pioneers"
PUBLISHER_SECTION = "2 - Publishers"
PREVIOUS_PUBINFO = "last year's PubInfo"
MONTH_SHEETS = "the month sheets only"


@dataclass(frozen=True, slots=True)
class Recovered:
    """A reporter rebuilt for the summaries because PubInfo does not list them."""

    publisher: Publisher
    source: str
    months: list[str]


def _safe_filename(value: str) -> str:
    return _UNSAFE_FILENAME.sub("-", value).strip(" .") or "Unnamed"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pubcardgen",
        description="Generate S-21 publisher record cards from the field report workbook.",
    )
    parser.add_argument(
        "--current_workbook",
        type=Path,
        default=Path("FeildReport_v4_2026-2027.xlsm"),
        help="Current service year field report workbook (.xlsm/.xlsx).",
    )
    parser.add_argument(
        "--template", type=Path, default=Path("S-21_E.pdf"), help="Blank S-21 form."
    )
    parser.add_argument("--out", type=Path, default=Path("output"), help="Output directory.")
    parser.add_argument(
        "--year",
        help="Service year label, e.g. 2026-2027. Defaults to the year in the workbook file name.",
    )
    parser.add_argument(
        "--previous_workbook",
        type=Path,
        help="Previous service year workbook. Adds that year as a second page on every card.",
    )
    parser.add_argument(
        "--group", action="append", help="Only this field service group. Repeatable."
    )
    parser.add_argument(
        "--no_credit_overflow",
        action="store_true",
        help="Leave the credit overflow figure off the cards; only the total including credit.",
    )
    parser.add_argument(
        "--list_unbaptized",
        action="store_true",
        help="List the publishers with a card but no date of baptism.",
    )
    parser.add_argument(
        "--baptism_reminder",
        nargs=2,
        type=int,
        metavar=("MIN_MONTHS", "MAX_MONTHS"),
        help="List publishers baptized between this many months ago and that many months ago.",
    )
    return parser.parse_args(argv)


def _group(card: Card) -> str:
    return card.publisher.field_service_group or UNGROUPED


def destinations(card: Card, out: Path) -> list[Path]:
    """Every location the card is filed under: by group, and by pioneer/publisher section."""
    filename = f"{_safe_filename(card.publisher.name)}.pdf"
    group = _safe_filename(_group(card))

    section = (
        Path(PIONEER_SECTION)
        if card.publisher.is_pioneer
        else Path(PUBLISHER_SECTION) / group
    )
    return [
        out / BY_GROUP_TREE / group / filename,
        out / FILING_TREE / section / filename,
    ]


def _index(publishers) -> dict[str, Publisher]:
    return {excel_reader.normalize_name(p.name): p for p in publishers}


def as_of_previous_year(current: Publisher, previous: Publisher | None) -> Publisher:
    """Last year's card keeps this year's details but last year's appointment and standing."""
    return replace(
        current,
        appointment=previous.appointment if previous else None,
        pioneer_status=previous.pioneer_status if previous else None,
    )


def previous_year_roster(current_roster, previous_roster) -> list[Publisher]:
    """Everyone listed last year, described by this year's details where they still exist."""
    current = _index(current_roster)
    return [
        as_of_previous_year(current.get(excel_reader.normalize_name(p.name), p), p)
        for p in previous_roster
    ]


def build_cards(publishers, reports, service_year: str) -> list[Card]:
    cards = [
        Card(
            publisher=publisher,
            service_year=service_year,
            reports=dict(reports.get(excel_reader.normalize_name(publisher.name), {})),
        )
        for publisher in publishers
    ]
    cards.sort(key=lambda c: (_group(c).casefold(), c.publisher.name.casefold()))
    return cards


def _known_names(publishers, excluded) -> set[str]:
    return {excel_reader.normalize_name(p.name) for p in list(publishers) + list(excluded)}


def _from_month_reports(name: str, months) -> Publisher:
    """The little a month sheet knows about someone: their group and full-time standing."""
    latest = [months[m] for m in reversed(MONTHS) if m in months]
    return Publisher(
        name=name,
        pioneer_status=next((r.status for r in latest if r.status in FULL_TIME_STATUSES), None),
        field_service_group=next((r.group for r in latest if r.group), None),
    )


def recovered_publishers(publishers, excluded, reports, previous_roster) -> list[Recovered]:
    """Month sheet names missing from PubInfo, rebuilt so their reports still reach the summaries.

    Someone who moved away mid-year is off PubInfo and needs no card, but the months they
    did report still count. Last year's PubInfo supplies the personal details when it has
    them; the group and full-time standing always come from this year's month sheets.
    """
    known = _known_names(publishers, excluded)
    previous = _index(previous_roster)

    recovered = []
    for key, months in reports.items():
        if key in known:
            continue
        name = next((r.name for r in months.values() if r.name), key)
        from_months = _from_month_reports(name, months)
        prior = previous.get(key)
        if prior:
            from_months = replace(
                prior,
                pioneer_status=from_months.pioneer_status or prior.pioneer_status,
                field_service_group=from_months.field_service_group or prior.field_service_group,
            )
        recovered.append(
            Recovered(
                publisher=from_months,
                source=PREVIOUS_PUBINFO if prior else MONTH_SHEETS,
                months=[m for m in MONTHS if m in months],
            )
        )
    return sorted(recovered, key=lambda r: r.publisher.name.casefold())


def departed_publishers(publishers, excluded, reports, previous_roster) -> list[str]:
    """Last year's publishers who left PubInfo and filed no report this year."""
    known = _known_names(publishers, excluded)
    return sorted(
        p.name
        for p in previous_roster
        if excel_reader.normalize_name(p.name) not in known
        and excel_reader.normalize_name(p.name) not in reports
    )


def _months_ago(day: date, months: int) -> date:
    """The date ``months`` whole months before ``day``, clamped to the shorter month."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    return months - 1 if end.day < start.day else months


def months_label(months: int) -> str:
    years, rest = divmod(months, 12)
    if not years:
        return f"{months} months"
    text = "1 year" if years == 1 else f"{years} years"
    return text if not rest else f"{text} {rest} months"


def unbaptized(cards) -> list[Card]:
    return [card for card in cards if card.publisher.date_of_baptism is None]


def service_year_problem(current: str, previous: str) -> str | None:
    """The reason these are not a service year and the one before it, or None if they are."""
    current_start = int(current.split("-")[0])
    previous_start = int(previous.split("-")[0])
    if current_start == previous_start:
        return f"both workbooks are for the {current} service year."
    if current_start < previous_start:
        return (
            f"the current workbook is {current} but the previous workbook is {previous}, "
            "which is later. The two look swapped."
        )
    if current_start != previous_start + 1:
        return (
            f"{previous} and {current} are not consecutive service years. The previous "
            "workbook has to be the year immediately before the current one."
        )
    return None


def baptism_reminders(
    cards, low_months: int, high_months: int, today: date
) -> list[tuple[Card, date]]:
    """Cards baptized more than ``low_months`` and less than ``high_months`` ago, oldest first."""
    earliest, latest = _months_ago(today, high_months), _months_ago(today, low_months)
    found = [
        (card, card.publisher.date_of_baptism)
        for card in cards
        if card.publisher.date_of_baptism
        and earliest <= card.publisher.date_of_baptism <= latest
    ]
    return sorted(found, key=lambda row: row[1])


def main(argv: list[str] | None = None, progress: ProgressCallback | None = None) -> int:
    args = _parse_args(argv)
    report_progress = progress or (lambda done, total, label: None)

    required = [args.current_workbook, args.template]
    if args.previous_workbook:
        required.append(args.previous_workbook)
    for path in required:
        if not path.is_file():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1

    try:
        service_year = args.year or excel_reader.service_year_from_filename(args.current_workbook)
        previous_year = (
            excel_reader.service_year_from_filename(args.previous_workbook)
            if args.previous_workbook
            else None
        )
    except excel_reader.WorkbookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if previous_year:
        problem = service_year_problem(service_year, previous_year)
        if problem:
            print(f"error: {problem}", file=sys.stderr)
            return 1

    # A total of zero means "busy, length unknown".
    report_progress(0, 0, "Reading the workbooks")
    all_publishers, excluded, reports = excel_reader.load(args.current_workbook)

    previous_roster: list[Publisher] = []
    previous_reports: dict = {}
    if args.previous_workbook:
        prior, prior_excluded, previous_reports = excel_reader.load(args.previous_workbook)
        previous_roster = prior + prior_excluded

    recovered = recovered_publishers(all_publishers, excluded, reports, previous_roster)
    departed = departed_publishers(all_publishers, excluded, reports, previous_roster)
    # Counted in the summaries but never given a card of their own.
    cardless = excluded + [r.publisher for r in recovered]
    publishers = all_publishers

    if args.group:
        wanted = {g.casefold() for g in args.group}
        publishers = [
            p for p in publishers if (p.field_service_group or UNGROUPED).casefold() in wanted
        ]
        if not publishers:
            print(f"error: no publishers in group(s): {', '.join(args.group)}", file=sys.stderr)
            return 1

    cards = build_cards(publishers, reports, service_year)
    renderer = CardRenderer(args.template, show_credit_overflow=not args.no_credit_overflow)

    previous_by_name = _index(previous_roster)
    new_publishers: list[str] = []

    def pages_for(card: Card) -> tuple[bytes, bytes | None]:
        """This year's page, plus last year's unless the publisher is new this year."""
        current = renderer.render(card)
        if not previous_year:
            return current, None

        key = excel_reader.normalize_name(card.publisher.name)
        prior = previous_by_name.get(key)
        prior_reports = previous_reports.get(key)
        if not prior and not prior_reports:
            new_publishers.append(card.publisher.name)
            return current, None

        return current, renderer.render(
            Card(
                publisher=as_of_previous_year(card.publisher, prior),
                service_year=previous_year,
                reports=dict(prior_reports or {}),
            )
        )

    def store(current: bytes, previous: bytes | None, destinations_: list[Path]) -> None:
        current_pages.append(current)
        document = current
        if previous is not None:
            previous_pages.append(previous)
            document = renderer.merge([current, previous])
        for destination in destinations_:
            renderer.save(document, destination)

    current_pages: list[bytes] = []
    previous_pages: list[bytes] = []

    # The three summary cards and the master PDFs are the steps that follow the cards.
    total_steps = len(cards) + 4
    step = 0
    report_progress(0, total_steps, "Rendering cards")

    for card in cards:
        current, previous = pages_for(card)
        store(current, previous, destinations(card, args.out))
        step += 1
        report_progress(step, total_steps, card.publisher.name)

    # Summaries cover the whole congregation, including people who get no card of their own.
    counted = build_cards(all_publishers + cardless, reports, service_year)
    summaries = summary.build(counted, service_year)

    previous_summaries = []
    if previous_year:
        roster = previous_year_roster(all_publishers + cardless, previous_roster)
        previous_summaries = summary.build(
            build_cards(roster, previous_reports, previous_year), previous_year
        )

    for index, (stem, card) in enumerate(summaries):
        previous = renderer.render(previous_summaries[index][1]) if previous_summaries else None
        store(renderer.render(card), previous, [args.out / f"{_safe_filename(stem)}.pdf"])
        step += 1
        report_progress(step, total_steps, stem)

    masters = [renderer.combine(current_pages, args.out / f"All cards {service_year}.pdf")]
    if previous_pages:
        masters.append(
            renderer.combine(previous_pages, args.out / f"All cards {previous_year}.pdf")
        )
    report_progress(total_steps, total_steps, "Master PDFs")

    unreported = [c.publisher.name for c in cards if not c.has_any_report]

    print(f"Service year        : {service_year}")
    if previous_year:
        print(f"Previous year       : {previous_year}")
    print(f"Cards generated     : {len(cards)}")
    print(f"Summary cards       : {len(summaries)}")
    print(f"Output directory    : {args.out.resolve()}")
    if args.no_credit_overflow:
        print("Credit overflow     : not printed on cards")
    for master in masters:
        print(f"Master PDF          : {master.name}")
    if excluded:
        names = sorted(p.name for p in excluded)
        print(f"Skipped (do not generate): {len(excluded)} - {', '.join(names)}")
    if new_publishers:
        names = sorted(new_publishers)
        print(f"New this year (no {previous_year} page): {len(names)} - {', '.join(names)}")

    if args.list_unbaptized:
        rows = unbaptized(cards)
        print(f"\nUnbaptized publishers: {len(rows)}")
        for card in rows:
            print(f"         {card.publisher.name} ({_group(card)})")

    if args.baptism_reminder:
        today = datetime.now().astimezone().date()
        low, high = sorted(args.baptism_reminder)
        rows = baptism_reminders(cards, low, high, today)
        print(
            f"\nBaptized between {months_label(low)} and {months_label(high)} ago: {len(rows)}"
        )
        for card, baptism in rows:
            elapsed = months_label(months_between(baptism, today))
            print(
                f"         {card.publisher.name} ({_group(card)}) - baptized "
                f"{baptism:%d %b %Y}, {elapsed} ago"
            )

    if unreported:
        print(
            f"warning: {len(unreported)} name(s) in PubInfo have no report in any month sheet, "
            "so their card is blank:",
            file=sys.stderr,
        )
        for name in unreported:
            print(f"         {name}", file=sys.stderr)
    if recovered:
        print(
            f"warning: {len(recovered)} name(s) report in the month sheets but are missing from "
            "PubInfo. Their figures are in the summaries, but they get no card. Add them to "
            "PubInfo if they still need one:",
            file=sys.stderr,
        )
        for entry in recovered:
            print(
                f"         {entry.publisher.name} - details from {entry.source}"
                f" ({', '.join(entry.months)})",
                file=sys.stderr,
            )
    if departed:
        print(
            f"warning: {len(departed)} name(s) in the {previous_year} PubInfo are no longer in "
            "PubInfo and filed no report this year, so they get no card:",
            file=sys.stderr,
        )
        for name in departed:
            print(f"         {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
