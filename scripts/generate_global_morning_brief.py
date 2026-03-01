#!/usr/bin/env python3
import datetime as dt
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "global_sources.json"
OUT_DIR = ROOT / "output"


def strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag


def child_text(node, names):
    names = set(names)
    for c in list(node):
        if strip_ns(c.tag) in names and c.text:
            return re.sub(r"\s+", " ", c.text).strip()
    return ""


def parse_dt(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def fetch_source(src, since_utc):
    req = urllib.request.Request(src["url"], headers={"User-Agent": "24N-global/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    root_name = strip_ns(root.tag).lower()
    items = []

    if src.get("type") == "sitemap" or root_name == "urlset":
        include = src.get("include_path", "")
        for u in root.findall("{*}url"):
            link = child_text(u, ["loc"])
            if include and include not in link:
                continue
            pub = parse_dt(child_text(u, ["lastmod"]))
            if not pub:
                continue
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=dt.timezone.utc)
            if pub >= since_utc:
                title = link.rstrip('/').split('/')[-1].replace('-', ' ')
                items.append((pub, title, link))
        return items

    if root_name == "rss":
        channel = root.find("channel")
        if channel is None:
            return items
        rows = channel.findall("item")
    else:
        rows = root.findall("{*}entry")

    for it in rows:
        title = child_text(it, ["title"])
        link = child_text(it, ["link"])
        if not link:
            lk = it.find("{*}link")
            if lk is not None:
                link = lk.attrib.get("href", "")
        pub = parse_dt(child_text(it, ["pubDate", "published", "updated", "date"]))
        if not pub:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        if pub >= since_utc:
            items.append((pub, title, link))
    return items


def build_brief(collected):
    sections = ["국제정세", "글로벌경제", "중국", "일본", "빅테크·AI", "리걸테크"]
    lines = []
    lines.append("# [24N] 간밤 글로벌 동향 브리핑")
    lines.append("")

    total = sum(len(v) for v in collected.values())
    lines.append(f"- 간밤 수집 건수: {total}건")
    lines.append("")

    for sec in sections:
        rows = sorted(collected.get(sec, []), key=lambda x: x[0], reverse=True)
        lines.append(f"## {sec}")
        if not rows:
            lines.append("- 신규 핵심 이슈 없음")
            lines.append("")
            continue
        # 해석 요약 1문장
        lines.append(f"- 간밤에는 {sec} 관련 신규 발행 {len(rows)}건이 확인됐고, 핵심 쟁점이 빠르게 갱신되는 흐름입니다.")
        for pub, title, link in rows[:4]:
            lines.append(f"- {title} | {link}")
        lines.append("")

    lines.append("## 종합")
    lines.append("- 국제정세·경제·기술 이슈가 분리되지 않고 상호 연동되는 국면입니다.")
    lines.append("- 중국·일본 관련 정책·산업 뉴스는 공급망과 규제 흐름에 직접 연결돼 후속 점검이 필요합니다.")
    lines.append("- 빅테크·AI와 리걸테크는 기능 발표보다 규제·도입 구조 변화 관점으로 읽는 편이 유효합니다.")
    lines.append("")
    return "\n".join(lines)


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    since_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=12)

    collected = {}
    errors = []
    for src in cfg["sources"]:
        sec = src["category"]
        collected.setdefault(sec, [])
        try:
            items = fetch_source(src, since_utc)
            collected[sec].extend(items)
        except Exception as e:
            errors.append(f"{src['name']}: {e}")

    md = build_brief(collected)
    if errors:
        md += "\n## 수집 오류\n" + "\n".join([f"- {e}" for e in errors]) + "\n"

    kst = dt.timezone(dt.timedelta(hours=9))
    out = OUT_DIR / f"24n-global-{dt.datetime.now(kst).strftime('%Y-%m-%d')}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
