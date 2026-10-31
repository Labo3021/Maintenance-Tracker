"""iCalendar (.ics) feed of open tasks, so phone/desktop calendars deliver the reminders."""

from datetime import datetime, timedelta, timezone

from config import settings

from .schemas import TaskView


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\;").replace(",", "\,").replace("\n", "\n")


def _fold(line: str) -> list[str]:
    """RFC 5545: lines over 75 octets continue on the next line with a leading space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return out


def _alarm(trigger: str, text: str) -> list[str]:
    return ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(text)}", f"TRIGGER:{trigger}", "END:VALARM"]


def build_ics(tasks: list[TaskView]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    hour = settings.reminder_hour
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LabGuard AI//Maintenance Tasks//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:LabGuard maintenance",
    ]
    for t in tasks:
        summary = f"{t.asset_name}: {t.title}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{t.id}@labguard",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{t.due_date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{t.due_date + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(t.description or t.title)}",
            f"PRIORITY:{ {'critical': 1, 'high': 3, 'medium': 5, 'low': 9}[t.priority] }",
            "TRANSP:TRANSPARENT",
        ]
        # All-day events start at midnight, so PT9H = 9:00 on the due day.
        lines += _alarm(f"PT{hour}H", f"Due today: {summary}")
        if settings.remind_days_before > 0:
            d = settings.remind_days_before
            lines += _alarm(f"-P{d - 1}DT{24 - hour}H", f"Due in {d} days: {summary}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(folded for line in lines for folded in _fold(line)) + "\r\n"
