#!/usr/bin/env python3
import datetime as dt
import html
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


def normalize_summary(text: str, limit: int = 180) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t)
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"


def fetch_source(src, since_utc):
    req = urllib.request.Request(src["url"], headers={"User-Agent": "24N-global/1.1"})
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
                items.append({"pub": pub, "title": title, "link": link, "summary": ""})
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
        if pub >= since_utc:
            items.append({
                "pub": pub,
                "title": title,
                "link": link,
                "summary": normalize_summary(summary),
            })
    return items


def _match_keyword(text: str, kw: str) -> bool:
    t = (text or "").lower()
    k = kw.lower()
    if re.fullmatch(r"[a-z0-9\-\.]+", k):
        return re.search(rf"\b{re.escape(k)}\b", t) is not None
    return k in t


def topic_brief(topic: str, rows: list[dict]) -> str:
    summaries = [r.get("summary", "") for r in rows if r.get("summary")]
    if summaries:
        # 같은 표현 반복 방지
        uniq = []
        seen = set()
        for s in summaries:
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(s)
            if len(uniq) >= 2:
                break
        if uniq:
            return " ".join(uniq)

    fallback = {
        "미국-이란 충돌": "중동 관련 보도가 연속으로 나오며 긴장 국면이 이어지는 흐름이다.",
        "중국 정책·산업": "중국 정책 관련 보도가 정책 우선순위와 성장·기술 전략의 방향성을 재확인하는 재료로 작동했다.",
        "일본·동북아 외교": "동북아 외교 관련 뉴스가 통상·안보 변수와 맞물리며 정책 불확실성을 키우는 흐름이다.",
        "빅테크·AI": "빅테크·AI는 기술 경쟁뿐 아니라 규제·책임 구조 정비 속도가 핵심 변수로 부상했다.",
        "리걸테크": "리걸테크는 기능 출시보다 실제 도입 속도와 규제 적합성이 핵심 쟁점으로 이동했다.",
    }
    return fallback.get(topic, "해당 이슈가 단기 뉴스 재료를 넘어 정책·시장 변수로 연결되는 흐름이다.")


def build_brief(collected):
    lines = []
    lines.append("# [24N] 간밤 글로벌 동향 브리핑")
    lines.append("")

    all_rows = []
    for _, rows in collected.items():
        all_rows.extend(rows)

    topic_map = {
        "미국-이란 충돌": ["iran", "israel", "strike", "middle east", "war", "oil"],
        "중국 정책·산업": ["china", "xi", "beijing", "import", "innovation", "5-year"],
        "일본·동북아 외교": ["japan", "korea", "tokyo", "east asia", "evacuate"],
        "빅테크·AI": ["openai", "anthropic", "nvidia", "llm", "chatgpt", "gemini", "chip", "ai"],
        "리걸테크": ["legal", "law", "contract", "court"],
    }

    score = {k: 0 for k in topic_map}
    topic_rows = {k: [] for k in topic_map}
    for r in all_rows:
        text = f"{r.get('title', '')} {r.get('summary', '')}".lower()
        for topic, kws in topic_map.items():
            if any(_match_keyword(text, k) for k in kws):
                score[topic] += 1
                topic_rows[topic].append(r)

    picked = [k for k, v in sorted(score.items(), key=lambda x: x[1], reverse=True) if v > 0][:3]

    if not picked:
        lines.append("간밤에는 다수 소스에서 동시에 반복된 핵심 이슈가 확인되지 않았다.")
        return "\n".join(lines)

    second = picked[1] if len(picked) > 1 else '후속 이슈'
    third = picked[2] if len(picked) > 2 else '연관 이슈'
    lines.append(f"{picked[0]} 이슈가 간밤 흐름을 주도했고, 이어 {second} 이슈와 {third} 논점이 함께 부상했다.")
    lines.append("")

    lines.append("쟁점과 현안")
    lines.append("")
    for topic in picked:
        rows = sorted(topic_rows.get(topic, []), key=lambda x: x.get("pub"), reverse=True)
        rows = rows[:3]
        if not rows:
            continue
        lines.append(f"• {topic}")
        lines.append(topic_brief(topic, rows))
        for r in rows:
            if r.get("summary"):
                lines.append(f"  - {r['title']}: {r['summary']}")
        lines.append("")

    lines.append("원문 링크")
    lines.append("")
    shown = 0
    seen_links = set()
    for topic in picked:
        rows = sorted(topic_rows.get(topic, []), key=lambda x: x.get("pub"), reverse=True)
        for r in rows:
            link = r.get("link", "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            lines.append(f"• {r.get('title', '').strip()}")
            lines.append(f"[{link}]({link})")
            lines.append("")
            shown += 1
            if shown >= 10:
                break
        if shown >= 10:
            break

    return "\n".join(lines)


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    since_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=12)

    collected = {}
    for src in cfg["sources"]:
        sec = src["category"]
        collected.setdefault(sec, [])
        try:
            items = fetch_source(src, since_utc)
            collected[sec].extend(items)
        except Exception:
            continue

    md = build_brief(collected)

    kst = dt.timezone(dt.timedelta(hours=9))
    out = OUT_DIR / f"24n-global-{dt.datetime.now(kst).strftime('%Y-%m-%d')}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
