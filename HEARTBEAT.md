# HEARTBEAT.md

- 매 30분 heartbeat 때 먼저 아래 명령으로 '읽지 않은 메일'만 점검.
- 긴급 메일이 있으면 요약을 사용자에게 바로 알림.
- 긴급 메일이 없으면 아래 퀵 리마인더 상태도 확인.
- 퀵 리마인더가 활성화돼 있고 마지막 알림 후 1시간이 지났으면 사용자에게 리마인드.
- 둘 다 해당 없으면 HEARTBEAT_OK.

메일 명령:
`/Users/sanghoon/.openclaw/workspace/mail_setup/.venv/bin/python /Users/sanghoon/.openclaw/workspace/mail_setup/check_unread_urgent.py`

퀵 리마인더 명령:
`python3 /Users/sanghoon/.openclaw/workspace/scripts/check_quick_reminder.py`

긴급 기준 키워드:
긴급, urgent, asap, 결제, 미납, 계약, 소송, 마감, 당일, 즉시, payment, invoice
