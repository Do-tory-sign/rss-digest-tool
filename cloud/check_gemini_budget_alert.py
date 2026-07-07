"""Cloud Billing 예산 알림(Pub/Sub)을 확인해서 텔레그램으로 중계한다.

Gemini API는 Cloud Billing이 아니라 AI Studio 자체 선불 크레딧으로 관리되지만, 결제 계정에
등록해둔 "제미니 API 잔액 알림" 예산(월 ₩16,000, 50/90/94/100% 임계값)이 지출 시점마다
Pub/Sub 토픽(gemini-budget-alerts)으로 메시지를 보낸다. GitHub Actions에는 Cloud Function
같은 상시 리스너를 못 두므로, 이 스크립트를 주기적으로 실행해서 구독(gemini-budget-alerts-sub)
에 쌓인 메시지를 꺼내(pull) 텔레그램으로 보내고 ack 처리한다.

사용법:
    python cloud/check_gemini_budget_alert.py
필요 환경변수:
    GEMINI_BUDGET_RELAY_SA_JSON — 이 작업 전용 서비스 계정 키(Pub/Sub 구독자 권한만 있음)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.cloud import pubsub_v1
from google.oauth2 import service_account

from cloud.telegram_gate import _send_message

PROJECT_ID = "gen-lang-client-0635458502"
SUBSCRIPTION_ID = "gemini-budget-alerts-sub"


def main():
    sa_json = os.environ.get("GEMINI_BUDGET_RELAY_SA_JSON", "")
    if not sa_json:
        print("[check_gemini_budget_alert] GEMINI_BUDGET_RELAY_SA_JSON 환경변수 없음")
        sys.exit(1)

    from google.api_core.exceptions import DeadlineExceeded

    creds = service_account.Credentials.from_service_account_info(json.loads(sa_json))
    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    try:
        response = subscriber.pull(
            request={"subscription": subscription_path, "max_messages": 20},
            timeout=30,
        )
    except DeadlineExceeded:
        # 큐가 비어있을 때 pull이 그냥 타임아웃으로 끝나는 경우가 있음 — "알림 없음"과 동일하게 처리
        print("[check_gemini_budget_alert] pull 타임아웃 (알림 없음으로 간주)")
        return

    if not response.received_messages:
        print("[check_gemini_budget_alert] 새 알림 없음")
        return

    ack_ids = []
    for msg in response.received_messages:
        ack_ids.append(msg.ack_id)
        try:
            data = json.loads(msg.message.data.decode("utf-8"))
        except Exception as e:
            print(f"[check_gemini_budget_alert] 메시지 파싱 실패: {e}")
            continue

        cost = data.get("costAmount")
        budget = data.get("budgetAmount")
        currency = data.get("currencyCode", "KRW")
        name = data.get("budgetDisplayName", "예산")

        if cost is None or budget is None:
            continue

        remaining = budget - cost
        pct = (cost / budget * 100) if budget else 0
        print(f"[check_gemini_budget_alert] {name}: {cost}/{budget} {currency} ({pct:.1f}%)")

        text = (
            f"💰 {name}\n\n"
            f"지출: {cost:,.0f}{currency} / {budget:,.0f}{currency} ({pct:.1f}%)\n"
            f"남은 크레딧(추정): {remaining:,.0f}{currency}"
        )
        if remaining <= 2000:
            text = "⚠️ 제미니 API 크레딧이 얼마 안 남았어요!\n\n" + text
        _send_message(text)

    subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})
    print(f"[check_gemini_budget_alert] {len(ack_ids)}건 처리 완료")


if __name__ == "__main__":
    main()
