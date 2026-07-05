"""repository_dispatch로 워크플로우가 켜졌을 때, GitHub이 넘겨준 client_payload(slot, extra)를
환경변수나 GITHUB_EVENT_PATH의 JSON에서 꺼내 쓰기 쉽게 해주는 헬퍼.

GitHub Actions는 repository_dispatch 이벤트의 client_payload를
$GITHUB_EVENT_PATH가 가리키는 JSON 파일의 event.client_payload 에 넣어준다.
워크플로우 yaml에서 이 파일을 실행해 SLOT/EXTRA 값을 얻은 뒤 다음 스텝에 넘긴다.

사용법 (workflow 안에서):
    python cloud/dispatch_payload.py slot   # -> 예: morning
    python cloud/dispatch_payload.py extra  # -> 예: cover (card_regen일 때 카드 이름)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_payload() -> dict:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if not event_path or not Path(event_path).exists():
        return {}
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return event.get("client_payload", {}) or {}


def main():
    if len(sys.argv) < 2:
        print("사용법: python dispatch_payload.py <key>")
        sys.exit(2)
    key = sys.argv[1]
    payload = _load_payload()
    print(payload.get(key, ""))


if __name__ == "__main__":
    main()
