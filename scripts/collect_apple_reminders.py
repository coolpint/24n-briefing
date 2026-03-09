#!/usr/bin/env python3
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "apple-reminders-open.json"


def run_applescript(script: str) -> str:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Reminders 접근이 시간 초과됐습니다. macOS 자동화/미리 알림 권한 확인이 필요합니다.") from e
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.strip()


def main():
    script = r'''
set oldTID to AppleScript's text item delimiters
set AppleScript's text item delimiters to "\n"
set outLines to {}
tell application "Reminders"
    repeat with listNameWanted in {"할일", "머니앤로"}
        if (exists list listNameWanted) then
            set rl to list listNameWanted
            repeat with r in (every reminder of rl whose completed is false)
                set listName to name of rl as text
                set rTitle to name of r as text
                set dueText to ""
                try
                    if due date of r is not missing value then
                        set dueText to ((due date of r) as «class isot» as text)
                    end if
                end try
                set end of outLines to (listName & "\t" & rTitle & "\t" & dueText)
            end repeat
        end if
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
            if len(parts) != 3:
                continue
            list_name, title, due = parts
            rows.append({"list": list_name, "title": title, "due": due or None})
        rows.sort(key=lambda x: (x["due"] is None, x["due"] or "", x["list"], x["title"]))
        payload = {"generated_at": dt.datetime.now().isoformat(), "reminders": rows, "error": None}
        print(f"Reminders: {len(rows)}")
    except Exception as e:
        payload = {"generated_at": dt.datetime.now().isoformat(), "reminders": [], "error": str(e)}
        print(f"Reminders unavailable: {e}")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
