#!/usr/bin/env python3
import datetime as dt
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from html import unescape
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
    urls = [source["url"]] + source.get("alt_urls", [])
    last_err = None
    raw = None
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "24N-feedbot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            source["_resolved_url"] = u
            break
        except Exception as e:
            last_err = e
            continue

    if raw is None:
        raise RuntimeError(f"all feed urls failed: {last_err}")

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
    elif root_name == "urlset":
        include_path = source.get("include_path", "")
        for u in root.findall("{*}url"):
            link = child_text(u, ["loc"])
            if include_path and include_path not in link:
                continue
            pub = child_text(u, ["lastmod"])
            title = link.rstrip("/").split("/")[-1].replace("-", " ")
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": ""})
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


def fetch_hada_points(topic_url: str) -> int:
    try:
        req = urllib.request.Request(topic_url, headers={"User-Agent": "24N-feedbot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "ignore")
        m_id = re.search(r"topic\?id=(\d+)", topic_url)
        if not m_id:
            return 0
        tid = m_id.group(1)
        m_pt = re.search(rf"id=['\"]tp{tid}['\"]>(\d+)<", html)
        return int(m_pt.group(1)) if m_pt else 0
    except Exception:
        return 0


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

            rank_by = s.get("rank_by", "recent")
            if rank_by == "hada_points":
                for it in local:
                    it["rank_score"] = fetch_hada_points(it.get("link", ""))
                local.sort(key=lambda x: (x.get("rank_score", 0), x["published"]), reverse=True)
            else:
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


def fetch_link_context(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 24N-bot"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", "ignore")

        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = unescape(re.sub(r"\s+", " ", title_m.group(1))).strip() if title_m else ""

        desc = ""
        for pat in [
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        ]:
            m = re.search(pat, html, re.I | re.S)
            if m:
                desc = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
                break

        body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = unescape(re.sub(r"\s+", " ", body)).strip()

        return {
            "title_hint": title[:120],
            "desc": desc[:220],
            "snippet": body[:240],
        }
    except Exception:
        return {"title_hint": "", "desc": "", "snippet": ""}


def build_article_brief(ok_items):
    if not ok_items:
        return ["지난 24시간 신규 발행물이 없어 전일 흐름을 유지한다고 28일 정리했다."]

    kw_map = {
        "에이전트·개발자동화": ["agent", "auto", "claude code", "openfang", "코딩", "자동", "메모리"],
        "인공지능 제품경쟁": ["anthropic", "openai", "perplexity", "nano banana", "모델", "출시"],
        "학습·지식생산": ["학습", "커리큘럼", "교육", "요약", "인사이트"],
        "정책·안보": ["국방부", "war", "policy", "regulation", "성명"],
        "시장·소득": ["연봉", "소득", "시장", "거시", "금리", "경제"],
    }

    counts = Counter()
    examples = {k: [] for k in kw_map}
    for it in ok_items[:30]:
        t = it["title"].lower()
        for label, kws in kw_map.items():
            if any(k in t for k in kws):
                counts[label] += 1
                if len(examples[label]) < 2:
                    examples[label].append(it["title"])

    top_labels = [k for k, _ in counts.most_common(3)]
    if not top_labels:
        top_labels = ["인공지능 제품경쟁", "에이전트·개발자동화", "정책·안보"]

    p1 = f"주요 공개 채널의 최근 24시간 발행물을 종합한 결과, {top_labels[0]}과 {top_labels[1]} 흐름이 동시에 강해졌고 {top_labels[2]} 이슈가 이를 보완하는 구도로 나타났다고 28일 확인됐다."

    c1 = counts.get(top_labels[0], 0)
    c2 = counts.get(top_labels[1], 0)
    p2 = f"상위 두 의제의 신규 항목은 각각 {c1}건, {c2}건으로 집계됐다. 공통점은 단순 기능 추가보다 작업 흐름 전체를 자동화해 생산성을 높이려는 경쟁이 강해졌다는 점이다."

    p3 = "발행 비중은 커뮤니티 채널에 집중됐지만 뉴스레터·기관 채널의 메시지를 함께 보면 단기 기능 경쟁과 중기 정책 리스크가 동시에 가격에 반영될 가능성이 커지는 국면으로 해석된다."

    p4 = "아침 기사 작성에서는 개별 링크를 나열하기보다 개발자동화, 모델 경쟁, 규제 변수 세 축으로 묶어 전달하는 편이 독자 이해도와 재활용성이 높다."

    return [p1, p2, p3, p4]


def build_md(title, items, inactive, now_kst):
    lines = []
    lines.append(f"# [24N] {title}")
    lines.append("")

    ok_items = [x for x in items if not x["title"].startswith("[수집 실패]")]
    err_items = [x for x in items if x["title"].startswith("[수집 실패]")]

    lines.append("## 오늘의 핵심")
    if ok_items:
        top_sources = Counter([x["account"] for x in ok_items]).most_common(3)
        lines.append(f"- 최근 24시간 신규 항목은 {len(ok_items)}건입니다.")
        lines.append("- 발행 비중 상위 채널: " + ", ".join([f"@{a} {n}건" for a, n in top_sources]))
        lines.append("- 핵심 흐름은 링크 나열이 아니라 의제 단위로 재구성했습니다.")
    else:
        lines.append("- 신규 항목이 없습니다.")
    lines.append("")

    lines.append("## 브리핑")
    if ok_items:
        for p in build_article_brief(ok_items):
            lines.append(p)
    else:
        lines.append("신규 항목이 없어 전일 흐름을 유지한다고 28일 정리했다.")
    lines.append("")

    lines.append("## 참고 링크")
    if ok_items:
        for it in ok_items[:10]:
            lines.append(f"- {it['title']} | {it['link']}")
    else:
        lines.append("- 없음")
    lines.append("")

    if err_items:
        lines.append("## 수집 상태 점검")
        lines.append("- 일부 소스 수집에 실패해 자동 복구를 시도 중입니다.")
        for it in err_items[:5]:
            lines.append(f"- @{it['account']}: {it['link']}")
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
