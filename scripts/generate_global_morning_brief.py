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


def normalize_summary(text: str, limit: int = 220) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t)
    # 제목/관련기사 뭉치를 피하기 위한 간단 정리
    t = re.sub(r"^(\d+\s+hours?\s+ago\s+)?", "", t, flags=re.I)
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"


def fetch_source(src, since_utc):
    req = urllib.request.Request(src["url"], headers={"User-Agent": "24N-global/1.2"})
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
                items.append({"pub": pub, "title": title, "link": link, "summary": "", "source": src.get("name", "")})
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
        if pub >= since_utc:
            items.append({
                "pub": pub,
                "title": title,
                "link": link,
                "summary": normalize_summary(summary),
                "source": src.get("name", ""),
            })
    return items


def _match_keyword(text: str, kw: str) -> bool:
    t = (text or "").lower()
    k = kw.lower()
    if re.fullmatch(r"[a-z0-9\-\.]+", k):
        return re.search(rf"\b{re.escape(k)}\b", t) is not None
    return k in t


def assign_topic(row: dict, topic_map: OrderedDict) -> str:
    text = f"{row.get('title', '')} {row.get('summary', '')}".lower()
    for topic, kws in topic_map.items():
        if any(_match_keyword(text, kw) for kw in kws):
            return topic
    return "기타 글로벌 이슈"


def fallback_summary(title: str) -> str:
    t = (title or "").strip()
    return f"{t} 관련 핵심 사실을 점검할 필요가 있다." if t else "핵심 사실 점검이 필요하다."


def topic_intro(topic: str, count: int) -> str:
    return f"{topic} 관련 기사 {count}건을 바탕으로 간밤 흐름을 정리했다."


def build_brief(collected):
    lines = ["# [24N] 간밤 글로벌 동향 브리핑", ""]

    # 1) 전체 기사 병합 + 링크 기준 중복 제거(최신 우선)
    merged = {}
    for rows in collected.values():
        for r in rows:
            link = (r.get("link") or "").strip()
            if not link:
                continue
            prev = merged.get(link)
            if prev is None or r.get("pub") > prev.get("pub"):
                merged[link] = r

    all_rows = sorted(merged.values(), key=lambda x: x.get("pub"), reverse=True)
    total = len(all_rows)

    if total == 0:
        lines.append("간밤에는 수집된 글로벌 기사 데이터가 없었다.")
        return "\n".join(lines), 0, 0

    topic_map = OrderedDict({
        "미국-이란 충돌": ["iran", "israel", "strike", "middle east", "war", "oil", "hormuz"],
        "중국 정책·산업": ["china", "xi", "beijing", "import", "innovation", "5-year", "two sessions"],
        "일본·동북아 외교": ["japan", "korea", "tokyo", "east asia", "evacuate"],
        "빅테크·AI": ["openai", "anthropic", "nvidia", "llm", "chatgpt", "gemini", "chip", "ai"],
        "리걸테크": ["legal", "law", "contract", "court"],
    })

    topic_rows = OrderedDict((k, []) for k in topic_map.keys())
    topic_rows["기타 글로벌 이슈"] = []

    for r in all_rows:
        topic = assign_topic(r, topic_map)
        topic_rows[topic].append(r)

    sorted_topics = sorted(topic_rows.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_topics = [k for k, v in sorted_topics[:3] if len(v) > 0]

    if top_topics:
        second = top_topics[1] if len(top_topics) > 1 else "후속 이슈"
        third = top_topics[2] if len(top_topics) > 2 else "연관 이슈"
        lines.append(f"{top_topics[0]} 이슈가 간밤 흐름을 주도했고, 이어 {second} 이슈와 {third} 논점이 함께 부상했다.")
    else:
        lines.append("간밤 글로벌 이슈가 다면적으로 분산됐다.")
    lines.append("")

    # 2) 핵심 이슈 요약: 불릿 대신 서술형 장문 요약
    used_links = set()
    issue_no = 1

    for topic, rows in sorted_topics:
        if not rows:
            continue
        lines.append(f"## 핵심 이슈 {issue_no}) {topic}")
        lines.append(topic_intro(topic, len(rows)))

        sent = []
        for i, r in enumerate(rows, start=1):
            title = (r.get("title") or "(제목 없음)").strip()
            summary = r.get("summary") or fallback_summary(title)
            if i == 1:
                sent.append(f"먼저 {title} 보도에서는 {summary}")
            else:
                sent.append(f"또한 {title} 기사에서는 {summary}")
            used_links.add(r["link"])

        paragraph = " ".join(s.rstrip('.。…') + "." for s in sent)
        lines.append(paragraph)
        lines.append("")
        issue_no += 1

    # 3) 원문 링크: 누락 없이 전량 출력
    lines.append("원문 링크")
    lines.append("")
    for r in all_rows:
        title = (r.get("title") or "(제목 없음)").strip()
        link = r["link"]
        lines.append(f"• {title}")
        lines.append(f"[{link}]({link})")
        lines.append("")

    return "\n".join(lines), total, len(used_links)


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
            errors.append(f"{src.get('name', 'unknown')}: {e}")

    md, total, used = build_brief(collected)

    # 누락 방지 점검: 쟁점 섹션에 반영된 링크 수 == 전체 링크 수
    if total != used:
        raise RuntimeError(f"누락 감지: total={total}, used={used}")

    kst = dt.timezone(dt.timedelta(hours=9))
    out = OUT_DIR / f"24n-global-{dt.datetime.now(kst).strftime('%Y-%m-%d')}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote: {out}")
    print(f"Coverage check OK: {used}/{total}")
    if errors:
        print(f"Source errors: {len(errors)}")
        for e in errors[:5]:
            print(f"- {e}")


if __name__ == "__main__":
    main()
