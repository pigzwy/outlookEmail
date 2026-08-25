"""Shared types for the mail.com cookie provider (adapted from OpenMail)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


@dataclass
class Message:
    id: str
    subject: str = ""
    from_: str = ""
    from_address: str = ""
    to: str = ""
    date: str | None = None
    body_preview: str = ""
    body_text: str = ""
    body_html: str = ""
    folder: str = "inbox"
    verification_code: str | None = None
    raw_refs: dict[str, Any] = field(default_factory=dict)
    uidvalidity: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "subject": self.subject,
            "from": self.from_,
            "from_address": self.from_address,
            "to": self.to,
            "date": self.date,
            "body_preview": self.body_preview,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "folder": self.folder,
            "verification_code": self.verification_code,
            "raw_refs": self.raw_refs,
        }
        if self.uidvalidity is not None:
            payload["uidvalidity"] = self.uidvalidity
        return payload


@dataclass
class CredentialUpdates:
    refresh_token: str | None = None
    access_token: str | None = None
    session_cookies: list[dict[str, Any]] | None = None
    session_meta: dict[str, Any] | None = None
    password: str | None = None
    mailboxes: list[str] | None = None

    def any(self) -> bool:
        return any(
            [
                self.refresh_token,
                self.access_token,
                self.session_cookies is not None,
                self.session_meta is not None,
                self.password,
                self.mailboxes is not None,
            ]
        )


@dataclass
class FetchResult:
    ok: bool
    messages: list[Message] = field(default_factory=list)
    message_count: int = 0
    folder: str = "inbox"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    credential_updates: CredentialUpdates | None = None
    session_restored: bool = False
    error: str | None = None
    uidvalidity: int | None = None
    phase: str = "full"
    pending_body_ids: list[str] = field(default_factory=list)
    partial: bool = False

    def __post_init__(self) -> None:
        if self.message_count == 0 and self.messages:
            self.message_count = len(self.messages)
        if self.uidvalidity is not None:
            for message in self.messages:
                if message.uidvalidity is None:
                    message.uidvalidity = self.uidvalidity


@dataclass
class HealthResult:
    ok: bool
    detail: str | None = None


_DIGIT_NEAR_CODE = re.compile(
    r"(?:验证码|校验码|confirmation\s*code|verification\s*code|security\s*code|"
    r"access\s*code|login\s*code|\botp\b|(?<![A-Za-z])code(?![A-Za-z]))"
    r"[^\d]{0,48}(\d{4,8})",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG = re.compile(r"<[^>]+>")


def extract_verification_code(
    subject: str = "",
    body_text: str = "",
    body_html: str = "",
    custom_regex: str | None = None,
) -> str | None:
    text = "\n".join(
        [
            str(subject or ""),
            str(body_text or ""),
            _HTML_TAG.sub(" ", str(body_html or "")),
        ]
    )
    if custom_regex:
        try:
            match = re.search(custom_regex, text)
            if match:
                return match.group(1) if match.lastindex else match.group(0)
        except re.error:
            pass
    match = _DIGIT_NEAR_CODE.search(text)
    return match.group(1) if match else None


def attach_verification_code(messages: list[Message]) -> list[Message]:
    for message in messages:
        if message.verification_code:
            continue
        message.verification_code = extract_verification_code(
            subject=message.subject,
            body_text=message.body_text,
            body_html=message.body_html,
        )
    return messages


def filter_messages_by_time(
    messages: list[Message],
    *,
    since: str | None = None,
    before: str | None = None,
) -> list[Message]:
    if not since and not before:
        return messages

    def _ms(date: str | int | float | None) -> float | None:
        if date is None:
            return None
        if isinstance(date, (int, float)):
            value = float(date)
            return value if abs(value) >= 100_000_000_000 else value * 1000.0
        if not isinstance(date, str):
            return None
        raw = date.strip()
        if not raw:
            return None
        try:
            numeric = float(raw)
            return numeric if abs(numeric) >= 100_000_000_000 else numeric * 1000.0
        except ValueError:
            pass
        normalized = re.sub(r"\s+at\s+", " ", raw, flags=re.I)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        candidates = (
            normalized,
            raw,
            re.sub(
                r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+",
                "",
                normalized,
                flags=re.I,
            ),
        )
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp() * 1000.0
            except Exception:
                pass
            try:
                parsed = parsedate_to_datetime(candidate)
                if parsed is None:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp() * 1000.0
            except Exception:
                pass
            for fmt in (
                "%A, %B %d, %Y %I:%M %p",
                "%B %d, %Y %I:%M %p",
                "%A, %B %d, %Y %H:%M",
                "%B %d, %Y %H:%M",
            ):
                try:
                    parsed = datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
                    return parsed.timestamp() * 1000.0
                except ValueError:
                    continue
        return None

    since_ms = _ms(since) if since else None
    before_ms = _ms(before) if before else None
    if since_ms is not None:
        since_ms -= 120_000.0
    out: list[Message] = []
    for message in messages:
        stamp = _ms(message.date)
        if since_ms is not None:
            if stamp is None:
                out.append(message)
                continue
            if stamp < since_ms:
                continue
        if before_ms is not None:
            if stamp is None:
                continue
            if stamp >= before_ms:
                continue
        out.append(message)
    return out
