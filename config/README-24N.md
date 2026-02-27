# 24N 운영 메모

## 계정 목록 관리
- 파일: `config/accounts.txt`
- 형식: 한 줄에 계정 1개 (`@` 없이)
- `#`으로 시작하는 줄은 주석 처리

## GitHub Secrets
리포지토리 설정 → Secrets and variables → Actions에 아래 등록

- `X_BEARER_TOKEN` (필수)

현재 버전은 OpenAI 키 없이 동작하며, 규칙 기반 제목·요약을 생성합니다.

## 실행 방식
- 자동: 매일 06:00 KST (`.github/workflows/daily-24n.yml`)
- 수동: Actions 탭에서 `daily-24n` → Run workflow

## 결과물
- `output/24n-YYYY-MM-DD.md`
- 제목 형식: `[24N] 당일 주제 요약`
