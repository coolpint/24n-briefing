# 24N 운영 메모 (X 비의존 버전)

## 소스 목록 관리
- 파일: `config/sources.json`
- `sources[].active=true` 인 항목만 수집
- 계정 추가/삭제는 JSON에서 즉시 반영

## 실행 방식
- 자동: 매일 06:00 KST (`.github/workflows/daily-24n.yml`)
- 수동: Actions 탭에서 `daily-24n` → Run workflow

## 결과물
- `output/24n-YYYY-MM-DD.md`
- 제목 형식: `[24N] 당일 주제 요약`

## 참고
- 현재 파이프라인은 X API 키가 필요 없습니다.
- 대신 RSS/Atom/공식 채널이 없는 계정은 `inactive_accounts`에 남겨두고, 대체 소스가 생기면 `sources`에 추가하세요.
