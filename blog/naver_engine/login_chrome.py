"""도토리뉴스 BloFit 전용 네이버 로그인 크롬 실행.

전용 디버그 포트(config.DEBUG_PORT) + 전용 프로필(config.CHROME_PROFILE_DIR)로 크롬을 띄운다.
다른 BloFit류 자동화(지솔이슈 등)와 포트/프로필이 겹치지 않으므로 동시에 켜져 있어도 안전하다.

사용자는 이 창에서 네이버에 '한 번' 로그인하면 된다(프로필에 세션 저장 → 다음부터 자동 유지).
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from .config import CHROME_PROFILE_DIR, DEBUG_PORT
except ImportError:  # 단독 실행 대비 — config.py의 실제 값과 반드시 일치시킬 것
    # 2026-07-02: 이 폴백이 실제 config.DEBUG_PORT(9722)와 어긋나 있어서, 이 스크립트를
    # 모듈이 아니라 파일로 직접 실행하면(-m 없이) 로그인한 크롬을 naver_engine.py가
    # 못 찾는 버그가 있었음. 값을 하드코딩하지 말고 파일에서 직접 읽어와 항상 일치시킴.
    import re
    from pathlib import Path
    _config_text = (Path(__file__).parent / "config.py").read_text(encoding="utf-8")
    DEBUG_PORT = int(re.search(r"DEBUG_PORT\s*=\s*(\d+)", _config_text).group(1))
    CHROME_PROFILE_DIR = Path(r"C:\chrome_debug_trot")

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def find_chrome():
    from pathlib import Path
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    return next((p for p in candidates if p.exists()), None)


def chrome_already_running() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=1.0)
        return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.naver.com/"
    if chrome_already_running():
        print(f"도토리뉴스 블로핏 네이버 크롬이 이미 실행 중입니다 (포트 {DEBUG_PORT}).")
        return 0
    chrome = find_chrome()
    if not chrome:
        print("Google Chrome을 찾지 못했습니다.")
        return 1
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(chrome),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        # ★백그라운드여도 페이지를 'hidden'으로 처리하지 않게 — 네이버 에디터가 창이 안 보여도
        #  입력칸을 렌더하도록(블로그 RPA가 백그라운드에서도 동작하게 하는 핵심 플래그)
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-features=CalculateNativeWinOcclusion",
        target_url,
    ]
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW) \
        if sys.platform.startswith("win") else 0
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, close_fds=not sys.platform.startswith("win"))
    print(f"도토리뉴스 블로핏 네이버 크롬 창을 열었습니다 (포트 {DEBUG_PORT}, 프로필 {CHROME_PROFILE_DIR}).")
    print("이 창에서 네이버에 로그인해 주세요. (최초 1회)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
