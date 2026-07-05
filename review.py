"""도토리뉴스 텔레그램 리뷰 — 기사+이미지 전송 후 승인/반려 대기, 마감 도달 시 카드 빌드까지 트리거.

2026-06-26 재설계: 카드 조립(main.py)을 더 이상 고정 시각(06:55)에 별도로 실행하지 않는다.
이 스크립트가 마감을 직접 들고 있다가, 마감이 되거나 "전체 승인"을 누르면 그 자리에서
main.py를 호출해 카드 빌드+사이트 배포+인스타 업로드까지 끝내고 텔레그램으로 결과를 알린다.

마감 규칙: deadline = max(기준 마감, 마지막 "재생성" 클릭 시각 + 10분)
  - 기준 마감은 기본 오늘 06:55. 컴퓨터를 늦게 켠 날(캐치업)에는 --deadline-ts로
    "PC 시작 + 60분" 같은 다른 절대 시각을 넘겨받는다.
  - 재생성을 누르면 그 즉시 시간과 무관하게 마감이 (그 시각 + 10분)으로 늘어난다.
    여러 번 누르면 그때마다 다시 늘어난다 (무제한).

2026-06-29 재설계: 하루 4슬롯(아침/점심/저녁/야식)으로 나뉘면서, 기사도 한 번에 1개만
다룬다. 2026-07-02: 슬롯이 더 이상 카테고리에 고정되지 않아 --slot으로 어느 슬롯인지
받아서 그 슬롯 파일/플래그만 본다 (실제 카테고리는 그 슬롯 기사 데이터 안에 들어있음).

사용법:
    python -X utf8 review.py --slot morning                          # 기준 마감 = 오늘 06:55
    python -X utf8 review.py --slot morning --deadline-ts "2026-06-29T07:10:00"
    python -X utf8 review.py --slot morning --dry-run                # main.py --dry-run으로 빌드 (테스트용)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

_env = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env, encoding="utf-8", override=True)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

V2_DIR   = Path(__file__).parent / "web" / "v2"
IMG_DIR  = V2_DIR / "img"
TODAY    = datetime.now().strftime("%Y%m%d")

CAT_LABEL = {"hot": "🔥 핫뉴스", "economy": "💰 경제·IT", "culture": "🎵 트렌드"}
VALID_SLOTS = ("morning", "lunch", "evening", "night")

REGEN_EXTENSION_MIN = 10  # 재생성 클릭 시 마감을 이만큼 뒤로 늘림

# --slot(필수) / --deadline-ts ISO시각 / --dry-run 파싱
_args = sys.argv[1:]
_dry_run = "--dry-run" in _args
_slot = None
if "--slot" in _args:
    _idx = _args.index("--slot")
    if _idx + 1 < len(_args):
        _slot = _args[_idx + 1]
if _slot not in VALID_SLOTS:
    print(f"사용법: python review.py --slot {'|'.join(VALID_SLOTS)} [--deadline-ts ISO] [--dry-run]")
    sys.exit(2)

FLAG_OK = V2_DIR / f".approved_{TODAY}_{_slot}"
FLAG_NO = V2_DIR / f".rejected_{TODAY}_{_slot}"

_deadline_ts: datetime
_deadline_arg = None
for i, arg in enumerate(_args):
    if arg == "--deadline-ts" and i + 1 < len(_args):
        _deadline_arg = _args[i + 1]
if _deadline_arg:
    _deadline_ts = datetime.fromisoformat(_deadline_arg)
else:
    # 2026-07-03: 하드코딩된 06:55는 항상 아침 슬롯 기준이라, --deadline-ts 없이 다른
    # 슬롯을 수동 실행하면 이미 지난 시각으로 잡혀서 기사 승인 대기를 건너뛰고 바로
    # 마감 처리돼버리는 버그가 있었음 — 슬롯별 실제 시각(daily_runner.SLOT_CONFIG)을 따름.
    from daily_runner import SLOT_CONFIG
    _default_hour = SLOT_CONFIG.get(_slot, {}).get("hour", 6)
    _deadline_ts = datetime.now().replace(hour=_default_hour, minute=55, second=0, microsecond=0)


def _get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 30,
                    "allowed_updates": ["callback_query", "message"]},
            timeout=35,
        )
        if r.ok:
            return r.json().get("result", [])
    except Exception as e:
        print(f"[review] getUpdates 오류: {e}")
    return []


def _answer(callback_id: str, text: str = ""):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def _remove_buttons(chat_id, message_id):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup",
            json={"chat_id": chat_id, "message_id": message_id,
                  "reply_markup": json.dumps({})},
            timeout=10,
        )
    except Exception:
        pass


def _send_article(article: dict, idx: int, total: int) -> int | None:
    """기사 1개를 이미지+버튼으로 전송. 전송된 message_id 반환."""
    cat   = article.get("category", "")
    title = article.get("title", "")
    lead  = article.get("lead", "")
    label = CAT_LABEL.get(cat, cat.upper())

    img_name = f"{TODAY}_{cat}.png"
    img_path = IMG_DIR / img_name

    warning = "\n\n⚠️ 내용과 안 맞을 수 있어요 — 잘 봐주세요" if article.get("image_mismatch_suspected") else ""
    if article.get("fallback_used"):
        warning += "\n\n⚠️ AI 합성이 실패해서 간단 규칙기반 문구로 대체됐어요 — 품질 확인 필요"
    caption = (
        f"{label}\n\n"
        f"<b>{title}</b>\n\n"
        f"{lead}"
        f"{warning}"
    )
    # 2026-06-29: 슬롯당 기사 1개라 "전체 승인" 같은 구분이 필요 없어짐 — 승인/재생성 버튼을
    # 기사 카드 자체에 바로 달고, 별도 요약 메시지는 없앰
    markup = {
        "inline_keyboard": [
            [{"text": "✅ 승인 → 배포", "callback_data": "approve_all"},
             {"text": "🔄 이미지 재생성", "callback_data": f"regen_{cat}"}],
            [{"text": "❌ 반려 (오늘 이 게시물 취소)", "callback_data": "reject_all"}],
        ]
    }

    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML",
            "reply_markup": json.dumps(markup)}

    # 사진은 무조건 보여드려야 의미가 있어서(텍스트만 가면 판단을 못 하심 — 2026-06-28),
    # 텍스트로 대체하지 않고 사진이 실제로 도착할 때까지 강하게 재시도한다.
    # 뒤로 갈수록 타임아웃을 늘리고, 마지막 시도들은 이미지를 가볍게 압축해서 보냄
    # (느린 네트워크에서 큰 원본 파일이 자꾸 타임아웃나는 걸 우회).
    TIMEOUTS = [30, 30, 45, 45, 60, 60]
    SLEEP_BETWEEN = [5, 10, 15, 20, 30]
    COMPRESS_FROM_ATTEMPT = 4  # 5번째 시도부터 압축본 사용

    last_err = None
    photo_bytes = None
    if img_path.exists():
        photo_bytes = img_path.read_bytes()

    for attempt, timeout in enumerate(TIMEOUTS):
        try:
            if photo_bytes is not None:
                send_bytes = photo_bytes
                if attempt >= COMPRESS_FROM_ATTEMPT:
                    send_bytes = _compress_image(photo_bytes)
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    data=data, files={"photo": ("image.jpg", send_bytes)}, timeout=timeout,
                )
            else:
                markup_text = {"chat_id": CHAT_ID, "text": caption,
                               "parse_mode": "HTML", "reply_markup": json.dumps(markup)}
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json=markup_text, timeout=15,
                )
            if r.ok:
                return r.json().get("result", {}).get("message_id")
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
        if attempt < len(SLEEP_BETWEEN):
            print(f"[review] {cat} 사진 전송 실패 (시도 {attempt + 1}/{len(TIMEOUTS)}): "
                  f"{last_err} — {SLEEP_BETWEEN[attempt]}초 후 재시도")
            time.sleep(SLEEP_BETWEEN[attempt])

    # 여기까지 왔으면 정말 다 실패한 것 — 그래도 버튼은 받아보게 텍스트로 최후 시도
    print(f"[review] {cat} 사진 전송 끝까지 실패 — 텍스트로 최후 전송: {last_err}")
    try:
        markup_text = {"chat_id": CHAT_ID,
                        "text": f"⚠️ (사진이 끝까지 전송 안 됨 — 텍스트만) {caption}",
                        "parse_mode": "HTML", "reply_markup": json.dumps(markup)}
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=markup_text, timeout=15,
        )
        if r.ok:
            return r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[review] {cat} 텍스트 대체 전송도 실패: {e}")
    return None


def _compress_image(image_bytes: bytes, max_side: int = 720, quality: int = 75) -> bytes:
    """느린 네트워크에서 원본 PNG가 자꾸 타임아웃날 때 쓰는 가벼운 JPEG 버전."""
    import io
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = im.size
    scale = max_side / max(w, h)
    if scale < 1:
        im = im.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


FEEDBACK_TIMEOUT_MIN = 10


def _ask_for_feedback(cat: str, articles: list, awaiting_feedback: dict):
    """피드백 답장 요청만 보내고 즉시 리턴 (non-blocking) — 다른 카테고리 처리를 막지 않음."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": f"🔄 {cat} 재생성 — 반영할 피드백을 답장으로 입력해주세요 "
                        f"(없으면 '없음', {FEEDBACK_TIMEOUT_MIN}분 안에).",
                "reply_markup": json.dumps({
                    "force_reply": True,
                    "input_field_placeholder": "피드백 입력 (없으면 '없음')",
                }),
            },
            timeout=15,
        )
        if not r.ok:
            print(f"[review] {cat} 피드백 요청 메시지 전송 실패 — 피드백 없이 재생성")
            _regen_image(cat, articles, "")
            return
        ask_msg_id = r.json().get("result", {}).get("message_id")
        awaiting_feedback[cat] = {"ask_msg_id": ask_msg_id,
                                   "deadline": time.time() + FEEDBACK_TIMEOUT_MIN * 60}
    except Exception as e:
        print(f"[review] {cat} 피드백 요청 전송 실패: {e}")
        _regen_image(cat, articles, "")


_last_scene: dict[str, dict] = {}  # 카테고리별 마지막으로 쓴 장면 — 재생성 시 재사용(2026-07-03)


def _regen_image(cat: str, articles: list, feedback: str):
    """실제 이미지 재생성 후 재전송 (피드백은 이미 받은 상태로 호출됨).
    2026-07-03: 재생성 버튼을 누를 때마다 장면(공간/구도)을 처음부터 새로 설계해서
    "이 그림 마음에 드는데 이 부분만 고쳐줘" 피드백을 줘도 매번 완전히 다른 그림이
    나오는 문제가 있었음 — 직전 재생성에서 쓴 장면을 그대로 재사용하도록 고침."""
    from notify import send
    print(f"[review] {cat} 이미지 재생성 중... (피드백: {feedback or '없음'})")
    article = next((a for a in articles if a["category"] == cat), None)
    if not article:
        return

    from news.article_image import generate_article_image
    body = " ".join(article.get("body", [])[:1])
    img_path = IMG_DIR / f"{TODAY}_{cat}.png"
    scene_out: dict = {}
    style, scene, mismatch, tone = generate_article_image(
        cat, article["title"], article.get("lead", ""),
        img_path, body=body, feedback=feedback,
        reuse_scene=_last_scene.get(cat), scene_out=scene_out)
    if scene_out:
        _last_scene[cat] = scene_out

    if style:
        print(f"[review] {cat} 재생성 완료 ({style}, 내용 적합성 의심={mismatch})")
        article["image_mismatch_suspected"] = mismatch
        article["tone"] = tone
        if feedback:
            send(f"✅ {cat} 재생성 완료 (반영한 피드백: {feedback})")
        idx = next((i for i, a in enumerate(articles, 1) if a["category"] == cat), 0)
        _send_article(article, idx, len(articles))
    else:
        send(f"⚠️ {cat} 이미지 재생성 실패 — 기존 이미지 유지")


REGEN_BUFFER_MIN = 5  # 재생성(보통 1~1.5분)이 끝날 여유가 이만큼 안 남았을 때만 마감을 늘림


def _extend_deadline(state: dict, reason: str):
    """재생성 버튼을 눌렀을 때, 마감까지 남은 시간이 REGEN_BUFFER_MIN보다 적을 때만
    마감을 (지금+10분)으로 늘림. 여유가 충분하면 굳이 미룰 필요 없음 — 재생성이 보통
    1~1.5분이면 끝나서 5분 버퍼면 충분히 마감 전에 끝남."""
    now = datetime.now()
    remaining = state["deadline"] - now
    if remaining >= timedelta(minutes=REGEN_BUFFER_MIN):
        print(f"[review] 마감 연장 불필요 ({reason}): 마감까지 {remaining.seconds // 60}분 남음")
        return
    candidate = now + timedelta(minutes=REGEN_EXTENSION_MIN)
    print(f"[review] 마감 연장 ({reason}): {state['deadline']:%H:%M:%S} → {candidate:%H:%M:%S}")
    state["deadline"] = candidate


def _trigger_build():
    """main.py를 호출해 카드 빌드+배포(+업로드)까지 진행하고, 결과를 텔레그램으로 알림."""
    from notify import send
    print(f"[review] [{_slot}] 카드 빌드 트리거 (dry_run={_dry_run})")
    args = [sys.executable, "-X", "utf8", "main.py", "--slot", _slot] + (["--dry-run"] if _dry_run else [])
    result = subprocess.run(args, cwd=Path(__file__).parent)
    if result.returncode == 0:
        if _dry_run:
            send("✅ [TEST] 카드뉴스 빌드 테스트 완료 (배포/업로드 안 함)")
        else:
            send("✅ 도토리뉴스 카드뉴스 빌드 + 사이트 배포 완료!")
    else:
        send(f"⚠️ 카드뉴스 빌드 실패 (exit code {result.returncode}) — 로그 확인 필요")
    return result.returncode == 0


# ── 2026-07-02: 카드뉴스 이미지 승인 단계 (기사 승인 다음 두 번째 게이트) ──────────
# 기사 승인 → 카드 생성(배포/업로드 없이) → 텔레그램으로 전송 + 승인 대기
# → 승인되면 슬롯 :55까지 기다렸다가 그때 실제 배포(인스타+블로그).
# 2026-07-03: "viewpoint"(서로 다른 시각)가 처음에 빠져있어서 has_viewpoint_diff=true인
# 기사에서도 텔레그램에 5장만 오고 실제로는 있는 6번째 카드가 승인 대상에서 누락됐었음
# — has_viewpoint_diff가 아닌 기사는 파일 자체가 없어서 _card_paths()가 알아서 건너뜀.
CARD_NAMES = ["cover", "fact", "viewpoint", "why", "outlook"]
CARD_LABELS = {"cover": "커버", "fact": "오늘의 사실", "viewpoint": "서로 다른 시각",
               "why": "왜 중요할까요?", "outlook": "앞으로는?"}


def _trigger_card_build_only() -> bool:
    """카드 5장만 생성(배포/업로드 없이) — main.py --dry-run 재사용(빌드+검증까지만 하고
    파일은 그대로 run_dir에 남기는 기존 동작을 그대로 씀)."""
    print(f"[review] [{_slot}] 카드뉴스 이미지 생성 중 (배포 전)...")
    args = [sys.executable, "-X", "utf8", "main.py", "--slot", _slot, "--dry-run"]
    result = subprocess.run(args, cwd=Path(__file__).parent)
    return result.returncode == 0


def _card_paths() -> dict[str, Path]:
    import config
    run_dir = config.OUTPUT_DIR / TODAY
    paths = {}
    for name in CARD_NAMES + ["outro"]:
        matches = sorted(run_dir.glob(f"{_slot}_*_{name}.png"))
        if matches:
            paths[name] = matches[0]
    return paths


def _send_cards_for_approval() -> dict[str, int]:
    """카드 5장을 순서대로 보내고, 마지막에 전체승인/카드별 재생성 버튼이 달린 요약 메시지를 보낸다.
    반환: {"summary": message_id} (버튼 없는 부분은 추적 불필요)."""
    paths = _card_paths()
    order = CARD_NAMES + ["outro"]
    for name in order:
        p = paths.get(name)
        if not p or not p.exists():
            continue
        try:
            with open(p, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    data={"chat_id": CHAT_ID, "caption": CARD_LABELS.get(name, name)},
                    files={"photo": (p.name, f)}, timeout=30,
                )
        except Exception as e:
            print(f"[review] 카드 이미지 전송 실패({name}): {e}")
        time.sleep(0.5)

    # viewpoint는 이 기사에 실제로 있을 때만 재생성 버튼 노출(없으면 파일 자체가 없어 눌러도 실패함)
    regen_rows = [
        [{"text": f"🔄 {CARD_LABELS['cover']}", "callback_data": "cards_regen_cover"},
         {"text": f"🔄 {CARD_LABELS['fact']}", "callback_data": "cards_regen_fact"}],
    ]
    if "viewpoint" in paths:
        regen_rows.append(
            [{"text": f"🔄 {CARD_LABELS['viewpoint']}", "callback_data": "cards_regen_viewpoint"}]
        )
    regen_rows.append(
        [{"text": f"🔄 {CARD_LABELS['why']}", "callback_data": "cards_regen_why"},
         {"text": f"🔄 {CARD_LABELS['outlook']}", "callback_data": "cards_regen_outlook"}]
    )
    markup = {
        "inline_keyboard": [
            [{"text": "✅ 전체승인", "callback_data": "cards_approve_all"}],
            *regen_rows,
        ]
    }
    msg_id = None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID,
                  "text": "위 카드뉴스 5장 확인해주세요. 전체승인 또는 카드별 재생성을 눌러주세요.",
                  "reply_markup": json.dumps(markup)},
            timeout=15,
        )
        if r.ok:
            msg_id = r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[review] 카드 승인 버튼 전송 실패: {e}")
    return {"summary": msg_id} if msg_id else {}


def _regen_card(card_name: str):
    """main.regenerate_single_card()로 카드 1장만 다시 만들고 재전송."""
    from notify import send
    import main as main_module
    print(f"[review] 카드 재생성: {card_name}")
    out_path = main_module.regenerate_single_card(_slot, card_name)
    if not out_path:
        send(f"⚠️ {CARD_LABELS.get(card_name, card_name)} 카드 재생성 실패")
        return
    try:
        with open(out_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": f"🔄 재생성됨: {CARD_LABELS.get(card_name, card_name)}"},
                files={"photo": (out_path.name, f)}, timeout=30,
            )
    except Exception as e:
        print(f"[review] 재생성 카드 전송 실패: {e}")


def _schedule_publish_task(publish_at: datetime) -> bool:
    """Windows 작업 스케줄러에 슬롯:55 1회성 작업을 등록해 scheduled_publish.py를 그 시각에
    실행시킨다. review.py 프로세스의 생존 여부와 무관하게 OS가 실행을 보장한다."""
    task_name = f"DotoryPublish_{_slot}"
    script_dir = Path(__file__).resolve().parent
    cmd = f'"{sys.executable}" -X utf8 scheduled_publish.py --slot {_slot}'
    tr = f'cmd /c "cd /d {script_dir} && {cmd}"'
    args = [
        "schtasks", "/create", "/tn", task_name, "/tr", tr,
        "/sc", "once",
        "/sd", publish_at.strftime("%Y/%m/%d"),  # 한국어 Windows 로캘 기준 날짜 형식
        "/st", publish_at.strftime("%H:%M"),
        "/f",  # 같은 이름 있으면 덮어씀
    ]
    # schtasks는 한국어 Windows에서 콘솔 코드페이지(cp949)로 출력하므로 utf-8로 그대로
    # 디코딩하면 깨짐 — errors="replace"로 안전하게 받는다.
    result = subprocess.run(args, capture_output=True, text=True, encoding="cp949", errors="replace")
    if result.returncode != 0:
        print(f"[review] 작업 스케줄러 등록 실패: {(result.stderr or '').strip()}")
        return False
    print(f"[review] 작업 스케줄러에 '{task_name}' 등록 완료 ({publish_at:%m/%d %H:%M})")
    return True


def _wait_until_slot_deadline_and_publish():
    """카드 승인 이후 슬롯 시각:55에 배포되도록 처리한다.
    2026-07-05: 예전엔 이 프로세스가 time.sleep(wait_sec)로 직접 몇십 분을 대기하다가
    main.py --publish-only를 호출했는데, 그 사이 프로세스가 죽으면(강제종료·PC 절전·크래시
    등 — 실제로 07-05 저녁한입에서 발생) 배포가 통째로 누락되고 알림도 없었음. 이제는
    Windows 작업 스케줄러에 정확한 시각의 1회성 작업(scheduled_publish.py 실행)을 등록만
    해두고 이 프로세스는 바로 끝난다 — review.py가 살아있지 않아도 OS가 대신 실행해준다.
    단, 마감이 이미 지났으면(캐치업 등) 예약할 필요 없이 바로 배포한다."""
    from notify import send
    from daily_runner import SLOT_CONFIG  # 시각 매핑을 여기 따로 하드코딩하면 나중에 어긋날 위험 — 단일 소스 참조
    cfg_hour = SLOT_CONFIG[_slot]["hour"]
    publish_at = datetime.now().replace(hour=cfg_hour, minute=55, second=0, microsecond=0)
    now = datetime.now()

    if now >= publish_at:
        print("[review] 카드 승인 시점에 이미 게시 시각 지남 — 즉시 배포")
        args = [sys.executable, "-X", "utf8", "main.py", "--slot", _slot, "--publish-only"]
        result = subprocess.run(args, cwd=Path(__file__).parent)
        if result.returncode == 0:
            send(f"✅ 도토리뉴스 [{_slot}] 사이트+인스타 업로드 완료! (블로그는 별도 알림 확인)")
        else:
            send(f"⚠️ [{_slot}] 배포 실패 (exit code {result.returncode}) — 로그 확인 필요")
        return result.returncode == 0

    print(f"[review] 카드 승인 완료 — {publish_at:%H:%M}에 배포되도록 작업 스케줄러 등록")
    if _schedule_publish_task(publish_at):
        send(f"✅ 카드뉴스 승인 완료! {publish_at:%H:%M}에 인스타+블로그 업로드할게요 "
             f"(작업 스케줄러 예약 — 이 창을 꺼도 진행돼요).")
        return True
    else:
        # 스케줄 등록 자체가 실패하면 기존 방식(직접 대기)으로 폴백 — 최소한 이번 한 번은 보장
        wait_sec = (publish_at - now).total_seconds()
        print(f"[review] 스케줄 등록 실패 — 기존 방식으로 직접 대기 ({int(wait_sec)}초)")
        send(f"⚠️ 작업 스케줄러 등록 실패 — 이 창을 계속 켜두셔야 {publish_at:%H:%M}에 배포돼요.")
        time.sleep(wait_sec)
        args = [sys.executable, "-X", "utf8", "main.py", "--slot", _slot, "--publish-only"]
        result = subprocess.run(args, cwd=Path(__file__).parent)
        if result.returncode == 0:
            send(f"✅ 도토리뉴스 [{_slot}] 사이트+인스타 업로드 완료! (블로그는 별도 알림 확인)")
        else:
            send(f"⚠️ [{_slot}] 배포 실패 (exit code {result.returncode}) — 로그 확인 필요")
        return result.returncode == 0


def run_card_approval() -> bool:
    """카드 5장 생성 → 텔레그램 전송+승인 대기 → 승인되면 :55까지 대기 후 실제 배포.
    반려/타임아웃 없이 승인 버튼이 눌릴 때까지 무기한 대기(기사 승인은 이미 끝난 뒤라
    사람이 어차피 봐야 하는 마지막 게이트)."""
    if not _trigger_card_build_only():
        from notify import send
        send(f"⚠️ [{_slot}] 카드뉴스 이미지 생성 실패 — 로그 확인 필요")
        return False

    print(f"[review] [{_slot}] 카드 5장 텔레그램 전송 중...")
    _send_cards_for_approval()

    offset = 0
    while True:
        updates = _get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            cq = upd.get("callback_query")
            if not cq:
                continue
            data = cq.get("data", "")
            cq_id = cq["id"]
            chat_id = cq["message"]["chat"]["id"]
            msg_id = cq["message"]["message_id"]

            if data == "cards_approve_all":
                _answer(cq_id, "✅ 승인!")
                _remove_buttons(chat_id, msg_id)
                print("[review] 카드 전체승인")
                return _wait_until_slot_deadline_and_publish()

            elif data.startswith("cards_regen_"):
                card_name = data.replace("cards_regen_", "")
                _answer(cq_id, f"🔄 {CARD_LABELS.get(card_name, card_name)} 재생성 중...")
                _regen_card(card_name)


def run():
    import config
    data_path = config.OUTPUT_DIR / TODAY / f"v2_articles_{_slot}.json"
    if not data_path.exists():
        print(f"[review] [{_slot}] 작업용 데이터 없음 — v2_main.py --slot {_slot} 먼저 실행 필요")
        from notify import send
        send(f"⚠️ 도토리뉴스 리뷰 실패({_slot}): 오늘 데이터 없음")
        sys.exit(1)

    articles = json.loads(data_path.read_text(encoding="utf-8")).get("articles", [])
    if not articles:
        print("[review] 기사 없음")
        sys.exit(1)

    print(f"[review] 기사 {len(articles)}개 텔레그램 전송 중...")

    # 기사별 전송
    msg_ids = {}
    for i, a in enumerate(articles, 1):
        mid = _send_article(a, i, len(articles))
        if mid:
            msg_ids[a["category"]] = mid
        time.sleep(1)

    state = {"deadline": _deadline_ts}
    print(f"[review] 전송 완료. 마감: {state['deadline']:%Y-%m-%d %H:%M:%S} "
          f"(마감 {REGEN_BUFFER_MIN}분 전 안에 재생성 누르면 그 시점부터 +{REGEN_EXTENSION_MIN}분 연장, "
          f"그 전이면 연장 안 함)")

    # 콜백 폴링
    offset = 0
    awaiting_feedback: dict[str, dict] = {}  # cat -> {ask_msg_id, deadline} — 여러 카테고리 동시 대기 가능

    while datetime.now() < state["deadline"]:
        # 피드백 답장 대기 타임아웃 체크 — 응답 없으면 피드백 없이 재생성 진행
        for cat, info in list(awaiting_feedback.items()):
            if time.time() > info["deadline"]:
                awaiting_feedback.pop(cat, None)
                from notify import send
                send(f"⏰ {cat} 피드백 응답 없음 — 피드백 없이 재생성해요")
                _regen_image(cat, articles, "")
                _extend_deadline(state, f"{cat} 피드백 타임아웃 재생성")

        updates = _get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1

            # 피드백 답장(message) 처리 — 여러 카테고리가 동시에 대기 중이어도 각자 매칭
            msg = upd.get("message")
            if msg:
                reply_to = msg.get("reply_to_message") or {}
                ask_id = reply_to.get("message_id")
                matched_cat = next((c for c, info in awaiting_feedback.items()
                                     if info["ask_msg_id"] == ask_id), None)
                if matched_cat:
                    awaiting_feedback.pop(matched_cat, None)
                    text = (msg.get("text") or "").strip()
                    feedback = "" if text in ("없음", "no", "NO") else text
                    _regen_image(matched_cat, articles, feedback)
                    _extend_deadline(state, f"{matched_cat} 피드백 반영 재생성")
                continue

            cq = upd.get("callback_query")
            if not cq:
                continue

            data    = cq.get("data", "")
            cq_id   = cq["id"]
            chat_id = cq["message"]["chat"]["id"]
            msg_id  = cq["message"]["message_id"]

            if data == "approve_all":
                _answer(cq_id, "✅ 승인! 카드뉴스 만들게요")
                _remove_buttons(chat_id, msg_id)
                FLAG_OK.write_text("approved", encoding="utf-8")
                from notify import send
                send("✅ 기사 승인 완료! 카드뉴스 5장 만들고 있어요 🎨")
                print("[review] 기사 승인 완료 → approved 플래그 저장, 카드 생성 단계로")
                if _dry_run:
                    return _trigger_build()  # 테스트 모드는 기존 단일단계 그대로
                return run_card_approval()

            elif data == "reject_all":
                _answer(cq_id, "❌ 반려됨")
                _remove_buttons(chat_id, msg_id)
                FLAG_NO.write_text("rejected", encoding="utf-8")
                from notify import send
                send("❌ 도토리뉴스 전체 반려\n오늘 배포가 취소됩니다.")
                print("[review] 전체 반려")
                return False

            elif data.startswith("regen_"):
                cat = data.replace("regen_", "")
                _answer(cq_id, f"🔄 {cat} 피드백 요청 전송...")
                _remove_buttons(chat_id, msg_id)
                _extend_deadline(state, f"{cat} 재생성 버튼 클릭")
                _ask_for_feedback(cat, articles, awaiting_feedback)  # non-blocking

    # 마감 도달 → 그 상태 그대로 카드 생성 단계로
    print(f"[review] 마감 도달 ({state['deadline']:%H:%M:%S}) → 지금 상태로 카드뉴스 생성")
    FLAG_OK.write_text("deadline-reached", encoding="utf-8")
    from notify import send
    send("⏰ 기사 승인 마감 도달 — 지금 상태로 카드뉴스 5장 만들고 있어요 🎨")
    if _dry_run:
        return _trigger_build()
    return run_card_approval()


if __name__ == "__main__":
    import run_log
    run_log.enable(f"review_{_slot}")
    # 2026-07-03: 이 프로세스가 PC 절전/예외 등으로 조용히 죽으면 카드도 승인 요청도
    # 아무 알림 없이 그냥 멈춰버려서, 사용자가 "왜 안 왔지"를 직접 물어봐야만 알아챘음
    # — 처리 안 된 예외가 여기까지 올라오면 최소한 텔레그램으로는 알리고 죽는다.
    try:
        result = run()
    except Exception as exc:
        try:
            from notify import notify_failure
            notify_failure(f"[{_slot}] review 프로세스가 예외로 중단됨: {exc}")
        except Exception:
            pass
        raise
    sys.exit(0 if result else 1)
