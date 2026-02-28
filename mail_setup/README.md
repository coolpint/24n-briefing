# Mail OAuth Quick Setup

이 폴더는 Gmail OAuth 토큰을 계정별로 발급/저장하는 자동화 스크립트입니다.

## 준비물 (1회)
- Google Cloud에서 만든 OAuth Desktop Client JSON
- 파일 경로 예: `mail_setup/google_client_secret.json`

## 실행
```bash
cd /Users/sanghoon/.openclaw/workspace
python3 mail_setup/bootstrap_mail_oauth.py \
  --client-secret mail_setup/google_client_secret.json \
  --account dlfjs2@snu.ac.kr \
  --account sanghoon.kim@silverlining.mobi
```

성공하면 아래 파일이 생성됩니다.
- `mail_setup/tokens/dlfjs2_snu_ac_kr.json`
- `mail_setup/tokens/sanghoon_kim_silverlining_mobi.json`

## 참고
- 첫 승인만 브라우저 로그인/동의가 필요합니다.
- 이후에는 토큰 갱신으로 자동 유지됩니다.
