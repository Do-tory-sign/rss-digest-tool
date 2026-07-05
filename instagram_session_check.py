"""매일 자정 Instagram 세션 유효성 확인 — 만료 시 텔레그램 알림"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION_FILE = Path(__file__).parent / "instagram_session.json"


def check_session() -> bool:
    if not SESSION_FILE.exists():
        print("[session_check] instagram_session.json 없음")
        return False

    session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    sessionid = session.get("sessionid", "")
    ds_user_id = session.get("ds_user_id", "")

    if not sessionid:
        print("[session_check] sessionid 없음")
        return False

    print("[session_check] Instagram 로그인 상태 확인 중...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies([
            {"name": "sessionid",  "value": sessionid,  "domain": ".instagram.com",
             "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax"},
            {"name": "ds_user_id", "value": ds_user_id, "domain": ".instagram.com",
             "path": "/", "sameSite": "Lax"},
        ])
        page = context.new_page()
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            url = page.url
            browser.close()

            if "login" in url or "accounts" in url:
                print("[session_check] 세션 만료 — 로그인 페이지로 리다이렉트됨")
                return False

            print("[session_check] 세션 정상")
            return True

        except PWTimeout:
            browser.close()
            print("[session_check] 타임아웃 — 세션 상태 불명확")
            return None
        except Exception as e:
            browser.close()
            print(f"[session_check] 오류: {e}")
            return None


if __name__ == "__main__":
    result = check_session()

    try:
        from notify import notify_session_expired, notify_session_ok
        if result is False:
            notify_session_expired()
            print("[session_check] 만료 알림 전송 완료")
            sys.exit(1)
        elif result is True:
            # 정상일 때는 알림 없음 (매일 자정마다 오면 피로도 높음)
            print("[session_check] 세션 정상, 알림 없음")
            sys.exit(0)
        else:
            print("[session_check] 확인 불가, 알림 없음")
            sys.exit(0)
    except Exception as e:
        print(f"[session_check] 알림 전송 실패: {e}")
