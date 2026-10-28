"""Mail date parsing utilities shared by segmented app bootstrap and helpers."""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional


RFC_INTERNALDATE_RE = re.compile(r'^\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$')
ISO_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T')
TRAILING_ZONE_NAME_RE = re.compile(r'\s+\([A-Za-z0-9_./+-]+\)$')
MAILCOM_AT_RE = re.compile(r'\s+at\s+', flags=re.IGNORECASE)
MAILCOM_WEEKDAY_RE = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+',
    flags=re.IGNORECASE,
)
MAILCOM_UI_FORMATS = (
    '%A, %B %d, %Y %I:%M %p',
    '%B %d, %Y %I:%M %p',
    '%A, %B %d, %Y %H:%M',
    '%B %d, %Y %H:%M',
)


def _parse_mailcom_ui_datetime(value: str) -> Optional[datetime]:
    """Parse mail.com lightmailer dates like 'Monday, August 24, 2026 at 5:07 PM'."""
    normalized = MAILCOM_AT_RE.sub(' ', value or '')
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if not normalized:
        return None
    candidates = (normalized, MAILCOM_WEEKDAY_RE.sub('', normalized))
    for candidate in candidates:
        if not candidate:
            continue
        for fmt in MAILCOM_UI_FORMATS:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def parse_mail_datetime(value: str) -> Optional[datetime]:
    """解析常见邮件日期格式，返回本地无时区 datetime。"""
    if not value:
        return None
    try:
        value_str = str(value).strip()
        value_str = TRAILING_ZONE_NAME_RE.sub('', value_str)
        if ISO_DATETIME_RE.match(value_str):
            parsed = datetime.fromisoformat(value_str.replace('Z', '+00:00'))
        elif RFC_INTERNALDATE_RE.match(value_str):
            parsed = datetime.strptime(value_str, '%d-%b-%Y %H:%M:%S %z')
        else:
            parsed = None
            try:
                parsed = parsedate_to_datetime(value_str)
            except Exception:
                parsed = None
            if parsed is None:
                parsed = _parse_mailcom_ui_datetime(value_str)
            if parsed is None:
                return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def normalize_mail_date_for_display(value: str) -> str:
    """把邮件日期收成前端 formatDate 能解析的 ISO，失败则原样返回。"""
    raw = str(value or '').strip()
    if not raw:
        return ''
    parsed = parse_mail_datetime(raw)
    if parsed is None:
        return raw
    return parsed.isoformat(timespec='seconds')
