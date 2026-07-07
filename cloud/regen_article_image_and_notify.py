"""기사 승인 단계에서 "그림만 다시 그리기" 눌렸을 때(art_image_regen dispatch 전용).

기사 제목/본문은 그대로 두고 메인 일러스트만 news.article_image.generate_article_image()로
다시 그린 뒤, 기사 승인 메시지를 다시 전송한다(telegram_gate.cmd_send_article 재사용).

사용법:
    python cloud/regen_article_image_and_notify.py --slot morning
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from news.article_image import generate_article_image  # noqa: E402
from cloud.telegram_gate import cmd_send_article, _send_message  # noqa: E402


def run(slot: str) -> bool:
    today = config.now_kst().strftime("%Y%m%d")
    articles_path = config.OUTPUT_DIR / today / f"v2_articles_{slot}.json"
    if not articles_path.exists():
        _send_message(f"⚠️ 그림 재생성 실패: {articles_path} 없음")
        return False

    import json
    data = json.loads(articles_path.read_text(encoding="utf-8"))
    articles = data.get("articles", [])
    if not articles:
        _send_message(f"⚠️ 그림 재생성 실패: articles 비어있음({slot})")
        return False

    article = articles[0]
    category = article.get("category", "hot")
    title = article.get("title", "")
    lead = article.get("lead") or article.get("card_summary", "")
    img_path = ROOT / "web" / "v2" / "img" / f"{today}_{category}.png"

    for attempt in range(3):
        style, _scene = generate_article_image(category, title, lead, img_path)
        if style and style != "F":
            break
    else:
        _send_message(f"⚠️ [{slot}] 메인 일러스트 재생성 실패 (3회 시도 모두 실패)")
        return False

    cmd_send_article(SimpleNamespace(slot=slot))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True)
    args = parser.parse_args()
    ok = run(args.slot)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
