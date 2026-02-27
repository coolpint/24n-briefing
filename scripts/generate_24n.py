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

    # query length safety: split accounts into small chunks
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

    # attach usernames + score
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

    # dedupe by id
    uniq = {x["id"]: x for x in enriched}
    return sorted(uniq.values(), key=lambda x: x["score"], reverse=True)


def fallback_title(tweets):
    if not tweets:
        return "관심 계정 동향 요약"
    tokens = []
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "just",
        "you",
        "your",
        "about",
        "오늘",
        "관련",
        "발표",
        "시장",
    }
    for t in tweets[:20]:
        for w in re.findall(r"[A-Za-z가-힣]{2,}", t["text"].lower()):
            if w not in stop:
                tokens.append(w)
    common = [w for w, _ in Counter(tokens).most_common(3)]
    if not common:
        return "관심 계정 동향 요약"
    return " · ".join(common) + " 이슈 점검"


def call_openai_summary(tweets):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None

    sample = [
        {
            "author": t["author"],
            "text": t["text"][:300],
            "score": t["score"],
            "created_at": t["created_at"],
        }
        for t in tweets[:30]
    ]

    prompt = (
        "다음 X 포스트 묶음을 보고 한국어 아침 브리핑을 작성하라. "
        "출력은 JSON만 반환: "
        '{"title":"당일 요약 제목(20~40자)","highlights":["..."],"brief":"700~1200자"}. '
        "제목은 시리즈명 없이 순수 제목만 작성. 과장 금지, 사실 중심."
    )

    body = {
        "model": "gpt-4.1-mini",
        "input": [
            {"role": "system", "content": "You are a concise Korean financial/legal news brief writer."},
            {
                "role": "user",
                "content": prompt + "\n\n데이터:\n" + json.dumps(sample, ensure_ascii=False),
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data.get("output", [])[0].get("content", [])[0].get("text", "{}")
        return json.loads(text)
    except Exception:
        return None


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

    if not tweets:
        title = "수집 계정의 공개 포스트 없음"
        highlights = ["지난 24시간 기준 수집된 공개 포스트가 없습니다."]
        brief = "X API 검색 조건에 맞는 포스트를 찾지 못했습니다. 계정 목록과 API 권한을 점검해 주세요."
    else:
        llm = call_openai_summary(tweets)
        if llm and isinstance(llm, dict):
            title = llm.get("title") or fallback_title(tweets)
            highlights = llm.get("highlights") or ["핵심 포스트를 점검했습니다."]
            brief = llm.get("brief") or "상위 반응 포스트를 중심으로 이슈를 정리했습니다."
        else:
            title = fallback_title(tweets)
            top_authors = ", ".join([f"@{t['author']}" for t in tweets[:5]])
            highlights = [
                "상위 반응 포스트를 중심으로 이슈를 압축했습니다.",
                f"영향력 계정 중심 상위 작성자: {top_authors}",
                "세부 포스트는 본문 하단 목록을 확인해 주세요.",
            ]
            brief = (
                "지난 24시간 동안 추적 계정들의 포스트를 집계한 결과, 기술·거시경제·시장 코멘트가 혼재했습니다. "
                "특히 반응 점수가 높은 계정의 메시지는 단기 뉴스보다는 해석과 시각 제시에 집중하는 흐름이었습니다. "
                "아침 브리핑에서는 상위 포스트를 먼저 확인한 뒤, 중복 의제를 묶어 해석하는 접근이 유효합니다."
            )

    md = build_markdown(title.strip(), highlights, brief.strip(), tweets, now_kst)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"24n-{now_kst.strftime('%Y-%m-%d')}.md"
    out_path.write_text(md, encoding="utf-8")

    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
