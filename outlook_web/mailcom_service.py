"""mail.com cookie fetch adapter for the OutlookEmail web app."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from outlook_web.mail_datetime import normalize_mail_date_for_display
from outlook_web.mailcom_provider import MailcomCookieProvider
from outlook_web.mailcom_types import Message

MAILCOM_PROVIDER_KEY = "mailcom"
MAILCOM_METHOD = "mail.com Cookie"
MAILCOM_REQUEST_METHOD = "mailcom"
MAILCOM_DOMAINS = frozenset(
    {
        "mail.com",
        "email.com",
        "usa.com",
        "myself.com",
        "consultant.com",
        "europe.com",
        "asia.com",
    }
)
_UNSUPPORTED_ACTIONS = {
    "mark-read": "mail.com Cookie 会话暂不支持标记已读",
    "delete": "mail.com Cookie 会话暂不支持删除邮件",
    "attachment": "mail.com Cookie 会话暂不支持附件下载",
}


def is_mailcom_account(account: Optional[Dict[str, Any]]) -> bool:
    if not account:
        return False
    return str(account.get("provider") or "").strip().lower() == MAILCOM_PROVIDER_KEY


def is_mailcom_domain(email_addr: str) -> bool:
    if not email_addr or "@" not in email_addr:
        return False
    domain = email_addr.rsplit("@", 1)[-1].strip().lower()
    return domain in MAILCOM_DOMAINS or domain.endswith(".mail.com")


def _build_error(code: str, message: str, error_type: str = "MailcomError", status: int = 502) -> Dict[str, Any]:
    try:
        from web_outlook_app import build_error_payload
        return build_error_payload(code, message, error_type, status, "")
    except Exception:
        return {
            "code": code,
            "message": message,
            "type": error_type,
            "status": status,
        }


def mailcom_unsupported_action(action: str) -> Dict[str, Any]:
    message = _UNSUPPORTED_ACTIONS.get(action, "mail.com Cookie 会话暂不支持该操作")
    return {
        "success": False,
        "error": _build_error("MAILCOM_UNSUPPORTED", message, "MailcomUnsupportedError", 400),
        "error_code": "MAILCOM_UNSUPPORTED",
        "method": MAILCOM_METHOD,
    }


def load_mailcom_session(account: Dict[str, Any]) -> Dict[str, Any]:
    raw = account.get("mailcom_session") or ""
    if not raw:
        return {"cookies": [], "session_meta": {}}
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"cookies": [], "session_meta": {}}
    if not isinstance(payload, dict):
        return {"cookies": [], "session_meta": {}}
    cookies = payload.get("cookies") or payload.get("session_cookies") or []
    meta = payload.get("session_meta") or payload.get("meta") or {}
    return {
        "cookies": cookies if isinstance(cookies, list) else [],
        "session_meta": meta if isinstance(meta, dict) else {},
    }


def dump_mailcom_session(cookies: Optional[List[Dict[str, Any]]], meta: Optional[Dict[str, Any]]) -> str:
    return json.dumps(
        {
            "cookies": list(cookies or []),
            "session_meta": dict(meta or {}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def persist_mailcom_session(account: Dict[str, Any], cookies: Optional[List[Dict[str, Any]]],
                            meta: Optional[Dict[str, Any]]) -> None:
    account_id = account.get("id")
    if not account_id:
        return
    payload = dump_mailcom_session(cookies, meta)
    try:
        from web_outlook_app import encrypt_data, get_db
        db = get_db()
        db.execute(
            "UPDATE accounts SET mailcom_session = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (encrypt_data(payload) if payload else payload, account_id),
        )
        db.commit()
        account["mailcom_session"] = payload
    except Exception:
        account["mailcom_session"] = payload


def persist_mailcom_updates(account: Dict[str, Any], updates: Any) -> None:
    if updates is None:
        return
    cookies = getattr(updates, "session_cookies", None)
    meta = getattr(updates, "session_meta", None)
    if cookies is None and meta is None:
        return
    current = load_mailcom_session(account)
    persist_mailcom_session(
        account,
        cookies if cookies is not None else current.get("cookies"),
        meta if meta is not None else current.get("session_meta"),
    )


def _message_to_list_item(message: Message, folder: str) -> Dict[str, Any]:
    sender = message.from_address or message.from_ or "未知"
    preview = (message.body_preview or message.body_text or message.subject or "")[:200]
    return {
        "id": str(message.id),
        "subject": message.subject or "无主题",
        "from": sender,
        "to": message.to or "",
        "date": normalize_mail_date_for_display(message.date or ""),
        "id_mode": MAILCOM_REQUEST_METHOD,
        "is_read": False,
        "has_attachments": False,
        "body_preview": preview,
        "folder": folder,
        "verification_code": message.verification_code or "",
    }


def _message_to_detail(message: Message) -> Dict[str, Any]:
    body_html = (message.body_html or "").strip()
    body_text = (message.body_text or "").strip()
    if body_html:
        body, body_type = body_html, "html"
    else:
        body, body_type = body_text, "text"
    return {
        "id": str(message.id),
        "subject": message.subject or "无主题",
        "from": message.from_address or message.from_ or "未知",
        "to": message.to or "",
        "cc": "",
        "date": normalize_mail_date_for_display(message.date or ""),
        "body": body,
        "body_type": body_type,
        "attachments": [],
        "has_attachments": False,
        "verification_code": message.verification_code or "",
    }


def _build_credentials(account: Dict[str, Any], proxy_url: str = "") -> Dict[str, Any]:
    session = load_mailcom_session(account)
    return {
        "email": account.get("email") or "",
        "password": account.get("imap_password") or account.get("password") or "",
        "cookies": session.get("cookies") or [],
        "session_meta": session.get("session_meta") or {},
        "site": "mail.com",
        "proxy": proxy_url or None,
    }


def get_emails_mailcom(
    account: Dict[str, Any],
    folder: str = "inbox",
    skip: int = 0,
    top: int = 20,
    proxy_url: str = "",
) -> Dict[str, Any]:
    skip = max(0, int(skip or 0))
    top = max(1, int(top or 20))
    limit = min(200, skip + top)
    provider = MailcomCookieProvider()
    result = provider.fetch(
        SimpleNamespace(email=account.get("email"), provider=MAILCOM_PROVIDER_KEY),
        folder=folder,
        quick=False,
        limits={"max_messages": limit},
        credentials=_build_credentials(account, proxy_url),
    )
    if not result.ok:
        return {
            "success": False,
            "error": _build_error(
                "MAILCOM_FETCH_FAILED",
                result.error or "mail.com 取信失败",
                "MailcomFetchError",
                502,
            ),
            "error_code": "MAILCOM_FETCH_FAILED",
        }
    persist_mailcom_updates(account, result.credential_updates)
    emails = [_message_to_list_item(message, folder) for message in result.messages]
    page = emails[skip:skip + top]
    return {
        "success": True,
        "emails": page,
        "method": MAILCOM_METHOD,
        "has_more": len(emails) > skip + top or len(result.messages) >= limit,
        "request_method": MAILCOM_REQUEST_METHOD,
    }


def get_email_detail_mailcom(
    account: Dict[str, Any],
    message_id: str,
    folder: str = "inbox",
    proxy_url: str = "",
) -> Dict[str, Any]:
    if not message_id:
        return {
            "success": False,
            "error": _build_error("EMAIL_DETAIL_INVALID", "message_id 不能为空", "ValidationError", 400),
        }
    provider = MailcomCookieProvider()
    # Reuse list fetch session restore/login, then pull one detail.
    creds = _build_credentials(account, proxy_url)
    result = provider.fetch(
        SimpleNamespace(email=account.get("email"), provider=MAILCOM_PROVIDER_KEY),
        folder=folder,
        quick=True,
        limits={"max_messages": 1},
        credentials=creds,
    )
    if not result.ok:
        return {
            "success": False,
            "error": _build_error(
                "MAILCOM_DETAIL_FAILED",
                result.error or "mail.com 登录失败",
                "MailcomFetchError",
                502,
            ),
        }
    persist_mailcom_updates(account, result.credential_updates)
    session = load_mailcom_session(account)
    client = None
    try:
        from outlook_web.mailcom_provider import _http_client

        client = _http_client(provider.timeout, proxy=proxy_url or None)
        cookies = session.get("cookies") or []
        if cookies:
            from outlook_web.mailcom_provider import apply_cookies

            apply_cookies(client, cookies)
        detail = provider.fetch_detail(
            client,
            str(message_id),
            folder=folder,
            site="mail.com",
            meta=session.get("session_meta") or {},
        )
        if detail is None:
            matched = next((item for item in result.messages if str(item.id) == str(message_id)), None)
            if matched and (matched.body_html or matched.body_text or matched.subject):
                detail = matched
        if detail is None:
            return {
                "success": False,
                "error": _build_error("MAILCOM_DETAIL_FAILED", "未找到该邮件", "MailcomFetchError", 404),
            }
        return {"success": True, "email": _message_to_detail(detail), "method": MAILCOM_METHOD}
    except Exception as exc:
        return {
            "success": False,
            "error": _build_error("MAILCOM_DETAIL_FAILED", f"mail.com 取信失败: {exc}", "MailcomFetchError", 502),
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def get_raw_email_mailcom(
    account: Dict[str, Any],
    message_id: str,
    folder: str = "inbox",
    proxy_url: str = "",
) -> Optional[str]:
    result = get_email_detail_mailcom(account, message_id, folder, proxy_url)
    if not result.get("success"):
        return None
    email = result.get("email") or {}
    headers = [
        f"From: {email.get('from') or ''}",
        f"To: {email.get('to') or ''}",
        f"Subject: {email.get('subject') or ''}",
        f"Date: {email.get('date') or ''}",
        "MIME-Version: 1.0",
    ]
    body = email.get("body") or ""
    if str(email.get("body_type") or "").lower() == "html":
        headers.append("Content-Type: text/html; charset=utf-8")
    else:
        headers.append("Content-Type: text/plain; charset=utf-8")
    return "\r\n".join(headers) + "\r\n\r\n" + str(body)
