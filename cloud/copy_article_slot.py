"""한 슬롯에서 만들어진 기사(v2_articles_<slot>.json/v2_curated_<slot>.json)를 다른
슬롯 이름으로 복사한 뒤 그 슬롯의 기사 승인 메시지를 새로 보낸다.
("이 주제 마음에 드는데 다른 시간대로 쓰고 싶다" 요청 대응용, 일회성 CLI)

사용법:
    python cloud/copy_article_slot.py --from evening --to night
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from cloud.telegram_gate import cmd_send_article, _send_message  # noqa: E402


def run(src_slot: str, dst_slot: str) -> bool:
    today = config.now_kst().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today

    src_articles = run_dir / f"v2_articles_{src_slot}.json"
    src_curated = run_dir / f"v2_curated_{src_slot}.json"
    if not src_articles.exists():
        _send_message(f"⚠️ 슬롯 복사 실패: {src_articles} 없음")
        return False

    shutil.copy2(src_articles, run_dir / f"v2_articles_{dst_slot}.json")
    if src_curated.exists():
        shutil.copy2(src_curated, run_dir / f"v2_curated_{dst_slot}.json")

    cmd_send_article(SimpleNamespace(slot=dst_slot))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="src", required=True)
    parser.add_argument("--to", dest="dst", required=True)
    args = parser.parse_args()
    ok = run(args.src, args.dst)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
