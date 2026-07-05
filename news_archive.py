"""매일 뉴스 데이터를 web/data.json에 누적 저장"""
import json
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "web" / "data.json"


def get_used_links(days: int = 7) -> set:
    """최근 N일간 사용된 기사 링크 반환 (중복 방지용)"""
    if not DATA_FILE.exists():
        return set()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    links = set()
    for entry in data[:days]:
        for item in entry.get("news", []):
            if item.get("link"):
                links.add(item["link"])
    return links


def get_week_data() -> list:
    """이번 주 월~토 데이터 반환 (일요일에 호출). Mon→Sat 순서."""
    from datetime import timedelta
    if not DATA_FILE.exists():
        return []
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    today = datetime.now()
    week_dates = {
        (today - timedelta(days=i)).strftime("%Y.%m.%d")
        for i in range(1, 7)
    }
    result = [e for e in data if e.get("date") in week_dates]
    result.sort(key=lambda e: e.get("date", ""))
    return result


def save_today(curated: dict[str, dict], v2_articles: list[dict] | None = None,
               date_override: str = "") -> None:
    """date_override: 'YYYYMMDD' 형식으로 지정하면 해당 날짜로 저장 (백필용)"""
    if date_override:
        d = datetime.strptime(date_override, "%Y%m%d")
        today = d.strftime("%Y.%m.%d")
    else:
        today = datetime.now().strftime("%Y.%m.%d")
    v2_by_cat = {a["category"]: a for a in (v2_articles or [])}

    news_items = []
    for cat_key, cat_label in [("hot", "hot"), ("economy", "economy"), ("culture", "culture")]:
        data = curated.get(cat_key, {})
        if not data.get("card_headline"):
            continue
        item: dict = {
            "category": cat_label,
            "headline": data.get("card_headline", ""),
            "summary":  data.get("card_summary", ""),
            "source":   data.get("source_name", ""),
            "link":     data.get("article_link", ""),
        }
        # v2 합성 데이터가 있으면 추가 (기사 본문 인라인 뷰용)
        v2 = v2_by_cat.get(cat_key)
        if v2 and v2.get("body"):
            item["headline"] = v2.get("title", item["headline"])
            item["summary"]  = v2.get("card_summary", item["summary"])
            item["lead"]     = v2.get("lead", "")
            item["body"]     = v2.get("body", [])
            item["outlets"]  = v2.get("outlets", [])
            item["source_count"] = v2.get("source_count", 1)
            item["hashtags"] = v2.get("hashtags", "")
            item["image"]    = ("v2/" + v2["image"]) if v2.get("image") else ""
            item["source"]   = ""
            item["link"]     = ""
        news_items.append(item)

    # 기존 데이터 불러오기
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        existing = []

    # 하루 3슬롯(아침/점심/저녁)이 각자 다른 시간에 따로 호출하므로, 오늘 항목을 통째로
    # 덮어쓰지 않고 카테고리 단위로 병합한다 — 안 그러면 점심 슬롯이 저장될 때 아침 기사가
    # 사라짐 (2026-06-29 하루 3회 발행 구조 도입 시 발견).
    today_entry = next((e for e in existing if e.get("date") == today), None)
    merged_by_cat = {item.get("category"): item for item in (today_entry.get("news", []) if today_entry else [])}
    for item in news_items:
        merged_by_cat[item.get("category")] = item
    merged_news = list(merged_by_cat.values())

    existing = [e for e in existing if e.get("date") != today]
    updated = [{"date": today, "news": merged_news}] + existing

    DATA_FILE.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[archive] {today} 저장 완료 (이번 호출 {len(news_items)}건, 오늘 누적 {len(merged_news)}건) → {DATA_FILE}")


def save_weekly_summary(keywords: dict, week_range: str) -> None:
    today = datetime.now().strftime("%Y.%m.%d")

    entry = {
        "date": today,
        "type": "weekly",
        "week_range": week_range,
        "news": [
            {"category": "hot",     "headline": keywords.get("hot", ""), "summary": "", "source": "", "link": ""},
            {"category": "economy", "headline": keywords.get("eco", ""), "summary": "", "source": "", "link": ""},
            {"category": "culture", "headline": keywords.get("trd", ""), "summary": "", "source": "", "link": ""},
        ],
    }

    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        existing = []

    existing = [e for e in existing if e.get("date") != today]
    updated = [entry] + existing

    DATA_FILE.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[archive] {today} 주간 요약 저장 완료 → {DATA_FILE}")
