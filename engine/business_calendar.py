"""Business calendar: US federal holidays and optional closed-day overrides.

5 U.S.C. § 6103 federal holidays (11 total; Juneteenth from 2021 only):
  New Year's Day          Jan 1
  MLK Birthday            3rd Monday January
  Washington's Birthday   3rd Monday February
  Memorial Day            last Monday May
  Juneteenth              Jun 19 (from 2021 only)
  Independence Day        Jul 4
  Labor Day               1st Monday September
  Columbus Day            2nd Monday October
  Veterans Day            Nov 11
  Thanksgiving            4th Thursday November
  Christmas Day           Dec 25

Fixed-date holidays (Jan 1, Jun 19, Jul 4, Nov 11, Dec 25) falling on Saturday
are observed the Friday before; on Sunday the Monday after (OPM rule).

federal_holidays(year) returns exactly the OPM list for that year — 11 entries
for years >= 2021 (10 for earlier years without Juneteenth).  It never reaches
into an adjacent year.  Specifically it does NOT include the observed New Year's
Day of year+1 (which falls on Dec 31 when Jan 1 of year+1 is Saturday); that
date belongs to federal_holidays(year+1).

BusinessCalendar.is_closed(d) handles the cross-year boundary: for Dec 31 it
also checks federal_holidays(d.year + 1), so a New Year's Day observed on Dec
31 is still marked closed.

Inauguration Day is not included.
stdlib only (csv, collections, datetime, pathlib, sys).
"""
from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence (1-based) of *weekday* in *month*/*year*.

    weekday: 0=Monday … 6=Sunday (same as date.weekday()).
    """
    # First day of the month
    first = date(year, month, 1)
    # Day of week of the 1st
    first_wd = first.weekday()
    # Days until the first occurrence of weekday
    delta = (weekday - first_wd) % 7
    first_occurrence = first + timedelta(days=delta)
    return first_occurrence + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of *weekday* in *month*/*year*."""
    # Last day of month
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    last_wd = last.weekday()
    delta = (last_wd - weekday) % 7
    return last - timedelta(days=delta)


def _observe(d: date) -> date:
    """Return the observed date for a fixed-date holiday.

    Saturday → Friday before; Sunday → Monday after.
    """
    wd = d.weekday()
    if wd == 5:  # Saturday
        return d - timedelta(days=1)
    if wd == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def federal_holidays(year: int) -> dict:
    """Return {observed_date: name} for all US federal holidays of *year*.

    Includes the New Year's Day of *year+1* if it is observed on Dec 31
    (i.e., Jan 1 of year+1 falls on Saturday).

    Parameters
    ----------
    year : int

    Returns
    -------
    dict mapping date -> str holiday name
    """
    holidays = {}

    def add(d: date, name: str) -> None:
        holidays[d] = name

    # New Year's Day (Jan 1 of *year*)
    add(_observe(date(year, 1, 1)), "New Year's Day")

    # MLK Birthday (3rd Monday January)
    add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")

    # Washington's Birthday (3rd Monday February)
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")

    # Memorial Day (last Monday May)
    add(_last_weekday(year, 5, 0), "Memorial Day")

    # Juneteenth (Jun 19, from 2021 only)
    if year >= 2021:
        add(_observe(date(year, 6, 19)), "Juneteenth National Independence Day")

    # Independence Day (Jul 4)
    add(_observe(date(year, 7, 4)), "Independence Day")

    # Labor Day (1st Monday September)
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")

    # Columbus Day (2nd Monday October)
    add(_nth_weekday(year, 10, 0, 2), "Columbus Day")

    # Veterans Day (Nov 11)
    add(_observe(date(year, 11, 11)), "Veterans Day")

    # Thanksgiving (4th Thursday November)
    add(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")

    # Christmas Day (Dec 25)
    add(_observe(date(year, 12, 25)), "Christmas Day")

    # New Year's Day of *year* itself may be observed on Dec 31 of *year-1*
    # when Jan 1 of *year* falls on Saturday.  In that case _observe() already
    # produced date(year-1, 12, 31) for the first add() call above, so it is
    # already in the dict.  Nothing extra needed here.

    return holidays


class BusinessCalendar:
    """Calendar that marks weekends and US federal holidays as closed.

    Parameters
    ----------
    overrides : dict[date, bool] or None
        Maps date → True (closed) or False (open), overriding the default rule.
        Takes precedence over both the weekend check and holiday check.
    """

    def __init__(self, overrides=None):
        self._overrides = dict(overrides) if overrides else {}
        # Cache of federal_holidays sets per year
        self._holiday_cache: dict[int, set] = {}

    def _get_holidays(self, year: int) -> set:
        if year not in self._holiday_cache:
            self._holiday_cache[year] = set(federal_holidays(year).keys())
        return self._holiday_cache[year]

    def is_closed(self, d: date) -> bool:
        """Return True if *d* is a closed day (weekend, federal holiday, or override)."""
        if d in self._overrides:
            return self._overrides[d]  # True → closed, False → open
        # Weekend
        if d.weekday() >= 5:  # Saturday or Sunday
            return True
        # Federal holiday of this year
        if d in self._get_holidays(d.year):
            return True
        # Dec 31 may be a New Year's Day observed date for the following year
        # (when Jan 1 of year+1 falls on Saturday).  federal_holidays(year+1)
        # contains date(year, 12, 31) in that case.
        if d.month == 12 and d.day == 31:
            if d in self._get_holidays(d.year + 1):
                return True
        return False

    def is_business_day(self, d: date) -> bool:
        """Return True if *d* is an open (business) day."""
        return not self.is_closed(d)

    def next_business_day(self, d: date) -> date:
        """Return *d* itself if it is a business day, otherwise the next one."""
        while self.is_closed(d):
            d = d + timedelta(days=1)
        return d

    def add_business_days(self, d: date, n: int) -> date:
        """Return the date *n* business days after (or before, if negative) *d*.

        n = 0 returns *d* unchanged (regardless of whether *d* is a business day).
        For n > 0: advance *n* business days starting the day after *d*.
        For n < 0: retreat *|n|* business days starting the day before *d*.
        """
        if n == 0:
            return d
        step = timedelta(days=1) if n > 0 else timedelta(days=-1)
        remaining = abs(n)
        current = d
        while remaining > 0:
            current = current + step
            if self.is_business_day(current):
                remaining -= 1
        return current

    def business_days_between(self, a: date, b: date) -> int:
        """Count open days *d* with *a* < *d* <= *b*.

        If *b* <= *a*, returns 0.
        """
        if b <= a:
            return 0
        count = 0
        current = a + timedelta(days=1)
        while current <= b:
            if self.is_business_day(current):
                count += 1
            current = current + timedelta(days=1)
        return count
