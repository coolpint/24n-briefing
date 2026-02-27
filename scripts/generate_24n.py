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
    top = ok_items[:6]
    if not top:
        return ["신규 항목이 없어 전일 흐름을 유지한다고 28일 정리했다."]

    enriched = []
    for it in top:
        ctx = fetch_link_context(it.get("link", ""))
        enriched.append({**it, **ctx})

    topic_counter = Counter()
    for it in ok_items[:20]:
        for t in it.get("tags", []):
            topic_counter[t] += 1

    mapping = {
        "ai": "인공지능",
        "tech": "기술",
        "startup": "창업",
        "policy": "정책",
        "economy": "경제",
        "macro": "거시",
        "creator": "콘텐츠",
        "korea": "국내",
        "semiconductor": "반도체",
        "labor": "노동",
    }
    tops = [mapping.get(k, k) for k, _ in topic_counter.most_common(3) if k != "error"]
    topic_text = "·".join(tops[:3]) if tops else "기술"

    p1 = f"주요 공개 채널의 최근 24시간 발행물을 점검한 결과 {topic_text} 축 이슈가 동시에 부각됐다고 28일 확인됐다."

    lead_items = []
    for it in enriched[:3]:
        core = it.get("desc") or it.get("title_hint") or it.get("title")
        core = re.sub(r"\s+", " ", core).strip()
        if len(core) > 90:
            core = core[:90] + "..."
        lead_items.append(f"{it['source']}은 {core}")
    p2 = "; ".join(lead_items) + " 등을 내놨다."

    p3 = "발행량은 특정 커뮤니티 소스에 집중됐지만, 기관·뉴스레터 채널에서도 정책·산업 관련 신호가 이어졌다. 단순 링크 나열보다 공통 의제 단위로 묶어 해석하는 편이 아침 기사 작성에 유리하다."

    p4 = "특히 인공지능 도구 공개, 개발 생산성, 규제·거버넌스 이슈가 함께 나타나는 흐름은 시장 반응과 정책 변수의 결합 가능성을 키우는 국면으로 읽힌다."

    return [p1, p2, p3, p4]


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
        for p in build_article_brief(ok_items):
            lines.append(p)
    else:
        lines.append("신규 항목이 없어 전일 흐름을 유지한다고 28일 정리했다.")
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
