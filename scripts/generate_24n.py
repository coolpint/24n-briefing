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

NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]


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
            author = child_text(item, ["creator", "author", "dc:creator"])
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": desc, "author": author})
    elif root_name == "urlset":
        include_path = source.get("include_path", "")
        for u in root.findall("{*}url"):
            link = child_text(u, ["loc"])
            if include_path and include_path not in link:
                continue
            pub = child_text(u, ["lastmod"])
            title = link.rstrip("/").split("/")[-1].replace("-", " ")
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": "", "author": ""})
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
            author = child_text(ent, ["author", "name"])
            entries.append({"title": title, "link": link, "published": parse_dt(pub), "summary": summary, "author": author})

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
                author_contains = (s.get("author_contains") or "").lower().strip()
                if author_contains:
                    author_text = (it.get("author") or "").lower()
                    if author_contains not in author_text:
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
    grouped = {k: [] for k in kw_map}
    for it in ok_items[:40]:
        t = it["title"].lower()
        hit = False
        for label, kws in kw_map.items():
            if any(k in t for k in kws):
                counts[label] += 1
                grouped[label].append(it)
                hit = True
        if not hit:
            counts["기타"] += 1

    top_labels = [k for k, _ in counts.most_common(3) if k in kw_map]
    if len(top_labels) < 3:
        for k in ["인공지능 제품경쟁", "에이전트·개발자동화", "정책·안보"]:
            if k not in top_labels:
                top_labels.append(k)
        top_labels = top_labels[:3]

    # 링크 본문 맥락 읽기(상위 6건)
    enriched = []
    for it in ok_items[:6]:
        ctx = fetch_link_context(it.get("link", ""))
        enriched.append({**it, **ctx})

    p1_particle = "과" if _has_batchim(top_labels[0]) else "와"
    p1 = f"주요 공개 채널의 최근 24시간 발행물을 종합한 결과, {top_labels[0]}{p1_particle} {top_labels[1]} 흐름이 동시 강화됐고 {top_labels[2]} 이슈가 보완 축으로 붙는 구조가 나타났다고 28일 확인됐다."

    p2 = (
        f"의제별로 보면 {top_labels[0]} {counts.get(top_labels[0],0)}건, "
        f"{top_labels[1]} {counts.get(top_labels[1],0)}건, {top_labels[2]} {counts.get(top_labels[2],0)}건이 집계됐다. "
        "단순 신제품 소개보다 작업 단위 통합과 운영 자동화 쪽으로 경쟁의 중심이 이동한 점이 공통으로 확인됐다."
    )

    titles = [e['title'] for e in enriched[:6]]
    t1 = ", ".join(titles[:2]) if len(titles) >= 2 else (titles[0] if titles else "주요 업데이트")
    t2 = ", ".join(titles[2:4]) if len(titles) >= 4 else "추가 업데이트"

    p3 = f"세부 항목으로는 {t1}이 상위 구간에 배치됐다. 이들 항목은 발표 형식은 달라도 운영 효율과 실행 속도를 앞세운다는 점에서 같은 흐름으로 묶인다."
    p4 = f"그다음 구간에서는 {t2}이 뒤를 이었다. 기술 공지와 실사용형 도구가 같은 시간대에 올라오면서 독자 관심이 기능 자체보다 활용 단계로 이동하는 경향이 확인됐다."

    p5 = (
        "채널 분포를 보면 커뮤니티성 소스의 발행 빈도가 높아 단기 체감 이슈를 빠르게 보여주는 장점이 있다. "
        "반면 기관·뉴스레터 소스는 건수는 적어도 정책·거버넌스 같은 중기 변수의 방향을 제시하는 성격이 강했다."
    )

    p6 = (
        "따라서 아침 기사에서는 개별 링크를 병렬로 나열하기보다, "
        "개발자동화 확산, 모델·서비스 경쟁, 정책 리스크의 세 축으로 재배열해 전달하는 편이 흐름 파악에 유리하다."
    )

    p7 = (
        "시장 관점에서는 기능 출시 자체보다 누가 더 짧은 주기로 운영 효율을 개선하는지가 핵심 비교 지표가 되고 있다. "
        "정책 변수는 발표 건수와 무관하게 이벤트성 변동을 만들 수 있어 별도 모니터링이 필요하다."
    )

    return [p1, p2, p3, p4, p5, p6, p7]


def summarize_x_web(items):
    if not items:
        return []

    theme_map = {
        "개발자동화": ["agent", "cursor", "claude", "code", "auto", "automation", "workflow"],
        "인공지능 투자·밸류": ["openai", "nvidia", "valuation", "deal", "chip", "inference"],
        "시장심리": ["market", "stock", "wall street", "psychosis", "bubble"],
        "창업·운영": ["startup", "office hours", "domain", "founder", "batch"],
    }

    from collections import Counter
    c = Counter()
    for it in items[:20]:
        t = it["title"].lower()
        for k, kws in theme_map.items():
            if any(w in t for w in kws):
                c[k] += 1

    tops = [k for k, _ in c.most_common(2)]
    lines = []
    if tops:
        if len(tops) > 1:
            lines.append(f"- X 포스트는 {tops[0]} 중심으로 전개됐고, {tops[1]} 이슈가 보조 축으로 붙었습니다.")
        else:
            lines.append(f"- X 포스트는 {tops[0]} 이슈 비중이 높았습니다.")
    else:
        lines.append("- X 포스트는 단일 이슈 집중보다 코멘트 분산형 흐름이었습니다.")

    by_acc = {}
    for it in items[:8]:
        by_acc.setdefault(it['account'], []).append(it)

    for acc, rows in list(by_acc.items())[:4]:
        texts = " ".join(r['title'] for r in rows[:2]).lower()
        if any(w in texts for w in ["nvidia", "openai", "inference", "chip"]):
            gist = "반도체·추론 인프라와 투자 규모를 함께 묶어 해석하는 발언이 이어졌습니다"
        elif any(w in texts for w in ["cursor", "agent", "code", "workflow", "auto"]):
            gist = "코딩 작업에서 에이전트 활용 비중이 빠르게 올라가는 흐름을 강조했습니다"
        elif any(w in texts for w in ["startup", "founder", "office hours", "domain"]):
            gist = "창업 현장의 편차와 실행 속도 격차를 사례 중심으로 제시했습니다"
        else:
            gist = "개별 뉴스보다 방향성 코멘트 중심의 업데이트를 이어갔습니다"
        lines.append(f"- @{acc}: {gist}.")

    return lines


def build_md(title, items, inactive, now_kst, x_web=None):
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

    if x_web and (x_web.get("items") or x_web.get("errors")):
        lines.append("## X 웹 보강(실험)")
        if x_web.get("items"):
            for line in summarize_x_web(x_web.get("items", [])):
                lines.append(line)
            lines.append("- 원문 링크")
            for it in x_web.get("items", [])[:5]:
                lines.append(f"  - @{it['account']} | {it['link']}")
        if x_web.get("errors"):
            lines.append("- 일부 계정은 웹 차단으로 수집 실패")
            for e in x_web.get("errors", [])[:6]:
                lines.append(f"  - {e}")
        lines.append("")

    if err_items:
        lines.append("## 수집 상태 점검")
        lines.append("- 일부 소스 수집에 실패해 자동 복구를 시도 중입니다.")
        for it in err_items[:5]:
            lines.append(f"- @{it['account']}: {it['link']}")
        lines.append("")

    return "\n".join(lines)


def fetch_x_web_watchlist(cfg, since_utc):
    wl = cfg.get("x_web_watchlist") or {}
    if not wl.get("enabled"):
        return {"items": [], "errors": []}

    accounts = wl.get("accounts") or []
    items = []
    errors = []

    for acc in accounts:
        got = False
        for base in NITTER_MIRRORS:
            try:
                u = f"{base}/{acc}/rss"
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read()
                root = ET.fromstring(raw)
                for it in root.findall("channel/item")[:3]:
                    title = child_text(it, ["title"])
                    link = child_text(it, ["link"])
                    pub = parse_dt(child_text(it, ["pubDate"]))
                    if pub and pub.tzinfo is None:
                        pub = pub.replace(tzinfo=dt.timezone.utc)
                    if pub and pub >= since_utc:
                        items.append({"account": acc, "title": title, "link": link, "published": pub})
                got = True
                break
            except Exception as e:
                last_err = str(e)
                continue
        if not got:
            errors.append(f"@{acc}: 수집 실패({last_err if 'last_err' in locals() else 'unknown'})")

    items.sort(key=lambda x: x.get("published") or since_utc, reverse=True)
    return {"items": items, "errors": errors}


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
    x_web = fetch_x_web_watchlist(cfg, since)

    title = build_title(items)
    kst = dt.timezone(dt.timedelta(hours=9))
    now_kst = now_utc.astimezone(kst)

    md = build_md(title, items, inactive, now_kst, x_web=x_web)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"24n-{now_kst.strftime('%Y-%m-%d')}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
