"""도토리뉴스 블로그 초안(dotory_blog_draft.py 결과)을 네이버 블로그에 임시저장/발행한다.

최초 1회 준비 필요:
  1) python -X utf8 blog/naver_engine/login_chrome.py   # 전용 크롬 띄우고 네이버 로그인(한 번만)
  2) python -X utf8 blog/dotory_blog_publish.py --set-id <네이버블로그ID>

평소 사용법:
    python -X utf8 blog/dotory_blog_draft.py --category hot
    python -X utf8 blog/dotory_blog_publish.py --draft <위에서 나온 경로>          # 임시저장까지
    python -X utf8 blog/dotory_blog_publish.py --draft <경로> --publish           # 발행까지

기본은 '임시저장'까지만 한다(발행 버튼 전 정지) — 사람이 네이버에서 검토 후 직접 발행 권장.
--publish를 줘야 자동 발행까지 시도한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # notify.py(Cardnews 루트)용
from naver_engine.config import ensure_directories
from naver_engine.settings import load_illua_settings, save_illua_settings


def latest_draft() -> Path:
    drafts_dir = Path(__file__).resolve().parent / "drafts"
    candidates = sorted(drafts_dir.glob("blog_draft_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("초안이 없습니다. 먼저 dotory_blog_draft.py를 실행하세요.")
    return candidates[0]


def main() -> int:
    args = sys.argv[1:]
    ensure_directories()

    if "--set-id" in args:
        idx = args.index("--set-id")
        blog_id = args[idx + 1] if idx + 1 < len(args) else ""
        if not blog_id:
            print("사용법: python dotory_blog_publish.py --set-id <네이버블로그ID>")
            return 2
        s = load_illua_settings()
        s.naver_id = blog_id.strip()
        if not s.naver_login_id:
            s.naver_login_id = blog_id.strip()
        save_illua_settings(s)
        print(f"[BLOG] 네이버 블로그 ID 등록 완료: {s.naver_id}")
        return 0

    draft_path = None
    if "--draft" in args:
        idx = args.index("--draft")
        if idx + 1 < len(args):
            draft_path = Path(args[idx + 1])
    if draft_path is None:
        draft_path = latest_draft()

    do_publish = "--publish" in args

    settings = load_illua_settings()
    if not settings.naver_id.strip():
        # 2026-07-06: 설정 파일(dotory_blofit_settings.json)은 .gitignore 대상이라 클라우드
        # 러너엔 없음 — 블로그 ID 자체는 공개된 값(blog.naver.com/dotory_news)이라 민감정보가
        # 아니므로 환경변수(NAVER_BLOG_ID, GitHub Secret)로 대체 가능하게 함.
        import os
        env_id = os.environ.get("NAVER_BLOG_ID", "").strip()
        if env_id:
            settings.naver_id = env_id
            if not settings.naver_login_id:
                settings.naver_login_id = env_id
    if not settings.naver_id.strip():
        print("[BLOG] ⚠️ 네이버 블로그 ID가 등록되지 않았습니다.")
        print("       먼저: python dotory_blog_publish.py --set-id <네이버블로그ID>")
        return 2

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    title = draft.get("title", "오늘의 이슈")
    body = draft.get("body", "")
    images = [Path(p) for p in draft.get("images", []) if p and Path(p).exists()]
    if not body.strip():
        print("[BLOG] ⚠️ 본문이 비어 있습니다.")
        return 2

    print(f"[BLOG] 초안: {draft_path.name}")
    print(f"[BLOG] 제목: {title}")
    print(f"[BLOG] 본문 {len(body)}자 / 사진 {len(images)}장")
    print(f"[BLOG] 모드: {'발행까지 시도' if do_publish else '임시저장까지(발행 전 정지)'}")

    from naver_engine.naver_engine import IlluaNaverEngine

    def _log(msg: str) -> None:
        print(f"[도토리블로그] {msg}")

    engine = IlluaNaverEngine(settings, log_callback=_log)
    try:
        ok, msg = engine.publish_draft(
            title=title, body=body, cta="", image_paths=images,
            publish_after_save=do_publish, log_callback=_log,
        )
    except Exception as exc:
        _log(f"❌ 실행 중 오류: {exc}")
        engine.quit()
        try:
            from notify import notify_failure
            notify_failure(f"블로그 자동 발행 중 오류로 중단됨 ({title}): {exc}")
        except Exception:
            pass
        return 1

    if not ok:
        engine.quit()
        # 2026-07-03/04: 로그인 만료로 여기서 멈춘 적이 두 번 있었는데, 터미널에만 찍히고
        # 아무 알림이 없어서 사람이 로그를 직접 봐야만 알아챘음 — 텔레그램으로도 보내게 함.
        # 2026-07-05: "디버그 포트가 안 열려있음"(=크롬 자체가 꺼져있음)과 "실제 로그인 세션
        # 만료"를 똑같이 "로그인 필요" 메시지로 뭉뚱그려 보내고 있었음 — 자동로그인을 설정해둔
        # 사용자 입장에선 크롬만 다시 켜면 되는데 "로그인해주세요"라고 나와서 혼란스러웠음.
        # connect() 실패(디버그 포트 안 열림)와 _ensure_logged_in() 실패(세션 쿠키 없음)를
        # 구분해서 정확한 메시지를 보내도록 수정.
        chrome_not_running = "디버그 포트" in msg
        try:
            from notify import send
            if chrome_not_running:
                send(
                    f"⏸️ [도토리뉴스 블로그] 크롬이 꺼져있어요 — 발행 중단됨\n제목: {title}\n"
                    f"(로그인은 자동으로 유지되니 로그인은 다시 안 하셔도 돼요, 크롬만 켜면 됩니다)\n"
                    f"1) python blog/naver_engine/login_chrome.py 실행\n"
                    f"2) python blog/dotory_blog_publish.py --draft {draft_path} 재실행"
                )
            elif "로그인" in msg:
                send(
                    f"⏸️ [도토리뉴스 블로그] 로그인 세션이 실제로 만료됐어요 — 발행 중단됨\n제목: {title}\n"
                    f"1) python blog/naver_engine/login_chrome.py 실행\n"
                    f"2) 뜬 크롬 창에서 네이버 로그인(로그인 상태 유지 체크)\n"
                    f"3) python blog/dotory_blog_publish.py --draft {draft_path} 재실행"
                )
            else:
                send(f"⏸️ [도토리뉴스 블로그] 발행 중단됨\n제목: {title}\n사유: {msg}")
        except Exception:
            pass
        if chrome_not_running:
            _log("⏸️ 멈춤: 크롬이 꺼져있어요(로그인은 유지됨) — login_chrome.py로 다시 켜주세요.")
        elif "로그인" in msg:
            _log("⏸️ 멈춤: 네이버 로그인 세션이 실제로 만료됐습니다.")
            _log("   1) python blog/naver_engine/login_chrome.py")
            _log("   2) 그 창에서 네이버 로그인")
            _log("   3) 다시 이 명령을 실행")
        else:
            _log(f"⏸️ 멈춤: {msg}")
        return 1

    if do_publish:
        url = ""
        try:
            url = engine.get_published_url()
        except Exception:
            pass
        engine.quit()
        _log(f"✅ 발행 완료: {msg}")
        if url:
            _log(f"   공개 URL: {url}")
        try:
            from notify import send
            send(f"✅ [도토리뉴스 블로그] 발행 완료\n제목: {title}\n링크: {url or '(공개 URL 확인 필요)'}")
        except Exception:
            pass
        return 0

    draft_url = ""
    try:
        draft_url = engine.get_current_draft_url()
    except Exception:
        pass
    engine.quit()
    _log(f"✅ 임시저장 완료: {msg}")
    _log("   → 네이버 블로그 '내가 쓴 글/임시저장'에서 확인 후 발행하세요.")
    _log("   → 자동 발행까지 원하면 같은 명령에 --publish 를 붙이세요.")
    if draft_url:
        _log(f"   → 링크: {draft_url}")
    try:
        from notify import send
        send(f"📝 [도토리뉴스 블로그] 임시저장 완료\n제목: {title}\n{draft_url or '(링크 확인 실패 — 네이버 블로그에서 직접 확인해주세요)'}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
