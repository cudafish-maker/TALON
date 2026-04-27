"""
Shared UI formatting helpers.

Import from here rather than duplicating in individual screens so that any
future change (timezone awareness, locale support, etc.) only needs one edit.
"""
import datetime


def format_ts(ts: int) -> str:
    """Return HH:MM for today's timestamps, MM/DD HH:MM for older ones."""
    dt = datetime.datetime.fromtimestamp(ts)
    if dt.date() == datetime.date.today():
        return dt.strftime("%H:%M")
    return dt.strftime("%m/%d %H:%M")
