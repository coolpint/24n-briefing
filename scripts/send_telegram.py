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
    # 일반 24N 아침 브리핑 파일만 대상으로 삼는다.
    # (예: 24n-2026-03-09.md) / 24n-global-*, 24n-korea-close-* 제외
    files = sorted(OUT_DIR.glob("24n-????-??-??.md"))
    return files[-1] if files else None


def main():
    print("Skip Telegram send: daily 24N auto-send temporarily disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
