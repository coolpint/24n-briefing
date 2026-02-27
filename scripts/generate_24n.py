#!/usr/bin/env python3
import datetime as dt
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "config" / "sources.json"
OUT_DIR = ROOT / "output"


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def child_text(node, names):
    names = set(names)
    for c in list(node):
        if strip_ns(c.tag) in names and c.text:
            return c.text.strip()
    return ""


def parse_dt(s: str):
    if not s:
        return None
    s = s.strip()
    try:
        # rss pubDate
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        # atom updated/published
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def fetch_feed(source):
    req = urllib.request.Request(source["url"], headers={"User-Agent": "24N-feedbot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    entries = []

    root_name = strip_ns(root.tag).lower()
    if root_name == "rss":
        channel = root.find("channel")
        if channel is None:
            return entries
        for item in channel.findall("item"):
            title = child_text(item, ["title"])
            link = child_text(item, ["link"])
            pub = child_text(item, ["pubDate", "date", "published", "updated"])
            desc = child_text(item, ["description", "summary"])
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": desc})
    else:
        # atom
        for ent in root.findall("{*}entry"):
            title = child_text(ent, ["title"])
            link = ""
            for lk in ent.findall("{*}link"):
                rel = lk.attrib.get("rel", "alternate")
                href = lk.attrib.get("href", "")
                if rel == "alternate" and href:
                    link = href
                    break
                if not link and href:
                    link = href
            pub = child_text(ent, ["published", "updated"])
            summary = child_text(ent, ["summary", "content"])
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": summary})

    return entries


def collect_recent(sources, since_utc):
    rows = []
    for s in sources:
        if not s.get("active", False):
            continue
        try:
            items = fetch_feed(s)
            local = []
            for it in items:
                p = it.get("published")
                if p is None:
                    continue
                if p.tzinfo is None:
                    p = p.replace(tzinfo=dt.timezone.utc)
                if p >= since_utc:
                    local.append(
                        {
                            "account": s["account"],
                            "source": s["label"],
                            "title": re.sub(r"\s+", " ", it.get("title", "")).strip(),
                            "link": it.get("link", ""),
                            "published": p,
                            "summary": re.sub(r"\s+", " ", it.get("summary", "")).strip(),
                            "tags": s.get("tags", []),
                        }
                    )

            local.sort(key=lambda x: x["published"], reverse=True)
            max_items = int(s.get("max_items", 10))
            rows.extend(local[:max_items])

        except Exception as e:
            rows.append(
                {
                    "account": s["account"],
                    "source": s["label"],
                    "title": f"[수집 실패] {e}",
                    "link": s["url"],
                    "published": dt.datetime.now(dt.timezone.utc),
                    "summary": "",
                    "tags": ["error"],
                }
            )

    rows.sort(key=lambda x: x["published"], reverse=True)
    return rows


def _has_batchim(word: str) -> bool:
    if not word:
        return False
    ch = word[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        return ((code - 0xAC00) % 28) != 0
    return False


def build_title(items):
    c = Counter()
    for it in items[:30]:
        for t in it.get("tags", []):
            c[t] += 1
    mapping = {
        "ai": "인공지능",
        "macro": "거시경제",
        "economy": "경제",
        "policy": "정책",
        "tech": "기술",
        "creator": "콘텐츠",
        "startup": "스타트업",
    }
    top = [mapping.get(k, k) for k, _ in c.most_common(2) if k != "error"]
    if len(top) >= 2:
        particle = "과" if _has_batchim(top[0]) else "와"
        return f"{top[0]}{particle} {top[1]} 이슈 점검"
    if len(top) == 1:
        return f"{top[0]} 동향 점검"
    return "글로벌 발신 채널 동향 점검"


def build_md(title, items, inactive, now_kst):
    lines = []
    lines.append(f"# [24N] {title}")
    lines.append("")
    lines.append(f"- 발행 시각: {now_kst.strftime('%Y-%m-%d %H:%M KST')}")
    lines.append("- 수집 범위: RSS/Atom/공식 채널 최근 24시간")
    lines.append("")

    ok_items = [x for x in items if not x["title"].startswith("[수집 실패]")]
    err_items = [x for x in items if x["title"].startswith("[수집 실패]")]

    lines.append("## 오늘의 핵심")
    if ok_items:
        lines.append(f"- 신규 항목 {len(ok_items)}건을 확인했습니다.")
        if ok_items:
            top_sources = Counter([x["account"] for x in ok_items]).most_common(3)
            lines.append("- 발행 비중 상위: " + ", ".join([f"@{a}({n}건)" for a, n in top_sources]))
        lines.append("- X 대신 공개 피드 기반 수집으로 구성했습니다.")
    else:
        lines.append("- 지난 24시간 신규 항목이 없습니다.")

    if err_items:
        lines.append(f"- 일부 소스 {len(err_items)}건은 수집에 실패했습니다.")
    lines.append("")

    lines.append("## 브리핑")
    if ok_items:
        top = ok_items[:5]
        sent = []
        for it in top:
            sent.append(f"{it['source']}에서 '{it['title']}' 항목이 올라왔습니다")
        lines.append(". ".join(sent) + ".")
        lines.append("오늘 판독 포인트는 개별 발언보다 반복되는 주제의 결입니다. 같은 문제를 서로 다른 채널이 어떤 언어로 설명하는지 비교해 읽으면 과장 없이 방향을 잡기 좋습니다.")
    else:
        lines.append("신규 항목이 없어 전일 흐름을 유지합니다. 소스 활성 상태와 발행 주기를 함께 점검해 주세요.")
    lines.append("")

    lines.append("## 신규 항목")
    if ok_items:
        for it in ok_items[:20]:
            kst_time = it["published"].astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%m-%d %H:%M")
            lines.append(f"- {kst_time} | @{it['account']} | {it['title']} | {it['link']}")
    else:
        lines.append("- 없음")
    lines.append("")

    lines.append("## 비활성/미매핑 계정")
    for a in inactive:
        lines.append(f"- @{a}")
    lines.append("")

    if err_items:
        lines.append("## 수집 오류")
        for it in err_items[:10]:
            lines.append(f"- @{it['account']} ({it['source']}): {it['title']}")
        lines.append("")

    return "\n".join(lines)


def main():
    if not SOURCES_FILE.exists():
        print(f"ERROR: missing {SOURCES_FILE}", file=sys.stderr)
        sys.exit(2)

    cfg = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sources = cfg.get("sources", [])
    inactive = cfg.get("inactive_accounts", [])

    now_utc = dt.datetime.now(dt.timezone.utc)
    since = now_utc - dt.timedelta(hours=24)
    items = collect_recent(sources, since)

    title = build_title(items)
    kst = dt.timezone(dt.timedelta(hours=9))
    now_kst = now_utc.astimezone(kst)

    md = build_md(title, items, inactive, now_kst)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"24n-{now_kst.strftime('%Y-%m-%d')}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
