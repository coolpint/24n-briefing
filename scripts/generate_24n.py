#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_FILE = ROOT / "config" / "accounts.txt"
OUT_DIR = ROOT / "output"


def read_accounts(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line.lstrip("@").strip())
    return sorted(set(rows))


def x_get(url: str, bearer: str):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {bearer}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_recent(accounts, bearer, start_time, end_time):
    tweets = []
    users = {}

    chunk_size = 8
    for i in range(0, len(accounts), chunk_size):
        chunk = accounts[i : i + chunk_size]
        query = "(" + " OR ".join([f"from:{a}" for a in chunk]) + ") -is:retweet"

        next_token = None
        page = 0
        while page < 3:
            page += 1
            params = {
                "query": query,
                "max_results": "100",
                "start_time": start_time,
                "end_time": end_time,
                "tweet.fields": "created_at,public_metrics,lang",
                "expansions": "author_id",
                "user.fields": "username,name",
            }
            if next_token:
                params["next_token"] = next_token

            url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
            payload = x_get(url, bearer)

            for u in payload.get("includes", {}).get("users", []):
                users[u.get("id")] = u
            tweets.extend(payload.get("data", []))

            next_token = payload.get("meta", {}).get("next_token")
            if not next_token:
                break

    enriched = []
    for t in tweets:
        metrics = t.get("public_metrics", {})
        score = (
            metrics.get("like_count", 0)
            + 2 * metrics.get("retweet_count", 0)
            + 2 * metrics.get("quote_count", 0)
            + metrics.get("reply_count", 0)
        )
        author = users.get(t.get("author_id"), {})
        enriched.append(
            {
                "id": t.get("id"),
                "author": author.get("username", "unknown"),
                "text": re.sub(r"\s+", " ", t.get("text", "")).strip(),
                "created_at": t.get("created_at"),
                "metrics": metrics,
                "score": score,
            }
        )

    uniq = {x["id"]: x for x in enriched}
    return sorted(uniq.values(), key=lambda x: x["score"], reverse=True)


def detect_topics(tweets):
    topic_map = {
        "ai": ["ai", "llm", "model", "gemini", "gpt", "agent", "inference", "nvidia"],
        "markets": ["market", "stocks", "equity", "bond", "fed", "rate", "inflation", "금리", "주가"],
        "policy": ["policy", "regulation", "law", "antitrust", "정부", "규제", "법안"],
        "products": ["launch", "release", "feature", "update", "ship", "제품", "출시", "업데이트"],
        "creator": ["video", "youtube", "creator", "media", "콘텐츠", "크리에이터"],
    }

    counts = Counter()
    for t in tweets[:40]:
        low = t["text"].lower()
        for topic, kws in topic_map.items():
            if any(kw in low for kw in kws):
                counts[topic] += 1

    labels = {
        "ai": "인공지능",
        "markets": "거시·시장",
        "policy": "정책·규제",
        "products": "제품·출시",
        "creator": "콘텐츠 생태계",
    }

    ordered = [labels[k] for k, _ in counts.most_common(3)]
    return ordered if ordered else ["관심 계정 동향"]


def build_title(tweets):
    topics = detect_topics(tweets)
    if len(topics) >= 2:
        return f"{topics[0]}와 {topics[1]} 동시 부각"
    return f"{topics[0]} 핵심 동향"


def build_highlights(tweets):
    top = tweets[:8]
    if not top:
        return ["지난 24시간 기준 수집된 공개 포스트가 없습니다."]

    authors = [f"@{t['author']}" for t in top[:5]]
    avg_score = int(sum(t["score"] for t in top) / len(top)) if top else 0

    return [
        f"상위 반응 계정: {', '.join(authors)}",
        f"상위 포스트 평균 반응 점수는 {avg_score}점 수준입니다.",
        f"핵심 화제는 {', '.join(detect_topics(tweets)[:3])}로 압축됩니다.",
    ]


def build_brief(tweets):
    if not tweets:
        return "X API 검색 조건에 맞는 포스트를 찾지 못했습니다. 계정 목록과 API 권한을 점검해 주세요."

    top = tweets[:12]
    lines = []
    lines.append("지난 24시간 동안 추적 계정 포스트를 집계한 결과, 단발성 이슈보다 해석 중심 메시지의 반응이 높았습니다.")

    topic_line = ", ".join(detect_topics(tweets)[:3])
    lines.append(f"오늘 흐름은 {topic_line} 축으로 묶였습니다.")

    top3 = top[:3]
    for i, t in enumerate(top3, start=1):
        m = t["metrics"]
        lines.append(
            f"{i}) @{t['author']} 포스트는 좋아요 {m.get('like_count',0)}회, 재게시 {m.get('retweet_count',0)}회로 반응이 컸고, "
            f"핵심 메시지는 '{t['text'][:90]}'로 요약됩니다."
        )

    lines.append("아침 기사 작성 시에는 상위 포스트를 개별 보도로 나누기보다 공통된 문제의식으로 묶어 전달하는 방식이 효율적입니다.")
    lines.append("특히 정책·시장·기술이 겹치는 주제는 발언의 사실관계와 맥락을 분리해 정리하면 과장 없이 읽히는 밀도가 올라갑니다.")
    return " ".join(lines)


def build_markdown(title, highlights, brief, tweets, now_kst):
    lines = []
    lines.append(f"# [24N] {title}")
    lines.append("")
    lines.append(f"- 발행 시각: {now_kst.strftime('%Y-%m-%d %H:%M KST')}")
    lines.append("- 기준 범위: 최근 24시간")
    lines.append("")
    lines.append("## 오늘의 핵심")
    for h in highlights[:5]:
        lines.append(f"- {h}")
    lines.append("")
    lines.append("## 브리핑")
    lines.append(brief)
    lines.append("")
    lines.append("## 주요 포스트(상위 12)")
    for t in tweets[:12]:
        m = t["metrics"]
        lines.append(
            f"- @{t['author']}: {t['text'][:180]}"
            f" (좋아요 {m.get('like_count',0)}, 재게시 {m.get('retweet_count',0)}, 답글 {m.get('reply_count',0)})"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    bearer = os.getenv("X_BEARER_TOKEN")
    if not bearer:
        print("ERROR: Missing X_BEARER_TOKEN", file=sys.stderr)
        sys.exit(2)

    if not ACCOUNTS_FILE.exists():
        print(f"ERROR: Missing accounts file: {ACCOUNTS_FILE}", file=sys.stderr)
        sys.exit(2)

    accounts = read_accounts(ACCOUNTS_FILE)
    if not accounts:
        print("ERROR: accounts.txt is empty", file=sys.stderr)
        sys.exit(2)

    now_utc = dt.datetime.now(dt.timezone.utc)
    start_utc = now_utc - dt.timedelta(hours=24)
    kst = dt.timezone(dt.timedelta(hours=9))
    now_kst = now_utc.astimezone(kst)

    tweets = fetch_recent(
        accounts,
        bearer,
        start_utc.isoformat().replace("+00:00", "Z"),
        now_utc.isoformat().replace("+00:00", "Z"),
    )

    title = build_title(tweets)
    highlights = build_highlights(tweets)
    brief = build_brief(tweets)

    md = build_markdown(title.strip(), highlights, brief.strip(), tweets, now_kst)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"24n-{now_kst.strftime('%Y-%m-%d')}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
