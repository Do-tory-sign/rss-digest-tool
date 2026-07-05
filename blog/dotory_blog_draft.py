"""도토리뉴스 기사(v2_articles_<slot>.json)로 네이버 블로그 초안(제목/본문/사진)을 만든다.

GSoul(지솔이슈)의 gsoul_blog_draft.py 구조를 참고해서 도토리뉴스 카드 데이터(사실/시각차이/
왜중요/전망)에 맞게 다시 짰다. main.py가 카드뉴스를 만들 때 쓰는 것과 같은 article dict를
그대로 입력으로 받는다 — 새로 수집하거나 합성하지 않는다.

2026-07-02: 하루 4슬롯(아침/점심/저녁/야식)이 카테고리에 고정되지 않게 되면서 파일이
카테고리가 아니라 슬롯 기준으로 저장됨(v2_curated_<slot>.json 등) — 이 스크립트도 슬롯
기준으로 맞춤. 실제 카테고리는 그 슬롯 기사 데이터 안(article["category"])에서 가져온다.

본문 마크업(naver_engine.py가 그대로 해석):
  {{big:문구}}    크게
  {{point:문구}}  굵게+색
  [photo_01.jpg]  해당 번호의 이미지를 그 자리에 삽입

사용법:
    python -X utf8 dotory_blog_draft.py --slot morning
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent
V2_DIR = ROOT.parent / "web" / "v2"
OUT_DIR = ROOT / "drafts"


def _load_article(slot: str) -> tuple[dict, dict]:
    today = datetime.now().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    curated_path = run_dir / f"v2_curated_{slot}.json"
    articles_path = run_dir / f"v2_articles_{slot}.json"
    curated = json.loads(curated_path.read_text(encoding="utf-8")) if curated_path.exists() else {}
    articles = json.loads(articles_path.read_text(encoding="utf-8")).get("articles", []) if articles_path.exists() else []
    article = articles[0] if articles else {}
    data = curated.get(article.get("category", ""), {})
    return data, article


def _find_card_images(slot: str) -> dict[str, Path]:
    """main.py가 만들어둔 실제 카드뉴스 PNG(커버/오늘의 사실/왜중요/앞으로는)를 찾아서
    변수명 -> 경로로 반환. 같은 AI 일러스트를 반복하는 대신 실제 카드를 블로그에 그대로 재사용한다."""
    today = datetime.now().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    found = {}
    for name in ("cover", "fact", "viewpoint", "why", "outlook"):
        matches = sorted(run_dir.glob(f"{slot}_*_{name}.png"))
        if matches:
            found[name] = matches[0]
    return found


def build_draft(slot: str, data: dict, article: dict) -> dict:
    category = article.get("category", "hot")
    title = article.get("title") or data.get("card_headline") or "오늘의 이슈"
    lead = article.get("lead", "")
    body_paragraphs = article.get("body") or []
    why = article.get("why_it_matters", "")
    outlook = article.get("outlook", "")
    has_vp = bool(article.get("has_viewpoint_diff"))

    n_src = article.get("source_count", 1)
    outlets = article.get("outlets", [])
    src_label = f"{n_src}곳 종합" if n_src >= 2 else (outlets[0] if outlets else data.get("source_name", ""))

    intro = (
        f"{src_label or '여러 언론'} 보도를 바탕으로 도토리가 쉽게 정리했어요. "
        "사진 아래 설명을 따라가면 핵심이 한눈에 들어와요."
    )

    hook = lead or (body_paragraphs[0] if body_paragraphs else "")

    # 카드뉴스 실물 이미지 사용 가능한 파일에 따라 사진 번호를 순서대로 배정
    # 순서: 인트로(출처 안내) → 커버 → "오늘의 사실" 헤더 → 훅(핵심 한 줄) → 팩트 사진 → 본문
    card_images = _find_card_images(slot)
    photo_num = {}
    _next_num = [1]
    def _assign(name: str) -> str:
        if name not in card_images:
            return ""
        photo_num[name] = _next_num[0]
        token = f"[photo_{_next_num[0]:02d}.jpg]"
        _next_num[0] += 1
        return token

    cover_token = _assign("cover")
    fact_token = _assign("fact")
    viewpoint_token = _assign("viewpoint")
    why_token = _assign("why")
    outlook_token = _assign("outlook")

    parts = [
        intro,
        cover_token,
        "{{bigb:| 오늘의 사실}}",
        hook,
        fact_token,
    ]

    for p in body_paragraphs:
        parts.append(p)

    if has_vp:
        a_label = article.get("viewpoint_a_label", "")
        a_quote = article.get("viewpoint_a_quote", "")
        b_label = article.get("viewpoint_b_label", "")
        b_quote = article.get("viewpoint_b_quote", "")
        summary = article.get("viewpoint_summary", "")
        parts += [
            "{{bigb:| 서로 다른 시각}}",
            viewpoint_token,
            f"{a_label}: {a_quote}" if a_label else "",
            f"{b_label}: {b_quote}" if b_label else "",
            f"{{{{point:{summary}}}}}" if summary else "",
        ]

    if why:
        parts += ["{{bigb:| 왜 중요할까요?}}", why_token, why]
    if outlook:
        parts += ["{{bigb:| 앞으로는?}}", outlook_token, outlook]

    hashtags = article.get("hashtags", "")
    parts.append("{{color:다음 소식도 도토리가 냉큼 물어올게요~ 🌰}}")
    if hashtags:
        parts.append(hashtags)

    # naver_engine.py가 "<라벨>: <url>" 패턴을 자동으로 클릭 가능한 링크로 바꿔줌
    # (뒤에 다른 텍스트가 붙으면 자동링크 인식이 깨지므로 "언론사명: url" 형태로 한 줄에
    #  묶어서 둘 것 — 예전엔 언론사명과 "원문: url"을 별도 줄로 뒀는데, 렌더링에서 두 줄이
    #  붙어보여 "한겨레원문: ..."처럼 보이는 문제가 있어서 2026-07-03에 한 줄로 통일)
    source_links = [s for s in article.get("source_links", []) if s.get("link")]
    has_source = bool(source_links) or bool(data.get("article_link") or article.get("article_link", ""))
    if has_source:
        # naver_engine.py의 _type_body_text가 연속 빈 줄을 전부 문단 하나로 뭉개버려서
        # (re.split(r"\n{2,}", ...)) 그냥 개행만 늘리면 효과가 없음 — 눈에 보이지 않는
        # 문자(zero-width space)로 된 빈 문단을 2개 끼워넣어 실제로 빈 줄 2개를 더 만든다.
        parts += ["​", "​"]
    if source_links:
        parts.append("{{point:원문 보기}}")
        for s in source_links:
            outlet = s.get("outlet", "").strip()
            parts.append(f"{outlet}: {s['link']}" if outlet else s["link"])
    else:
        article_link = data.get("article_link") or article.get("article_link", "")
        if article_link:
            parts.append(f"원문: {article_link}")

    body = "\n\n".join(p for p in parts if p)

    # photo_num에 배정된 순서 그대로 실제 파일 목록 구성 (없으면 AI 일러스트 하나로 폴백)
    if photo_num:
        images = [str(card_images[name]) for name, _ in sorted(photo_num.items(), key=lambda kv: kv[1])]
    else:
        img_path = V2_DIR / article["image"] if article.get("image") else None
        images = [str(img_path)] * 3 if img_path and img_path.exists() else []

    return {
        "title": title,
        "body": body,
        "category": category,
        "images": images,
        "source": src_label,
    }


def main():
    slot = None
    if "--slot" in sys.argv:
        idx = sys.argv.index("--slot")
        if idx + 1 < len(sys.argv):
            slot = sys.argv[idx + 1]
    if slot not in ("morning", "lunch", "evening", "night"):
        print("사용법: python dotory_blog_draft.py --slot morning|lunch|evening|night")
        sys.exit(2)

    data, article = _load_article(slot)
    if not article:
        print(f"[blog] {slot} 작업용 데이터 없음 — main.py/v2_main.py 먼저 실행 필요")
        sys.exit(1)

    draft = build_draft(slot, data, article)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"blog_draft_{stamp}_{slot}.json"
    out_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BLOG_DRAFT] {out_path}")
    print(f"[TITLE] {draft['title']}")
    return out_path


if __name__ == "__main__":
    main()
