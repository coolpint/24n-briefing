# Calendar setup

## Apple Calendar / Reminders

권한 필요:
- 시스템 설정 > 개인정보 보호 및 보안 > 자동화
- 터미널 또는 osascript/python 이 Calendar, Reminders 접근 허용

확인 방법:
- Calendar 앱 실행
- Reminders 앱 실행
- 권한 팝업이 뜨면 허용

## Google Workspace Calendar

현재 상태:
- OAuth 토큰은 생성 가능
- 하지만 Google Cloud 프로젝트에서 **Google Calendar API**가 비활성화돼 있으면 조회가 실패함

먼저 아래 페이지에서 API를 켜야 함:
- https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=667450462213

그다음 calendar.readonly 권한을 다시 받아야 함.

```bash
/Users/sanghoon/.openclaw/workspace/mail_setup/.venv/bin/python /Users/sanghoon/.openclaw/workspace/scripts/bootstrap_google_calendar_oauth.py
```

인증 후 테스트:

```bash
/Users/sanghoon/.openclaw/workspace/mail_setup/.venv/bin/python /Users/sanghoon/.openclaw/workspace/scripts/collect_google_calendar.py
```

## O365 Calendar

추후 필요 정보:
- tenant_id
- client_id
- account(email)
- 회사 정책상 Microsoft Graph 허용 여부
