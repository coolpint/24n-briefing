#!/usr/bin/env python3
import datetime as dt
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


def classify(subj: str, sender: str):
    s = f"{subj} {sender}".lower()
    if re.search(r"긴급|urgent|asap|결제|미납|계약|송장|invoice|법무", s):
        return "긴급"
    if re.search(r"meeting|미팅|일정|schedule|확인 부탁|review|action required", s):
        return "오늘 처리"
    if re.search(r"newsletter|news|홍보|광고|프로모션|digest", s):
        return "참고"
    return "일반"


def fetch_gmail_oauth(account, since_dt):
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
    q = f"after:{int(since_dt.timestamp())}"
    resp = svc.users().messages().list(userId="me", q=q, maxResults=account.get("max_per_account", 30)).execute()
    out = []
    for m in resp.get("messages", []):
        full = svc.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        subj = dec(headers.get("Subject", ""))
        sender = dec(headers.get("From", ""))
        out.append({"account": account["email"], "subject": subj, "from": sender, "date": headers.get("Date", ""), "cat": classify(subj, sender)})
    return out


def fetch_imap_password(account, since_dt):
    user = secret(account["env_user"], account.get("email", ""))
    pw = secret(account["env_password"], "")
    if not pw:
        raise RuntimeError(f"missing env password: {account['env_password']}")
    m = imaplib.IMAP4_SSL(account["imap_host"], int(account.get("imap_port", 993)))
    m.login(user, pw)
    m.select("INBOX")
    crit = since_dt.strftime('%d-%b-%Y')
    typ, data = m.search(None, "SINCE", crit)
    ids = (data[0].split() if data and data[0] else [])[-account.get("max_per_account", 30):]
    out = []
    for mid in ids:
        typ, msg_data = m.fetch(mid, "(RFC822.HEADER)")
        if not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subj = dec(msg.get("Subject", ""))
        sender = dec(msg.get("From", ""))
        out.append({"account": account["email"], "subject": subj, "from": sender, "date": msg.get("Date", ""), "cat": classify(subj, sender)})
    m.logout()
    return out


def fetch_gmail_app_password(account, since_dt):
    return fetch_imap_password(account, since_dt)


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    hours = int(cfg.get("brief", {}).get("hours", 24))
    since_dt = dt.datetime.now() - dt.timedelta(hours=hours)

    items = []
    errors = []

    for a in cfg["accounts"]:
        try:
            t = a["type"]
            if t == "gmail_oauth":
                rows = fetch_gmail_oauth(a, since_dt)
            elif t in ("imap_password", "gmail_app_password"):
                rows = fetch_imap_password(a, since_dt)
            else:
                raise RuntimeError(f"unsupported type: {t}")
            items.extend(rows)
        except Exception as e:
            errors.append(f"{a['email']}: {e}")

    groups = {"긴급": [], "오늘 처리": [], "참고": [], "일반": []}
    for it in items:
        groups[it["cat"]].append(it)

    lines = []
    lines.append("# 메일 브리핑")
    lines.append("")
    for k in ["긴급", "오늘 처리", "참고", "일반"]:
        lines.append(f"## {k} ({len(groups[k])}건)")
        for it in groups[k][:20]:
            lines.append(f"- [{it['account']}] {it['subject']} / {it['from']}")
        lines.append("")

    if errors:
        lines.append("## 수집 오류")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    out_path = ROOT / cfg.get("brief", {}).get("output_file", "mail_setup/output/mail-brief-latest.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
