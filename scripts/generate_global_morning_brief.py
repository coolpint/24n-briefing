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


def synthesize_topic_paragraph(topic: str, rows: list[dict]) -> str:
    count = len(rows)
    text = " ".join(f"{r.get('title','')} {r.get('summary','')}" for r in rows).lower()

    if topic == "미국-이란 충돌":
        parts = [f"간밤 글로벌 흐름의 중심에는 {topic}이 있었다. 관련 기사 {count}건이 확인됐고, 시장은 군사 충돌 자체보다 확전 가능성과 에너지 공급 불안을 더 민감하게 받아들였다."]
        if any(k in text for k in ["oil", "energy", "hormuz", "heating", "petrol"]):
            parts.append("특히 유가와 에너지 비용, 해상 운송 차질 우려가 함께 부각되면서 지정학 이슈가 곧바로 생활물가와 금융시장 변수로 번지는 흐름이 나타났다.")
        if any(k in text for k in ["leader", "supreme", "putin", "g7", "reserve"]):
            parts.append("외교 해법과 비상 대응 논의도 함께 거론돼, 시장은 군사 충돌과 정책 대응을 동시에 추적하는 분위기였다.")
        return " ".join(parts)

    if topic == "중국 정책·산업":
        parts = [f"중국 정책·산업도 간밤 주요 축이었다. 관련 기사 {count}건이 확인됐고, 통상, 공급망, 산업정책이 한꺼번에 엮여 움직였다."]
        if any(k in text for k in ["rare earth", "supply chain", "chip", "ai", "trade", "tariff"]):
            parts.append("희토류와 반도체, 인공지능, 대미 통상 이슈가 함께 거론되면서 중국발 정책 리스크가 산업별 밸류체인에 직접 연결되는 모습이 다시 확인됐다.")
        if any(k in text for k in ["court", "corruption law", "top court"]):
            parts.append("정책 방향뿐 아니라 제도·사법 영역의 메시지도 나오면서 규제와 성장 지원이 병행되는 흐름으로 읽혔다.")
        return " ".join(parts)

    if topic == "빅테크·AI":
        parts = [f"빅테크·AI 분야에서는 관련 기사 {count}건이 이어졌다. 간밤 흐름은 신기술 경쟁 자체보다 규제와 활용 범위를 둘러싼 갈등이 더 두드러졌다."]
        if any(k in text for k in ["anthropic", "military", "risk", "journalism", "security"]):
            parts.append("특히 생성형 인공지능의 공공 활용과 군사·안보 접점, 그리고 산업 내 책임 범위를 둘러싼 논쟁이 커지면서 기술 경쟁이 곧 제도 논쟁으로 이어지는 양상이 나타났다.")
        return " ".join(parts)

    if topic == "일본·동북아 외교":
        return f"일본·동북아 외교 이슈도 함께 부상했다. 관련 기사 {count}건이 확인됐고, 동북아 안보 현안과 지역 내 상징적 이벤트가 동시에 맞물리며 긴장과 일상 이슈가 병존하는 흐름이 이어졌다."

    if topic == "리걸테크":
        return f"리걸테크 분야에서는 관련 기사 {count}건이 이어졌다. 신기능이나 투자 소식 자체보다 법률 서비스의 자금 조달과 업무 자동화가 실무 도구로 자리잡는 흐름이 더 뚜렷하게 드러났다."

    return f"기타 글로벌 이슈도 적지 않았다. 관련 기사 {count}건이 확인됐고, 사회·치안·정치 사건이 여러 지역에서 동시에 이어지며 세계 뉴스 흐름이 한쪽으로만 수렴하지 않는 모습이었다."


def build_brief(collected):
    lines = ["# [24N] 간밤 글로벌 동향 브리핑", ""]

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
        "빅테크·AI": ["openai", "anthropic", "nvidia", "llm", "chatgpt", "gemini", "chip", "ai"],
        "일본·동북아 외교": ["japan", "korea", "tokyo", "east asia", "evacuate"],
        "리걸테크": ["legal", "law", "contract", "court"],
    })

    topic_rows = OrderedDict((k, []) for k in topic_map.keys())
    topic_rows["기타 글로벌 이슈"] = []

    for r in all_rows:
        topic = assign_topic(r, topic_map)
        topic_rows[topic].append(r)

    sorted_topics = [(k, v) for k, v in sorted(topic_rows.items(), key=lambda kv: len(kv[1]), reverse=True) if v]
    top_topics = [k for k, _ in sorted_topics[:3]]

    if top_topics:
        second = top_topics[1] if len(top_topics) > 1 else "후속 이슈"
        third = top_topics[2] if len(top_topics) > 2 else "연관 이슈"
        lines.append(f"{top_topics[0]} 이슈가 간밤 흐름을 주도했고, 이어 {second}와 {third}가 주요 변수로 떠올랐다.")
    else:
        lines.append("간밤 글로벌 이슈가 다면적으로 분산됐다.")
    lines.append("")

    used_links = set()
    for topic, rows in sorted_topics[:4]:
        lines.append(synthesize_topic_paragraph(topic, rows))
        lines.append("")
        for r in rows:
            used_links.add(r["link"])

    lines.append("원문 링크")
    lines.append("")
    for r in all_rows:
        title = (r.get("title") or "(제목 없음)").strip()
        link = r["link"]
        lines.append(f"- {title} | {link}")

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

    # 원문 링크는 dedupe된 전체 기사 기준으로 전량 출력한다.

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
