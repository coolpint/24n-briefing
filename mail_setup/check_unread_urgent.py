#!/usr/bin/env python3
import email
import imaplib
import json
import os
import re
from email.header import decode_header
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "mail_setup" / "accounts.json"
SECRETS = ROOT / "mail_setup" / "secrets.json"

URGENT_RE = re.compile(r"긴급|urgent|asap|결제|미납|계약|소송|마감|당일|즉시|payment|invoice", re.I)
EXCLUDE_RE = re.compile(r"자산운용보고서|운용보고서|박사과정|박사 과정|대학원|모집요강|원서접수|입학설명회|ASSIST", re.I)
EXCLUDE_SENDER_RE = re.compile(r"@ksdreport\.or\.kr", re.I)
AD_PREFIX_RE = re.compile(r"^\s*(\(\s*광고\s*\)|\[\s*광고\s*\]|광고)\b", re.I)


def secret(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v:
        return v
    if SECRETS.exists():
        try:
            d = json.loads(SECRETS.read_text(encoding="utf-8"))
            return d.get(key, default)
        except Exception:
            return default
    return default


def dec(v: str) -> str:
    if not v:
        return ""
    out = []
    for t, enc in decode_header(v):
        if isinstance(t, bytes):
            out.append(t.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(t)
    return " ".join(out).strip()


def is_urgent(subject: str, sender: str) -> bool:
    text = f"{subject} {sender}"
    subj = subject or ""
    if AD_PREFIX_RE.search(subj):
        return False
    if EXCLUDE_RE.search(text):
        return False
    if EXCLUDE_SENDER_RE.search(sender or ""):
        return False
    return bool(URGENT_RE.search(text))


def unread_gmail_oauth(account):
    token_path = ROOT / account["token_file"]
    creds = Credentials.from_authorized_user_file(
        str(token_path),
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")

    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    resp = svc.users().messages().list(userId="me", q="is:unread in:inbox", maxResults=50).execute()
    out = []
    for m in resp.get("messages", []):
        full = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        subj = dec(headers.get("Subject", ""))
        sender = dec(headers.get("From", ""))
        if is_urgent(subj, sender):
            out.append({"account": account["email"], "subject": subj, "from": sender, "date": headers.get("Date", "")})
    return out


def unread_imap(account):
    user = secret(account["env_user"], account.get("email", ""))
    pw = secret(account["env_password"], "")
    if not pw:
        raise RuntimeError(f"missing env password: {account['env_password']}")

    m = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port", 993)))
    m.login(user, pw)
    m.select("INBOX")
    typ, data = m.search(None, "UNSEEN")
    ids = data[0].split()[-50:] if data and data[0] else []
    out = []
    for mid in ids:
        typ, msg_data = m.fetch(mid, "(RFC822.HEADER)")
        if not msg_data or not msg_data[0]:
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        subj = dec(msg.get("Subject", ""))
        sender = dec(msg.get("From", ""))
        if is_urgent(subj, sender):
            out.append({"account": account["email"], "subject": subj, "from": sender, "date": msg.get("Date", "")})
    m.logout()
    return out


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    urgent = []
    errors = []
    for a in cfg["accounts"]:
        try:
            if a["type"] == "gmail_oauth":
                urgent.extend(unread_gmail_oauth(a))
            else:
                urgent.extend(unread_imap(a))
        except Exception as e:
            errors.append(f"{a['email']}: {e}")

    if urgent:
        print("URGENT_FOUND")
        for i, m in enumerate(urgent, 1):
            print(f"{i}. [{m['account']}] {m['subject']} / {m['from']}")
    else:
        print("NO_URGENT_UNREAD")

    if errors:
        print("ERRORS")
        for e in errors:
            print(f"- {e}")


if __name__ == "__main__":
    main()
