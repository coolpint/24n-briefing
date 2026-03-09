#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output"
APPLE_CAL = OUT_DIR / "apple-calendar-today.json"
GOOGLE_CAL = OUT_DIR / "google-calendar-today.json"
APPLE_REM = OUT_DIR / "apple-reminders-open.json"
OUT = OUT_DIR / "combined-agenda.md"
KST = dt.timezone(dt.timedelta(hours=9))


def load_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        clean = value.replace(" ", "T")
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        obj = dt.datetime.fromisoformat(clean)
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=KST)
        return obj.astimezone(KST)
    except Exception:
        return None


def fmt_time(value: str | None) -> str:
    obj = parse_dt(value)
    return obj.strftime("%H:%M") if obj else "시간 미정"


def is_today_due(value: str | None) -> bool:
    obj = parse_dt(value)
    return bool(obj and obj.date() == dt.datetime.now(KST).date())


def reminder_priority(title: str, list_name: str) -> tuple:
    key = f"{list_name} {title}"
    urgent_words = ["오늘", "마감", "납부", "이체", "공유", "전달", "쓰기", "준비"]
    score = 0
    for w in urgent_words:
        if w in key:
            score -= 1
    if list_name == "머니앤로":
        score -= 1
    return (score, list_name, title)


def main():
    now = dt.datetime.now(KST)
    apple_cal = load_payload(APPLE_CAL)
    google_cal = load_payload(GOOGLE_CAL)
    apple_rem = load_payload(APPLE_REM)

    events = []
    for payload, source in [(apple_cal, "Apple"), (google_cal, "Google")]:
        for ev in payload.get("events", []):
            row = dict(ev)
            row["source"] = source
            events.append(row)
    events.sort(key=lambda x: parse_dt(x.get("start")) or dt.datetime.max.replace(tzinfo=KST))

    reminders = apple_rem.get("reminders", [])
    reminders = sorted(reminders, key=lambda x: reminder_priority(x.get("title", ""), x.get("list", "")))
    today_due = [r for r in reminders if is_today_due(r.get("due"))]
    undated = [r for r in reminders if not r.get("due")][:12]

    lines = ["# 데일리 합산 브리핑", ""]
    lines.append(f"기준 시각: {now.strftime('%Y-%m-%d %H:%M KST')}")
    for label, payload in [("Apple 캘린더", apple_cal), ("Google 캘린더", google_cal), ("Apple 미리 알림", apple_rem)]:
        if payload.get("error"):
            lines.append(f"- 참고: {label} 읽기 미완료 ({payload.get('error')})")
    lines.append("")

    if events:
        lines.append("오늘 일정은 아래와 같습니다.")
        for ev in events:
            if ev.get("all_day"):
                when = "종일"
            else:
                when = f"{fmt_time(ev.get('start'))}~{fmt_time(ev.get('end'))}"
            lines.append(f"- {when} {ev.get('title', '(제목 없음)')} ({ev.get('source')} / {ev.get('calendar', '')})")
    else:
        lines.append("오늘 확인된 일정은 아직 없습니다.")
    lines.append("")
    lines.append("오늘 신경쓸 할 일은 아래와 같습니다.")

    if today_due:
        for r in today_due:
            lines.append(f"- 오늘 처리 권장: {r.get('title')} [{r.get('list')}]")
    elif undated:
        for r in undated[:8]:
            lines.append(f"- 확인 필요: {r.get('title')} [{r.get('list')}]")
    else:
        lines.append("- 현재 열려 있는 핵심 할 일이 없습니다.")

    lines.append("")
    lines.append("## 원본 데이터")
    lines.append(f"- Apple 일정: {len(apple_cal.get('events', []))}건")
    lines.append(f"- Google 일정: {len(google_cal.get('events', []))}건")
    lines.append(f"- 미리 알림(할일/머니앤로): {len(reminders)}건")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
