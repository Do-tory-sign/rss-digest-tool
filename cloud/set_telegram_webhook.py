"""로컬에서 1회 실행 — 텔레그램 봇의 webhook URL을 Cloudflare Worker 주소로 등록한다.

Cloudflare Worker(cloud/telegram_webhook_worker.js)를 먼저 배포한 뒤, 그 URL을 인자로
넘겨 실행한다. 이 스크립트는 기존 파일을 건드리지 않고 .env의 TELEGRAM_BOT_TOKEN만 읽는다.

사용법:
    python cloud/set_telegram_webhook.py https://your-worker.workers.dev
    python cloud/set_telegram_webhook.py --check     # 현재 등록된 webhook 확인
    python cloud/set_telegram_webhook.py --delete    # webhook 해제(로컬 review.py로 되돌릴 때)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT / ".env", encoding="utf-8", override=True)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN이 .env에 없습니다.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    arg = sys.argv[1]
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    if arg == "--check":
        r = requests.get(f"{base}/getWebhookInfo", timeout=15)
        print(r.json())
        return

    if arg == "--delete":
        r = requests.post(f"{base}/deleteWebhook", timeout=15)
        print(r.json())
        return

    url = arg
    r = requests.post(f"{base}/setWebhook", json={
        "url": url,
        "allowed_updates": ["callback_query", "message"],
    }, timeout=15)
    print(r.json())
    if r.ok and r.json().get("ok"):
        print(f"\n✅ webhook 등록 완료: {url}")
    else:
        print("\n⚠️ 등록 실패 — 응답 확인 필요")


if __name__ == "__main__":
    main()
