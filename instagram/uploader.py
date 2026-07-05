"""인스타그램 웹 자동화 업로드 (Playwright channel=chrome + sessionid 쿠키)"""
from pathlib import Path
from datetime import datetime
import json
import urllib.parse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION_FILE = Path(__file__).parent.parent / "instagram_session.json"


def _load_session() -> dict:
    if not SESSION_FILE.exists():
        raise FileNotFoundError("instagram_session.json 없음 — instagram_setup.py 실행 필요")
    with open(SESSION_FILE, encoding="utf-8") as f:
        return json.load(f)


def _run_dir() -> Path:
    today = datetime.now().strftime("%Y%m%d")
    d = SESSION_FILE.parent / "output" / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_carousel(image_paths: list, curated: dict, caption: str = None) -> bool:
    session = _load_session()
    sessionid = session.get("sessionid", "")
    ds_user_id = session.get("ds_user_id", "")

    if not sessionid:
        print("[uploader] sessionid 없음 — instagram_setup.py 실행 필요")
        return False

    caption = caption or _build_caption(curated)
    shot_dir = _run_dir()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",
            headless=False,
            slow_mo=400,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-save-password-bubble",
                  "--window-position=0,0"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )

        # sessionid 쿠키 주입
        context.add_cookies([
            {"name": "sessionid",  "value": sessionid,  "domain": ".instagram.com",
             "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax"},
            {"name": "ds_user_id", "value": ds_user_id, "domain": ".instagram.com",
             "path": "/", "sameSite": "Lax"},
        ])

        page = context.new_page()

        try:
            # 1. Instagram 홈 접속 및 로그인 확인
            print("[uploader] Instagram 접속 중...")
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 스크린샷 저장 (디버그)
            page.screenshot(path=str(shot_dir / "uploader_debug.png"))
            print(f"[uploader] 현재 URL: {page.url}")

            if "/accounts/login" in page.url or "login" in page.url:
                print("[uploader] 세션 만료 — Chrome에서 sessionid 재추출 후 instagram_setup.py 실행 필요")
                browser.close()
                return False

            # 홈 피드 요소 확인
            try:
                page.locator('[aria-label="홈"], [aria-label="Home"], nav').first.wait_for(
                    state="visible", timeout=5000
                )
                print("[uploader] 로그인 확인됨")
            except PWTimeout:
                print("[uploader] 로그인 상태 불명확 — 계속 진행...")

            # 알림 팝업 자동 닫기 (최초)
            _dismiss_popups(page)

            # 2. 새 게시물 만들기 (클릭 직전 팝업 한 번 더 정리)
            _dismiss_popups(page)
            print("[uploader] 새 게시물 클릭...")
            _click_create_button(page)
            page.wait_for_timeout(1500)

            # 2-1. 서브메뉴에 "게시물" 옵션이 뜨면 클릭
            _click_post_submenu(page)
            page.wait_for_timeout(2000)

            # 3. 파일 업로드
            print("[uploader] 이미지 업로드 중...")
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files([str(p) for p in image_paths])
            page.wait_for_timeout(4000)

            # 4. 크기 조정 → 다음
            print("[uploader] 크기 조정 → 다음...")
            _click_next(page)
            page.wait_for_timeout(2500)

            # 5. 필터 → 다음
            print("[uploader] 필터 → 다음...")
            _click_next(page)
            page.wait_for_timeout(2500)

            # 6. 캡션 입력
            print("[uploader] 캡션 입력...")
            _input_caption(page, caption)
            page.wait_for_timeout(1000)

            # 7. 공유
            print("[uploader] 공유 클릭...")
            _click_share(page)
            page.wait_for_timeout(10000)

            print("[uploader] 업로드 완료!")

            # Playwright 쿠키 전달 후 브라우저 종료
            pw_cookies = {c["name"]: c["value"] for c in context.cookies()
                          if "instagram.com" in c.get("domain", "")}
            browser.close()

            # 스토리 공유 (instagrapi) — 피드 게시물 링크 스티커
            if image_paths:
                try:
                    from instagram.story import share_latest_post_to_story
                    share_latest_post_to_story(image_paths[0], pw_cookies)
                except Exception as e:
                    print(f"[uploader] 스토리 공유 실패 (업로드는 성공): {e}")

            # 텔레그램 성공 알림
            if curated:
                try:
                    import sys; sys.path.insert(0, str(SESSION_FILE.parent))
                    from notify import notify_success
                    from datetime import datetime
                    day_names = ["월","화","수","목","금","토","일"]
                    now = datetime.now()
                    date_str = f"{now.strftime('%Y.%m.%d')} ({day_names[now.weekday()]})"
                    notify_success(date_str, curated)
                except Exception:
                    pass

            return True

        except Exception as e:
            print(f"[uploader] 업로드 실패: {e}")
            try:
                page.screenshot(path=str(shot_dir / "uploader_error.png"))
                print(f"[uploader] 스크린샷 저장됨: {shot_dir / 'uploader_error.png'}")
            except Exception:
                pass

            # 텔레그램 실패 알림
            try:
                import sys; sys.path.insert(0, str(SESSION_FILE.parent))
                from notify import notify_failure
                notify_failure(str(e))
            except Exception:
                pass

            browser.close()
            return False


def _dismiss_popups(page, retries: int = 3):
    """알림 허용 / 정보 저장 등 팝업 자동 닫기 — 팝업이 연속으로 뜰 수 있어 최대 retries회 반복"""
    dismiss_texts = [
        "나중에 하기", "나중에", "Not Now",
        "이미 팔로우 중인 사람 찾기 건너뛰기",
        "정보 저장 안 함", "Save Info",
        "허용 안 함", "지금은 안 함", "알림 끄기",
    ]
    for _ in range(retries):
        dismissed = False
        for text in dismiss_texts:
            try:
                btn = page.get_by_role("button", name=text)
                if btn.is_visible(timeout=1500):
                    btn.click()
                    page.wait_for_timeout(800)
                    dismissed = True
            except Exception:
                pass
        if not dismissed:
            break


def _click_post_submenu(page):
    """만들기 클릭 후 뜨는 서브메뉴에서 '게시물' 선택"""
    for text in ["게시물", "Post"]:
        try:
            el = page.get_by_text(text, exact=True).first
            if el.is_visible(timeout=2000):
                el.click()
                print(f"[uploader] 서브메뉴 '{text}' 클릭")
                return
        except Exception:
            pass


def _click_create_button(page):
    selectors = [
        '[aria-label="새로운 게시물"]',
        '[aria-label="새 게시물 만들기"]',
        '[aria-label="New post"]',
        '[aria-label="Create"]',
    ]
    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=3000)
            return
        except PWTimeout:
            continue
    raise RuntimeError("새 게시물 만들기 버튼을 찾지 못했습니다.")


def _click_next(page):
    for text in ["다음", "Next"]:
        try:
            page.get_by_role("button", name=text).click(timeout=4000)
            return
        except PWTimeout:
            continue
    for text in ["다음", "Next"]:
        try:
            page.locator(f'div[role="button"]:has-text("{text}")').click(timeout=3000)
            return
        except PWTimeout:
            continue


def _input_caption(page, caption: str):
    for sel in ['div[aria-label*="캡션"]', 'div[aria-label*="caption"]',
                'div[aria-label*="Caption"]', 'textarea[aria-label*="캡션"]']:
        try:
            box = page.locator(sel).first
            box.click(timeout=3000)
            page.keyboard.type(caption, delay=15)
            return
        except PWTimeout:
            continue
    try:
        page.locator('[contenteditable="true"]').last.click(timeout=3000)
        page.keyboard.type(caption, delay=15)
    except PWTimeout:
        print("[uploader] 캡션 입력 실패 (계속 진행)")


def _click_share(page):
    # 공유 버튼 활성화 대기 (캡션 입력 후 약간 딜레이 필요)
    page.wait_for_timeout(1500)

    # aria-disabled="false" 인 공유하기 버튼만 클릭
    for sel in [
        'div[role="button"][aria-disabled="false"]:has-text("공유하기")',
        'div[role="button"][aria-disabled="false"]:has-text("Share")',
    ]:
        try:
            page.locator(sel).first.click(timeout=4000)
            return
        except PWTimeout:
            continue

    # fallback: exact 매칭
    for text in ["공유하기", "Share"]:
        try:
            page.get_by_role("button", name=text, exact=True).click(timeout=4000)
            return
        except PWTimeout:
            continue



def _build_caption(curated: dict) -> str:
    now = datetime.now()
    day_names = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.strftime('%Y.%m.%d')} ({day_names[now.weekday()]})"
    hot     = curated.get("hot", {})
    eco     = curated.get("economy", {})
    culture = curated.get("culture", {})
    lines = [
        f"오늘의 DO's TORY NEWS 🐿 | {date_str}", "", "",
        f"HOT | {hot.get('card_headline', '')}",
        f"ECO | {eco.get('card_headline', '')}",
        f"TRD | {culture.get('card_headline', '')}",
        "", "",
        "원문은 프로필 링크에서 확인하세요.",
        "", "",
        "#도토리뉴스 #오늘의뉴스 #카드뉴스 #뉴스요약 #핫이슈",
    ]
    return "\n".join(lines)
