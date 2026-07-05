"""(2단계 스캐폴딩) GitHub Actions 안에서 Playwright headless Chromium에 네이버 로그인
쿠키를 주입해 로그인 상태를 복원한다.

기존 blog/naver_engine의 "좌표 클릭 + 로컬 크롬 프로필 재사용" 방식은 headless
클라우드 환경에 그대로 이식할 수 없다(원인은 docs/github_actions_migration.md
"2단계 설계" 섹션 참고). 이 파일은 그 대체 경로의 뼈대만 만들어둔 것이며,
실제 스마트에디터 조작(제목/본문 입력, 이미지 첨부, 저장/발행 버튼) 로직은
아직 구현되지 않았다 — TODO 표시된 부분을 다음 세션에서 완성해야 한다.

사용법(완성 후):
    python cloud/naver_cookie_login.py --draft <blog_draft_json_path> [--publish]

필요 조건:
    pip install playwright
    playwright install chromium
    환경변수 NAVER_COOKIES_JSON (GitHub Secret에서 주입됨, extract_naver_cookies.py로 생성한 형식)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_cookies() -> list[dict]:
    raw = os.getenv("NAVER_COOKIES_JSON", "")
    if not raw:
        print("[naver_cookie_login] NAVER_COOKIES_JSON 환경변수 없음")
        sys.exit(1)
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"[naver_cookie_login] NAVER_COOKIES_JSON 파싱 실패: {e}")
        sys.exit(1)
    # extract_naver_cookies.py가 만드는 형식: {"NID_AUT": "...", "NID_SES": "...", ...}
    # Playwright의 add_cookies()가 요구하는 형식으로 변환
    cookies = []
    for name, value in data.items():
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".naver.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        })
    return cookies


def run(draft_path: Path, do_publish: bool) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[naver_cookie_login] playwright 미설치 — requirements에 추가 필요: pip install playwright")
        return False

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    title = draft.get("title", "")
    body = draft.get("body", "")
    images = [Path(p) for p in draft.get("images", []) if p and Path(p).exists()]

    cookies = _load_cookies()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        # 로그인 상태 확인 — 네이버 메인에서 로그인 사용자 메뉴가 보이는지로 판단
        page.goto("https://www.naver.com/", wait_until="networkidle")
        is_logged_in = page.locator("a.MyView-module__link_login___HpHMW").count() == 0
        if not is_logged_in:
            print("[naver_cookie_login] 로그인 실패 감지 — 쿠키 만료 가능성")
            _notify_cookie_expired()
            browser.close()
            return False

        # TODO(다음 세션): 네이버 블로그 글쓰기 페이지로 이동 후 스마트에디터 ONE의
        # 실제 DOM 구조(iframe 내부의 제목/본문 편집영역, 이미지 첨부 input[type=file],
        # 저장/발행 버튼)를 조사해 selector 기반으로 다음을 구현해야 한다:
        #   1) https://blog.naver.com/{blog_id}?Redirect=Write 이동
        #   2) 제목 입력란에 title 입력
        #   3) 본문 편집 iframe 진입 → body 텍스트 입력(줄바꿈/서식 처리 주의)
        #   4) 이미지 첨부 컨트롤에 images 경로들을 set_input_files로 업로드
        #   5) 저장(임시저장) 버튼 클릭, do_publish=True면 발행 버튼까지 클릭
        # 기존 blog/naver_engine/naver_engine.py의 좌표값은 재사용 불가하지만, 어떤
        # 단계들이 필요한지 순서 참고용으로는 그 파일을 읽어봐도 좋다(수정하지 말 것).
        print("[naver_cookie_login] 로그인 확인 완료 — 여기서부터 스마트에디터 자동화 미구현")
        browser.close()

    return False  # 완성 전까지는 항상 실패로 보고(오탐 방지)


def _notify_cookie_expired():
    """쿠키 만료 시 텔레그램 알림 — cloud/telegram_gate.py 재사용."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from telegram_gate import _send_message
        _send_message("⚠️ 네이버 블로그 쿠키 만료 — 로컬에서 재추출 필요:\n"
                       "python cloud/extract_naver_cookies.py 실행 후 "
                       "GitHub Secret NAVER_COOKIES_JSON 갱신")
    except Exception as e:
        print(f"[naver_cookie_login] 만료 알림 전송 실패: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    ok = run(Path(args.draft), args.publish)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
