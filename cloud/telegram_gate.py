"""GitHub Actions용 텔레그램 승인 요청 CLI — review.py의 "보내고 끝" 부분만 재구현.

기존 review.py와 다른 점: 이 스크립트는 메시지를 보내고 **바로 종료**한다.
응답 대기(getUpdates 폴링)는 하지 않는다 — 응답은 Cloudflare Worker가 텔레그램
webhook으로 직접 받아서 GitHub repository_dispatch를 호출하는 방식으로 처리된다
(cloud/telegram_webhook_worker.js 참고).

이 파일은 새로 작성된 파일이며, review.py/notify.py를 수정하지 않고 그대로 둔 채
텔레그램 HTTP API만 독립적으로 다시 호출한다(로직은 review.py의 _send_article /
_send_cards_for_approval을 참고했지만 대기 로직 없이 "전송"만 담당하도록 새로 씀).

사용법:
    python cloud/telegram_gate.py send-article --slot morning
    python cloud/telegram_gate.py send-cards   --slot morning
    python cloud/telegram_gate.py notify --text "메시지"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(dotenv_path=ROOT / ".env", encoding="utf-8", override=True)

from config import now_kst

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TODAY = now_kst().strftime("%Y%m%d")

CAT_LABEL = {"hot": "🔥 핫뉴스", "economy": "💰 경제·IT", "culture": "🎵 트렌드"}
CARD_NAMES = ["cover", "fact", "viewpoint", "why", "outlook"]
CARD_LABELS = {
    "cover": "커버", "fact": "오늘의 사실", "viewpoint": "서로 다른 시각",
    "why": "왜 중요할까요?", "outlook": "앞으로는?",
}


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def _send_message(text: str, reply_markup: dict | None = None) -> int | None:
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(_api("sendMessage"), json=payload, timeout=15)
        if r.ok:
            return r.json().get("result", {}).get("message_id")
        print(f"[telegram_gate] sendMessage 실패: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[telegram_gate] sendMessage 예외: {e}")
    return None


def _send_photo(photo_bytes: bytes, filename: str, caption: str = "",
                 reply_markup: dict | None = None) -> int | None:
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(_api("sendPhoto"), data=data,
                           files={"photo": (filename, photo_bytes)}, timeout=45)
        if r.ok:
            return r.json().get("result", {}).get("message_id")
        print(f"[telegram_gate] sendPhoto 실패: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[telegram_gate] sendPhoto 예외: {e}")
    return None


def cmd_notify(args):
    ok = _send_message(args.text) is not None
    sys.exit(0 if ok else 1)


def cmd_send_article(args):
    """v2_articles_<slot>.json 을 읽어 기사 승인 요청 전송. review.py._send_article과
    동일한 캡션/버튼 구조를 새로 구현(대기 로직만 뺌). callback_data에 slot을 포함시켜
    Worker가 어느 슬롯인지 알 수 있게 한다(로컬 review.py는 프로세스별로 슬롯 고정이라
    이 정보가 필요 없었지만, 클라우드는 무상태 웹훅이라 콜백 자체에 슬롯을 실어야 한다)."""
    import config

    slot = args.slot
    run_dir = config.OUTPUT_DIR / TODAY
    data_path = run_dir / f"v2_articles_{slot}.json"
    if not data_path.exists():
        print(f"[telegram_gate] 데이터 없음: {data_path}")
        sys.exit(1)

    articles = json.loads(data_path.read_text(encoding="utf-8")).get("articles", [])
    if not articles:
        print("[telegram_gate] 기사 없음")
        sys.exit(1)

    article = articles[0]
    cat = article.get("category", "")
    title = article.get("title", "")
    lead = article.get("lead", "")
    label = CAT_LABEL.get(cat, cat.upper())

    img_path = (ROOT / "web" / "v2" / "img" / f"{TODAY}_{cat}.png")

    warning = ""
    if article.get("image_mismatch_suspected"):
        warning += "\n\n⚠️ 내용과 안 맞을 수 있어요 — 잘 봐주세요"
    if article.get("fallback_used"):
        warning += "\n\n⚠️ AI 합성이 실패해서 간단 규칙기반 문구로 대체됐어요"

    caption = f"{label}\n\n<b>{title}</b>\n\n{lead}{warning}"

    markup = {
        "inline_keyboard": [
            [{"text": "✅ 승인 → 카드 생성", "callback_data": f"art_approve|{slot}"},
             {"text": "🔄 재생성", "callback_data": f"art_regen|{slot}|{cat}"}],
            [{"text": "❌ 반려 (오늘 이 게시물 취소)", "callback_data": f"art_reject|{slot}"}],
        ]
    }

    msg_id = None
    if img_path.exists():
        msg_id = _send_photo(img_path.read_bytes(), "image.jpg", caption, markup)
    if msg_id is None:
        msg_id = _send_message(caption, markup)

    print(f"[telegram_gate] [{slot}] 기사 승인 요청 전송 완료 (message_id={msg_id})")
    sys.exit(0 if msg_id else 1)


def _card_paths(slot: str) -> dict[str, Path]:
    import config
    run_dir = config.OUTPUT_DIR / TODAY
    paths = {}
    for name in CARD_NAMES + ["outro"]:
        matches = sorted(run_dir.glob(f"{slot}_*_{name}.png"))
        if matches:
            paths[name] = matches[0]
    return paths


def cmd_send_cards(args):
    """main.py --dry-run이 만들어둔 카드 이미지들을 순서대로 전송 + 승인 버튼."""
    slot = args.slot
    paths = _card_paths(slot)
    if not paths:
        print(f"[telegram_gate] [{slot}] 카드 이미지 없음 — main.py --dry-run 먼저 실행 필요")
        sys.exit(1)

    order = CARD_NAMES + ["outro"]
    for name in order:
        p = paths.get(name)
        if not p or not p.exists():
            continue
        _send_photo(p.read_bytes(), p.name, CARD_LABELS.get(name, name))
        time.sleep(0.4)

    regen_rows = [
        [{"text": f"🔄 {CARD_LABELS['cover']}", "callback_data": f"card_regen|{slot}|cover"},
         {"text": f"🔄 {CARD_LABELS['fact']}", "callback_data": f"card_regen|{slot}|fact"}],
    ]
    if "viewpoint" in paths:
        regen_rows.append(
            [{"text": f"🔄 {CARD_LABELS['viewpoint']}", "callback_data": f"card_regen|{slot}|viewpoint"}]
        )
    regen_rows.append(
        [{"text": f"🔄 {CARD_LABELS['why']}", "callback_data": f"card_regen|{slot}|why"},
         {"text": f"🔄 {CARD_LABELS['outlook']}", "callback_data": f"card_regen|{slot}|outlook"}]
    )
    markup = {
        "inline_keyboard": [
            [{"text": "✅ 전체승인 → 배포", "callback_data": f"card_approve|{slot}"},
             {"text": "❌ 전체 반려 (오늘 이 슬롯 취소)", "callback_data": f"card_reject|{slot}"}],
            *regen_rows,
        ]
    }
    msg_id = _send_message(
        "위 카드뉴스 확인해주세요. 전체승인 또는 카드별 재생성을 눌러주세요.", markup)
    print(f"[telegram_gate] [{slot}] 카드 승인 요청 전송 완료 (message_id={msg_id})")
    sys.exit(0 if msg_id else 1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_notify = sub.add_parser("notify")
    p_notify.add_argument("--text", required=True)
    p_notify.set_defaults(func=cmd_notify)

    p_art = sub.add_parser("send-article")
    p_art.add_argument("--slot", required=True)
    p_art.set_defaults(func=cmd_send_article)

    p_cards = sub.add_parser("send-cards")
    p_cards.add_argument("--slot", required=True)
    p_cards.set_defaults(func=cmd_send_cards)

    args = parser.parse_args()
    if not BOT_TOKEN or not CHAT_ID:
        print("[telegram_gate] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정")
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
