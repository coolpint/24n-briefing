#!/usr/bin/env python3
import datetime as dt
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "global_sources.json"
OUT_DIR = ROOT / "output"

TOPIC_MAP = OrderedDict({
    "미국-이란 충돌": ["iran", "israel", "strike", "middle east", "war", "oil", "hormuz", "hezbollah", "tehran", "beirut"],
    "중국 정책·산업": ["china", "xi", "beijing", "hong kong", "taiwan", "trade", "tariff", "chip", "semiconductor", "catl", "openclaw"],
    "빅테크·AI": ["openai", "anthropic", "nvidia", "meta", "ai", "artificial intelligence", "memory", "openclaw", "gemini"],
    "일본·동북아": ["japan", "korea", "north korea", "tokyo", "wbc"],
    "기타 글로벌 이슈": [],
})


def strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag


def child_text(node, names):
    names = set(names)
    for c in list(node):
        if strip_ns(c.tag) in names and c.text:
            return re.sub(r"\s+", " ", c.text).strip()
    return ""


def node_inner_text(node):
    if node is None:
        return ""
    txt = "".join(node.itertext())
    txt = html.unescape(txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


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


def clean_text(text: str, limit: int = 280) -> str:
    t = html.unescape((text or "").strip())
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\b\d+\s*-MIN READ\b", " ", t, flags=re.I)
    t = re.sub(r"\bListen\b", " ", t, flags=re.I)
    t = re.sub(r"\bPublished:.*$", " ", t, flags=re.I)
    t = re.sub(r"\bUpdated:.*$", " ", t, flags=re.I)
    t = re.sub(r"British Broadcasting Corporation.*$", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .|-")
    if len(t) > limit:
        t = t[:limit].rstrip() + "…"
    return t


def fetch_source(src, since_utc):
    req = urllib.request.Request(src["url"], headers={"User-Agent": "24N-global/2.0"})
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
                items.append({
                    "pub": pub,
                    "title": clean_text(title, 140),
                    "summary": "",
                    "link": link,
                    "source": src.get("name", ""),
                    "category": src.get("category", ""),
                })
        return items

    rows = []
    if root_name == "rss":
        channel = root.find("channel")
        if channel is not None:
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
        summary = child_text(it, ["description", "summary", "content"])
        if not summary:
            summary = node_inner_text(it.find("{*}description"))
        if not summary:
            summary = node_inner_text(it.find("{*}summary"))
        pub = parse_dt(child_text(it, ["pubDate", "published", "updated", "date"]))
        if not pub:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        if pub >= since_utc and link:
            items.append({
                "pub": pub,
                "title": clean_text(title, 140),
                "summary": clean_text(summary, 240),
                "link": link,
                "source": src.get("name", ""),
                "category": src.get("category", ""),
            })
    return items


def _match_keyword(text: str, kw: str) -> bool:
    t = (text or "").lower()
    k = kw.lower()
    if re.fullmatch(r"[a-z0-9\-\. ]+", k):
        return re.search(rf"\b{re.escape(k)}\b", t) is not None
    return k in t


def assign_topic(row: dict) -> str:
    text = f"{row.get('title', '')} {row.get('summary', '')}".lower()
    scores = {}
    for topic, kws in TOPIC_MAP.items():
        if topic == "기타 글로벌 이슈":
            continue
        score = 0
        for kw in kws:
            if _match_keyword(text, kw):
                score += 1
        scores[topic] = score

    best_topic = max(scores, key=scores.get)
    best_score = scores[best_topic]
    if best_score <= 0:
        return "기타 글로벌 이슈"

    if best_topic == "미국-이란 충돌":
        if not any(_match_keyword(text, kw) for kw in ["iran", "israel", "hezbollah", "tehran", "beirut", "hormuz"]):
            return "기타 글로벌 이슈"

    return best_topic


def score_row(row: dict) -> int:
    text = f"{row.get('title','')} {row.get('summary','')}".lower()
    score = 0
    if row.get("summary"):
        score += 2
    if row.get("source", "").startswith("Reuters"):
        score += 3
    if row.get("source", "").startswith("BBC") or row.get("source", "").startswith("SCMP"):
        score += 2
    if any(k in text for k in ["warn", "cut", "sue", "summit", "strike", "profit", "trade", "oil", "tariff", "warning"]):
        score += 2
    if any(k in text for k in ["opinion", "video", "watch:"]):
        score -= 2
    return score


def dedupe_rows(rows: list[dict]) -> list[dict]:
    merged = {}
    for r in rows:
        link = (r.get("link") or "").strip()
        if not link:
            continue
        prev = merged.get(link)
        if prev is None or r.get("pub") > prev.get("pub"):
            merged[link] = r
    return sorted(merged.values(), key=lambda x: x.get("pub"), reverse=True)


def select_candidates(rows: list[dict]) -> list[dict]:
    by_topic = OrderedDict((k, []) for k in TOPIC_MAP.keys())
    for row in rows:
        row["topic"] = assign_topic(row)
        row["score"] = score_row(row)
        by_topic[row["topic"]].append(row)

    for topic in by_topic:
        by_topic[topic] = sorted(by_topic[topic], key=lambda r: (r["score"], r["pub"]), reverse=True)

    selected = []
    seen = set()
    # topic diversity first
    for topic in ["미국-이란 충돌", "중국 정책·산업", "빅테크·AI", "기타 글로벌 이슈"]:
        for row in by_topic.get(topic, []):
            if row["link"] in seen:
                continue
            selected.append(row)
            seen.add(row["link"])
            break
    # fill remaining slots
    pool = sorted(rows, key=lambda r: (r["score"], r["pub"]), reverse=True)
    for row in pool:
        if row["link"] in seen:
            continue
        selected.append(row)
        seen.add(row["link"])
        if len(selected) >= 8:
            break
    return selected[:8]


def build_source_pack(rows: list[dict], selected: list[dict]) -> str:
    lines = ["# [24N] 간밤 글로벌 동향 브리핑 소스 팩", ""]
    lines.append("## 작성 규칙")
    lines.append("- 제목 → 한국어 서술형 장문 3~4문단 → 하단 원문 링크")
    lines.append("- 건수 요약 금지")
    lines.append("- 범주형 뭉뚱그림 금지")
    lines.append("- 각 문단에는 기사별 사실이 드러나야 함")
    lines.append("")
    lines.append("## 우선 기사 후보")
    lines.append("")
    for i, r in enumerate(selected, 1):
        lines.append(f"### {i}. {r['title']}")
        lines.append(f"- 주제: {r['topic']}")
        lines.append(f"- 출처: {r['source']}")
        lines.append(f"- 요약: {r['summary'] or '(요약 없음)'}")
        lines.append(f"- 링크: {r['link']}")
        lines.append("")
    lines.append("## 전체 링크")
    lines.append("")
    for r in rows:
        lines.append(f"- {r['title']} | {r['link']}")
    return "\n".join(lines)


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    since_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=12)
    collected = []
    errors = []
    for src in cfg["sources"]:
        try:
            collected.extend(fetch_source(src, since_utc))
        except Exception as e:
            errors.append(f"{src.get('name', 'unknown')}: {e}")

    rows = dedupe_rows(collected)
    selected = select_candidates(rows)

    kst = dt.timezone(dt.timedelta(hours=9))
    day = dt.datetime.now(kst).strftime('%Y-%m-%d')
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_out = OUT_DIR / f"24n-global-candidates-{day}.json"
    md_out = OUT_DIR / f"24n-global-source-pack-{day}.md"

    json_ready = []
    for r in selected:
        json_ready.append({
            "topic": r["topic"],
            "source": r["source"],
            "title": r["title"],
            "summary": r["summary"],
            "link": r["link"],
            "published_at": r["pub"].isoformat(),
            "score": r["score"],
        })

    json_out.write_text(json.dumps({
        "date": day,
        "selected": json_ready,
        "total_links": len(rows),
        "errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(build_source_pack(rows, selected), encoding="utf-8")

    print(f"Wrote: {json_out}")
    print(f"Wrote: {md_out}")
    print(f"Selected: {len(selected)} / Total links: {len(rows)}")
    if errors:
        print(f"Source errors: {len(errors)}")
        for e in errors[:5]:
            print(f"- {e}")


if __name__ == "__main__":
    main()
