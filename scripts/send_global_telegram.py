#!/usr/bin/env python3
import datetime as dt
import glob
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def latest_file():
    files = sorted(glob.glob(str(OUT / "24n-global-*.md")))
    return files[-1] if files else None


def todays_file_kst():
    kst = dt.timezone(dt.timedelta(hours=9))
    today = dt.datetime.now(kst).strftime('%Y-%m-%d')
    path = OUT / f"24n-global-{today}.md"
    return str(path) if path.exists() else None


def validate_24n_format(text: str):
    required = [
        "# [24N] 간밤 글로벌 동향 브리핑",
        "\n쟁점과 현안\n",
        "\n원문 링크\n",
    ]
    forbidden = [
        "## 더 깊게 읽기",
    ]

    for r in required:
        if r not in text:
            return False, f"required block missing: {r}"
    for f in forbidden:
        if f in text:
            return False, f"forbidden block found: {f}"
    return True, "ok"


def send(token, chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Skip: missing telegram secrets")
        return

    f = todays_file_kst()
    if not f:
        print("Error: today's global brief file is missing (KST). Do not send stale file.")
        sys.exit(1)

    text = Path(f).read_text(encoding="utf-8")
    ok, reason = validate_24n_format(text)
    if not ok:
        print(f"Error: format validation failed: {reason}")
        sys.exit(1)

    max_len = 3900
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for i, c in enumerate(chunks, 1):
        if len(chunks) > 1:
            c = f"[글로벌브리핑 {i}/{len(chunks)}]\n\n" + c
        send(token, chat_id, c)
    print(f"Sent: {Path(f).name}")


if __name__ == "__main__":
    main()
