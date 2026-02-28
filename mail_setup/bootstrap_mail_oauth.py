#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def safe_name(email: str) -> str:
    return email.replace('@', '_').replace('.', '_')


def ensure_deps():
    try:
        import google_auth_oauthlib  # noqa: F401
        import google.auth.transport.requests  # noqa: F401
    except Exception:
        os.system("python3 -m pip install --user google-auth-oauthlib google-auth-httplib2 google-api-python-client")


def run_flow(client_secret: Path, account: str, out_dir: Path):
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    print(f"\n[{account}] 브라우저에서 해당 계정으로 로그인/동의해 주세요.")
    creds = flow.run_local_server(port=0, prompt='consent', authorization_prompt_message='OAuth 승인 페이지를 엽니다.')

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{safe_name(account)}.json"
    out_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"[{account}] 토큰 저장 완료: {out_file}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client-secret", required=True)
    p.add_argument("--account", action="append", required=True)
    p.add_argument("--out-dir", default="mail_setup/tokens")
    args = p.parse_args()

    ensure_deps()

    client_secret = Path(args.client_secret).expanduser().resolve()
    if not client_secret.exists():
        raise SystemExit(f"client secret not found: {client_secret}")

    out_dir = Path(args.out_dir).expanduser().resolve()

    for acct in args.account:
        run_flow(client_secret, acct.strip(), out_dir)

    print("\n완료: 계정별 OAuth 토큰 발급이 끝났습니다.")


if __name__ == "__main__":
    main()
