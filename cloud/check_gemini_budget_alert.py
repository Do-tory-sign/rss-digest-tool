"""Cloud Billing 예산 알림(Pub/Sub)을 확인해서 텔레그램으로 중계한다.

결제 계정에 등록해둔 "제미니 API 잔액 알림" 예산(월 ₩16,000, 50/90/94/100% 임계값)이
지출 시점마다 Pub/Sub 토픽(gemini-budget-alerts)으로 메시지를 보낸다. GitHub Actions에는
Cloud Function 같은 상시 리스너를 못 두므로, 이 스크립트를 주기적으로 실행해서 구독
(gemini-budget-alerts-sub)에 쌓인 메시지를 꺼내(pull) 텔레그램으로 보내고 ack 처리한다.

2026-07-17: 계정을 선불(prepay)에서 후불(postpay)로 전환함 — 예산 알림 자체(Cloud Billing
기능)는 선불/후불과 무관하게 그대로 동작하지만, "크레딧이 0이 되면 API가 멈춘다"는 선불
특유의 셧다운 개념은 후불일 때는 적용되지 않는다. 처음엔 이 문구 차이를 코드에 그냥
하드코딩했는데(코드 리뷰 지적) — 나중에 다시 선불로 돌아가면 "괜찮다"고 잘못 안내하게
되므로, GEMINI_BILLING_MODE 환경변수("postpay" 기본값 / "prepay")로 분기한다.

사용법:
    python cloud/check_gemini_budget_alert.py
필요 환경변수:
    GEMINI_BUDGET_RELAY_SA_JSON — 이 작업 전용 서비스 계정 키(Pub/Sub 구독자 권한만 있음)
    GEMINI_BILLING_MODE — "postpay"(기본) 또는 "prepay"
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
    billing_mode = os.environ.get("GEMINI_BILLING_MODE", "postpay").strip().lower()
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

    # 2026-07-08: GCP 예산 알림은 임계값을 한 번 넘으면 그 뒤로도 비용이 재계산될 때마다
    # 계속 같은 내용을 반복 발행함(GCP 쪽 사양 — 우리 pull/ack 로직 버그 아님) — 그래서
    # 하루 새벽 내내 거의 동일한 텔레그램 메시지가 몇십 통씩 오는 문제가 있었음.
    # 큐는 매번 비워야(ack) 하지만, 텔레그램 전송은 이 run들 중 "가장 심각한(%가 가장 높은)"
    # 메시지 하나만, 그것도 오늘 하루에 아직 안 보냈을 때만 하도록 제한한다.
    ack_ids = []
    best = None  # (pct, text)
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

        pct = (cost / budget * 100) if budget else 0
        print(f"[check_gemini_budget_alert] {name}: {cost}/{budget} {currency} ({pct:.1f}%)")

        if billing_mode == "prepay":
            # 선불: 크레딧 잔액이 0이 되면 API 키가 실제로 멈춘다 — 잔액 소진 경고로 표시.
            remaining = budget - cost
            text = (
                f"💰 {name}\n\n"
                f"지출: {cost:,.0f}{currency} / {budget:,.0f}{currency} ({pct:.1f}%)\n"
                f"남은 크레딧(추정): {remaining:,.0f}{currency}"
            )
            if remaining <= 2000:
                text = "⚠️ 제미니 API 크레딧이 얼마 안 남았어요!\n\n" + text
        else:
            # 후불(기본): 예산을 넘어도 서비스가 안 멈춤 — 정보성 지출 알림으로 표시.
            text = (
                f"💰 {name}\n\n"
                f"이번 달 지출: {cost:,.0f}{currency} / 예산 {budget:,.0f}{currency} ({pct:.1f}%)\n"
                f"(후불 결제라 이 예산을 넘어도 서비스는 계속돼요 — 참고용 알림이에요)"
            )
            if pct >= 100:
                text = "📈 제미니 API 이번 달 지출이 설정 예산을 넘었어요!\n\n" + text
        if best is None or pct > best[0]:
            best = (pct, text)

    subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})
    print(f"[check_gemini_budget_alert] {len(ack_ids)}건 처리(ack) 완료")

    if best is None:
        return

    marker = Path("cloud/.gemini_budget_alert_sent_today")
    if marker.exists():
        print("[check_gemini_budget_alert] 오늘 이미 보냈음 — 텔레그램 전송 생략")
        return

    _send_message(best[1])
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("sent", encoding="utf-8")
    print("[check_gemini_budget_alert] 텔레그램 전송 완료")


if __name__ == "__main__":
    main()
