#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output"
CAL = OUT_DIR / "apple-calendar-today.json"
REM = OUT_DIR / "apple-reminders-open.json"
OUT = OUT_DIR / "daily-agenda.md"
KST = dt.timezone(dt.timedelta(hours=9))


def load_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fmt_time(iso_text: str) -> str:
    if not iso_text:
        return "시간 미정"
    try:
        clean = iso_text.replace(" ", "T")
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt_obj = dt.datetime.fromisoformat(clean)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=KST)
        return dt_obj.astimezone(KST).strftime("%H:%M")
    except Exception:
        return iso_text


def is_today_due(iso_text: str) -> bool:
    if not iso_text:
        return False
    try:
        clean = iso_text.replace(" ", "T")
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt_obj = dt.datetime.fromisoformat(clean)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=KST)
        return dt_obj.astimezone(KST).date() == dt.datetime.now(KST).date()
    except Exception:
        return False


def main():
    now = dt.datetime.now(KST)
    cal_payload = load_payload(CAL)
    rem_payload = load_payload(REM)
    events = cal_payload.get("events", [])
    reminders = rem_payload.get("reminders", [])

    lines = ["# 데일리 일정 브리핑", ""]
    lines.append(f"기준 시각: {now.strftime('%Y-%m-%d %H:%M KST')}")
    if cal_payload.get("error"):
        lines.append(f"- 참고: 캘린더 읽기 미완료 ({cal_payload.get('error')})")
    if rem_payload.get("error"):
        lines.append(f"- 참고: 미리 알림 읽기 미완료 ({rem_payload.get('error')})")
    lines.append("")

    if events:
        lines.append("## 오늘 일정")
        for ev in events:
            when = "종일" if ev.get("all_day") else f"{fmt_time(ev.get('start'))}~{fmt_time(ev.get('end'))}"
            lines.append(f"- {when} | {ev.get('title','(제목 없음)')} [{ev.get('calendar','')}]")
        lines.append("")
    else:
        lines.append("## 오늘 일정")
        lines.append("- 확인된 일정이 없습니다.")
        lines.append("")

    today_due = [r for r in reminders if is_today_due(r.get("due"))]
    undated = [r for r in reminders if not r.get("due")][:10]

    lines.append("## 오늘 신경쓸 할 일")
    if today_due:
        for r in today_due:
            lines.append(f"- 오늘 마감 | {r.get('title')} [{r.get('list')}]")
    else:
        lines.append("- 오늘 마감으로 잡힌 미리 알림은 없습니다.")
    lines.append("")

    lines.append("## 미기한 할 일")
    if undated:
        for r in undated:
            lines.append(f"- {r.get('title')} [{r.get('list')}]")
    else:
        lines.append("- 미기한 할 일 없음")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
