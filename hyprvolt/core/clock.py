"""The instance's time zone, and times in it.

Everything stored is naive UTC (``models.utcnow``). A time a person types or
reads, such as the start of a maintenance window, is in the instance's time
zone instead: an admin setting, which starts as the ``TZ`` environment
variable, or UTC. So "22:00" means the same hour to everyone using the
instance, and a change of zone moves nothing that is stored.
"""
import os
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from ..models import get_setting

SETTING = "time_zone"
SHOWN = "%Y-%m-%d %H:%M"


@lru_cache(maxsize=1)
def names() -> tuple[str, ...]:
    """Every time zone the system knows, by name."""
    return tuple(sorted(available_timezones() | {"UTC"}))


def valid(name: str) -> bool:
    return isinstance(name, str) and name in names()


def default_name() -> str:
    env = (os.environ.get("TZ") or "").strip()
    return env if valid(env) else "UTC"


def zone_name() -> str:
    stored = get_setting(SETTING)
    return stored if valid(stored) else default_name()


def zone() -> ZoneInfo:
    return ZoneInfo(zone_name())


def to_local(dt: datetime) -> datetime:
    """A stored time (naive UTC) in the instance's zone, still naive."""
    return dt.replace(tzinfo=timezone.utc).astimezone(zone()).replace(tzinfo=None)


def to_utc(local: datetime) -> datetime:
    """A time in the instance's zone as it is stored. An hour that a change
    to daylight saving skips or repeats is read as its first meaning."""
    return local.replace(tzinfo=zone()).astimezone(timezone.utc).replace(tzinfo=None)


def shown(dt: datetime | None) -> str:
    """"2026-10-03 22:00", in the instance's zone."""
    return to_local(dt).strftime(SHOWN) if dt else ""


def input_value(dt: datetime | None) -> str:
    """For ``<input type="datetime-local">``."""
    return to_local(dt).strftime("%Y-%m-%dT%H:%M") if dt else ""
