"""블로그 발행이 끝난 뒤, 지금 쓰고 있던(클라우드) 크롬 세션에서 최신 네이버 쿠키를
다시 뽑아 GitHub Secret(NAVER_COOKIES_JSON)을 덮어쓴다.

네이버는 활동이 있으면 세션 쿠키(NID_SES)의 유효기간을 슬쩍 늘려주는 경우가 많다 —
그래서 "방금 로그인해서 실제로 글을 쓰는 데 쓴" 세션을 매번 다시 저장해두면, 로컬에서
수동으로 재추출하지 않아도 계속 살아있을 가능성이 높다(단, 언젠가 네이버 쪽 정책으로
막히면 이 자동 갱신도 결국 멈추고 예전처럼 수동 재추출이 필요해질 수 있음 — 그때는
cloud/extract_naver_cookies.py를 로컬에서 다시 실행).

GitHub Secret 쓰기는 Actions 기본 GITHUB_TOKEN 권한 밖이라, 이 저장소 전용으로 발급한
개인 액세스 토큰(Secrets 쓰기 권한)이 필요하다 — GH_PAT_FOR_SECRETS 환경변수로 전달.

사용법 (naver_cookie_login.py로 띄운 크롬이 아직 살아있는 상태에서):
    python cloud/refresh_naver_cookies.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "blog"))

import requests
from nacl import encoding, public

from naver_engine.config import DEBUGGER_ADDRESS

REPO = "Do-tory-sign/Do.story_news"
SECRET_NAME = "NAVER_COOKIES_JSON"
COOKIE_NAMES = {"NID_AUT", "NID_SES"}


def _encrypt(public_key_b64: str, secret_value: str) -> str:
    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def main():
    pat = os.environ.get("GH_PAT_FOR_SECRETS", "")
    if not pat:
        print("[refresh_naver_cookies] GH_PAT_FOR_SECRETS 없음 — 갱신 건너뜀")
        return

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"[refresh_naver_cookies] 크롬 연결 실패(갱신 건너뜀): {e}")
        return

    cookies = {c["name"]: c["value"] for c in driver.get_cookies() if c["name"] in COOKIE_NAMES}
    if "NID_AUT" not in cookies or "NID_SES" not in cookies:
        print("[refresh_naver_cookies] 쿠키를 못 읽음 — 갱신 건너뜀")
        return

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
    }
    key_res = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers, timeout=15
    )
    key_res.raise_for_status()
    key_data = key_res.json()

    encrypted_value = _encrypt(key_data["key"], json.dumps(cookies, ensure_ascii=False))
    put_res = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/{SECRET_NAME}",
        headers=headers,
        json={"encrypted_value": encrypted_value, "key_id": key_data["key_id"]},
        timeout=15,
    )
    if put_res.status_code in (201, 204):
        print("[refresh_naver_cookies] NAVER_COOKIES_JSON 갱신 완료")
    else:
        print(f"[refresh_naver_cookies] 갱신 실패: {put_res.status_code} {put_res.text}")


if __name__ == "__main__":
    main()
