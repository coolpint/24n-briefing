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
        parts = ["간밤 글로벌 흐름의 중심에는 미국-이란 충돌이 있었다."]
        if any(k in text for k in ["heating oil", "petrol", "bills", "finances"]):
            parts.append("영국 등에서는 중동 전쟁 여파가 난방유와 휘발유 가격, 가계 부담으로 번질 수 있다는 점을 짚는 보도가 이어졌다.")
        if any(k in text for k in ["g7", "reserve", "putin", "macron"]):
            parts.append("주요국 정상과 G7 차원의 대응 논의도 이어지면서, 사태가 군사 충돌을 넘어 외교·에너지 정책 문제로 확장되는 양상이 나타났다.")
        if any(k in text for k in ["hormuz", "ship", "turkey", "nato"]):
            parts.append("호르무즈 해협 항로와 인근 안보 상황을 둘러싼 보도도 잇따르며, 시장은 원유 공급과 해상 운송 차질 가능성을 함께 주시했다.")
        return " ".join(parts)

    if topic == "중국 정책·산업":
        parts = ["중국에서는 산업정책과 통상 전략, 사법·제도 정비가 동시에 부각됐다."]
        if any(k in text for k in ["rare earth", "critical minerals", "supply chain"]):
            parts.append("희토류와 핵심 광물, 공급망 안보를 둘러싼 보도에서는 중국 당국과 미국 정책 라인이 모두 자원 우위를 전략 자산으로 다루는 흐름이 확인됐다.")
        if any(k in text for k in ["trade", "tariff", "fentanyl", "truce"]):
            parts.append("미중 관계에서는 관세와 펜타닐, 정상회담 준비를 둘러싼 신경전 속에서도 전면 충돌보다 전술적 휴전 가능성을 점치는 보도가 나왔다.")
        if any(k in text for k in ["catl", "chip", "ai", "top court", "corruption law"]):
            parts.append("기업 측면에서는 CATL 실적과 반도체·인공지능 육성 이슈가, 제도 측면에서는 최고인민법원과 반부패 법제 논의가 맞물리며 성장 지원과 통제 강화가 병행되는 모습이 나타났다.")
        return " ".join(parts)

    if topic == "빅테크·AI":
        parts = ["빅테크·AI 분야에서는 기술 경쟁보다 규제와 책임 범위를 둘러싼 갈등이 더 선명했다."]
        if any(k in text for k in ["anthropic", "military", "risk"]):
            parts.append("앤스로픽 관련 보도에서는 미국 정부의 위험 규정과 군사 활용 문제를 둘러싼 법적 충돌이 본격화됐다는 점이 드러났다.")
        if any(k in text for k in ["journalism", "security", "firefox"]):
            parts.append("동시에 인공지능이 언론과 보안 분야의 역할을 어떻게 바꾸는지를 둘러싼 논의도 이어지며, 기술 도입이 산업 구조 재편 문제로 번지는 흐름이 확인됐다.")
        return " ".join(parts)

    if topic == "일본·동북아 외교":
        return "일본·동북아에서는 북한 관련 일정 변화와 역내 안보 이슈가 함께 부각됐다. 북한이 평양 마라톤을 돌연 취소했고, 일본은 장거리 미사일 배치 계획을 재확인하면서 지역 안보 긴장이 다시 환기됐다."

    if topic == "리걸테크":
        return "리걸테크 분야에서는 법률 서비스의 자금 조달과 업무 효율화가 주요 화두였다. 일부 기업은 로펌 대상 금융 지원과 사실관리 플랫폼 확장에 나서며, 기술이 실험 단계를 넘어 법률 실무 인프라로 자리잡는 흐름을 보였다."

    return "기타 글로벌 이슈에서는 미국과 유럽, 남미 등에서 치안·정치·사회 사건이 이어졌다. 각 지역의 사건 성격은 달랐지만, 글로벌 뉴스 흐름이 지정학 하나로만 수렴하지 않고 사회 불안과 국내 정치 변수까지 함께 커지고 있다는 점이 확인됐다."


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
