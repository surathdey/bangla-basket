"""
Direct Resend email client (replaces the Emergent integrations proxy).

Sends transactional HTML emails via api.resend.com.
- Uses RESEND_API_KEY (server-side only, never exposed)
- from address/name come from EMAIL_FROM / EMAIL_FROM_NAME env vars,
  defaulting to the brand config (brand.json)
- Keeps the old email guardrails (no forms, https-only links,
  no cred-harvesting) unchanged.
"""
from __future__ import annotations

import os
import ipaddress
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

from brand import BRAND_EMAIL_FROM, BRAND_NAME

RESEND_BASE_URL = "https://api.resend.com"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", BRAND_EMAIL_FROM)
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", BRAND_NAME)
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: set = set()
        self.urls: list = []
        self.anchors: list = []
        self._href = None
        self._text: list = []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks for credentials: {p!r}")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Links must be absolute https: {url!r}")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened / IP / creds URL: {url!r}")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor {m.group(1)!r} ≠ href host {real!r}")


class EmailError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


async def send_email(*, to: str, subject: str, html: str,
                     reply_to: str | None = None) -> str | None:
    if not RESEND_API_KEY:
        raise EmailError(500, "RESEND_API_KEY is not set on the backend")
    _assert_safe_email(subject, html)
    payload = {"from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>",
               "to": [to], "subject": subject, "html": html}
    reply = reply_to or EMAIL_REPLY_TO
    if reply:
        payload["reply_to"] = reply
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RESEND_BASE_URL}/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        log.error(f"Email send failed: {e.response.status_code} {e.response.text}")
        raise EmailError(502, "Email provider returned an error")
    except Exception as e:
        log.error(f"Email send error: {e}")
        raise EmailError(500, "Failed to send email")


def is_configured() -> bool:
    return bool(RESEND_API_KEY)
