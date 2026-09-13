"""Data model for publisher record cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Service year runs September through August; this order matches the S-21 table rows.
MONTHS: tuple[str, ...] = (
    "Sep",
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
)

PIONEER_STATUSES = frozenset({"AP", "RP", "SP", "FM"})
FULL_TIME_STATUSES = frozenset({"RP", "SP", "FM"})

# Reported hours plus credit may not exceed this in any one month.
CREDIT_CAP = 55.0


@dataclass(frozen=True, slots=True)
class MonthlyReport:
    month: str
    name: str = ""
    group: str | None = None
    shared: bool = False
    bible_studies: int | None = None
    status: str | None = None
    hours: float | None = None
    remarks: str | None = None
    credit: float | None = None

    @property
    def is_empty(self) -> bool:
        return not (
            self.shared
            or self.bible_studies
            or self.status
            or self.hours
            or self.remarks
            or self.credit
        )

    @property
    def has_figures(self) -> bool:
        """Whether the month was reported at all; the status alone is often pre-filled for the year."""
        return bool(
            self.shared or self.bible_studies or self.hours or self.remarks or self.credit
        )


@dataclass(frozen=True, slots=True)
class Publisher:
    name: str
    date_of_birth: date | None = None
    date_of_baptism: date | None = None
    gender: str | None = None
    hope: str | None = None
    appointment: str | None = None
    pioneer_status: str | None = None
    field_service_group: str | None = None

    @property
    def is_regular_pioneer(self) -> bool:
        return self.pioneer_status == "RP"

    @property
    def is_special_pioneer(self) -> bool:
        return self.pioneer_status == "SP"

    @property
    def is_field_missionary(self) -> bool:
        return self.pioneer_status == "FM"

    @property
    def is_pioneer(self) -> bool:
        """Regular pioneers, special pioneers and field missionaries. Auxiliary pioneers are not."""
        return self.is_regular_pioneer or self.is_special_pioneer or self.is_field_missionary

    @property
    def is_male(self) -> bool:
        return (self.gender or "").strip().casefold() == "male"

    @property
    def is_female(self) -> bool:
        return (self.gender or "").strip().casefold() == "female"

    @property
    def is_anointed(self) -> bool:
        return (self.hope or "").strip().casefold() == "anointed"

    @property
    def is_other_sheep(self) -> bool:
        return (self.hope or "").strip().casefold() == "other sheep"

    @property
    def is_elder(self) -> bool:
        return (self.appointment or "").strip().casefold() == "elder"

    @property
    def is_ministerial_servant(self) -> bool:
        return (self.appointment or "").strip().casefold() in {"ms", "ministerial servant"}


@dataclass(slots=True)
class Card:
    publisher: Publisher
    service_year: str
    reports: dict[str, MonthlyReport] = field(default_factory=dict)

    def report(self, month: str) -> MonthlyReport | None:
        return self.reports.get(month)

    @property
    def total_hours(self) -> float:
        return sum(r.hours or 0 for r in self.reports.values())

    @property
    def has_any_report(self) -> bool:
        return any(not r.is_empty for r in self.reports.values())

    @property
    def has_credit(self) -> bool:
        return any(r.credit for r in self.reports.values())

    @property
    def credit_applied(self) -> float:
        return self._credit[0]

    @property
    def credit_overflow(self) -> float:
        return self._credit[1]

    @property
    def total_with_credit(self) -> float:
        return self.total_hours + self.credit_applied

    @property
    def pioneer_months(self) -> list[str]:
        """Months served as a regular/special pioneer or field missionary, in service year order.

        Read from the month sheet status column only: PubInfo gives today's standing, which says
        nothing about the months before somebody started pioneering.
        """
        return [
            month
            for month in MONTHS
            if (report := self.report(month))
            and report.has_figures
            and report.status in FULL_TIME_STATUSES
        ]

    @property
    def pioneer_average(self) -> float | None:
        """Average monthly hours including credit across the pioneer months.

        None unless the publisher was still pioneering at their last report: somebody who gave
        up pioneering part way through the year is not averaged at all, while somebody who took
        it up mid-year is averaged over the pioneer months only.
        """
        months = self.pioneer_months
        if not months:
            return None

        for month in MONTHS[MONTHS.index(months[0]):]:
            report = self.report(month)
            if report and report.has_figures and month not in months:
                return None

        return sum(_hours_with_credit(self.reports[m]) for m in months) / len(months)

    @property
    def _credit(self) -> tuple[float, float]:
        """Credit that fits under the monthly cap, and the remainder that does not."""
        applied = overflow = 0.0
        for report in self.reports.values():
            credit = report.credit or 0
            if not credit or not serves_as_pioneer(self.publisher, report):
                continue
            usable = max(0.0, CREDIT_CAP - (report.hours or 0))
            used = min(credit, usable)
            applied += used
            overflow += credit - used
        return applied, overflow


def _hours_with_credit(report: MonthlyReport) -> float:
    """The month's hours plus whatever credit fits under the cap."""
    hours = report.hours or 0
    return hours + min(report.credit or 0, max(0.0, CREDIT_CAP - hours))


def serves_as_pioneer(publisher: Publisher, report: MonthlyReport) -> bool:
    """Whether the month was served as a regular/special pioneer or field missionary."""
    if report.status == "AP":
        return False
    return report.status in FULL_TIME_STATUSES or publisher.is_pioneer
