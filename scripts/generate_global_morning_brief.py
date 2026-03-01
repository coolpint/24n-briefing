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


def _match_keyword(text: str, kw: str) -> bool:
    t = (text or "").lower()
    k = kw.lower()
    if re.fullmatch(r"[a-z0-9\-\.]+", k):
        return re.search(rf"\b{re.escape(k)}\b", t) is not None
    return k in t


def build_brief(collected):
    lines = []
    lines.append("# [24N] 간밤 글로벌 동향 브리핑")
    lines.append("")

    all_rows = []
    for sec, rows in collected.items():
        for pub, title, link in rows:
            all_rows.append({"sec": sec, "pub": pub, "title": title, "link": link})

    # 반응 대체 지표: 여러 소스/섹션에서 반복되는 주제를 우선
    topic_map = {
        "미국-이란 충돌": ["iran", "israel", "strike", "khamenei", "middle east", "war"],
        "중국 정책·산업": ["china", "xi", "beijing", "sportswear", "communist party"],
        "일본·동북아 외교": ["japan", "korea", "tokyo", "ties"],
        "빅테크·AI": ["ai", "openai", "anthropic", "model", "chip", "agent"],
        "리걸테크": ["legal", "law", "contract", "court"],
    }

    score = {k: 0 for k in topic_map}
    topic_rows = {k: [] for k in topic_map}
    for r in all_rows:
        t = (r["title"] or "").lower()
        for topic, kws in topic_map.items():
            if any(_match_keyword(t, k) for k in kws):
                score[topic] += 1
                if len(topic_rows[topic]) < 5:
                    topic_rows[topic].append(r)

    picked = [k for k, v in sorted(score.items(), key=lambda x: x[1], reverse=True) if v > 0][:3]

    if not picked:
        lines.append("간밤에는 다수 소스에서 동시에 반복된 핵심 이슈가 확인되지 않았다.")
        return "\n".join(lines)

    second = picked[1] if len(picked) > 1 else '후속 이슈'
    third = picked[2] if len(picked) > 2 else '연관 이슈'
    lines.append(f"{picked[0]} 관련 보도가 가장 집중됐고, 이어 {second}과 {third} 순으로 관심이 모였다.")
    lines.append("")

    lines.append("## 쟁점과 현안")
    for topic in picked:
        rows = topic_rows.get(topic, [])[:3]
        if not rows:
            continue
        lines.append(f"{topic}.")
        for r in rows:
            lines.append(f"- {r['title']}")
    lines.append("")

    lines.append("## 다르게 읽기")
    if "미국-이란 충돌" in picked:
        lines.append("- 중동 변수는 국제유가와 위험자산 변동성에 바로 연결돼, 외교 뉴스가 곧 금융 변수로 전이될 가능성이 크다.")
    if "중국 정책·산업" in picked or "일본·동북아 외교" in picked:
        lines.append("- 중국·일본 이슈는 단일 국가 뉴스로 보기보다 공급망·통상·외교 축에서 함께 읽는 편이 정확하다.")
    if "빅테크·AI" in picked or "리걸테크" in picked:
        lines.append("- AI·리걸테크는 신기능 발표보다 도입 속도와 규제 대응 역량에서 기업 간 격차가 벌어지는 국면이다.")
    lines.append("")

    lines.append("## 원문 링크")
    shown = 0
    for topic in picked:
        for r in topic_rows.get(topic, [])[:2]:
            lines.append(f"- {r['title']} | {r['link']}")
            shown += 1
            if shown >= 8:
                break
        if shown >= 8:
            break
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

    kst = dt.timezone(dt.timedelta(hours=9))
    out = OUT_DIR / f"24n-global-{dt.datetime.now(kst).strftime('%Y-%m-%d')}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
