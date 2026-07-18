"""카드뉴스 메인 파이프라인 — 카드 조립 전용 (단일 주제, 하루 4슬롯).

2026-06-29 재설계: 하루에 한 게시물(3주제 5장)이 아니라, 아침/점심/저녁/야식 4번에 걸쳐
"한 주제를 깊게 설명하는" 게시물을 따로 올린다. 이 스크립트는 그중 한 슬롯만 맡아서,
v2_main.py --slot <slot>이 만들어둔 결과(v2_curated_<slot>.json, v2_articles_<slot>.json,
web/v2/img/*.png)를 그대로 가져다 카드 조립 + 사이트 배포 + 인스타 업로드만 한다.
여기서 뉴스를 다시 수집하거나 Gemini를 다시 부르지 않는다.

카드 구성(가변): 커버 → 오늘의 사실 → [시각차이, 있으면] → 왜중요할까? → 앞으로는? → 아웃트로

2026-07-02 재설계: 슬롯이 더 이상 카테고리에 고정되지 않음 — 그 시간대 가장 화제성 높은
뉴스를 카테고리 무관하게 골라서 다룬다(대신 하루 안에서는 카테고리가 안 겹치게 함,
daily_runner.py가 담당). 그래서 이 스크립트도 카테고리가 아니라 슬롯을 기준으로 동작한다.

사용법:
    python -X utf8 main.py --slot morning              # 카드 조립 + 사이트 배포 + 인스타 업로드
    python -X utf8 main.py --slot morning --dry-run    # 운영에 영향 없이 로컬에서만 조립/검증
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

import config
from pipeline_lock import pipeline_lock


from image.html_composer import compose_cover_explain, compose_explain_card, compose_outro
from instagram.uploader_graph import upload_carousel
from news_archive import save_today
from news import character

UPLOADS_DIR = Path(__file__).parent / "web" / "uploads"
BASE_URL_UPLOADS = "https://dotory-news.web.app/uploads"
V2_DIR = Path(__file__).parent / "web" / "v2"

VALID_SLOTS = ("morning", "lunch", "evening", "night")

# 인스타그램 업로드 ON/OFF
UPLOAD_ENABLED = True  # 2026-07-02: 실패 원인(PNG 미지원 — JPEG만 허용) 발견 및 수정 완료, 재개

MIN_IMAGE_SIZE_KB = 15  # 이 크기 미만이면 렌더링 오류로 판단
# (텍스트만 있는 미니멀 카드 — why/viewpoint 등 — 는 사진이 없어 30KB대로도 정상이라
#  50KB 기준이면 정상 렌더링도 경고로 잡혔음. 진짜 빈 화면은 단색이라 5KB 미만으로 훨씬 작음)
MIN_CARDS = 5  # 커버+사실+왜중요+전망+아웃트로 (시각차이 있으면 +1장)


def _verify_images(image_paths: list) -> bool:
    """이미지 품질 검증. 카드 장수는 시각차이 유무로 5장 또는 6장 — 가변이라 최소 장수만 확인."""
    print("\n[verify] 이미지 품질 검증 중...")
    if len(image_paths) < MIN_CARDS:
        print(f"[verify] 실패 — 이미지 {len(image_paths)}장 (최소 {MIN_CARDS}장 필요)")
        return False

    all_ok = True
    for p in image_paths:
        path = Path(p)
        if not path.exists():
            print(f"[verify] 누락: {path.name}")
            all_ok = False
            continue
        size_kb = path.stat().st_size / 1024
        status = "OK" if size_kb >= MIN_IMAGE_SIZE_KB else "WARNING (너무 작음 — 빈 화면 의심)"
        print(f"[verify]   {path.name}: {size_kb:.0f} KB  {status}")
        if size_kb < MIN_IMAGE_SIZE_KB:
            all_ok = False

    if all_ok:
        print("[verify] 전체 이미지 정상 확인")
    else:
        print("[verify] 이상 감지 — 배포/업로드 중단")
    return all_ok


def _prepare_uploads(image_paths: list) -> list[str]:
    """이미지를 web/uploads/ 에 복사하고 공개 URL 목록 반환 (Firebase 배포 전 호출).
    2026-07-02: Instagram Graph API는 캐러셀/피드 미디어로 PNG를 거부하고 JPEG만
    받는다(에러 code 9004 "Only photo or video can be accepted as media type") —
    몇 주간 반복된 업로드 실패의 원인이 이거였음. 그래서 여기서 PNG를 JPEG로 변환해
    올린다. 로컬 원본(run_dir의 .png)은 그대로 두고, 업로드용 사본만 JPEG로 만든다."""
    from PIL import Image

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for f in UPLOADS_DIR.glob("*"):
        if f.suffix in (".png", ".jpg"):
            f.unlink()
    urls = []
    for p in image_paths:
        p = Path(p)
        dest = UPLOADS_DIR / f"{p.stem}.jpg"
        Image.open(p).convert("RGB").save(dest, "JPEG", quality=92)
        urls.append(f"{BASE_URL_UPLOADS}/{dest.name}")
    print(f"[main] 이미지 {len(urls)}장 → web/uploads/ 복사 (JPEG 변환)")
    return urls


def _deploy_firebase():
    """메인 URL(dotory-news.web.app)에 진짜 배포"""
    project_dir = Path(__file__).parent
    print("\n[main] Firebase 배포 중...")
    result = subprocess.run(
        "firebase deploy --only hosting",
        cwd=project_dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    if result.returncode == 0:
        print("[main] Firebase 배포 완료")
    else:
        print(f"[main] Firebase 배포 실패:\n{result.stderr}")


def _load_v2_data(run_dir: Path, slot: str) -> tuple[dict, dict]:
    """v2_main.py --slot이 만들어둔 큐레이션/기사 데이터를 로드.
    (curated, article) 반환. 하나라도 없으면 ({}, {})."""
    curated_path = run_dir / f"v2_curated_{slot}.json"
    articles_path = run_dir / f"v2_articles_{slot}.json"
    if not curated_path.exists() or not articles_path.exists():
        return {}, {}
    curated_by_cat = json.loads(curated_path.read_text(encoding="utf-8"))
    articles = json.loads(articles_path.read_text(encoding="utf-8")).get("articles", [])
    article = articles[0] if articles else {}
    data = curated_by_cat.get(article.get("category", ""), {})
    return data, article


def build_cards(slot: str, data: dict, article: dict, run_dir: Path) -> list[Path]:
    """v2_main.py가 만들어둔 기사/이미지로 단일주제 카드 조립 (커버~아웃트로, 가변 장수).
    카드마다 news/character.py로 기사 톤(tone)에 맞는 도토리 표정을 자동으로 골라 배지에 넣는다."""
    final_images = []
    category = article.get("category", "hot")
    img_path = V2_DIR / article["image"] if article.get("image") else None
    headline = article.get("title") or data.get("card_headline", "")
    tone = article.get("tone", "heavy")
    idx = 0

    def _next_path(name: str) -> Path:
        nonlocal idx
        # 슬롯명을 파일명에 포함 — 하루 4슬롯이 같은 날짜 폴더를 공유하므로 안 그러면
        # 나중 슬롯이 앞 슬롯 이미지를 그대로 덮어써버림 (2026-07-02 발견)
        path = run_dir / f"{slot}_{idx:02d}_{name}.png"
        idx += 1
        return path

    def _pick(variant: str, emotion_key: str, facing: str) -> Path | None:
        """Gemini가 기사 내용 기반으로 고른 감정(emotion_fact 등)이 있으면 그걸 그대로 쓰고,
        없으면(구버전 데이터 등) 카드종류+톤 기반 고정 매핑으로 폴백."""
        emotion = article.get(emotion_key)
        if emotion:
            return character.pose_path(emotion, facing=facing)
        return character.pick_pose(variant, tone, facing=facing)

    try:
        pose = character.pick_pose("cover", tone, facing="front")
        final_images.append(compose_cover_explain(slot, category, headline, img_path, _next_path("cover"), pose_path=pose))
    except Exception as e:
        print(f"[main] 커버 생성 실패: {e}")

    try:
        n_src = article.get("source_count", 1)
        outlets = article.get("outlets", [])
        src_label = f"{n_src}곳 종합" if n_src >= 2 else (outlets[0] if outlets else data.get("source_name", ""))
        fact_text = article.get("card_summary") or data.get("card_summary") or headline
        pose = _pick("fact", "emotion_fact", facing="left")
        final_images.append(compose_explain_card(
            "fact", category, "오늘의 사실", slot=slot, headline=fact_text, image_path=img_path,
            caption=f"출처: {src_label}" if src_label else "", pose_path=pose,
            reaction=article.get("reaction_fact", ""), output_path=_next_path("fact")))
    except Exception as e:
        print(f"[main] 사실확인 카드 생성 실패: {e}")

    if article.get("has_viewpoint_diff"):
        try:
            pose = character.pick_pose("viewpoint", tone, facing="front")
            final_images.append(compose_explain_card(
                "viewpoint", category, "서로 다른 시각", slot=slot,
                vp_a_label=article.get("viewpoint_a_label", ""), vp_a_quote=article.get("viewpoint_a_quote", ""),
                vp_b_label=article.get("viewpoint_b_label", ""), vp_b_quote=article.get("viewpoint_b_quote", ""),
                vp_summary=article.get("viewpoint_summary", ""), pose_path=pose, output_path=_next_path("viewpoint")))
        except Exception as e:
            print(f"[main] 시각차이 카드 생성 실패: {e}")

    try:
        pose = _pick("why", "emotion_why", facing="front")
        final_images.append(compose_explain_card(
            "why", category, "왜 중요할까?", slot=slot, headline=article.get("why_it_matters", ""),
            image_path=img_path, pose_path=pose,
            reaction=article.get("reaction_why", ""), output_path=_next_path("why")))
    except Exception as e:
        print(f"[main] 왜중요 카드 생성 실패: {e}")

    try:
        pose = _pick("outlook", "emotion_outlook", facing="right")
        final_images.append(compose_explain_card(
            "outlook", category, "앞으로는?", slot=slot, headline=article.get("outlook", ""),
            image_path=img_path, pose_path=pose,
            reaction=article.get("reaction_outlook", ""), output_path=_next_path("outlook")))
    except Exception as e:
        print(f"[main] 전망 카드 생성 실패: {e}")

    try:
        final_images.append(compose_outro(_next_path("outro")))
    except Exception as e:
        print(f"[main] 아웃트로 생성 실패: {e}")

    return final_images


def regenerate_single_card(slot: str, card_name: str) -> Path | None:
    """카드 중 하나만(cover/fact/viewpoint/why/outlook) 다시 렌더링해 같은 파일 경로에 덮어쓴다.
    2026-07-02: 텔레그램 카드 승인 단계에서 "이 카드만 재생성" 버튼용으로 추가.
    2026-07-03: viewpoint(서로 다른 시각) 지원 추가 — 처음엔 빠져있어서 재생성이 안 됐음."""
    today = config.now_kst().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    data, article = _load_v2_data(run_dir, slot)
    if not data or not article:
        return None

    existing = sorted(run_dir.glob(f"{slot}_*_{card_name}.png"))
    if not existing:
        return None
    out_path = existing[0]

    category = article.get("category", "hot")
    img_path = V2_DIR / article["image"] if article.get("image") else None
    headline = article.get("title") or data.get("card_headline", "")
    tone = article.get("tone", "heavy")

    def _pick(variant: str, emotion_key: str, facing: str) -> Path | None:
        emotion = article.get(emotion_key)
        if emotion:
            return character.pose_path(emotion, facing=facing)
        return character.pick_pose(variant, tone, facing=facing)

    try:
        if card_name == "cover":
            pose = character.pick_pose("cover", tone, facing="front")
            compose_cover_explain(slot, category, headline, img_path, out_path, pose_path=pose)
        elif card_name == "fact":
            n_src = article.get("source_count", 1)
            outlets = article.get("outlets", [])
            src_label = f"{n_src}곳 종합" if n_src >= 2 else (outlets[0] if outlets else data.get("source_name", ""))
            fact_text = article.get("card_summary") or data.get("card_summary") or headline
            pose = _pick("fact", "emotion_fact", facing="left")
            compose_explain_card("fact", category, "오늘의 사실", slot=slot, headline=fact_text,
                                  image_path=img_path, caption=f"출처: {src_label}" if src_label else "",
                                  pose_path=pose, reaction=article.get("reaction_fact", ""), output_path=out_path)
        elif card_name == "viewpoint":
            pose = character.pick_pose("viewpoint", tone, facing="front")
            compose_explain_card("viewpoint", category, "서로 다른 시각", slot=slot,
                                  vp_a_label=article.get("viewpoint_a_label", ""), vp_a_quote=article.get("viewpoint_a_quote", ""),
                                  vp_b_label=article.get("viewpoint_b_label", ""), vp_b_quote=article.get("viewpoint_b_quote", ""),
                                  vp_summary=article.get("viewpoint_summary", ""), pose_path=pose, output_path=out_path)
        elif card_name == "why":
            pose = _pick("why", "emotion_why", facing="right")
            compose_explain_card("why", category, "왜 중요할까요?", slot=slot,
                                  headline=article.get("why_it_matters", ""), image_path=img_path,
                                  pose_path=pose, reaction=article.get("reaction_why", ""), output_path=out_path)
        elif card_name == "outlook":
            pose = _pick("outlook", "emotion_outlook", facing="right")
            compose_explain_card("outlook", category, "앞으로는?", slot=slot,
                                  headline=article.get("outlook", ""), image_path=img_path,
                                  pose_path=pose, reaction=article.get("reaction_outlook", ""), output_path=out_path)
        else:
            return None
        return out_path
    except Exception as e:
        print(f"[main] {card_name} 카드 재생성 실패: {e}")
        return None


def regenerate_article_image(slot: str, feedback: str = "") -> list[Path] | None:
    """기사 내용(제목/본문 등)은 그대로 두고 메인 일러스트(article["image"])만 다시 그린 뒤,
    그 일러스트를 쓰는 카드(cover/fact/why/outlook 등)를 전부 다시 렌더링한다.
    2026-07-06: 카드별 "재생성" 버튼은 캐릭터 포즈만 바뀌고 배경 일러스트는 그대로였음
    (모든 카드가 같은 article["image"]를 공유해서 그림) — "그림만 다시 만들고 싶다"는
    요청은 이 일러스트 자체를 다시 생성해야 해결됨.
    2026-07-17: feedback(사용자가 텔레그램 답장으로 남긴 구체적 수정 요청)을 추가 —
    카드별 재생성은 포즈 라이브러리에서 고르기만 할 뿐 AI로 새로 그리지 않으므로
    (아래 참고), "그림 자체"에 대한 피드백은 전부 여기(공유 일러스트)로 들어와야 함."""
    from news.article_image import generate_article_image

    today = config.now_kst().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    data, article = _load_v2_data(run_dir, slot)
    if not data or not article or not article.get("image"):
        return None

    img_path = V2_DIR / article["image"]
    category = article.get("category", "hot")
    title = article.get("title") or data.get("card_headline", "")
    lead = article.get("lead") or article.get("card_summary", "")

    for attempt in range(3):
        style, _scene, _mismatch, _tone = generate_article_image(
            category, title, lead, img_path, feedback=feedback)
        if style and style != "F":
            break
    else:
        print("[main] 메인 일러스트 재생성 실패 (3회 시도 모두 실패)")
        return None

    rebuilt = []
    card_names = ["cover", "fact", "why", "outlook"]
    if article.get("has_viewpoint_diff"):
        card_names.insert(2, "viewpoint")
    for name in card_names:
        out_path = regenerate_single_card(slot, name)
        if out_path:
            rebuilt.append(out_path)
    return rebuilt or None


def run(slot: str, dry_run: bool = False, publish_only: bool = False) -> bool:
    """오늘 v2 데이터(해당 슬롯)로 카드 조립 → 검증 → (dry_run 아니면) 사이트 배포 + 인스타 업로드.
    성공하면 True, 실패하면 False.
    publish_only=True: 카드 생성은 건너뛰고(이미 승인받은 기존 이미지 재사용) 배포/업로드만 진행
    (2026-07-02: 텔레그램 카드 승인 후 슬롯 :55에 실제 배포하는 2단계 흐름용)."""
    today = config.now_kst().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    run_dir.mkdir(parents=True, exist_ok=True)

    mode_label = "DRY-RUN (배포/업로드 안 함)" if dry_run else ("배포만(카드 재사용)" if publish_only else "진짜 배포")
    print(f"\n{'='*50}")
    print(f"  카드뉴스 빌드: {today} [{slot}] [{mode_label}]")
    print(f"{'='*50}\n")

    data, article = _load_v2_data(run_dir, slot)
    if not data or not article:
        print(f"[main] v2 데이터 없음 ({slot}) — v2_main.py --slot {slot} 먼저 실행 필요. 중단.")
        if not dry_run:
            try:
                from notify import notify_failure
                notify_failure(f"카드 빌드 실패({slot}) — 오늘 v2 데이터 없음")
            except Exception:
                pass
        return False

    if publish_only:
        final_images = sorted(run_dir.glob(f"{slot}_*.png"))
        print(f"[main] [{slot}] 기존 카드 {len(final_images)}장 재사용 (승인 완료 상태)")
    else:
        print(f"[main] [{slot}] 카드 조립 중 (v2 데이터 재사용, 신규 생성 없음)...")
        final_images = build_cards(slot, data, article, run_dir)
    print(f"\n[main] 완성된 이미지 {len(final_images)}장:")
    for p in final_images:
        print(f"  - {p}")

    if not _verify_images(final_images):
        if not dry_run:
            try:
                from notify import notify_failure
                notify_failure(f"이미지 품질 검증 실패({slot}) — 배포/업로드 중단됨. 폴더: {run_dir}")
            except Exception:
                pass
        return False

    if dry_run:
        print(f"\n[dry-run] 여기까지만 진행 — 사이트 배포·인스타 업로드는 건너뜀")
        print(f"[dry-run] 결과물 확인: {run_dir}")
        return True

    category = article.get("category", "hot")
    save_today({category: data}, v2_articles=[article])
    public_urls = _prepare_uploads(final_images)
    _deploy_firebase()

    done_flag = run_dir / f"build_done_{slot}.txt"
    upload_ok = True
    if UPLOAD_ENABLED:
        print("\n[main] 인스타그램 업로드 중...")
        upload_ok = upload_carousel(final_images, article, slot=slot, public_urls=public_urls)
        if not upload_ok:
            print("\n📁 이미지만 저장됨 (인스타 업로드 건너뜀)")
            try:
                from notify import notify_failure
                notify_failure(f"인스타그램 업로드 실패({slot}) — 사이트는 정상 배포됨. 이미지: {run_dir}")
            except Exception:
                pass
    else:
        print("\n[main] 업로드 건너뜀 (UPLOAD_ENABLED = False)")

    # 인스타 업로드 다음 순서로 블로그 초안 작성 — 인스타/블로그는 서로 다른 시스템(Graph API vs
    # 셀레니움 브라우저 자동화)이라 동시에 돌리면 크롬 세션 충돌 위험만 커서 순차로 진행한다.
    # 2026-07-02: 원래 기본은 임시저장까지만(자동 발행 안 함) — 사람이 최종 확인 후 네이버에서
    # 직접 발행하는 게 안전하다는 원칙이었으나, 2026-07-17 자동 발행(--publish)으로 전환함
    # (사용자 확인이 늦어질 때마다 발행이 계속 밀리는 게 더 큰 문제였음).
    import os
    if os.environ.get("SKIP_BLOG") == "1":
        # 2026-07-06: 클라우드(GitHub Actions) 런너에는 네이버 로그인 세션이 없음(Phase 2
        # 쿠키 자동화 미구현) — 사이트+인스타만 여기서 처리하고, 블로그는 로컬에서 별도 실행.
        print("\n[main] SKIP_BLOG=1 — 블로그 단계 건너뜀 (로컬에서 별도 처리 필요)")
    else:
        try:
            print("\n[main] 블로그 초안 작성 중...")
            blog_dir = Path(__file__).parent / "blog"
            draft_result = subprocess.run(
                [sys.executable, "-X", "utf8", "dotory_blog_draft.py", "--slot", slot],
                cwd=blog_dir, capture_output=True, text=True,
            )
            draft_path = None
            for line in draft_result.stdout.splitlines():
                if line.startswith("[BLOG_DRAFT]"):
                    draft_path = line.split("[BLOG_DRAFT]", 1)[1].strip()
            if draft_path:
                # 2026-07-17: 그동안 임시저장까지만 하고 사람이 네이버에서 직접 발행하게
                # 해뒀는데(2026-07-02 도입, 자동화 버그 안전장치), 사용자가 승인을 늦게
                # 확인하는 경우가 잦아서 그만큼 발행이 계속 늦어지는 문제가 더 커짐 —
                # --publish로 바로 발행까지 진행하도록 전환.
                publish_result = subprocess.run(
                    [sys.executable, "-X", "utf8", "dotory_blog_publish.py",
                     "--draft", draft_path, "--publish"],
                    cwd=blog_dir,
                )
                if publish_result.returncode != 0:
                    print(f"[main] 블로그 발행 단계 실패 (exit code {publish_result.returncode})")
            else:
                print(f"[main] 블로그 초안 생성 실패:\n{draft_result.stdout}\n{draft_result.stderr}")
                try:
                    from notify import notify_failure
                    notify_failure(f"블로그 초안 생성 실패({slot}) — dotory_blog_draft.py 자체가 실패함")
                except Exception:
                    pass
        except Exception as e:
            print(f"[main] 블로그 단계 실패(건너뜀): {e}")
            try:
                from notify import notify_failure
                notify_failure(f"블로그 단계 예외로 중단({slot}): {e}")
            except Exception:
                pass

    done_flag.write_text(config.now_kst().isoformat(), encoding="utf-8")
    print(f"\n✅ 카드뉴스 빌드 완료! [{slot}]")
    return upload_ok


if __name__ == "__main__":
    slot = None
    if "--slot" in sys.argv:
        idx = sys.argv.index("--slot")
        if idx + 1 < len(sys.argv):
            slot = sys.argv[idx + 1]
    if slot not in VALID_SLOTS:
        print(f"사용법: python main.py --slot {'|'.join(VALID_SLOTS)} [--dry-run] [--publish-only]")
        sys.exit(2)

    import run_log
    run_log.enable(f"build_{slot}")

    dry_run = "--dry-run" in sys.argv
    publish_only = "--publish-only" in sys.argv

    with pipeline_lock(f"main.py --slot {slot}" + (" --dry-run" if dry_run else "") + (" --publish-only" if publish_only else "")) as got_lock:
        if not got_lock:
            if not dry_run:
                try:
                    from notify import notify_failure
                    notify_failure(f"main.py({slot}) — 다른 파이프라인이 실행 중이라 건너뜀")
                except Exception:
                    pass
            sys.exit(1)
        ok = run(slot, dry_run=dry_run, publish_only=publish_only)
    sys.exit(0 if ok else 1)
