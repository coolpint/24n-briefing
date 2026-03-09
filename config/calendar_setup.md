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

현재 토큰은 Gmail용 scope만 있어 캘린더 조회에 실패함.
아래 명령으로 calendar.readonly 권한을 다시 받아야 함.

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
