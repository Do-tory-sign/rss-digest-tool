"""네이버 블로그 자동로그인 세션 만료 체크 — Windows 스케줄러에서 매일 실행.

NID_AUT 쿠키(자동로그인 토큰)의 만료 시각을 실제 디버그 크롬에서 읽어와 비교한다.
2026-08-16: 세션 만료는 지금까지 "발행이 실제로 실패해야만" 사후에 텔레그램으로 알려졌음
(dotory_blog_publish.py) — Instagram 토큰 체크(token_check.py)처럼 만료 며칠 전에 미리
경고하도록 신설.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "blog"))

# 이 날 이하로 남으면 텔레그램 경고
WARN_DAYS = 3


def check():
    from naver_engine import login_chrome
    from naver_engine.settings import load_illua_settings
    from naver_engine.naver_engine import IlluaNaverEngine

    login_chrome.main()  # 이미 켜져 있으면 즉시 no-op, 꺼져 있으면 새로 띄움

    settings = load_illua_settings()
    engine = IlluaNaverEngine(settings, log_callback=lambda msg: print(f"[naver_session_check] {msg}"))
    try:
        ok, msg = engine.connect()
        if not ok:
            print(f"[naver_session_check] Chrome 연결 실패: {msg}")
            return
        cookies = engine.driver.get_cookies()
    finally:
        try:
            engine.quit()
        except Exception:
            pass

    aut = next((c for c in cookies if c.get("name") == "NID_AUT"), None)
    if not aut or not aut.get("expiry"):
        # expiry가 없으면(세션 쿠키) 자동로그인이 아예 꺼져있는 상태 — 재로그인 때 자동로그인
        # 체크를 안 했을 가능성이 큼(2026-08-16 실제로 겪은 경우).
        print("[naver_session_check] ⚠️ NID_AUT에 만료시간이 없음 — 자동로그인 미설정 상태로 추정")
        try:
            from notify import send
            send(
                "⚠️ 네이버 블로그 자동로그인이 꺼져 있는 것 같아요\n\n"
                "세션 쿠키에 만료시간이 없습니다 — 크롬 재시작 시 바로 로그아웃될 수 있어요.\n"
                "네이버에 다시 로그인하면서 '자동로그인'을 꼭 체크해주세요."
            )
        except Exception:
            pass
        return

    expires_on = datetime.fromtimestamp(aut["expiry"], tz=timezone.utc)
    days_left = (expires_on - datetime.now(timezone.utc)).days
    expires_str = expires_on.strftime("%Y-%m-%d")

    print(f"[naver_session_check] 만료일: {expires_str}  남은 날: {days_left}일")

    if days_left <= 0:
        print("[naver_session_check] ❌ 세션 이미 만료됨!")
        try:
            from notify import send
            send(
                "🚨 네이버 블로그 로그인 세션 만료됨!\n\n"
                f"만료일: {expires_str}\n\n"
                "블로그 자동 발행이 멈춰있을 거예요 — 지금 다시 로그인해주세요."
            )
        except Exception:
            pass
        sys.exit(1)

    if days_left <= WARN_DAYS:
        print(f"[naver_session_check] ⚠️ 만료 {days_left}일 전 — 텔레그램 경고 발송")
        try:
            from notify import send
            urgency = "🚨 긴급" if days_left <= 1 else "⚠️ 주의"
            send(
                f"{urgency} 네이버 블로그 로그인 세션 만료 임박\n\n"
                f"만료일: {expires_str}\n"
                f"남은 기간: {days_left}일\n\n"
                "미리 다시 로그인해주세요(자동로그인 체크 필수)."
            )
        except Exception as e:
            print(f"[naver_session_check] 알림 발송 실패: {e}")
    else:
        print(f"[naver_session_check] ✅ 정상 ({days_left}일 남음)")


if __name__ == "__main__":
    check()
