"""Log timestamps in Pacific time, where Daniel reads them.
Display only: market hours are always checked in New York time (strategy.py)."""
import logging
from datetime import datetime

import pytz

PACIFIC = pytz.timezone("US/Pacific")


def now_pacific() -> datetime:
    return datetime.now(PACIFIC)


class PacificFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, PACIFIC).strftime("%Y-%m-%d %H:%M:%S %Z")


def setup_logging(fmt: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(PacificFormatter(fmt))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
