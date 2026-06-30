from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def build_schedule_slots(
    count: int,
    slot_strings: list[str],
    timezone: str,
    start_after: datetime | None = None,
) -> list[datetime]:
    if not slot_strings:
        raise ValueError("At least one calendar slot is required.")

    tz = ZoneInfo(timezone)
    cursor = start_after.astimezone(tz) if start_after else datetime.now(tz)
    parsed_slots = sorted(_parse_time(slot) for slot in slot_strings)
    result: list[datetime] = []
    day = cursor.date()

    while len(result) < count:
        for slot in parsed_slots:
            candidate = datetime.combine(day, slot, tzinfo=tz)
            if candidate > cursor + timedelta(minutes=2):
                result.append(candidate)
                if len(result) == count:
                    break
        day += timedelta(days=1)

    return result


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))
