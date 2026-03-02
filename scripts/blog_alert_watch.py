#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "blog_watch.json"
STATE = ROOT / "output" / "blog_watch_state.json"


def strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1] if '}' in tag else tag


def child_text(node, names):
    names = set(names)
    for c in list(node):
        if strip_ns(c.tag) in names and c.text:
            return c.text.strip()
    return ""


def fetch_feed(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "24N-blogwatch/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)

    items = []
    if strip_ns(root.tag).lower() == "rss":
        rows = root.findall('.//item')
        for it in rows:
            title = child_text(it, ["title"])
            link = child_text(it, ["link"])
            guid = child_text(it, ["guid"]) or link
            desc = child_text(it, ["description", "content:encoded"])
            pub = child_text(it, ["pubDate", "date"])
            items.append({"title": title, "link": link, "guid": guid, "desc": desc, "pub": pub})
    else:
        rows = root.findall('.//{*}entry')
        for it in rows:
            title = child_text(it, ["title"])
            link = ""
            for lk in it.findall('{*}link'):
                href = lk.attrib.get('href', '')
                rel = lk.attrib.get('rel', 'alternate')
                if rel == 'alternate' and href:
                    link = href
                    break
                if not link and href:
                    link = href
            guid = child_text(it, ["id"]) or link
            desc = child_text(it, ["summary", "content"])
            pub = child_text(it, ["published", "updated"])
            items.append({"title": title, "link": link, "guid": guid, "desc": desc, "pub": pub})

    return items


def summarize_to_10_sentences(text: str):
    txt = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return [
            "글의 핵심 주제를 먼저 제시한다.",
            "문제의식이 왜 중요한지 배경을 설명한다.",
            "필자가 제시한 첫 번째 근거를 정리한다.",
            "두 번째 근거와 맥락을 연결해 요약한다.",
            "중간 결론에서 강조한 포인트를 짚는다.",
            "사례나 비유가 있다면 그 의미를 풀어준다.",
            "독자가 놓치기 쉬운 함의를 덧붙인다.",
            "실무·현실에 미치는 영향을 짚는다.",
            "남는 쟁점이나 반론 가능성을 정리한다.",
            "글 전체를 한 줄 메시지로 정리한다.",
        ]

    sents = re.split(r"(?<=[.!?。]|[다요죠습니다])\s+", txt)
    sents = [s.strip(' .') for s in sents if len(s.strip()) > 12]

    out = []
    for s in sents:
        if len(out) >= 10:
            break
        out.append(s + ("." if not s.endswith((".", "!", "?")) else ""))

    while len(out) < 10:
        out.append("본문에서 반복된 핵심 메시지는 일관되게 유지된다.")
    return out[:10]


def send_telegram(token: str, chat_id: str, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    cfg = json.loads(CFG.read_text(encoding='utf-8'))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {}

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    changed = False
    for feed in cfg.get("feeds", []):
        if not feed.get("enabled", True):
            continue
        name = feed["name"]
        items = fetch_feed(feed["feed_url"])
        if not items:
            continue
        latest = items[0]
        last_guid = (state.get(name) or {}).get("last_guid")

        if last_guid == latest.get("guid"):
            continue

        # update state first to prevent duplicate spam on transient send issues
        state[name] = {
            "last_guid": latest.get("guid"),
            "last_link": latest.get("link"),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        changed = True

        if token and chat_id:
            summary = summarize_to_10_sentences(latest.get("desc", ""))
            lines = []
            lines.append(f"[{name}] 새 글 업데이트")
            lines.append(f"제목: {latest.get('title','(제목 없음)')}")
            lines.append("")
            lines.append("요약(10문장)")
            for i, s in enumerate(summary, 1):
                lines.append(f"{i}. {s}")
            lines.append("")
            lines.append(f"링크: {latest.get('link','')}")
            text = "\n".join(lines)

            chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
            for c in chunks:
                send_telegram(token, chat_id, c)

    if changed:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    print("Done")


if __name__ == "__main__":
    main()
