"""Playwright로 HTML 카드뉴스 렌더링 → PNG"""
import base64
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from config import now_kst

TEMPLATES_DIR = Path(__file__).parent / "templates"
# 2026-07-05: 예전엔 사용자 로컬 PC의 절대경로(C:/Users/.../cardnews/assets/...)로 하드코딩돼
# 있어서 GitHub Actions 클라우드 러너(체크아웃 경로가 완전히 다름)에서 파일을 못 찾아 카드
# 생성이 통째로 실패했음 — 저장소 안의 assets/ 폴더를 __file__ 기준 상대경로로 참조하도록 수정.
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ACORN_PATH            = ASSETS_DIR / "dotory_news.png"
ACORN_ICON_PATH       = ASSETS_DIR / "favicon_acorn_transparent.png"
ACORN_ICON_RIGHT_PATH = ASSETS_DIR / "favicon_acorn_우측_transparent.png"

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

def _acorn_base64(path: Path = None) -> str:
    target = path or ACORN_PATH
    with open(target, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{data}"


def _image_base64(path: Path) -> str:
    """임의 이미지 파일을 base64 data URI로 변환."""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = Path(path).suffix.lstrip(".").lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64,{data}"

CAT_LABELS = {
    "hot":     "HOT 핫뉴스",
    "economy": "ECO 경제·IT",
    "culture": "TRD 트렌드",
}
CAT_CLASS = {
    "hot": "hot",
    "economy": "eco",
    "culture": "soc",
}


def _render(html: str, output_path: Path, size: tuple[int, int] = (1080, 1080)) -> Path:
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.set_content(html, wait_until="networkidle")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output_path), type="png")
            browser.close()
        print(f"[html_composer] 저장: {output_path}")
        return output_path
    except Exception as e:
        print(f"[html_composer] 렌더링 실패 ({output_path.name}): {e}")
        raise  # 호출부에서 이미지 수 검증하므로 예외 전파


def compose_cover(
    output_path: Path = None,
    headlines: dict = None,
    is_weekly: bool = False,
    week_range: str = "",
    keywords: dict = None,
) -> Path:
    if output_path is None:
        output_path = Path(f"output/cover_{now_kst().strftime('%Y%m%d')}.png")

    now = now_kst()
    days = ["월", "화", "수", "목", "금", "토", "일"]

    h = headlines or {}
    kw = keywords or {}
    tmpl = env.get_template("cover.html")
    html = tmpl.render(
        acorn_path=_acorn_base64(),
        date_badge=now.strftime("%Y.%m.%d"),
        date_main=f"{now.year}년 {now.month}월 {now.day}일 ({days[now.weekday()]})",  # Windows strftime 로케일 인코딩 버그 회피(2026-07-05)
        hot_headline=h.get("hot", {}).get("cover_headline") or h.get("hot", {}).get("card_headline", ""),
        eco_headline=h.get("economy", {}).get("cover_headline") or h.get("economy", {}).get("card_headline", ""),
        trd_headline=h.get("culture", {}).get("cover_headline") or h.get("culture", {}).get("card_headline", ""),
        is_weekly=is_weekly,
        week_range=week_range,
        hot_keyword=kw.get("hot", ""),
        eco_keyword=kw.get("eco", ""),
        trd_keyword=kw.get("trd", ""),
    )
    return _render(html, output_path)


def compose_profile_intro(output_path: Path = None) -> Path:
    if output_path is None:
        output_path = Path("output/profile_intro.png")

    tmpl = env.get_template("profile_intro.html")
    html = tmpl.render(acorn_path=_acorn_base64())
    return _render(html, output_path)


def compose_outro(output_path: Path = None) -> Path:
    if output_path is None:
        output_path = Path(f"output/outro_{now_kst().strftime('%Y%m%d')}.png")

    tmpl = env.get_template("outro.html")
    html = tmpl.render(acorn_path=_acorn_base64())
    return _render(html, output_path)


def _split_paragraphs(text: str, per_para: int = 2) -> str:
    """문장을 per_para개씩 묶어 <br><br>로 연결. \n 없으면 마침표 기준 분리."""
    import re
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) <= 1:
        lines = [s.strip() for s in re.split(r'(?<=[.?!。])\s+', text.strip()) if s.strip()]
    chunks = [" ".join(lines[i:i+per_para]) for i in range(0, len(lines), per_para)]
    return "<br><br>".join(chunks)


def compose_cover_v2(
    output_path: Path = None,
    headlines: dict = None,
    image_path: Path = None,
    date_override: str = "",
) -> Path:
    """B안 커버 — v2 일러스트 풀블리드 배경 + 텍스트 오버레이.
    date_override: 'YYYYMMDD' 형식으로 지정하면 해당 날짜로 표시 (백필용)"""
    if output_path is None:
        output_path = Path(f"output/cover_{now_kst().strftime('%Y%m%d')}.png")

    now = datetime.strptime(date_override, "%Y%m%d") if date_override else now_kst()
    days = ["월", "화", "수", "목", "금", "토", "일"]

    h = headlines or {}

    if image_path and Path(image_path).exists():
        image_src = _image_base64(image_path)
    else:
        # 이미지 없으면 기존 cover로 폴백
        return compose_cover(output_path, headlines=headlines)

    tmpl = env.get_template("cover_v2.html")
    html = tmpl.render(
        acorn_path=_acorn_base64(),
        image_src=image_src,
        date_badge=now.strftime("%Y.%m.%d"),
        date_main=f"{now.year}년 {now.month}월 {now.day}일 ({days[now.weekday()]})",  # Windows strftime 로케일 인코딩 버그 회피(2026-07-05)
        hot_headline=h.get("hot", {}).get("cover_headline") or h.get("hot", {}).get("card_headline", ""),
        eco_headline=h.get("economy", {}).get("cover_headline") or h.get("economy", {}).get("card_headline", ""),
        trd_headline=h.get("culture", {}).get("cover_headline") or h.get("culture", {}).get("card_headline", ""),
    )
    return _render(html, output_path)


def compose_story_v2(
    output_path: Path = None,
    image_path: Path = None,
    date_override: str = "",
) -> Path:
    """피드 게시물 업로드 후 자동 공유용 스토리 이미지 (1080x1920) —
    풀블리드 배경 + '프로필에서 확인하세요' 안내 문구. 인터랙티브 스티커 없이 텍스트로 디자인."""
    if output_path is None:
        output_path = Path(f"output/story_{now_kst().strftime('%Y%m%d')}.png")

    now = datetime.strptime(date_override, "%Y%m%d") if date_override else now_kst()

    if not image_path or not Path(image_path).exists():
        return None

    tmpl = env.get_template("story_v2.html")
    html = tmpl.render(
        acorn_path=_acorn_base64(),
        image_src=_image_base64(image_path),
        date_badge=now.strftime("%Y.%m.%d"),
    )
    return _render(html, output_path, size=(1080, 1920))


def compose_card_v2(
    category: str,
    headline: str,
    lead: str,
    source: str,
    image_path: Path,
    output_path: Path = None,
    date_override: str = "",
) -> Path:
    """A안 기사 카드 — 상단 이미지(55%) + 하단 텍스트(45%).
    date_override: 'YYYYMMDD' 형식으로 지정하면 해당 날짜로 표시 (백필용)"""
    if output_path is None:
        output_path = Path(f"output/{category}_{now_kst().strftime('%Y%m%d')}.png")

    if not Path(image_path).exists():
        # 이미지 없으면 기존 카드로 폴백
        return compose_card(category, headline, lead, source, output_path=output_path)

    image_src = _image_base64(image_path)
    date_str = (datetime.strptime(date_override, "%Y%m%d") if date_override else now_kst()).strftime("%Y.%m.%d")

    tmpl = env.get_template("card_v2.html")
    html = tmpl.render(
        category=CAT_CLASS.get(category, "hot"),
        cat_label=CAT_LABELS.get(category, category),
        acorn_path=_acorn_base64(ACORN_ICON_PATH),
        image_src=image_src,
        date=date_str,
        headline=headline,
        lead=lead,
        source=source,
    )
    return _render(html, output_path)


TIME_LABELS = {
    "morning": "☀️ 오늘의 아침한입",
    "lunch":   "🌤 오늘의 점심한입",
    "evening": "🌙 오늘의 저녁한입",
    "night":   "🌃 오늘의 야식한입",
}
SLOT_TITLES = {
    "morning": "오늘의 아침한입",
    "lunch":   "오늘의 점심한입",
    "evening": "오늘의 저녁한입",
    "night":   "오늘의 야식한입",
}


def compose_cover_explain(
    slot: str,
    category: str,
    headline: str,
    image_path: Path,
    output_path: Path,
    pose_path: Path = None,
) -> Path:
    """하루 3슬롯(아침/점심/저녁) 단일주제 게시물용 커버 — 일러스트 풀블리드 + 시간대 라벨.
    pose_path: 도토리 표정 자동매칭(news/character.py)으로 고른 포즈 이미지. 없으면 표정 배지 생략."""
    image_src = _image_base64(image_path) if image_path and Path(image_path).exists() else ""
    acorn_path = _acorn_base64(pose_path) if pose_path and Path(pose_path).exists() else ""
    now = now_kst()
    days = ["월", "화", "수", "목", "금", "토", "일"]
    tmpl = env.get_template("cover_explain.html")
    html = tmpl.render(
        image_src=image_src,
        slot_title=SLOT_TITLES.get(slot, "오늘의 뉴스"),
        date_badge=now.strftime("%Y.%m.%d"),
        date_main=f"{now.year}년 {now.month}월 {now.day}일 ({days[now.weekday()]})",  # Windows strftime 로케일 인코딩 버그 회피(2026-07-05)
        cat_label=CAT_LABELS.get(category, category),
        headline=headline,
        acorn_path=acorn_path,
        brand_icon_path=_acorn_base64(ACORN_ICON_RIGHT_PATH if ACORN_ICON_RIGHT_PATH.exists() else ACORN_ICON_PATH),
    )
    return _render(html, output_path)


def compose_explain_card(
    variant: str,
    category: str,
    label: str,
    slot: str = "morning",
    headline: str = "",
    image_path: Path = None,
    caption: str = "",
    text_align: str = "left",
    vp_a_label: str = "", vp_a_quote: str = "",
    vp_b_label: str = "", vp_b_quote: str = "",
    vp_summary: str = "",
    pose_path: Path = None,
    reaction: str = "",
    output_path: Path = None,
) -> Path:
    """설명형 카드 — variant: fact / why / outlook / viewpoint.
    말풍선 없이 라벨+타이포 중심, 카드 종류마다 텍스트 위치를 다르게 둬서 캐러셀에 리듬을 줌.
    pose_path: 도토리 표정 자동매칭(news/character.py)으로 고른 포즈 이미지. 없으면 배지 생략."""
    image_src = _image_base64(image_path) if image_path and Path(image_path).exists() else ""
    acorn_path = _acorn_base64(pose_path) if pose_path and Path(pose_path).exists() else ""
    body_classes = [variant]
    if text_align == "right":
        body_classes.append("right-align")

    tmpl = env.get_template("explain_card.html")
    html = tmpl.render(
        body_class=" ".join(body_classes),
        variant=variant,
        time_label=TIME_LABELS.get(slot, "오늘의 뉴스"),
        label=label,
        headline=headline,
        image_src=image_src,
        caption=caption,
        vp_a_label=vp_a_label, vp_a_quote=vp_a_quote,
        vp_b_label=vp_b_label, vp_b_quote=vp_b_quote,
        vp_summary=vp_summary,
        acorn_path=acorn_path,
        reaction=reaction,
        brand_icon_path=_acorn_base64(ACORN_ICON_RIGHT_PATH if ACORN_ICON_RIGHT_PATH.exists() else ACORN_ICON_PATH),
    )
    return _render(html, output_path)


def compose_weekly(category: str, week_rows: list, week_range: str, output_path: Path = None) -> Path:
    if output_path is None:
        output_path = Path(f"output/weekly_{category}_{now_kst().strftime('%Y%m%d')}.png")

    tmpl = env.get_template("weekly.html")
    html = tmpl.render(
        category=CAT_CLASS.get(category, "hot"),
        cat_label=CAT_LABELS.get(category, category),
        acorn_path=_acorn_base64(ACORN_ICON_PATH),
        week_range=week_range,
        rows=week_rows,
    )
    return _render(html, output_path)


def compose_card(
    category: str,
    headline: str,
    summary: str,
    source: str,
    link: str = "",
    output_path: Path = None,
    link_note: str = "원문은 프로필 링크에",
) -> Path:
    if output_path is None:
        output_path = Path(f"output/{category}_{now_kst().strftime('%Y%m%d')}.png")

    summary = summary.rstrip()
    summary_html = _split_paragraphs(summary)

    tmpl = env.get_template("card.html")
    html = tmpl.render(
        category=CAT_CLASS.get(category, "hot"),
        cat_label=CAT_LABELS.get(category, category),
        acorn_path=_acorn_base64(ACORN_ICON_PATH),
        date=now_kst().strftime("%Y.%m.%d"),
        headline=headline,
        summary=summary_html,
        source=source,
        link=link,
        link_note=link_note,
    )
    return _render(html, output_path)
