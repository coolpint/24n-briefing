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

## [24N] 간밤 글로벌 동향 브리핑 형식 고정
- 생성 스크립트: `scripts/generate_global_morning_brief.py`
- 아래 순서를 고정 포맷으로 사용
  1) `# [24N] 간밤 글로벌 동향 브리핑`
  2) 1문장 리드
  3) `쟁점과 현안`
  4) `• 토픽명` + 설명 문단 + **기사별 핵심내용 bullet(직접 읽은 요지 기반)**
  5) `원문 링크`
  6) `• 기사 제목` + `[URL](URL)` 반복
- `## 더 깊게 읽기` 섹션은 사용하지 않음.
- 기계식 동일 문장 반복 금지(토픽/기사별로 내용 차이 명확히 기재).
- **누락 금지 원칙:** 수집된 기사(중복 링크 제거 후) 전량을 `쟁점과 현안`과 `원문 링크`에 모두 반영.
- 생성 스크립트는 `Coverage check OK: used/total` 점검을 수행하며, 불일치 시 실패 처리.
- 링크는 중복 없이 출력.
- 텔레그램 발송 스크립트(`scripts/send_global_telegram.py`)는 KST 당일 파일만 발송하며, 포맷 검증 실패 시 발송을 중단한다(구형 템플릿/전일 파일 재발송 방지).

## 텔레그램 자동 발송(선택)
- Secrets 추가 시 생성 직후 텔레그램으로 본문 발송
- 필요한 Secrets
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`

## 참고
- 현재 파이프라인은 X API 키가 필요 없습니다.
- 대신 RSS/Atom/공식 채널이 없는 계정은 `inactive_accounts`에 남겨두고, 대체 소스가 생기면 `sources`에 추가하세요.
