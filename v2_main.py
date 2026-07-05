"""도토리뉴스 v2 — 다수 소스 수집 → 팩트 합성 → 일러스트 생성

여기서 만든 결과(article 본문/이미지)는 main.py가 가져다 루트 사이트(news.mydotory.com)
카드와 web/data.json에 반영함. 이 파일은 별도 페이지를 만들지 않음 — 작업용 데이터만 생성.

사용법:
    python -X utf8 v2_main.py --slot morning --fresh --exclude economy,culture
    # --slot: 슬롯별 파일 분리(morning/lunch/evening/night)
    # --fresh: 뉴스 수집·큐레이션부터 새로 실행
    # --exclude: 오늘 다른 슬롯에서 이미 쓴 카테고리(쉼표구분) — 카테고리 중복 방지
    # --deploy: 생성 후 Firebase 배포 (전체 호스팅 재배포)
    # --deploy-only: 생성 없이 배포만 (승인 플래그 확인 후)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import json
import subprocess
from datetime import datetime
from pathlib import Path

import config
from pipeline_lock import pipeline_lock

V2_DIR = Path(__file__).parent / "web" / "v2"
CAT_META = {
    "hot":     {"code": "HOT", "label": "핫뉴스"},
    "economy": {"code": "ECO", "label": "경제·IT"},
    "culture": {"code": "TRD", "label": "트렌드"},
}


def _curated_filename(slot: str | None) -> str:
    """슬롯별로 하루 4번 따로 도는 구조라, 슬롯이 주어지면 파일도 따로 써서
    같은 날 다른 시간대 슬롯끼리 덮어쓰지 않게 함. 슬롯 없으면(구버전 호환) 통합 파일."""
    return f"v2_curated_{slot}.json" if slot else "v2_curated.json"


def _load_today_curated(slot: str | None = None) -> dict:
    today = config.now_kst().strftime("%Y%m%d")
    candidates = [config.OUTPUT_DIR / today / _curated_filename(slot)]
    if not slot:
        # 1순위: 메인 파이프라인의 오늘 큐레이션 (구버전 호환)
        candidates.insert(0, config.OUTPUT_DIR / today / "curated.json")
    for p in candidates:
        if p.exists():
            print(f"[v2] 오늘 큐레이션 재사용: {p}")
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _save_v2_curated(curated: dict, slot: str | None = None):
    today = config.now_kst().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / _curated_filename(slot), "w", encoding="utf-8") as f:
        json.dump(curated, f, ensure_ascii=False, indent=2)


def _fresh_curation(exclude_categories: list = None) -> dict:
    """2026-07-02: 슬롯이 더 이상 카테고리에 고정되지 않음 — hot/economy/culture 전체
    후보 중 그 시간대 가장 화제성 높은 기사 하나를 뽑는다. exclude_categories로 오늘
    다른 슬롯에서 이미 쓴 카테고리는 제외해 하루 안 카테고리가 안 겹치게 한다."""
    from news.collector import fetch_all_news
    from news.curator import curate_any
    from news_archive import get_used_links

    news, _health = fetch_all_news()
    used_links = get_used_links(days=7)  # 오늘 다른 슬롯에서 이미 쓴 기사도 자동 포함됨
    print(f"\n[v2] Gemini 큐레이션 중 (카테고리 무관, 제외: {exclude_categories or '없음'})...")
    result = curate_any(news, used_links, exclude_categories=exclude_categories)
    picked_cat = result.pop("_picked_category", "hot")
    print(f"[v2] 선정된 카테고리: {picked_cat}")
    return {picked_cat: result}


def build_articles(curated: dict) -> list[dict]:
    """카테고리별 다수 소스 수집 + 팩트 합성 → v2 기사 목록"""
    from news.multi_source import collect_sources
    from news.synthesizer import synthesize_or_fallback
    from news.article_image import generate_article_image

    articles = []
    used_scenes: list[str] = []
    for cat, data in curated.items():
        if not data or not data.get("card_headline"):
            print(f"[v2] {cat}: 큐레이션 데이터 없음, 건너뜀")
            continue
        headline = data.get("article_title") or data.get("card_headline", "")
        print(f"\n[v2] ===== {cat.upper()}: {headline} =====")

        sources = collect_sources(
            headline,
            primary_link=data.get("article_link", ""),
            primary_source=data.get("source_name", ""),
        )
        if not sources:
            print(f"[v2] {cat}: 소스 확보 실패, 건너뜀")
            continue

        synth = synthesize_or_fallback(sources)
        if not synth:
            print(f"[v2] {cat}: 합성 실패(폴백도 실패), 건너뜀")
            continue
        if synth.get("_fallback_used"):
            print(f"[v2] {cat}: ⚠️ AI 합성 실패 — 규칙 기반 쉬운설명 폴백으로 진행")

        # 기사 일러스트 생성 (모든 기사 1장 보장 — 실패 시 카테고리 폴백)
        today = config.now_kst().strftime("%Y%m%d")
        img_name = f"{today}_{cat}.png"
        body_text = " ".join(synth.get("body", [])[:1])  # 첫 문단만
        img_style, img_scene, img_mismatch, img_tone = generate_article_image(
            cat, synth["title"], synth.get("lead", ""), V2_DIR / "img" / img_name,
            body=body_text, avoid_scenes=used_scenes)
        if img_scene:
            used_scenes.append(img_scene)
        image_url = f"img/{img_name}" if img_style else ""

        articles.append({
            "category": cat,
            "image": image_url,
            "image_style": img_style,
            "image_mismatch_suspected": img_mismatch,
            "tone": img_tone,
            "cat_code": CAT_META[cat]["code"],
            "cat_label": CAT_META[cat]["label"],
            "title": synth["title"],
            "card_headline": synth.get("card_headline", ""),
            "lead": synth.get("lead", ""),
            "body": synth["body"],
            "card_summary": synth.get("card_summary", ""),
            "hashtags": synth.get("hashtags", ""),
            "outlets": synth.get("outlets", []),
            "source_count": synth.get("source_count", len(sources)),
            "source_links": synth.get("source_links", []),
            "why_it_matters": synth.get("why_it_matters", ""),
            "outlook": synth.get("outlook", ""),
            "has_viewpoint_diff": bool(synth.get("has_viewpoint_diff")),
            "viewpoint_a_label": synth.get("viewpoint_a_label", ""),
            "viewpoint_a_quote": synth.get("viewpoint_a_quote", ""),
            "viewpoint_b_label": synth.get("viewpoint_b_label", ""),
            "viewpoint_b_quote": synth.get("viewpoint_b_quote", ""),
            "viewpoint_summary": synth.get("viewpoint_summary", ""),
            "reaction_fact": synth.get("reaction_fact", ""),
            "reaction_why": synth.get("reaction_why", ""),
            "reaction_outlook": synth.get("reaction_outlook", ""),
            "emotion_fact": synth.get("emotion_fact", ""),
            "emotion_why": synth.get("emotion_why", ""),
            "emotion_outlook": synth.get("emotion_outlook", ""),
            "fallback_used": bool(synth.get("_fallback_used")),
        })
        print(f"[v2] {cat}: 합성 완료 — {synth['title']}")
    return articles


def _working_data_path(today_key: str | None = None, slot: str | None = None) -> Path:
    """그날의 v2 합성 결과를 담는 작업용 파일 경로.
    review.py / --deploy-only 등 별도 프로세스 간 핸드오프 용도 — 공개 사이트(web/)에는 노출 안 함.
    실제 사이트(web/data.json)는 news_archive.save_today()가 단일 소스로 관리함.
    슬롯이 주어지면 슬롯별 파일로 분리 (하루 4슬롯이 서로 안 덮어쓰게)."""
    today_key = today_key or config.now_kst().strftime("%Y%m%d")
    fname = f"v2_articles_{slot}.json" if slot else "v2_articles.json"
    return config.OUTPUT_DIR / today_key / fname


def save_working_data(articles: list[dict], slot: str | None = None) -> Path:
    """v2 합성 결과를 작업용 파일로 저장 (사이트 페이지는 더 만들지 않음 — main.py가 web/data.json에 반영)."""
    now = config.now_kst()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.year}년 {now.month}월 {now.day}일 {weekdays[now.weekday()]}요일"
    payload = {"date": date_str, "updated": now.strftime("%H:%M"), "articles": articles}

    out = _working_data_path(now.strftime("%Y%m%d"), slot=slot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[v2] 작업용 데이터 저장: {out}")
    return out


def _send_post_deploy_buttons():
    """배포 완료 후 수정 버튼 텔레그램 전송. 카테고리별 재생성→승인 전까지 미배포, 최대 12시간 대기."""
    import json as _json, os, requests
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8", override=True)
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot or not chat:
        return

    markup = {
        "inline_keyboard": [
            [
                {"text": "🔄 핫뉴스 재생성", "callback_data": "fix_hot"},
                {"text": "🔄 경제 재생성",   "callback_data": "fix_economy"},
                {"text": "🔄 트렌드 재생성", "callback_data": "fix_culture"},
            ],
            [
                {"text": "✅ 수정 완료",      "callback_data": "fix_done"},
            ]
        ]
    }
    fix_msg_id = None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            json={"chat_id": chat,
                  "text": "✅ 배포 완료! news.mydotory.com\n\n이미지 수정이 필요하면 아래 버튼을 누르세요.",
                  "reply_markup": _json.dumps(markup)},
            timeout=15,
        )
        if not r.ok:
            return
        fix_msg_id = r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[v2] 수정 버튼 전송 실패: {e}")
        return

    # "수정 완료" 누를 때까지 대기 (최대 12시간)
    import time
    from news.article_image import generate_article_image

    deadline = time.time() + 12 * 60 * 60
    offset = 0
    today = config.now_kst().strftime("%Y%m%d")
    data_path = _working_data_path(today)
    articles = _json.loads(data_path.read_text(encoding="utf-8")).get("articles", []) if data_path.exists() else []

    CONFIRM_TIMEOUT = 20 * 60
    FEEDBACK_TIMEOUT = 10 * 60
    pending: dict[str, float] = {}              # cat -> 승인 대기 만료 시각
    awaiting_feedback: dict[str, dict] = {}     # cat -> {ask_msg_id, deadline} — 피드백 답장 대기, 여러 카테고리 동시 가능

    def _send(text: str):
        requests.post(f"https://api.telegram.org/bot{bot}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=10)

    def _answer(cq_id: str, text: str):
        requests.post(f"https://api.telegram.org/bot{bot}/answerCallbackQuery",
                      json={"callback_query_id": cq_id, "text": text}, timeout=10)

    def _ask_for_feedback(cat: str):
        """피드백 답장을 요청만 하고 즉시 리턴 (non-blocking) — 다른 카테고리 처리를 막지 않음."""
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{bot}/sendMessage",
                json={
                    "chat_id": chat,
                    "text": f"🔄 {cat} 재생성 — 반영할 피드백을 답장으로 입력해주세요 (없으면 '없음', {FEEDBACK_TIMEOUT//60}분 안에).",
                    "reply_markup": _json.dumps({
                        "force_reply": True,
                        "input_field_placeholder": "피드백 입력 (없으면 '없음')",
                    }),
                },
                timeout=15,
            )
            if not r.ok:
                _regenerate_with_feedback(cat, "")
                return
            ask_msg_id = r.json().get("result", {}).get("message_id")
            awaiting_feedback[cat] = {"ask_msg_id": ask_msg_id, "deadline": time.time() + FEEDBACK_TIMEOUT}
        except Exception as e:
            print(f"[v2] {cat} 피드백 요청 전송 실패: {e}")
            _regenerate_with_feedback(cat, "")

    def _regenerate_with_feedback(cat: str, feedback: str):
        """실제 이미지 재생성 → 미리보기 + 승인/재생성 버튼 전송. 배포는 confirm_ 클릭 시에만.
        이미지 파일을 쓰는 동안만 짧게 lock — 다른 파이프라인과 충돌 방지."""
        article = next((a for a in articles if a["category"] == cat), None)
        if not article:
            _send(f"❌ {cat} 기사 데이터를 찾을 수 없음")
            return

        body = " ".join(article.get("body", [])[:1])
        img_path = V2_DIR / "img" / f"{today}_{cat}.png"
        with pipeline_lock(f"v2_main.py 수정({cat})", wait_seconds=60) as got:
            if not got:
                _send(f"⚠️ {cat} 재생성 — 다른 파이프라인 실행 중이라 잠시 후 다시 시도해주세요")
                return
            style, _, mismatch, tone = generate_article_image(cat, article["title"], article.get("lead", ""), img_path,
                                                                body=body, feedback=feedback)
        if not style:
            _send(f"❌ {cat} 이미지 재생성 실패")
            return
        article["image_mismatch_suspected"] = mismatch
        article["tone"] = tone

        confirm_markup = {
            "inline_keyboard": [[
                {"text": "👍 이 이미지로 배포", "callback_data": f"confirm_{cat}"},
                {"text": "🔄 다시 재생성",     "callback_data": f"fix_{cat}"},
            ]]
        }
        caption = f"🔄 {cat} 재생성 결과 — 이대로 배포할까요?"
        if feedback:
            caption += f"\n(반영한 피드백: {feedback})"
        try:
            with open(img_path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{bot}/sendPhoto",
                    data={"chat_id": chat, "caption": caption,
                          "reply_markup": _json.dumps(confirm_markup)},
                    files={"photo": f}, timeout=30,
                )
            pending[cat] = time.time() + CONFIRM_TIMEOUT
        except Exception as e:
            print(f"[v2] {cat} 미리보기 전송 실패: {e}")

    while time.time() < deadline:
        # 카테고리별 승인 대기 타임아웃 체크 (여러 개 동시 진행 중이어도 각자 따로 만료)
        for cat, exp in list(pending.items()):
            if time.time() > exp:
                pending.pop(cat, None)
                _send(f"⏰ {cat} 승인 응답 없음 — 배포 안 함 (기존 이미지 유지)")

        # 피드백 답장 대기 타임아웃 체크 — 응답 없으면 피드백 없이 재생성 진행
        for cat, info in list(awaiting_feedback.items()):
            if time.time() > info["deadline"]:
                awaiting_feedback.pop(cat, None)
                _send(f"⏰ {cat} 피드백 응답 없음 — 피드백 없이 재생성해요")
                _regenerate_with_feedback(cat, "")

        try:
            res = requests.get(
                f"https://api.telegram.org/bot{bot}/getUpdates",
                params={"offset": offset, "timeout": 20, "allowed_updates": ["callback_query", "message"]},
                timeout=25,
            )
            updates = res.json().get("result", []) if res.ok else []
        except Exception:
            updates = []

        for upd in updates:
            offset = upd["update_id"] + 1

            # 피드백 답장(message) 처리 — 여러 카테고리가 동시에 대기 중이어도 각자 매칭
            msg = upd.get("message")
            if msg:
                reply_to = msg.get("reply_to_message") or {}
                ask_id = reply_to.get("message_id")
                matched_cat = next((c for c, info in awaiting_feedback.items() if info["ask_msg_id"] == ask_id), None)
                if matched_cat:
                    awaiting_feedback.pop(matched_cat, None)
                    text = (msg.get("text") or "").strip()
                    feedback = "" if text in ("없음", "no", "NO") else text
                    _regenerate_with_feedback(matched_cat, feedback)
                continue

            cq = upd.get("callback_query")
            if not cq:
                continue
            data = cq.get("data", "")

            if data == "fix_done":
                _answer(cq["id"], "✅ 완료!")
                try:
                    requests.post(f"https://api.telegram.org/bot{bot}/editMessageReplyMarkup",
                                  json={"chat_id": chat, "message_id": fix_msg_id,
                                        "reply_markup": _json.dumps({})}, timeout=10)
                except Exception:
                    pass
                print("[v2] 수정 완료 확인")
                return

            if data.startswith("confirm_"):
                cat = data.replace("confirm_", "")
                if cat not in pending:
                    _answer(cq["id"], "이미 처리됐거나 만료된 요청이에요")
                    continue
                pending.pop(cat, None)
                _answer(cq["id"], "✅ 배포 중...")
                with pipeline_lock(f"v2_main.py 확정배포({cat})", wait_seconds=60) as got:
                    if not got:
                        _send(f"⚠️ {cat} 배포 — 다른 파이프라인 실행 중이라 잠시 후 다시 시도해주세요")
                        continue
                    ok = deploy()
                _send(f"✅ {cat} 배포 완료!" if ok else f"⚠️ {cat} 배포 실패")
                continue

            if data.startswith("fix_"):
                cat = data.replace("fix_", "")
                _answer(cq["id"], f"🔄 {cat} 피드백 요청 전송...")
                _ask_for_feedback(cat)  # non-blocking — 동시에 여러 카테고리 피드백 대기 가능
                continue

    print("[v2] 수정 대기 종료 (12시간)")


def deploy() -> bool:
    print("\n[v2] Firebase 배포 중 (전체 hosting)...")
    result = subprocess.run(
        "firebase deploy --only hosting",
        cwd=Path(__file__).parent, capture_output=True, text=True, shell=True,
    )
    if result.returncode == 0:
        print("[v2] 배포 완료: https://news.mydotory.com/")
        return True
    else:
        print(f"[v2] 배포 실패:\n{result.stderr}")
        return False


if __name__ == "__main__":
    # lock은 "생성/배포" 같은 짧은 작업에만 걸고, 텔레그램 승인 대기(최대 12시간)처럼
    # 오래 걸리는 단계는 lock 밖에서 실행한다 — 안 그러면 그 시간 동안 다른 파이프라인
    # (CardNewsAutoPost 등)이 lock을 못 잡고 조용히 실패하는 사고가 난다 (2026-06-21 발생).
    import run_log
    run_log.enable("v2_" + "_".join(a.lstrip("-") for a in sys.argv[1:]) or "v2_default")

    # 카테고리 값(hot/economy/culture)도 lock 이름에 포함 — 안 그러면 서로 다른
    # 슬롯(카테고리)이 실제로는 파일이 안 겹치는데도 같은 lock으로 묶여 막힘
    _lock_name = f"v2_main.py {' '.join(sys.argv[1:])}".strip()
    _need_post_deploy_buttons = False

    with pipeline_lock(_lock_name or "v2_main.py") as _got_lock:
        if not _got_lock:
            from notify import send
            send(f"⚠️ {_lock_name or 'v2_main.py'} — 다른 파이프라인이 실행 중이라 건너뜀")
            sys.exit(1)

        # --deploy-only: 생성 없이 배포만 (승인 플래그 확인)
        if "--deploy-only" in sys.argv:
            today = config.now_kst().strftime("%Y%m%d")
            flag = V2_DIR / f".approved_{today}"
            if not flag.exists():
                print("[v2] 승인 플래그 없음 — 배포 취소")
                sys.exit(1)
            data_path = _working_data_path(today)
            if not data_path.exists():
                print("[v2] 작업용 데이터 없음 — 배포 취소")
                sys.exit(1)
            print("[v2] 승인 확인 → 배포 시작")
            deploy()
            _need_post_deploy_buttons = True
        else:
            fresh = "--fresh" in sys.argv
            slot = None
            if "--slot" in sys.argv:
                idx = sys.argv.index("--slot")
                if idx + 1 < len(sys.argv):
                    slot = sys.argv[idx + 1]
            exclude_categories = []
            if "--exclude" in sys.argv:
                idx = sys.argv.index("--exclude")
                if idx + 1 < len(sys.argv):
                    exclude_categories = [c for c in sys.argv[idx + 1].split(",") if c]

            curated = {} if fresh else _load_today_curated(slot=slot)
            if not curated:
                curated = _fresh_curation(exclude_categories=exclude_categories)
                _save_v2_curated(curated, slot=slot)

            articles = build_articles(curated)
            # 2026-07-03: 선택된 기사가 포털 단독 기사라 원문 소스를 하나도 못 찾는 경우
            # (예: 네이트/다음 재게재만 있고 실제 언론사 기사가 없음) — 예전엔 여기서 그냥
            # 조용히 종료돼서 그 슬롯 게시물이 통째로 누락됐음. 실패한 카테고리를 제외하고
            # 최대 2번 더 다른 기사로 재시도한 뒤에만 포기하도록 수정.
            retry_count = 0
            while not articles and retry_count < 2:
                failed_cat = next(iter(curated.keys()), None)
                if failed_cat:
                    exclude_categories = list(set(exclude_categories + [failed_cat]))
                retry_count += 1
                print(f"[v2] 소스 확보 실패 — 다른 기사로 재시도 ({retry_count}/2, 제외: {exclude_categories})")
                curated = _fresh_curation(exclude_categories=exclude_categories)
                _save_v2_curated(curated, slot=slot)
                articles = build_articles(curated)

            if not articles:
                print("[v2] 생성된 기사 없음 (재시도 2회 모두 실패) — 종료")
                try:
                    from notify import notify_failure
                    retry_cmd = f"python -X utf8 v2_main.py --slot {slot} --fresh" if slot else "python -X utf8 v2_main.py --fresh"
                    notify_failure(
                        f"⚠️ 도토리뉴스({slot or '기본'}) 기사 생성 실패 — 후보 기사들이 전부 "
                        f"원문 소스를 못 찾았어요(포털 단독 기사 등). 자동 재시도 2회도 실패.\n"
                        f"수동 재시도: `{retry_cmd}` 실행 후 review.py로 이어서 진행하세요."
                    )
                except Exception:
                    pass
                sys.exit(1)

            page = save_working_data(articles, slot=slot)

            if "--deploy" in sys.argv:
                deploy()
                _need_post_deploy_buttons = True
            else:
                print(f"[v2] 로컬 확인: {page}")

    # lock 해제 후 — 텔레그램 승인 대기(최대 12시간)는 다른 파이프라인을 막지 않음
    if _need_post_deploy_buttons:
        _send_post_deploy_buttons()
