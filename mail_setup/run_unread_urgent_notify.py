#!/usr/bin/env python3
import email
import imaplib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from check_unread_urgent import CFG, unread_gmail_oauth, unread_imap

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "mail_setup" / "output" / "urgent_notified_ids.json"
LOG_PATH = ROOT / "mail_setup" / "output" / "urgent-check.log"
SECRETS = ROOT / "mail_setup" / "secrets.json"


def log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_secret(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v:
        return v
    s = load_json(SECRETS, {})
    return s.get(key, default)


def message_id(row: dict) -> str:
    base = f"{row.get('account','')}|{row.get('subject','')}|{row.get('from','')}|{row.get('date','')}"
    return re.sub(r"\s+", " ", base).strip()


def collect_urgent() -> tuple[list[dict], list[str]]:
    cfg = load_json(CFG, {})
    urgent = []
    errors = []
    for a in cfg.get("accounts", []):
        try:
            if a.get("type") == "gmail_oauth":
                urgent.extend(unread_gmail_oauth(a))
            else:
                urgent.extend(unread_imap(a))
        except Exception as e:
            errors.append(f"{a.get('email','unknown')}: {e}")
    return urgent, errors


def send_telegram(text: str):
    token = get_secret("TELEGRAM_BOT_TOKEN", "")
    chat_id = get_secret("TELEGRAM_CHAT_ID", "44370045")
    if not token:
        log("Skip notify: missing TELEGRAM_BOT_TOKEN")
        return False
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    return True


def cleanup_nyt_breaking() -> tuple[int, list[str]]:
    cfg = load_json(CFG, {})
    total_deleted = 0
    errors = []

    for a in cfg.get("accounts", []):
        try:
            acc_type = a.get("type")
            if acc_type == "gmail_oauth":
                token_path = ROOT / a["token_file"]
                creds = Credentials.from_authorized_user_file(
                    str(token_path),
                    scopes=["https://www.googleapis.com/auth/gmail.modify"],
                )
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    token_path.write_text(creds.to_json(), encoding="utf-8")

                svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
                q = 'in:inbox subject:"Breaking News:" from:(nytimes.com) older_than:2d'
                resp = svc.users().messages().list(userId="me", q=q, maxResults=200).execute()
                msgs = resp.get("messages", [])
                while True:
                    for m in msgs:
                        svc.users().messages().trash(userId="me", id=m["id"]).execute()
                        total_deleted += 1
                    nxt = resp.get("nextPageToken")
                    if not nxt:
                        break
                    resp = svc.users().messages().list(userId="me", q=q, maxResults=200, pageToken=nxt).execute()
                    msgs = resp.get("messages", [])
            else:
                user = get_secret(a["env_user"], a.get("email", ""))
                pw = get_secret(a["env_password"], "")
                if not pw:
                    continue
                m = imaplib.IMAP4_SSL(a["imap_host"], int(a.get("imap_port", 993)))
                m.login(user, pw)
                m.select("INBOX")
                before = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%d-%b-%Y")
                typ, data = m.search(None, 'SUBJECT "Breaking News:"', f'FROM "nytimes.com"', f'BEFORE {before}')
                ids = data[0].split() if (typ == "OK" and data and data[0]) else []
                for mid in ids:
                    m.store(mid, "+FLAGS", "\\Deleted")
                if ids:
                    m.expunge()
                    total_deleted += len(ids)
                m.logout()
        except Exception as e:
            errors.append(f"cleanup {a.get('email','unknown')}: {e}")

    return total_deleted, errors


def main():
    state = load_json(STATE_PATH, {"notified": []})
    notified = set(state.get("notified", []))

    deleted, cleanup_errors = cleanup_nyt_breaking()
    if deleted:
        log(f"NYT breaking cleanup deleted: {deleted}")
    if cleanup_errors:
        log("; ".join(cleanup_errors))

    urgent, errors = collect_urgent()
    if errors:
        log("; ".join(errors))

    if not urgent:
        log("NO_URGENT_UNREAD")
        return

    new_items = [m for m in urgent if message_id(m) not in notified]
    if not new_items:
        log(f"URGENT_FOUND but already notified: {len(urgent)}")
        return

    lines = ["[메일] 긴급 메일 감지", ""]
    for i, m in enumerate(new_items[:10], 1):
        lines.append(f"{i}. [{m['account']}] {m['subject']}")
        lines.append(f"   - 보낸사람: {m['from']}")
    if len(new_items) > 10:
        lines.append(f"...외 {len(new_items)-10}건")

    sent = send_telegram("\n".join(lines))
    if sent:
        for m in new_items:
            notified.add(message_id(m))
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"notified": sorted(notified)[-500:]}, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Sent urgent notify: {len(new_items)}")


if __name__ == "__main__":
    main()
