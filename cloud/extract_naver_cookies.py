"""(2단계 스캐폴딩) 로컬 Chrome의 네이버 로그인 세션에서 인증 쿠키를 추출해
GitHub Secret에 등록할 JSON을 만든다.

전제: blog/naver_engine/login_chrome.py로 띄운 전용 크롬 프로필
(config.CHROME_PROFILE_DIR, 기본 runtime/chrome_debug_dotory)에 이미 네이버
로그인이 되어 있어야 한다. 이 스크립트는 그 프로필의 쿠키 DB를 직접 읽는 대신,
이미 떠 있는 CDP(원격 디버깅) 세션에 붙어 Network.getCookies로 안전하게 가져온다
(SQLite 쿠키 DB를 프로세스 실행 중에 직접 여는 것보다 안전 — 잠금 충돌 없음).

사용법:
    1) python -X utf8 blog/naver_engine/login_chrome.py   # 크롬 띄우고 네이버 로그인
    2) python cloud/extract_naver_cookies.py               # 이 스크립트 실행
       -> cloud/naver_cookies_output.json 생성됨
    3) 그 파일 내용을 GitHub Secret NAVER_COOKIES_JSON 에 등록

주의: 이 파일은 만료 갱신 때마다 사용자가 로컬에서 재실행해야 하는 "수동 스크립트"다
(review.py처럼 자동화된 실행 흐름에는 들어가지 않는다 — 원 요청사항 그대로).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "blog"))

try:
    from naver_engine.config import DEBUG_PORT  # 기존 파일 재사용(읽기 전용 import)
except Exception:
    DEBUG_PORT = 9722  # naver_engine/config.py의 기본값과 동일 — import 실패 시 폴백

OUTPUT_PATH = Path(__file__).parent / "naver_cookies_output.json"
NEEDED_COOKIE_NAMES = {"NID_AUT", "NID_SES", "NID_JKL"}


def _cdp_json(path: str) -> dict | list:
    with urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}{path}", timeout=5) as r:
        return json.loads(r.read())


def main():
    try:
        targets = _cdp_json("/json")
    except Exception as e:
        print(f"[extract_naver_cookies] 크롬 CDP({DEBUG_PORT})에 연결 못함: {e}")
        print("먼저 실행: python -X utf8 blog/naver_engine/login_chrome.py")
        sys.exit(1)

    # websocket 기반 CDP Network.getCookies가 정석이지만 의존성을 늘리지 않기 위해
    # 여기서는 Chrome DevTools의 HTTP 엔드포인트로 얻을 수 있는 범위 내에서 시도한다.
    # (websocket-client 등 새 의존성 추가가 필요하면 requirements.txt에 반영 후 이 부분을
    #  Network.getCookies 정식 CDP 호출로 교체할 것 — 2단계 완성 시 후속 작업)
    print("[extract_naver_cookies] 이 스크립트는 스캐폴딩입니다.")
    print("[extract_naver_cookies] websocket-client 의존성 추가 후 아래 TODO를 구현하세요:")
    print("  1) targets에서 naver.com 탭의 webSocketDebuggerUrl 찾기")
    print("  2) websocket 연결 → Network.enable → Network.getCookies({'urls': ['https://www.naver.com']})")
    print("  3) NEEDED_COOKIE_NAMES에 해당하는 쿠키만 골라 JSON으로 저장")
    print(f"  4) 결과를 {OUTPUT_PATH} 에 저장 후 GitHub Secret NAVER_COOKIES_JSON 에 등록")

    # 최소한의 동작 확인용 — 연결된 탭 목록만 출력
    naver_tabs = [t for t in targets if "naver.com" in (t.get("url") or "")]
    print(f"[extract_naver_cookies] naver.com 관련 탭 {len(naver_tabs)}개 발견")
    for t in naver_tabs:
        print(f"  - {t.get('title')}: {t.get('url')}")


if __name__ == "__main__":
    main()
