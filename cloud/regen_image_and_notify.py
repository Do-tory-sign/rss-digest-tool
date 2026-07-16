"""메인 일러스트 재생성 + 전체 카드 재조립 + 텔레그램 재전송 (image_regen dispatch 전용).

main.py의 regenerate_article_image()를 그대로 가져다 쓴다(함수 재사용 — main.py 수정 없음).
카드별 재생성(card_regen)과 다른 점: card_regen은 캐릭터 포즈만 바뀌고 배경 일러스트는
그대로였는데, 이건 일러스트 자체를 다시 그린 뒤 그걸 쓰는 카드를 전부 재조립한다.

사용법:
    python cloud/regen_image_and_notify.py --slot morning
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as main_module  # noqa: E402  (읽기 전용 재사용 — main.py 수정 없음)
from cloud.telegram_gate import _send_photo, _send_message, CARD_LABELS  # noqa: E402


def run(slot: str, feedback: str = "") -> bool:
    rebuilt = main_module.regenerate_article_image(slot, feedback=feedback)
    if not rebuilt:
        _send_message(f"⚠️ 메인 그림 재생성 실패({slot})")
        return False
    for path in rebuilt:
        name = path.stem.split("_", 2)[-1]  # "{slot}_{idx}_{name}.png" -> name
        _send_photo(path.read_bytes(), path.name, f"🎨 재생성됨: {CARD_LABELS.get(name, name)}")
    note = f" (피드백 반영: {feedback})" if feedback else ""
    _send_message(f"🎨 [{slot}] 그림 재생성 완료{note} — 다시 확인 후 전체승인 또는 카드별 재생성 눌러주세요.")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True)
    parser.add_argument("--feedback", default="")
    args = parser.parse_args()
    ok = run(args.slot, feedback=args.feedback)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
