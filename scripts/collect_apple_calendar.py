#!/usr/bin/env python3
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "apple-calendar-today.json"


def run_applescript(script: str) -> str:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Calendar 접근이 시간 초과됐습니다. macOS 자동화/캘린더 권한 확인이 필요합니다.") from e
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.strip()


def main():
    script = r'''
set oldTID to AppleScript's text item delimiters
set AppleScript's text item delimiters to "\n"
set outLines to {}
tell application "Calendar"
    set startDate to current date
    set hours of startDate to 0
    set minutes of startDate to 0
    set seconds of startDate to 0
    set endDate to startDate + (1 * days)
    repeat with cal in calendars
        repeat with ev in (every event of cal whose start date ≥ startDate and start date < endDate)
            set calName to name of cal as text
            set evTitle to summary of ev as text
            set startIso to ((start date of ev) as «class isot» as text)
            set endIso to ((end date of ev) as «class isot» as text)
            set allDayFlag to allday event of ev as text
            set end of outLines to (calName & "\t" & evTitle & "\t" & startIso & "\t" & endIso & "\t" & allDayFlag)
        end repeat
    end repeat
end tell
set AppleScript's text item delimiters to oldTID
return outLines as text
'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = run_applescript(script)
        rows = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) != 5:
                continue
            cal, title, start_iso, end_iso, all_day = parts
            rows.append({
                "calendar": cal,
                "title": title,
                "start": start_iso,
                "end": end_iso,
                "all_day": all_day.lower() == "true",
            })
        rows.sort(key=lambda x: x["start"])
        payload = {"generated_at": dt.datetime.now().isoformat(), "events": rows, "error": None}
        print(f"Events: {len(rows)}")
    except Exception as e:
        payload = {"generated_at": dt.datetime.now().isoformat(), "events": [], "error": str(e)}
        print(f"Calendar unavailable: {e}")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
