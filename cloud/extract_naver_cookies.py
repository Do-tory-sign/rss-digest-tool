"""로컬 자동화 크롬의 네이버 로그인 세션 쿠키를 추출해 GitHub Secret 등록용 JSON을 만든다.

2026-07-06: 예전 버전은 CDP websocket을 직접 구현하려다 미완성 스캐폴딩으로 남아있었음 —
naver_engine.py가 이미 Selenium을 이 디버그 크롬에 attach하는 코드(webdriver.Chrome +
debugger_address)를 갖고 있어서, 그걸 그대로 재사용하면 훨씬 간단함(새 의존성 불필요).

전제: blog/naver_engine/login_chrome.py로 띄운 전용 크롬 프로필에 이미 네이버 로그인이
되어 있어야 한다.

사용법:
    1) python -X utf8 -m blog.naver_engine.login_chrome   # 크롬 띄우고 네이버 로그인
    2) python cloud/extract_naver_cookies.py               # 이 스크립트 실행
       -> cloud/naver_cookies_output.json 생성됨
    3) 그 파일 내용을 GitHub Secret NAVER_COOKIES_JSON 에 등록 (용량 작음 — 쿠키 3개뿐)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "blog"))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from naver_engine.config import DEBUGGER_ADDRESS

OUTPUT_PATH = Path(__file__).parent / "naver_cookies_output.json"
REQUIRED_COOKIE_NAMES = {"NID_AUT", "NID_SES"}  # 실제 세션 인증에 필요한 최소 쿠키
OPTIONAL_COOKIE_NAMES = {"NID_JKL"}  # 있으면 같이 저장하지만 없어도 진행


def main():
    options = Options()
    options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"[extract_naver_cookies] 크롬({DEBUGGER_ADDRESS})에 연결 못함: {e}")
        print("먼저 실행: python -X utf8 -m blog.naver_engine.login_chrome")
        sys.exit(1)

    # driver.quit()은 호출하지 않음 — Selenium이 attach만 한 것이라 quit해도 실제 크롬 창은
    # 안 닫히지만, 혹시 모를 부작용을 피하려고 그냥 이 프로세스만 종료되게 둔다.
    driver.get("https://www.naver.com/")
    cookies = driver.get_cookies()

    all_names = REQUIRED_COOKIE_NAMES | OPTIONAL_COOKIE_NAMES
    found = {c["name"]: c["value"] for c in cookies if c["name"] in all_names}
    missing_required = REQUIRED_COOKIE_NAMES - found.keys()
    if missing_required:
        print(f"[extract_naver_cookies] 누락된 필수 쿠키: {missing_required} — 네이버 로그인 상태 확인 필요")
        sys.exit(1)

    OUTPUT_PATH.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[extract_naver_cookies] 쿠키 {len(found)}개 저장 완료: {OUTPUT_PATH}")
    print("다음 명령으로 GitHub Secret 등록:")
    print(f'  gh secret set NAVER_COOKIES_JSON -R Do-tory-sign/rss-digest-tool < "{OUTPUT_PATH}"')


if __name__ == "__main__":
    main()
