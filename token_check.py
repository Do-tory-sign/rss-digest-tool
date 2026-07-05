"""Instagram Graph API 토큰 만료 체크 — Windows 스케줄러에서 매일 실행"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

TOKEN_FILE = Path(__file__).parent / "instagram_graph_token.json"

# 이 날 이하로 남으면 텔레그램 경고
WARN_DAYS = 14


def check():
    if not TOKEN_FILE.exists():
        print("[token_check] 토큰 파일 없음 — 건너뜀")
        return

    with open(TOKEN_FILE, encoding="utf-8") as f:
        data = json.load(f)

    issued_at_str = data.get("issued_at")
    expires_days = data.get("expires_days", 60)

    if not issued_at_str:
        print("[token_check] issued_at 필드 없음 — get_instagram_token.py 재실행 필요")
        try:
            from notify import send
            send(
                "⚠️ Instagram 토큰 만료일 추적 불가\n\n"
                "issued_at 필드가 없습니다.\n"
                "python -X utf8 get_instagram_token.py 로 토큰을 재발급해주세요."
            )
        except Exception:
            pass
        return

    issued = date.fromisoformat(issued_at_str)
    expires_on = issued + timedelta(days=expires_days)
    days_left = (expires_on - date.today()).days

    print(f"[token_check] 발급일: {issued_at_str}  만료일: {expires_on}  남은 날: {days_left}일")

    if days_left <= 0:
        print("[token_check] ❌ 토큰 이미 만료됨!")
        try:
            from notify import send
            send(
                "🚨 Instagram 토큰 만료됨!\n\n"
                f"만료일: {expires_on}\n\n"
                "지금 바로 재발급하세요:\n"
                "python -X utf8 get_instagram_token.py"
            )
        except Exception:
            pass
        sys.exit(1)

    if days_left <= WARN_DAYS:
        print(f"[token_check] ⚠️ 만료 {days_left}일 전 — 텔레그램 경고 발송")
        try:
            from notify import notify_token_warning
            notify_token_warning(days_left, str(expires_on))
        except Exception as e:
            print(f"[token_check] 알림 발송 실패: {e}")
    else:
        print(f"[token_check] ✅ 정상 ({days_left}일 남음)")


if __name__ == "__main__":
    check()
