import logging
from datetime import datetime, timezone
from logging_setup import PacificFormatter


def record_at(utc: datetime) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    record.created = utc.timestamp()
    return record


def test_log_times_are_pacific_daylight_in_october():
    utc = datetime(2026, 10, 1, 19, 41, 58, tzinfo=timezone.utc)
    assert PacificFormatter().formatTime(record_at(utc)) == "2026-10-01 12:41:58 PDT"


def test_log_times_are_pacific_standard_in_january():
    utc = datetime(2027, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
    assert PacificFormatter().formatTime(record_at(utc)) == "2027-01-15 06:30:00 PST"
