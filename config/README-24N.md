# 24N 운영 메모 (X 비의존 버전)

## 소스 목록 관리
- 파일: `config/sources.json`
- 파일 상단의 `_comment`, `_source_template`를 참고해 소스를 추가
- `sources[].active=true` 인 항목만 수집
- `sources[].max_items`로 소스별 최대 수집 건수 지정 (현재 10)
- `sources[].rank_by`로 정렬 기준 지정 (`recent`, `hada_points`)
- `sources[].author_contains`를 쓰면 통합 RSS에서 특정 필자만 필터링 가능
- 계정 추가/삭제는 JSON에서 즉시 반영
- `x_web_watchlist`는 웹 크롤링 보강용 예약 영역(기본 비활성)

## 실행 방식
- 자동: 매일 06:00 KST (`.github/workflows/daily-24n.yml`)
- 수동: Actions 탭에서 `daily-24n` → Run workflow

## 결과물
- `output/24n-YYYY-MM-DD.md`
- 제목 형식: `[24N] 당일 주제 요약`

## 텔레그램 자동 발송(선택)
- Secrets 추가 시 생성 직후 텔레그램으로 본문 발송
- 필요한 Secrets
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

## 참고
- 현재 파이프라인은 X API 키가 필요 없습니다.
- 대신 RSS/Atom/공식 채널이 없는 계정은 `inactive_accounts`에 남겨두고, 대체 소스가 생기면 `sources`에 추가하세요.
