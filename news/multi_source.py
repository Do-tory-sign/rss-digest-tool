"""v2 다수 소스 수집 — 선정된 뉴스 주제로 Google News 검색, 여러 언론사 기사 본문 확보"""
import time
import urllib.parse

import feedparser

from news.collector import scrape_body
from news.curator import client, FALLBACK_MODELS

MIN_BODY_CHARS = 200          # 이보다 짧으면 본문 확보 실패로 간주

# 포털 재게재 소스 제외 (원 기사 중복 → 교차검증 의미 없음)
_PORTAL_BLOCKLIST = ("daum.net", "v.daum", "naver.com", "news.nate", "네이트", "다음뉴스", "네이버")
TARGET_SOURCES = 4            # 목표 소스 수 (선정 기사 포함)
MAX_CANDIDATES = 10           # 검색 결과에서 시도할 최대 후보 수


def _extract_keywords(headline: str) -> str:
    """기사 제목 → Google News 검색 키워드 2~4개 (Gemini, 실패 시 제목 앞부분)"""
    prompt = f"""다음 뉴스 제목에서 같은 사건을 다룬 다른 기사를 찾기 위한 검색 키워드를 뽑아주세요.

제목: {headline}

규칙:
- 고유명사(인물·기업·기관·제품명)와 핵심 사건 단어 위주로 2~4개
- 제목에 있는 단어만 사용할 것. 제목에 없는 인물명·이름을 추측해서 만들지 마세요
  (예: '李대통령'을 특정 이름으로 바꾸지 말고 '대통령' 그대로)
- 조사·어미 제거, 공백으로 구분
- 키워드만 한 줄로 출력 (설명·따옴표 없이)"""
    for model in FALLBACK_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            kw = resp.text.strip().splitlines()[0].strip().strip('"')
            if 2 <= len(kw) <= 60:
                return kw
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(5)
            else:
                break
    # 폴백: 제목에서 따옴표·괄호 제거 후 앞 4어절
    import re
    clean = re.sub(r'[\"\'“”‘’\[\]()…]', ' ', headline)
    return " ".join(clean.split()[:4])


def _search_google_news(keywords: str, limit: int = 15) -> list[dict]:
    """키워드로 Google News RSS 검색 (최근 2일)"""
    q = urllib.parse.quote(f"{keywords} when:2d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:limit]:
            results.append({
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "source": entry.get("source", {}).get("title", ""),
                "published": entry.get("published", ""),
            })
        return results
    except Exception as e:
        print(f"[multi_source] 검색 실패 ({keywords}): {e}")
        return []


def collect_sources(headline: str, primary_link: str = "", primary_source: str = "",
                    rss_summary: str = "") -> list[dict]:
    """선정 기사와 같은 주제의 기사들을 여러 언론사에서 수집.

    Returns:
        [{"outlet": 언론사명, "title": 제목, "body": 본문, "link": 원문 URL}, ...]  (본문 확보 성공분만)
    """
    keywords = _extract_keywords(headline)
    print(f"[multi_source] 검색 키워드: {keywords}")

    candidates = _search_google_news(keywords)
    print(f"[multi_source] 검색 결과 {len(candidates)}건")

    sources: list[dict] = []
    seen_outlets: set[str] = set()

    # 1) 원래 선정된 기사 먼저 (링크가 있으면) — 단, 포털(다음/네이버/네이트)이면 제외
    _primary_is_portal = any(
        p in (primary_source or "").lower() or p in (primary_link or "").lower()
        for p in _PORTAL_BLOCKLIST)
    if primary_link and not _primary_is_portal:
        body = scrape_body(primary_link, max_chars=3000, rss_summary=rss_summary)
        if body and len(body) >= MIN_BODY_CHARS:
            outlet = primary_source or "선정기사"
            sources.append({"outlet": outlet, "title": headline, "body": body, "link": primary_link})
            seen_outlets.add(outlet)
            print(f"[multi_source]   + {outlet} (선정기사, {len(body)}자)")
    elif _primary_is_portal:
        print(f"[multi_source]   - 선정기사가 포털({primary_source}) → 검색 소스로만 구성")

    # 2) 검색 결과에서 언론사 중복 없이 추가 확보
    tried = 0
    for c in candidates:
        if len(sources) >= TARGET_SOURCES or tried >= MAX_CANDIDATES:
            break
        outlet = c.get("source", "").strip()
        if not outlet or outlet in seen_outlets:
            continue
        if any(p in outlet.lower() or p in c.get("link", "").lower() for p in _PORTAL_BLOCKLIST):
            continue
        tried += 1
        body = scrape_body(c["link"], max_chars=3000)
        if body and len(body) >= MIN_BODY_CHARS:
            title = c["title"].rsplit(" - ", 1)[0].strip()
            sources.append({"outlet": outlet, "title": title, "body": body, "link": c.get("link", "")})
            seen_outlets.add(outlet)
            print(f"[multi_source]   + {outlet} ({len(body)}자)")
        else:
            print(f"[multi_source]   - {outlet} 본문 확보 실패")
        time.sleep(0.5)

    print(f"[multi_source] 최종 {len(sources)}개 소스 확보")
    return sources
