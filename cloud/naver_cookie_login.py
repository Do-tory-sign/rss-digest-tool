"""GitHub Actions 러너에서 네이버 로그인 세션을 쿠키만으로 복원한다.

2026-07-06: 이전 버전은 Playwright로 스마트에디터 자체를 새로 자동화하려던 스캐폴딩이었는데,
그러면 blog/naver_engine.py에 이미 있는(수십 번 테스트해서 다듬은) 제목/본문/이미지/굵게
서식 로직을 통째로 재구현해야 해서 리스크가 컸다. 대신 이 스크립트는 "로그인된 브라우저를
준비하는 것"까지만 새로 하고, 그 뒤(naver_engine.py의 실제 글쓰기 자동화)는 전혀 안 건드린다.

방법: 헤드리스 크롬을 config.DEBUG_PORT로 원격 디버깅 포트를 열어서 띄우고, Selenium으로
그 포트에 붙어(naver_engine.py가 로컬에서 하는 것과 완전히 같은 방식) NID_AUT/NID_SES
쿠키를 주입한다. 이후 dotory_blog_draft.py/dotory_blog_publish.py를 그대로 실행하면
naver_engine.py가 같은 디버그 포트에 붙어서 평소처럼 동작한다.

사용법(GitHub Actions에서만 의미 있음, 로컬 자동화 크롬과 포트 겹치지 않게 주의):
    python -X utf8 cloud/naver_cookie_login.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "blog"))

from naver_engine.config import DEBUG_PORT, DEBUGGER_ADDRESS

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _find_chrome() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    return next((p for p in candidates if p.exists()), None)


def _wait_for_debug_port(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://{DEBUGGER_ADDRESS}/json/version", timeout=1.5)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def _notify_cookie_expired():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from telegram_gate import _send_message
        _send_message("⚠️ 네이버 블로그 쿠키 만료(또는 클라우드 IP 이상탐지) — 로컬에서 재추출 필요:\n"
                       "python cloud/extract_naver_cookies.py 실행 후 "
                       "GitHub Secret NAVER_COOKIES_JSON 갱신")
    except Exception as e:
        print(f"[naver_cookie_login] 만료 알림 전송 실패: {e}")


def main():
    cookies_json = os.environ.get("NAVER_COOKIES_JSON", "")
    if not cookies_json:
        print("[naver_cookie_login] NAVER_COOKIES_JSON 환경변수가 없음")
        sys.exit(1)
    cookies = json.loads(cookies_json)

    chrome = _find_chrome()
    if not chrome:
        print("[naver_cookie_login] Chrome을 찾지 못함")
        sys.exit(1)

    profile_dir = Path(tempfile.mkdtemp(prefix="naver_headless_"))
    cmd = [
        str(chrome),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile_dir}",
        # 2026-07-07: naver_engine.py의 실제 글쓰기 자동화는 pyautogui/win32gui로 진짜 화면
        # 좌표와 윈도우 포커스를 조작하는 방식이라 --headless=new(화면 자체가 없음)로는
        # 절대 동작 못 함(제목 입력이 항상 빈 문자열로 읽힘) — GitHub 호스팅 Windows 러너는
        # 로컬처럼 실제 대화형 데스크톱 세션이 있으므로, 헤드리스를 빼고 로컬과 동일하게
        # 진짜 창을 띄운다.
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-features=CalculateNativeWinOcclusion",
    ]
    subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW),
    )

    if not _wait_for_debug_port():
        print("[naver_cookie_login] 헤드리스 크롬 디버그 포트가 안 뜸")
        sys.exit(1)

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import NoSuchWindowException, WebDriverException

    # 2026-07-08: 가끔 크롬 창이 뜨자마자(원인 불명 — 첫 실행 팝업/크래시 복구 등으로 추정)
    # 닫혀버려서 "no such window: target window already closed"로 실패하는 경우가 있었음.
    # 몇 초 텀을 두고 재시도하면 대부분 두 번째엔 정상 동작함.
    driver = None
    last_exc = None
    for attempt in range(3):
        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
            driver = webdriver.Chrome(options=options)
            driver.get("https://www.naver.com/")
            break
        except (NoSuchWindowException, WebDriverException) as e:
            last_exc = e
            print(f"[naver_cookie_login] 크롬 창 접속 실패(시도 {attempt + 1}/3): {e}")
            time.sleep(3)
    else:
        print(f"[naver_cookie_login] 3회 시도 모두 실패 — 갱신 건너뜀: {last_exc}")
        sys.exit(1)

    for name, value in cookies.items():
        driver.add_cookie({"name": name, "value": value, "domain": ".naver.com", "path": "/"})
    driver.get("https://www.naver.com/")  # 쿠키 반영해서 새로고침

    page = driver.page_source
    logged_in = "로그아웃" in page or "logout" in page.lower()
    print(f"[naver_cookie_login] 로그인 상태: {'성공' if logged_in else '확인 불가(실패 가능성 — IP 이상탐지일 수 있음)'}")
    if not logged_in:
        _notify_cookie_expired()
        sys.exit(1)


if __name__ == "__main__":
    main()
