"""기사 데이터의 특정 필드(예: why_it_matters)를 고친 뒤 그 필드를 쓰는 카드 1장을
재생성해 텔레그램으로 재전송한다. (오타/문구 수정 요청 대응용, 일회성 CLI)

main.py의 regenerate_single_card()를 그대로 재사용한다(함수 재사용 — main.py 수정 없음).

사용법:
    python cloud/patch_article_field_and_regen.py --slot evening --field why_it_matters \
        --value "새 문구..." --card why
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import main as main_module  # noqa: E402
from cloud.telegram_gate import _send_photo, _send_message, CARD_LABELS  # noqa: E402


def run(slot: str, field: str, value: str, card: str) -> bool:
    today = config.now_kst().strftime("%Y%m%d")
    articles_path = config.OUTPUT_DIR / today / f"v2_articles_{slot}.json"
    if not articles_path.exists():
        _send_message(f"⚠️ 필드 수정 실패: {articles_path} 없음")
        return False

    data = json.loads(articles_path.read_text(encoding="utf-8"))
    if not data.get("articles"):
        _send_message(f"⚠️ 필드 수정 실패: articles 비어있음({slot})")
        return False
    data["articles"][0][field] = value
    articles_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    out_path = main_module.regenerate_single_card(slot, card)
    if not out_path:
        _send_message(f"⚠️ {CARD_LABELS.get(card, card)} 카드 재생성 실패({slot})")
        return False
    _send_photo(out_path.read_bytes(), out_path.name, f"✏️ 문구 수정 후 재생성됨: {CARD_LABELS.get(card, card)}")
    _send_message(f"✏️ [{slot}] {CARD_LABELS.get(card, card)} 수정 완료 — 다시 확인해주세요.")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--card", required=True)
    args = parser.parse_args()
    ok = run(args.slot, args.field, args.value, args.card)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
