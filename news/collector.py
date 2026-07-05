"""뉴스 수집 모듈 — Google News RSS + 네이버 많이 본 뉴스"""
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import email.utils
import time

from config import GOOGLE_NEWS_RSS, YONHAP_RSS

# 이번 실행에서 예외가 발생한 RSS URL 레이블 누적 (fetch_all_news 시작 시 초기화)
_fetch_errors: list[str] = []

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

KST = timezone(timedelta(hours=9))


def _is_today_kst(published: str) -> bool:
    """기사 발행일이 오늘 KST 날짜인지 확인 (GMT 기사도 KST 변환 후 비교)"""
    if not published:
        return False
    try:
        pub_dt = email.utils.parsedate_to_datetime(published)
        return pub_dt.astimezone(KST).date() == datetime.now(KST).date()
    except Exception:
        return False


def _is_recent(published: str, days: int = 2) -> bool:
    """최근 N일 내 기사인지 확인 — 날짜 없으면 통과"""
    if not published:
        return True
    try:
        pub_dt = email.utils.parsedate_to_datetime(published)
        now = datetime.now(pub_dt.tzinfo)
        return (now - pub_dt) <= timedelta(days=days)
    except Exception:
        return True


def _parse_feed(url: str, limit: int = 15) -> list[dict]:
    global _fetch_errors
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:limit * 3]:  # 필터 후 충분히 남도록 넉넉히 읽기
            published = entry.get("published", "")
            if not _is_recent(published, days=1):
                continue
            results.append({
                "title": entry.get("title", "").strip(),
                "summary": BeautifulSoup(
                    entry.get("summary", ""), "lxml"
                ).get_text()[:300].strip(),
                "link": entry.get("link", ""),
                "source": entry.get("source", {}).get("title", ""),
                "published": published,
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        label = url.split("/")[2] if "://" in url else url
        _fetch_errors.append(label)
        print(f"[collector] RSS 파싱 실패 ({url}): {e}")
        return []


def fetch_naver_popular() -> list[dict]:
    """네이버 많이 본 뉴스 (오늘 날짜)"""
    today = datetime.now().strftime("%Y%m%d")
    url = f"https://news.naver.com/main/ranking/popularDay.naver?rankingType=popular_day&date={today}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for a in soup.select("a.rankingnews_box"):
            title_tag = a.select_one("strong.ranking_headline")
            if title_tag:
                results.append({
                    "title": title_tag.get_text(strip=True),
                    "summary": "",
                    "link": "https://news.naver.com" + a.get("href", ""),
                    "source": "네이버 많이 본 뉴스",
                    "published": today,
                })
        return results[:10]
    except Exception as e:
        print(f"[collector] 네이버 많이 본 뉴스 실패: {e}")
        return []


def _parse_feed_today(url: str, limit: int = 15) -> list[dict]:
    """오늘 KST 날짜 기사만 파싱 (Google News GMT도 KST 변환 후 필터)"""
    global _fetch_errors
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:limit * 3]:
            published = entry.get("published", "")
            if not _is_today_kst(published):
                continue
            results.append({
                "title":     entry.get("title", "").strip(),
                "summary":   BeautifulSoup(entry.get("summary", ""), "lxml").get_text()[:300].strip(),
                "link":      entry.get("link", ""),
                "source":    entry.get("source", {}).get("title", ""),
                "published": published,
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        label = url.split("/")[2] if "://" in url else url
        _fetch_errors.append(label)
        print(f"[collector] RSS 파싱 실패 ({url}): {e}")
        return []


def fetch_all_news() -> tuple[dict[str, list[dict]], dict]:
    """카테고리별 뉴스 수집
    - 1차: Google News (다양한 언론사) + 연합뉴스 — 오늘 KST 날짜 기사만
    - 2차: 부족하면 연합뉴스 최근 2일로 확장
    - 3차: 여전히 3건 미만이면 네이버 많이 본 뉴스로 보강 (백업 소스)

    Returns:
        (news_by_category, health) 튜플
        health = {"counts": {...}, "fetch_errors": [...], "critical_categories": [...]}
    """
    global _fetch_errors
    _fetch_errors = []

    print("[collector] 뉴스 수집 시작...")

    # HOT: Google News 사회/연예 + 연합뉴스 사회/정치 (오늘 기사만)
    hot  = _parse_feed_today(GOOGLE_NEWS_RSS.get("hot_google", ""), 10)
    hot += _parse_feed_today(YONHAP_RSS["society"],  12)
    hot += _parse_feed_today(YONHAP_RSS["politics"], 8)

    time.sleep(0.5)

    # ECONOMY: Google News 경제/IT + 연합뉴스 경제/산업 (오늘 기사만)
    economy  = _parse_feed_today(GOOGLE_NEWS_RSS["tech"], 8)
    economy += _parse_feed_today(YONHAP_RSS["economy"],  12)
    economy += _parse_feed_today(YONHAP_RSS["industry"],  8)

    time.sleep(0.5)

    # CULTURE: Google News 연예 + 연합뉴스 연예/스포츠 (오늘 기사만)
    culture  = _parse_feed_today(GOOGLE_NEWS_RSS.get("culture_google", ""), 10)
    culture += _parse_feed_today(YONHAP_RSS["entertainment"], 12)
    culture += _parse_feed_today(YONHAP_RSS["sports"],         8)

    result = {
        "hot":     _dedupe(hot),
        "economy": _dedupe(economy),
        "culture": _dedupe(culture),
    }

    # 2차: 기사 부족 시 연합뉴스 2일치로 확장 (공휴일/새벽 대응)
    for cat, yonhap_keys, limit in [
        ("hot",     ["society", "politics"],   15),
        ("economy", ["economy", "industry"],   15),
        ("culture", ["entertainment", "sports"], 15),
    ]:
        if len(result[cat]) < 5:
            print(f"  [{cat}] 오늘 기사 부족 → 연합뉴스 2일치로 확장...")
            expanded = []
            for key in yonhap_keys:
                expanded += _parse_feed_days(YONHAP_RSS[key], limit, days=2)
            result[cat] = _dedupe(expanded)

    # 3차: 여전히 3건 미만이면 네이버 많이 본 뉴스로 보강 (소스 장애 대응)
    critical_before_naver = [cat for cat, items in result.items() if len(items) < 3]
    if critical_before_naver:
        print(f"  [backup] 네이버 많이 본 뉴스로 보강 시도 (부족: {critical_before_naver})...")
        naver_articles = fetch_naver_popular()
        if naver_articles:
            for cat in critical_before_naver:
                result[cat] = _dedupe(result[cat] + naver_articles)
                print(f"  [{cat}] 네이버 보강 후 {len(result[cat])}건")

    for cat, items in result.items():
        print(f"  [{cat}] {len(items)}개 수집")

    critical_categories = [cat for cat, items in result.items() if len(items) < 3]
    health = {
        "counts": {cat: len(items) for cat, items in result.items()},
        "fetch_errors": list(_fetch_errors),
        "critical_categories": critical_categories,
    }

    if _fetch_errors or critical_categories:
        print(f"  [⚠️ 장애] errors={_fetch_errors}, critical={critical_categories}")

    return result, health


def _parse_feed_days(url: str, limit: int, days: int) -> list[dict]:
    """days 파라미터를 직접 지정해서 피드 파싱"""
    global _fetch_errors
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:limit * 3]:
            published = entry.get("published", "")
            if not _is_recent(published, days=days):
                continue
            results.append({
                "title": entry.get("title", "").strip(),
                "summary": BeautifulSoup(
                    entry.get("summary", ""), "lxml"
                ).get_text()[:300].strip(),
                "link": entry.get("link", ""),
                "source": entry.get("source", {}).get("title", ""),
                "published": published,
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        label = url.split("/")[2] if "://" in url else url
        if label not in _fetch_errors:  # 같은 도메인 중복 제거
            _fetch_errors.append(label)
        print(f"[collector] RSS 파싱 실패 ({url}): {e}")
        return []


_KR_OUTLETS = [
    '연합뉴스', 'MBC', 'KBS', 'SBS', 'YTN', '조선일보', '동아일보', '중앙일보',
    '한국일보', '경향신문', '한겨레', '뉴시스', '뉴스1', '헤럴드경제', '한국경제',
    '매일경제', '머니투데이', '노컷뉴스', '오마이뉴스', '서울신문', '국민일보',
    '세계일보', '문화일보', '이데일리', '아시아경제', '데일리안',
]


def _is_cluster_content(text: str) -> bool:
    """구글뉴스 클러스터 페이지 내용인지 판별 (여러 언론사 이름 혼재)"""
    return sum(1 for o in _KR_OUTLETS if o in text) >= 3


def _is_garbage_content(text: str) -> bool:
    """날씨 위젯·광고·내비게이션 메뉴 등 쓸모없는 콘텐츠 감지"""
    import re
    # 날씨 데이터: "맑음XX 21.7℃" 패턴이 3개 이상
    weather_hits = len(re.findall(r'(맑음|흐림|구름|비|눈)\S*\s+\d+[\.\d]*℃', text))
    if weather_hits >= 3:
        return True
    # 기상청 제공 문구
    if '기상청 제공' in text:
        return True
    # 사이트 내비게이션 메뉴: '바로가기' 3회 이상 = 메뉴 텍스트
    if text.count('바로가기') >= 3:
        return True
    return False


def _clean_body_text(text: str) -> str:
    """본문 출처·저작권·byline 제거 (앞/끝/중간 모두 처리)"""
    import re
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append(line)
            continue
        # 기자 byline: "홍길동 매경 기자(email@x.com)" / "홍길동 기자" 단독 줄
        if re.search(r'기자\s*(\([^)]*\))?\s*$', s) and len(s) < 60:
            continue
        # 날짜 단독 줄: "2026. 5. 24. 09:27" / "2026-05-30 오전 5:14"
        if re.match(r'^\d{4}[\.\-]\s*\d+[\.\-]\s*\d+', s) and len(s) < 30:
            continue
        # "등록/수정 2026-05-30 오전..." 형식
        if re.match(r'^(등록|수정|입력|업데이트)\s+\d{4}', s):
            continue
        # ⓒ 저작권
        if re.match(r'^[ⓒ©]', s):
            continue
        # 이메일만 있는 줄
        if re.match(r'^[\w.+-]+@[\w.-]+\.\w+$', s):
            continue
        cleaned.append(line)

    # 연속 중복 줄 제거 (같은 문장이 바로 아래 반복되는 경우)
    deduped = []
    prev = None
    for line in cleaned:
        if line.strip() and line.strip() == prev:
            continue
        deduped.append(line)
        prev = line.strip() or prev

    text = "\n".join(deduped)
    # 본문 끝 언론사명 제거
    text = re.sub(r'\s*[ⓒ©]\s*\S+.*$', '', text, flags=re.MULTILINE | re.DOTALL)
    for outlet in _KR_OUTLETS:
        text = re.sub(rf'\s*{re.escape(outlet)}\s*$', '', text.rstrip())
    return text.strip()


def _scrape_via_playwright(url: str, max_chars: int = 2000) -> str | None:
    """Playwright로 Google News JS redirect 따라가서 실제 기사 본문 추출."""
    try:
        import trafilatura
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)
                # JS 리다이렉트 중인 경우 networkidle 대기 후 재시도
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                try:
                    html = page.content()
                except Exception:
                    page.wait_for_timeout(3000)
                    html = page.content()
            finally:
                browser.close()

        if _is_cluster_content(html[:3000]):
            print(f"[collector] 클러스터 페이지 감지, RSS 요약 사용")
            return None

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text.strip()) > 80 and not _is_cluster_content(text) and not _is_garbage_content(text):
            cleaned = _clean_body_text(text)[:max_chars]
            print(f"[collector] Playwright 본문 추출 성공 ({len(cleaned)}자)")
            return cleaned
        if text and _is_garbage_content(text):
            print(f"[collector] 날씨/광고 콘텐츠 감지, RSS 요약 사용")

    except Exception as e:
        print(f"[collector] Playwright 실패: {e}")

    return None


def scrape_body(url: str, max_chars: int = 2000, rss_summary: str = "") -> str:
    """기사 URL에서 본문 스크레이핑. 클러스터 페이지·실패 시 rss_summary 반환."""
    if not url:
        return _clean_body_text(rss_summary)[:max_chars]

    # Google News URL → Playwright로 JS redirect 따라가기
    if "news.google.com" in url:
        result = _scrape_via_playwright(url, max_chars)
        return result if result else _clean_body_text(rss_summary)[:max_chars]

    # 직접 URL → trafilatura 우선
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text and len(text.strip()) > 80 and not _is_cluster_content(text):
                return _clean_body_text(text)[:max_chars]
    except Exception:
        pass

    # BeautifulSoup fallback
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "figure"]):
            tag.decompose()

        for sel in ["#dic_area", "._article_body_contents", ".go_trans", "article",
                    ".article-body", ".article_view", ".news_view", ".view_con",
                    ".article-content", ".newsct_article", ".article_txt"]:
            el = soup.select_one(sel)
            if el:
                ps = [p.get_text(" ", strip=True) for p in el.select("p")
                      if len(p.get_text(strip=True)) > 25]
                if ps:
                    text = " ".join(ps)
                    if not _is_cluster_content(text):
                        return _clean_body_text(text)[:max_chars]
    except Exception:
        pass

    return _clean_body_text(rss_summary)[:max_chars]


def _dedupe(articles: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for a in articles:
        key = a["title"][:30]
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out
