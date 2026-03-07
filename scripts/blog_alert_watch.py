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


def clean_text(text: str) -> str:
    txt = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", txt).strip()


def fetch_article_text(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "24N-blogwatch/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

    # 1) og:description 우선
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        og = clean_text(m.group(1))
        if len(og) > 40:
            return og

    # 2) 본문 후보 태그 추출
    candidates = []
    for pat in [r"<article[^>]*>(.*?)</article>", r"<div[^>]+id=[\"\']postViewArea[\"\'][^>]*>(.*?)</div>"]:
        mm = re.search(pat, html, re.I | re.S)
        if mm:
            candidates.append(mm.group(1))

    for c in candidates:
        t = clean_text(c)
        if len(t) > 120:
            return t[:2000]

    return ""


NOISE_RE = re.compile(r"출처|unsplash|copyright|무단전재|재배포|구독|광고|댓글|좋아요|공유|관련기사", re.I)


def summarize_single_paragraph(text: str) -> str:
    txt = clean_text(text)
    if not txt:
        return "본문 요약을 추출하지 못해 링크 원문 확인이 필요하다."

    sents = re.split(r"(?<=[.!?。다])\s+", txt)
    cleaned = []
    for s in sents:
        s = s.strip(" -•\t")
        if len(s) < 25:
            continue
        if NOISE_RE.search(s):
            continue
        cleaned.append(s)

    if not cleaned:
        cleaned = [txt[:260]]

    out = " ".join(cleaned[:2]).strip()
    out = re.sub(r"\s+", " ", out)
    return out[:420]


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

        if token and chat_id:
            title = (latest.get('title') or '').strip()
            link = (latest.get('link') or '').strip()
            body_text = fetch_article_text(link)
            # RSS description을 우선 사용하고, 비어 있으면 본문 추출로 보완
            source_text = (latest.get("desc", "") or "").strip() or body_text
            summary = summarize_single_paragraph(source_text).strip()

            # fail-closed: 필수 포맷/필드가 하나라도 비면 발송하지 않음
            if (not title) or (not link) or (not summary):
                print(f"SKIP_SEND_INVALID_FORMAT: {name}")
                continue

            lines = [
                "[메르의 블로그 업데이트]",
                f"제목: {title}",
                f"요약: {summary}",
                f"링크: {link}",
            ]
            text = "\n".join(lines)
            if not (text.startswith("[메르의 블로그 업데이트]\n제목: ") and "\n요약: " in text and "\n링크: " in text):
                print(f"SKIP_SEND_TEMPLATE_MISMATCH: {name}")
                continue
            # 형식 오염 방지: 정확히 4줄 템플릿만 허용
            row_count = len(text.splitlines())
            if row_count != 4:
                print(f"SKIP_SEND_ROWCOUNT_MISMATCH: {name} ({row_count})")
                continue

            send_telegram(token, chat_id, text)

        # send 성공(또는 토큰 미설정 환경)에서만 상태 업데이트
        state[name] = {
            "last_guid": latest.get("guid"),
            "last_link": latest.get("link"),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        changed = True

    if changed:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    print("Done")


if __name__ == "__main__":
    main()
