#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output"


def find_latest_file() -> Path | None:
    files = sorted(OUT_DIR.glob("24n-*.md"))
    return files[-1] if files else None


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Skip Telegram send: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return 0

    latest = find_latest_file()
    if not latest:
        print("Skip Telegram send: no output file")
        return 0

    text = latest.read_text(encoding="utf-8")
    # Telegram message max length safety
    max_len = 3900
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for idx, chunk in enumerate(chunks, start=1):
        payload = {
            "chat_id": chat_id,
            "text": chunk if len(chunks) == 1 else f"[24N {idx}/{len(chunks)}]\n\n" + chunk,
            "disable_web_page_preview": True,
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "ignore")
            result = json.loads(body)
            if not result.get("ok"):
                print("Telegram send failed:", body)
                return 1

    print(f"Telegram sent: {latest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
