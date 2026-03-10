#!/usr/bin/env python3
import datetime as dt
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def latest_file():
    # 당일 마감 브리핑만 전송한다.
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    today = now.strftime('%Y-%m-%d')
    f = OUT / f"24n-korea-close-{today}.md"
    return str(f) if f.exists() else None


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
    print("Skip: korea close telegram delivery disabled")


if __name__ == "__main__":
    main()
