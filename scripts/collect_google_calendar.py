#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "calendar_sources.json"
OUT = ROOT / "output" / "google-calendar-today.json"
KST = dt.timezone(dt.timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def main():
    if not CFG.exists():
        payload = {"generated_at": dt.datetime.now().isoformat(), "events": [], "error": "config/calendar_sources.json not found"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote: {OUT}")
        return

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    src = cfg.get("google_workspace") or {}
    token_file = src.get("token_file")
    calendar_ids = src.get("calendar_ids", ["primary"])
    if not token_file:
        payload = {"generated_at": dt.datetime.now().isoformat(), "events": [], "error": "google_workspace.token_file missing"}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote: {OUT}")
        return

    token_path = ROOT / token_file
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")

    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = dt.datetime.now(KST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).isoformat()
    end = (now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)).astimezone(dt.timezone.utc).isoformat()

    events = []
    for cal_id in calendar_ids:
        resp = svc.events().list(calendarId=cal_id, timeMin=start, timeMax=end, singleEvents=True, orderBy="startTime").execute()
        for item in resp.get("items", []):
            s = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            e = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
            events.append({
                "calendar": cal_id,
                "title": item.get("summary", "(제목 없음)"),
                "start": s,
                "end": e,
                "all_day": "date" in item.get("start", {}),
            })
    payload = {"generated_at": dt.datetime.now().isoformat(), "events": events, "error": None}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT}")
    print(f"Events: {len(events)}")


if __name__ == "__main__":
    main()
