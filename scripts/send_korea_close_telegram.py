#!/usr/bin/env python3
import glob
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def latest_file():
    files = sorted(glob.glob(str(OUT / "24n-korea-close-*.md")))
    return files[-1] if files else None


def send(token, chat_id, text):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
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

    f = latest_file()
    if not f:
        print("Skip: no close brief")
        return

    text = Path(f).read_text(encoding="utf-8")
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for i, c in enumerate(chunks, 1):
        if len(chunks) > 1:
            c = f"[한국시황 {i}/{len(chunks)}]\n\n" + c
        send(token, chat_id, c)
    print(f"Sent: {Path(f).name}")


if __name__ == "__main__":
    main()
