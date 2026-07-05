"""텔레그램 알림"""
import json
import os
import requests
from dotenv import load_dotenv
from pathlib import Path

_env = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env, encoding="utf-8", override=True)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


def ask_feedback(prompt_text: str, timeout_s: int = 180) -> str:
    """force_reply로 사용자에게 텍스트 피드백을 요청하고 답장을 기다림.
    답장이 '없음'/'no'/빈 문자열이거나 timeout_s 안에 응답이 없으면 빈 문자열 반환."""
    if not BOT_TOKEN or not CHAT_ID:
        return ""
    try:
        sent = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": prompt_text,
                "reply_markup": json.dumps({
                    "force_reply": True,
                    "input_field_placeholder": "피드백 입력 (없으면 '없음')",
                }),
            },
            timeout=15,
        )
        if not sent.ok:
            return ""
        ask_msg_id = sent.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[notify] ask_feedback 전송 실패: {e}")
        return ""

    import time
    offset = 0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            res = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 15, "allowed_updates": ["message"]},
                timeout=20,
            )
            updates = res.json().get("result", []) if res.ok else []
        except Exception:
            updates = []
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg:
                continue
            reply_to = msg.get("reply_to_message") or {}
            if reply_to.get("message_id") != ask_msg_id:
                continue
            text = (msg.get("text") or "").strip()
            return "" if text in ("없음", "no", "NO", "") else text
    print("[notify] ask_feedback 응답 없음 — 피드백 없이 진행")
    return ""


def send_photo(image_path: Path, caption: str, reply_markup: dict = None) -> dict:
    """이미지 + 캡션 + 버튼 전송. message 객체 반환 (실패 시 {})."""
    if not BOT_TOKEN or not CHAT_ID:
        return {}
    if not Path(image_path).exists():
        print(f"[notify] send_photo: 파일 없음 — {image_path}")
        return {}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data=data, files={"photo": f}, timeout=30,
            )
        if r.ok:
            return r.json().get("result", {})
    except Exception as e:
        print(f"[notify] send_photo 실패: {e}")
    return {}


def answer_callback(callback_query_id: str, text: str = ""):
    """콜백 쿼리 응답 (버튼 로딩 스피너 제거)."""
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def edit_message_reply_markup(chat_id, message_id, reply_markup=None):
    """메시지 버튼 제거 (승인/반려 후 버튼 사라지게)."""
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup",
            json={"chat_id": chat_id, "message_id": message_id,
                  "reply_markup": json.dumps(reply_markup or {})},
            timeout=10,
        )
    except Exception:
        pass


def send(message: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


_SLOT_LABELS = {"morning": "아침한입", "lunch": "점심한입", "evening": "저녁한입", "night": "야식한입"}


def notify_success(date_str: str, article: dict, slot: str = ""):
    """단일 주제(하루 3슬롯 중 하나) 업로드 완료 알림.
    2026-07-02: 예전 3카테고리 다이제스트 포맷 → 하루 3슬롯 단일주제 포맷으로 교체."""
    slot_label = _SLOT_LABELS.get(slot, "")
    title = article.get("title") or article.get("card_headline", "")
    msg = (
        f"📰 DO's TORY NEWS 업로드 완료 ({slot_label})\n"
        f"{date_str}\n\n"
        f"{title}"
    )
    send(msg)


def notify_story_success():
    send("📲 스토리 공유 완료")


def notify_failure(reason: str):
    send(f"❌ DO's TORY NEWS 업로드 실패\n원인: {reason}")


def notify_session_expired():
    send(
        "⚠️ Instagram 세션 만료됨\n\n"
        "오늘 밤 안에 갱신해주세요:\n"
        "1. Chrome → instagram.com 로그인\n"
        "2. F12 → Application → Cookies → sessionid 복사\n"
        "3. 터미널: python -X utf8 instagram_setup.py"
    )


def notify_session_ok():
    send("✅ Instagram 세션 정상")


def notify_token_warning(days_left: int, expires_on: str):
    if days_left <= 7:
        urgency = "🚨 긴급"
    else:
        urgency = "⚠️ 주의"
    msg = (
        f"{urgency} Instagram 토큰 만료 임박\n\n"
        f"만료일: {expires_on}\n"
        f"남은 기간: {days_left}일\n\n"
        f"지금 갱신하세요:\n"
        f"터미널 → python -X utf8 get_instagram_token.py"
    )
    send(msg)


def notify_source_failure(health: dict):
    counts = health.get("counts", {})
    errors = health.get("fetch_errors", [])
    critical = health.get("critical_categories", [])

    lines = ["⚠️ DO's TORY NEWS — 뉴스 소스 장애 감지\n"]

    if errors:
        lines.append("RSS 수집 오류:")
        for url in errors:
            # URL에서 도메인 추출해서 읽기 쉽게
            domain = url.split("/")[2] if "://" in url else url
            lines.append(f"  • {domain}")
        lines.append("")

    lines.append("카테고리별 수집 결과:")
    cat_labels = {"hot": "HOT 핫뉴스", "economy": "ECO 경제/IT", "culture": "TRD 트렌드"}
    for cat, cnt in counts.items():
        flag = " ❌ 부족" if cat in critical else ""
        lines.append(f"  {cat_labels.get(cat, cat)}: {cnt}건{flag}")

    if critical:
        lines.append("\n네이버 백업 소스로 전환됨")

    send("\n".join(lines))
