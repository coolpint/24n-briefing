#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "calendar_sources.json"
OUT = ROOT / "output" / "o365-calendar-today.json"


def main():
    note = {
        "generated_at": dt.datetime.now().isoformat(),
        "events": [],
        "error": "O365 연동은 Microsoft Graph 인증 설정이 아직 필요합니다. config/calendar_sources.json에 tenant_id, client_id, account, calendar_ids를 채워야 합니다.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
