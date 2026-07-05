"""카드 1장 재생성 + 텔레그램 재전송 (card_regen dispatch 이벤트 전용).

main.py의 regenerate_single_card()를 그대로 가져다 쓴다(함수 재사용 — main.py 수정 없음).

사용법:
    python cloud/regen_card_and_notify.py --slot morning --card cover
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as main_module  # noqa: E402  (읽기 전용 재사용 — main.py 수정 없음)
from cloud.telegram_gate import _send_photo, CARD_LABELS  # noqa: E402


def run(slot: str, card: str) -> bool:
    out_path = main_module.regenerate_single_card(slot, card)
    if not out_path:
        _send_message_fallback(f"⚠️ {CARD_LABELS.get(card, card)} 카드 재생성 실패({slot})")
        return False
    _send_photo(Path(out_path).read_bytes(), Path(out_path).name,
                f"🔄 재생성됨: {CARD_LABELS.get(card, card)}")
    return True


def _send_message_fallback(text: str):
    from cloud.telegram_gate import _send_message
    _send_message(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True)
    parser.add_argument("--card", required=True)
    args = parser.parse_args()
    ok = run(args.slot, args.card)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
