from datetime import datetime, timedelta
from zoneinfo import ZoneInfoNotFoundError

from olkalou_engine.worker import load_eat_timezone


def test_eat_timezone_has_utc_plus_three_offset():
    eat = load_eat_timezone()
    assert eat.utcoffset(datetime(2026, 7, 16, 12, 0)) == timedelta(hours=3)


def test_eat_timezone_falls_back_when_iana_database_is_missing():
    def missing_zone(_key: str):
        raise ZoneInfoNotFoundError("test: timezone database unavailable")

    eat = load_eat_timezone(missing_zone)
    assert eat.utcoffset(datetime(2026, 7, 16, 12, 0)) == timedelta(hours=3)
    assert eat.tzname(None) == "EAT"
