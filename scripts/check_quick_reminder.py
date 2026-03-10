#!/usr/bin/env python3
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "memory" / "quick-reminder.json"
INTERVAL_SECONDS = 3600


def main():
    if not STATE.exists():
        print("NO_QUICK_REMINDER")
        return

    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        print("NO_QUICK_REMINDER")
        return

    if not data.get("active"):
        print("NO_QUICK_REMINDER")
        return

    now = int(time.time())
    last = int(data.get("last_reminded_at") or 0)
    created = int(data.get("created_at") or now)
    base = last or created
    if now - base < INTERVAL_SECONDS:
        print("NO_QUICK_REMINDER")
        return

    target = data.get("target_name") or "상대방"
    purpose = data.get("purpose") or "퀵"
    data["last_reminded_at"] = now
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("QUICK_REMINDER_DUE")
    print(f"{target}님께 {purpose} 보내셨나요? 보내셨으면 '보냈다'고 말씀해 주세요. 그러면 알림을 끄겠습니다.")


if __name__ == "__main__":
    main()
