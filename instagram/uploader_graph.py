"""Instagram Graph API 업로더 (공식 API)"""
import json
import time
import shutil
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

TOKEN_FILE = Path(__file__).parent.parent / "instagram_graph_token.json"
WEB_DIR = Path(__file__).parent.parent / "web" / "uploads"
BASE_URL = "https://dotory-news.web.app/uploads"
GRAPH = "https://graph.instagram.com/v21.0"


def _load_token() -> tuple[str, str]:
    with open(TOKEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data["long_token"], data["ig_user_id"]


def _post(url: str, params: dict) -> dict:
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def _get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def _deploy_images(image_paths: list) -> list[str]:
    """이미지를 Firebase Hosting에 배포하고 공개 URL 반환"""
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 업로드 폴더 정리
    for f in WEB_DIR.glob("*.png"):
        f.unlink()

    # 이미지 복사
    urls = []
    for p in image_paths:
        dest = WEB_DIR / Path(p).name
        shutil.copy2(p, dest)
        urls.append(f"{BASE_URL}/{Path(p).name}")

    # Firebase 배포
    project_dir = Path(__file__).parent.parent
    print("[graph] Firebase Hosting 배포 중...")
    result = subprocess.run(
        "firebase deploy --only hosting",
        cwd=project_dir,
        capture_output=True,
        text=True,
        shell=True,
    )
    if result.returncode != 0:
        print(f"[graph] Firebase 배포 실패: {result.stderr}")
        return []

    print("[graph] Firebase 배포 완료")
    return urls


def _create_item_container(ig_user_id: str, token: str, image_url: str) -> str | None:
    """캐러셀 개별 이미지 컨테이너 생성"""
    url = f"{GRAPH}/{ig_user_id}/media"
    res = _post(url, {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": token,
    })
    container_id = res.get("id")
    if not container_id:
        print(f"[graph] 컨테이너 생성 실패: {res}")
    return container_id


def _create_carousel_container(ig_user_id: str, token: str, children: list[str], caption: str) -> str | None:
    """캐러셀 전체 컨테이너 생성"""
    url = f"{GRAPH}/{ig_user_id}/media"
    res = _post(url, {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
        "access_token": token,
    })
    container_id = res.get("id")
    if not container_id:
        print(f"[graph] 캐러셀 컨테이너 생성 실패: {res}")
    return container_id


def _publish(ig_user_id: str, token: str, creation_id: str) -> bool:
    """컨테이너 게시"""
    url = f"{GRAPH}/{ig_user_id}/media_publish"
    res = _post(url, {
        "creation_id": creation_id,
        "access_token": token,
    })
    if "id" in res:
        print(f"[graph] 게시 완료! post_id={res['id']}")
        return True
    print(f"[graph] 게시 실패: {res}")
    return False


def publish_story(image_path: Path, public_url: str = None) -> bool:
    """이미지 1장을 인스타 스토리로 게시 (공식 Graph API, media_type=STORIES).
    인터랙티브 링크 스티커는 API로 못 붙이므로, 안내 문구는 이미지 자체에 디자인으로 포함돼 있어야 함."""
    try:
        token, ig_user_id = _load_token()
    except Exception as e:
        print(f"[graph] 스토리 — 토큰 로드 실패: {e}")
        return False

    if public_url:
        image_url = public_url
    else:
        urls = _deploy_images([image_path])
        if not urls:
            return False
        image_url = urls[0]

    url = f"{GRAPH}/{ig_user_id}/media"
    res = _post(url, {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": token,
    })
    container_id = res.get("id")
    if not container_id:
        print(f"[graph] 스토리 컨테이너 생성 실패: {res}")
        return False

    time.sleep(5)  # 처리 대기
    return _publish(ig_user_id, token, container_id)


def upload_carousel(image_paths: list, article: dict, slot: str = "", caption: str = None, public_urls: list = None) -> bool:
    try:
        token, ig_user_id = _load_token()
    except Exception as e:
        print(f"[graph] 토큰 로드 실패: {e}")
        return False

    caption = caption or _build_caption(article, slot)

    # 1. 공개 URL 확보 (main.py에서 이미 배포된 경우 재사용, 아니면 직접 배포)
    if public_urls:
        print(f"[graph] 공개 URL {len(public_urls)}개 재사용 (이미 배포됨)")
    else:
        print("[graph] 이미지 공개 URL 생성 중...")
        public_urls = _deploy_images(image_paths)
        if not public_urls:
            return False
        print(f"[graph] 공개 URL {len(public_urls)}개 생성됨")

    # 2. 개별 이미지 컨테이너 생성
    print("[graph] 이미지 컨테이너 생성 중...")
    children = []
    for url in public_urls:
        cid = _create_item_container(ig_user_id, token, url)
        if not cid:
            return False
        children.append(cid)
        time.sleep(1)

    print(f"[graph] 컨테이너 {len(children)}개 생성됨")

    # 3. 캐러셀 컨테이너 생성
    print("[graph] 캐러셀 컨테이너 생성 중...")
    carousel_id = _create_carousel_container(ig_user_id, token, children, caption)
    if not carousel_id:
        return False

    # 처리 대기
    print("[graph] 처리 대기 중 (10초)...")
    time.sleep(10)

    # 4. 게시
    print("[graph] 게시 중...")
    success = _publish(ig_user_id, token, carousel_id)

    if success and article:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from notify import notify_success
            day_names = ["월", "화", "수", "목", "금", "토", "일"]
            now = datetime.now()
            date_str = f"{now.strftime('%Y.%m.%d')} ({day_names[now.weekday()]})"
            notify_success(date_str, article, slot)
        except Exception:
            pass

    return success


_SLOT_LABELS = {
    "morning": "☀️ 오늘의 아침한입",
    "lunch":   "🌤 오늘의 점심한입",
    "evening": "🌙 오늘의 저녁한입",
    "night":   "🌃 오늘의 야식한입",
}


def _build_caption(article: dict, slot: str = "") -> str:
    """단일 주제(하루 3슬롯 중 하나) 게시물용 캡션.
    2026-07-02: 예전 3카테고리(HOT/ECO/TRD) 다이제스트 포맷을 하루 3슬롯 단일주제
    포맷으로 교체 — 이제 한 게시물 = 기사 하나라 그 기사 내용을 그대로 캡션에 담는다."""
    now = datetime.now()
    day_names = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.strftime('%Y.%m.%d')} ({day_names[now.weekday()]})"

    slot_label = _SLOT_LABELS.get(slot, "오늘의 뉴스")
    title = article.get("title") or article.get("card_headline", "")
    summary = article.get("card_summary") or article.get("lead", "")
    why = article.get("why_it_matters", "")
    outlook = article.get("outlook", "")
    hashtags = article.get("hashtags", "")

    lines = [
        f"{slot_label} | {date_str}", "",
        title, "",
        summary, "",
    ]
    if why:
        lines += [f"📌 왜 중요할까? {why}", ""]
    if outlook:
        lines += [f"🔮 앞으로는? {outlook}", ""]
    all_tags = (hashtags.split() if hashtags else []) + ["#도토리뉴스", "#오늘의뉴스", "#카드뉴스"]
    seen = set()
    unique_tags = [t for t in all_tags if not (t in seen or seen.add(t))]
    lines += [
        "더 자세한 내용은 프로필 링크(blog.naver.com/dotory_news)에서 확인하세요.", "",
        " ".join(unique_tags),
    ]
    return "\n".join(lines)
