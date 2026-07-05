"""도토리뉴스 전용 BloFit/Naver Blog 설정.

GSoul(지솔이슈) 검증된 네이버 블로그 발행 엔진(D:\\GSoul\\Gsoul_issue\\blog\\gsoul_blofit)을
그대로 가져와 도토리뉴스 전용 포트/Chrome 프로필/Credential prefix로 분리했다.
원본 GSoul 폴더는 건드리지 않았다 — 이 폴더(blog/naver_engine/)가 도토리뉴스용 사본이다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── 도토리뉴스 전용 분리 상수 (GSoul/지솔이슈와 포트·프로필 겹치지 않게 다른 값 사용) ──
DEBUG_PORT = 9722
DEBUGGER_ADDRESS = f"127.0.0.1:{DEBUG_PORT}"
CHROME_PROFILE_DIR = Path(__file__).resolve().parents[2] / "runtime" / "chrome_debug_dotory"
CREDENTIAL_PREFIX = "DotoryNewsBlofit"
SCHEDULER_PREFIX = "DotoryNewsBlofit"
APP_NAME_KO = "도토리뉴스 BloFit"

ROOT = Path(__file__).resolve().parents[1]            # .../Cardnews/blog
PKG_DIR = Path(__file__).resolve().parent              # .../naver_engine
DATA_DIR = PKG_DIR / "data"
RUN_LOG_DIR = DATA_DIR / "run_logs"
SETTINGS_PATH = DATA_DIR / "dotory_blofit_settings.json"
POST_REGISTRY_PATH = DATA_DIR / "dotory_blofit_registry.json"

# 도토리뉴스 블로그 패키지(초안) 위치
PACKAGES_DIR = ROOT / "data" / "packages"


def ensure_directories() -> None:
    for path in (DATA_DIR, RUN_LOG_DIR, CHROME_PROFILE_DIR, PACKAGES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
