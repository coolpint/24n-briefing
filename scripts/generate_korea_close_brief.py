#!/usr/bin/env python3
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "korea_market_sources.json"
OUT_DIR = ROOT / "output"


def kst_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def fetch_xml(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "24N-korea-close/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def parse_rss_titles(url: str, since: dt.datetime, limit=6):
    try:
        raw = fetch_xml(url)
        root = ET.fromstring(raw)
        out = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            pdt = None
            if pub:
                try:
                    pdt = parsedate_to_datetime(pub)
                except Exception:
                    pdt = None
            if pdt is None or pdt >= since:
                if title and link:
                    out.append((title, link))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def main():
    from pykrx import stock  # installed in workflow
    cfg = json.loads(CFG.read_text(encoding='utf-8'))
    now = kst_now()
    today = now.strftime('%Y%m%d')

    try:
        # 시장 개장 여부: pykrx의 영업일 API가 빈 응답으로 예외를 던질 수 있어,
        # 직접 종목 시세 존재 + 요일 기반으로 판정한다.
        chk = stock.get_market_ohlcv_by_date(today, today, '005930')
        is_weekday = now.weekday() < 5  # Mon=0 ... Sun=6
    except Exception as e:
        out = OUT_DIR / f"24n-korea-close-{now.strftime('%Y-%m-%d')}.md"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# [24N] 한국 증시 마감 브리핑\n\n"
            "- KRX 데이터 조회 중 일시 오류가 발생해 브리핑 생성을 보류합니다.\n"
            "- 잠시 후 재실행 시 정상화될 수 있습니다.\n"
            f"- 오류: {e}\n",
            encoding='utf-8'
        )
        print(f"Wrote (fetch error notice): {out}")
        return
    if chk is None or chk.empty:
        # 평일이면 데이터 지연 가능성이 크고, 주말이면 휴장으로 본다.
        if not is_weekday:
            out = OUT_DIR / f"24n-korea-close-{now.strftime('%Y-%m-%d')}.md"
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out.write_text("# [24N] 한국 증시 마감 브리핑\n\n- 오늘은 한국 증시 휴장일로 확인됩니다.\n", encoding='utf-8')
            print(f"Wrote: {out}")
            return
        out = OUT_DIR / f"24n-korea-close-{now.strftime('%Y-%m-%d')}.md"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# [24N] 한국 증시 마감 브리핑\n\n"
            "- 오늘은 개장일로 보이지만, 종가 데이터 반영이 지연돼 브리핑 생성을 잠시 보류합니다.\n"
            "- 10분 후 재실행하거나 수동 실행 시 정상 수집될 가능성이 큽니다.\n",
            encoding='utf-8'
        )
        print(f"Wrote (delayed data notice): {out}")
        return

    try:
        kospi = stock.get_index_ohlcv_by_date(today, today, '1001')
        kosdaq = stock.get_index_ohlcv_by_date(today, today, '2001')
    except Exception as e:
        out = OUT_DIR / f"24n-korea-close-{now.strftime('%Y-%m-%d')}.md"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# [24N] 한국 증시 마감 브리핑\n\n"
            "- 지수 데이터 조회 중 일시 오류가 발생해 브리핑 생성을 보류합니다.\n"
            f"- 오류: {e}\n",
            encoding='utf-8'
        )
        print(f"Wrote (index fetch error notice): {out}")
        return

    def idx_line(name, df):
        if df is None or df.empty:
            return f"- {name}: 데이터 없음"
        row = df.iloc[-1]
        close_ = float(row['종가'])
        chg = float(row['등락률'])
        return f"- {name}: {close_:,.2f} ({chg:+.2f}%)"

    # 당일 등락 상하위
    pc = stock.get_market_price_change_by_ticker(today, today)
    top_up = pc.sort_values('등락률', ascending=False).head(5)
    top_dn = pc.sort_values('등락률', ascending=True).head(5)

    # 주요 종목
    tracked_lines = []
    for s in cfg.get('tracked_stocks', []):
        t = s['ticker']
        nm = s['name']
        df = stock.get_market_ohlcv_by_date(today, today, t)
        if df is None or df.empty:
            tracked_lines.append(f"- {nm}({t}): 데이터 없음")
            continue
        r = df.iloc[-1]
        prev = float(r['시가']) if float(r['시가']) else float(r['종가'])
        close_ = float(r['종가'])
        pct = (close_ - prev) / prev * 100 if prev else 0.0
        tracked_lines.append(f"- {nm}({t}): {int(close_):,}원 ({pct:+.2f}%)")

    # 전문가/해석성 기사 헤드라인(최근 24h)
    since = now - dt.timedelta(hours=24)
    comm = []
    for src in cfg.get('commentary_sources', []):
        rows = parse_rss_titles(src['url'], since, limit=3)
        for t, l in rows:
            if re.search(r"시황|마감|전망|증권|리포트|분석|전문가|코스피|코스닥", t):
                comm.append((src['name'], t, l))

    lines = []
    lines.append('# [24N] 한국 증시 마감 브리핑')
    lines.append('')
    lines.append('## 오늘 시황')
    lines.append(idx_line('코스피', kospi))
    lines.append(idx_line('코스닥', kosdaq))
    lines.append('')

    lines.append('## 상승 상위 5')
    for tk, r in top_up.iterrows():
        lines.append(f"- {r['종목명']}({tk}): {r['등락률']:+.2f}%")
    lines.append('')

    lines.append('## 하락 상위 5')
    for tk, r in top_dn.iterrows():
        lines.append(f"- {r['종목명']}({tk}): {r['등락률']:+.2f}%")
    lines.append('')

    lines.append('## 주요 종목')
    lines.extend(tracked_lines)
    lines.append('')

    lines.append('## 전문가·해석 포인트')
    if comm:
        for src, t, l in comm[:8]:
            lines.append(f"- [{src}] {t} | {l}")
    else:
        lines.append('- 공개 피드 기준 해석성 기사 수집이 제한돼 후속 보강이 필요합니다.')
    lines.append('')

    lines.append('## 종합')
    lines.append('- 지수 흐름과 종목별 수급이 엇갈릴 수 있어, 지수와 대형주·테마주의 분리 해석이 필요합니다.')
    lines.append('- 기사형 해석은 매크로 변수(금리·환율)와 반도체·플랫폼 수급 축을 함께 보는 방식이 유효합니다.')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"24n-korea-close-{now.strftime('%Y-%m-%d')}.md"
    out.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Wrote: {out}")


if __name__ == '__main__':
    main()
