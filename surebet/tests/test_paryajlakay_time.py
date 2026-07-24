"""Tests de l'extraction d'heure de match chez Paryaj Lakay.

`match_id` est un hash (equipes + jour UTC) : une heure de debut erronee
empeche l'appariement cross-bookmakers. Ces tests verrouillent ce point.
"""
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from surebet.scrapers.paryajlakay import ParyajLakayScraper


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract(html: str) -> datetime:
    return ParyajLakayScraper._extract_start_time(soup(html))


class TestExtractStartTime:
    def test_explicit_date_and_time(self):
        dt = extract("<div>Match du 24/07 a 18:00</div>")
        assert (dt.day, dt.month, dt.hour, dt.minute) == (24, 7, 18, 0)
        assert dt.tzinfo is timezone.utc

    def test_explicit_date_with_year(self):
        dt = extract("<div>25/12/2026 20:30</div>")
        assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 12, 25, 20)

    def test_two_digit_year_is_expanded(self):
        dt = extract("<div>01/02/27 09:15</div>")
        assert dt.year == 2027

    def test_today_keeps_current_date(self):
        dt = extract("<div>Aujourd'hui 18:00</div>")
        today = datetime.now(timezone.utc).date()
        assert dt.date() == today
        assert (dt.hour, dt.minute) == (18, 0)

    def test_tomorrow_advances_one_day(self):
        dt = extract("<div>Demain 21:45</div>")
        expected = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        assert dt.date() == expected
        assert (dt.hour, dt.minute) == (21, 45)

    def test_creole_tomorrow_is_recognised(self):
        dt = extract("<div>Demen 15:00</div>")
        expected = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        assert dt.date() == expected

    def test_hour_separator_h_is_accepted(self):
        dt = extract("<div>Aujourd'hui 20h30</div>")
        assert (dt.hour, dt.minute) == (20, 30)

    def test_invalid_date_falls_back_without_crashing(self):
        dt = extract("<div>32/13 18:00</div>")
        assert dt.tzinfo is timezone.utc
        assert (dt.hour, dt.minute) == (18, 0)

    def test_no_time_information_defaults_to_midnight_today(self):
        dt = extract("<div>Pas d'horaire ici</div>")
        assert (dt.hour, dt.minute) == (0, 0)
        assert dt.date() == datetime.now(timezone.utc).date()

    def test_seconds_are_zeroed_for_stable_hashing(self):
        dt = extract("<div>Aujourd'hui 18:00</div>")
        assert dt.second == 0 and dt.microsecond == 0


class TestMatchIdStability:
    def test_same_match_same_day_yields_same_id(self):
        """Deux lectures du meme match doivent produire le meme match_id."""
        from surebet.normalizer.schema import make_match_id

        a = extract("<div>Aujourd'hui 18:00</div>")
        b = extract("<div>Aujourd'hui 18:00</div>")
        assert make_match_id("Como", "Paris FC", a) == make_match_id("Como", "Paris FC", b)

    def test_different_days_yield_different_ids(self):
        from surebet.normalizer.schema import make_match_id

        today = extract("<div>Aujourd'hui 18:00</div>")
        tomorrow = extract("<div>Demain 18:00</div>")
        assert make_match_id("Como", "Paris FC", today) != make_match_id("Como", "Paris FC", tomorrow)
