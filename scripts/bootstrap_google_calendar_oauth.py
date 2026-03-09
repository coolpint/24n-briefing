#!/usr/bin/env python3
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parents[1]
CLIENT_SECRET = ROOT / "mail_setup" / "google_client_secret.json"
CFG = ROOT / "config" / "calendar_sources.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]


def main():
    if not CLIENT_SECRET.exists():
        raise SystemExit(f"Missing client secret: {CLIENT_SECRET}")
    if not CFG.exists():
        raise SystemExit(f"Missing config: {CFG}")

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    src = cfg.get("google_workspace") or {}
    token_file = src.get("token_file")
    if not token_file:
        raise SystemExit("config/calendar_sources.json missing google_workspace.token_file")

    token_path = ROOT / token_file
    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"Saved token: {token_path}")
    print("Scopes:")
    for s in SCOPES:
        print(f"- {s}")


if __name__ == "__main__":
    main()
