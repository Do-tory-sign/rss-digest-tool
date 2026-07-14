"""Google Gemini로 뉴스 큐레이션 — 기사 선택만, 제목/본문은 원문 스크레이핑"""
import json
import email.utils
from datetime import datetime
from google import genai
from config import GEMINI_API_KEY
from news.collector import KST, scrape_body

client = genai.Client(api_key=GEMINI_API_KEY)


def _age_label(published: str) -> str:
    """기사 발행일 → '오늘' / '어제' / '2일전' / '3일전'

    2026-07-10: 예전엔 pub_dt.tzinfo(구글뉴스는 GMT) 기준으로 경과 시간을 계산했는데,
    이건 collector.py의 "오늘" 판정(KST 달력 날짜 기준)과 기준 자체가 달라서 구글뉴스
    기사가 실제로는 오늘(KST)인데도 "어제"로 잘못 라벨링되는 경우가 있었음 — 그 결과
    큐레이션 프롬프트가 "오늘 기사만 선택"을 강제하면서 구글뉴스 후보들이 통째로
    빠지고 연합뉴스(원래 KST라 항상 정확히 라벨링됨)만 남는 편향이 생겼음.
    collector.py와 동일하게 KST 달력 날짜 차이로 통일한다.
    """
    if not published:
        return ""
    try:
        pub_dt = email.utils.parsedate_to_datetime(published).astimezone(KST)
        diff = (datetime.now(KST).date() - pub_dt.date()).days
        return ["오늘", "어제", "2일전", "3일전"][min(max(diff, 0), 3)]
    except Exception:
        return ""


def _news_list_text(articles: list[dict], limit: int = 15) -> str:
    lines = []
    for i, a in enumerate(articles[:limit], 1):
        age = _age_label(a.get("published", ""))
        age_str = f" [{age}]" if age else ""
        lines.append(f"{i}.{age_str} 제목: {a['title']}")
        if a.get("summary"):
            lines.append(f"   내용: {a['summary']}")
        if a.get("source"):
            lines.append(f"   출처: {a['source']}")
        if a.get("link"):
            lines.append(f"   링크: {a['link']}")
    return "\n".join(lines)


def _strip_source(title: str) -> str:
    """RSS 제목 끝의 ' - 언론사명' 제거"""
    parts = title.rsplit(" - ", 1)
    if len(parts) == 2 and len(parts[1].strip()) <= 25:
        return parts[0].strip()
    return title.strip()


_HONORIFIC_MAP = [
    ("했습니다", "했다"), ("됩니다", "된다"), ("입니다", "이다"),
    ("합니다", "한다"), ("있습니다", "있다"), ("없습니다", "없다"),
    ("입니다", "이다"), ("옵니다", "온다"), ("갑니다", "간다"),
    ("봅니다", "본다"), ("줍니다", "준다"), ("받습니다", "받는다"),
    ("밝혔습니다", "밝혔다"), ("전했습니다", "전했다"), ("말했습니다", "말했다"),
    ("했으며", "했으며"), ("됩니다", "된다"), ("으며", "으며"),
]

def _to_haera(text: str) -> str:
    """경어체 → 해라체 후처리 변환"""
    import re
    for honorific, plain in _HONORIFIC_MAP:
        text = text.replace(honorific, plain)
    # 남은 ~ㅂ니다 패턴 정리
    text = re.sub(r'(\w)ㅂ니다', r'\1다', text)
    return text


def _extract_key_sentences(raw_body: str, headline: str) -> str:
    """원문 기반 서론·본론·결론 3단락 요약. 원문에 없는 사실 창작 금지.
    클러스터/날씨/광고 등 기사 무관 내용이면 빈 문자열 반환."""
    if not raw_body or len(raw_body.strip()) < 50:
        return ""

    prompt = f"""아래는 뉴스 기사 원문입니다. 제목: {headline}

--- 원문 ---
{raw_body[:2000]}
--- 끝 ---

위 원문만을 근거로 아래 3단락 구조로 요약하세요. 총 500자 이내. 각 단락은 줄바꿈으로 구분하세요.

서론 (1~2문장): 이 뉴스가 무엇에 관한 것인지
본론 (2~3문장): 핵심 사실과 구체적 수치·내용
결론 (1문장): 의미·영향 또는 향후 전망

규칙:
1. 원문에 없는 사실은 절대 지어내지 마세요. 원문에 있는 정보만 사용하세요.
2. 원문이 날씨·광고·내비게이션('바로가기' 반복)·기사 목록처럼 기사 본문이 아니면 "SKIP"만 출력하세요.
3. 이모지, 마크다운, 단락 제목(서론/본론/결론 글자) 없이 텍스트만 출력하세요.
4. 문체는 반드시 '~했다', '~이다', '~전망이다' 형식의 신문 기사체(해라체)로 작성하세요. '~했습니다', '~입니다' 등 경어체는 절대 사용하지 마세요."""

    import time
    for model in FALLBACK_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = resp.text.strip()
            if text == "SKIP" or len(text) < 20:
                return ""
            # 후처리: 내비게이션 메뉴 텍스트 안전망
            if text.count('바로가기') >= 2:
                return ""
            # 후처리: 첫 줄이 headline과 80% 이상 겹치면 제거
            lines = text.splitlines()
            if lines and headline[:15] in lines[0]:
                lines = lines[1:]
            text = _to_haera("\n".join(lines).strip())
            return text[:600] if len(text) >= 20 else ""
        except Exception as e:
            err = str(e)
            if "503" in err or "UNAVAILABLE" in err:
                time.sleep(5)
            else:
                break
    return raw_body[:600]   # Gemini 전부 실패 시 원문 앞부분


def _describe_from_headline(headline: str) -> str:
    """원문 스크레이핑이 완전 실패했을 때 마지막 폴백.
    기사 제목만으로 Gemini가 이 뉴스가 어떤 내용인지 2문장으로 설명."""
    prompt = f"""다음 뉴스 제목에 대해 독자가 이 뉴스가 무엇에 관한 것인지 알 수 있도록
2~3문장으로 간결하게 설명해주세요.
추측이나 과장 없이 제목에서 유추할 수 있는 사실만 담으세요.
이모지, 마크다운 없이 텍스트만 출력하세요.
문체는 '~했다', '~이다' 형식의 신문 기사체(해라체)로 작성하세요.

뉴스 제목: {headline}"""
    import time
    for model in FALLBACK_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = resp.text.strip()
            if len(text) > 30:
                return _to_haera(text[:400])
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(5)
            else:
                break
    return ""


def _fill_from_article(result: dict, articles: list[dict]) -> dict:
    """선택된 기사의 원본 제목·링크·본문을 result에 채워넣기."""
    selected = result.get("selected_title", "")
    key = selected[:20]
    for a in articles:
        if key and key in a.get("title", ""):
            headline = _strip_source(a.get("title", result.get("card_headline", "")))
            result["article_title"] = headline   # 원제목 (카드 본문용)
            # Gemini가 만든 20자 요약을 cover_headline으로 보존, 없으면 원제목
            result["cover_headline"] = result.get("card_headline") or headline
            result["card_headline"] = headline   # 카드 본문엔 원제목
            result["article_link"] = a.get("link", result.get("article_link", ""))
            src = a.get("source", result.get("source_name", ""))
            if not src:
                link = a.get("link", "")
                if "yna.co.kr" in link:       src = "연합뉴스"
                elif "chosun.com" in link:    src = "조선일보"
                elif "joongang.co.kr" in link: src = "중앙일보"
                elif "hani.co.kr" in link:    src = "한겨레"
                elif "khan.co.kr" in link:    src = "경향신문"
                elif "donga.com" in link:     src = "동아일보"
                elif "mk.co.kr" in link:      src = "매일경제"
                elif "hankyung.com" in link:  src = "한국경제"
            result["source_name"] = src
            rss = _strip_source(a.get("summary", ""))
            raw_body = scrape_body(a.get("link", ""), rss_summary=rss)
            # Gemini extractive: 원문에서 핵심 문장 그대로 뽑기
            summary = _extract_key_sentences(raw_body, headline)
            if not summary:
                # extractive 실패 → 원문 앞부분에서 제목과 완전히 동일한 줄만 제거
                fb_lines = [l for l in raw_body[:600].splitlines()
                            if l.strip() and l.strip() != headline.strip()]
                summary = "\n".join(fb_lines).strip()[:500]
            # 제목 반복 감지: summary가 headline보다 25자 이상 길지 않으면 제목 변형일 뿐
            if summary and len(summary.strip()) < len(headline) + 25:
                print(f"[curator] 본문이 제목 반복으로 판단, 제목 기반 설명으로 전환")
                summary = ""
            if len(summary) < 60:
                print(f"[curator] 원문 없음, 제목 기반 설명 시도: {headline[:20]}")
                summary = _describe_from_headline(headline)
            result["card_summary"] = summary
            break
    return result


SYSTEM_PREFIX = """당신은 인스타그램 카드뉴스 에디터입니다.
뉴스 목록을 보고 기사 하나를 선택한 뒤, 카드뉴스 제목(20자 이내)만 작성해주세요.
본문 요약은 절대 작성하지 마세요. selected_title은 목록에 있는 제목을 그대로 복사하세요.
반드시 JSON 형식으로만 응답하세요. 이모지는 절대 사용하지 마세요.
반드시 [오늘] 기사만 선택하세요. [오늘] 기사가 없을 때만 [어제] 기사를 선택하세요.
[오늘] 기사 중 내용(요약)이 있는 기사를 우선 선택하세요.\n\n"""


def curate_hot(articles: list[dict], used_links: set = None) -> dict:
    if used_links:
        filtered = [a for a in articles if a.get("link", "") not in used_links]
        articles = filtered if filtered else articles
    prompt = SYSTEM_PREFIX + f"""다음은 오늘의 핫뉴스 목록입니다 (연예 포함):

{_news_list_text(articles)}

가장 핫하고 화제가 될 기사 하나를 선택해 아래 JSON으로 응답하세요:
{{
  "selected_title": "목록에 있는 원본 기사 제목 그대로",
  "card_headline": "카드뉴스 제목 (20자 이내, 임팩트 있게)",
  "hashtags": "#태그1 #태그2 #태그3 #태그4 #태그5",
  "source_name": "출처 언론사명",
  "article_link": "목록에 있는 링크 그대로"
}}"""
    result = _call_gemini(prompt)
    return _fill_from_article(result, articles)


def curate_economy(articles: list[dict], used_links: set = None) -> dict:
    if used_links:
        filtered = [a for a in articles if a.get("link", "") not in used_links]
        articles = filtered if filtered else articles
    prompt = SYSTEM_PREFIX + f"""다음은 오늘의 경제/IT 뉴스 목록입니다:

{_news_list_text(articles)}

가장 중요한 경제/IT 기사 하나를 선택해 아래 JSON으로 응답하세요:
{{
  "selected_title": "목록에 있는 원본 기사 제목 그대로",
  "card_headline": "카드뉴스 제목 (20자 이내, 핵심만)",
  "hashtags": "#경제 #IT #주식 #태그4 #태그5",
  "source_name": "출처 언론사명",
  "article_link": "목록에 있는 링크 그대로"
}}"""
    result = _call_gemini(prompt)
    return _fill_from_article(result, articles)


def curate_culture(articles: list[dict], used_links: set = None) -> dict:
    if used_links:
        filtered = [a for a in articles if a.get("link", "") not in used_links]
        articles = filtered if filtered else articles
    prompt = SYSTEM_PREFIX + f"""다음은 오늘의 트렌드/문화/스포츠 뉴스 목록입니다:

{_news_list_text(articles)}

오늘 사람들이 가장 많이 이야기할 것 같은 문화·트렌드 기사 하나를 선택해주세요.
드라마·영화·스포츠·MZ트렌드·소비이슈·바이럴 콘텐츠 등이 좋습니다.

아래 JSON으로 응답하세요:
{{
  "selected_title": "목록에 있는 원본 기사 제목 그대로",
  "card_headline": "카드뉴스 제목 (20자 이내)",
  "hashtags": "#트렌드 #문화 #태그3 #태그4 #태그5",
  "source_name": "출처 언론사명",
  "article_link": "목록에 있는 링크 그대로"
}}"""
    result = _call_gemini(prompt)
    return _fill_from_article(result, articles)


def curate_any(news_by_cat: dict, used_links: set = None, exclude_categories: list = None,
               used_headlines: list = None) -> dict:
    """2026-07-02: 하루 4슬롯(아침/점심/저녁/야식)이 더 이상 카테고리에 고정되지 않고,
    그 시간대 전체 후보(hot+economy+culture) 중 가장 화제성 높은 기사 하나를 뽑는다.
    exclude_categories: 오늘 다른 슬롯에서 이미 쓴 카테고리 — 같은 날 카테고리 중복 방지.
    used_headlines: 최근 사용된 헤드라인 — 링크는 달라도 같은 사건이면 걸러내기 위함
    (2026-07-14, 중복 기사 반복 선정 문제 대응)."""
    exclude_categories = set(exclude_categories or [])
    pools = {cat: arts for cat, arts in news_by_cat.items() if cat not in exclude_categories}
    if not pools:
        pools = news_by_cat  # 다 제외됐으면 어쩔 수 없이 전체 허용(하루 슬롯 > 카테고리 수인 경우)

    combined: list[dict] = []
    for cat, arts in pools.items():
        if used_links:
            filtered = [a for a in arts if a.get("link", "") not in used_links]
            arts = filtered if filtered else arts
        for a in arts[:15]:
            a = dict(a)
            a["_cat"] = cat
            combined.append(a)

    recent_text = ""
    if used_headlines:
        joined = "\n".join(f"- {h}" for h in used_headlines)
        recent_text = f"""

아래는 최근 며칠간 이미 다룬 헤드라인입니다. 링크나 언론사가 다르더라도 같은
사건/이슈를 다루는 기사는 절대 다시 선택하지 마세요 (후속 보도, 종합 기사 포함):
{joined}"""

    prompt = SYSTEM_PREFIX + f"""다음은 지금 이 시간대의 뉴스 후보 전체 목록입니다
(핫이슈·경제/IT·트렌드/문화 카테고리 구분 없이 전부 섞여있음):

{_news_list_text(combined, limit=len(combined))}
{recent_text}

카테고리 상관없이, 지금 가장 화제성 높고 사람들이 궁금해할 기사 하나만 선택해
아래 JSON으로 응답하세요:
{{
  "selected_title": "목록에 있는 원본 기사 제목 그대로",
  "card_headline": "카드뉴스 제목 (20자 이내, 임팩트 있게)",
  "hashtags": "#태그1 #태그2 #태그3 #태그4 #태그5",
  "source_name": "출처 언론사명",
  "article_link": "목록에 있는 링크 그대로"
}}"""
    result = _call_gemini(prompt)
    result = _fill_from_article(result, combined)

    selected = result.get("selected_title", "")[:20]
    picked_cat = next((a["_cat"] for a in combined if selected and selected in a.get("title", "")), "hot")
    result["_picked_category"] = picked_cat
    return result


def generate_weekly_keywords(week_data: list) -> dict:
    """이번 주(월~토) 6일치 헤드라인으로 HOT/ECO/TRD 주간 키워드 한 줄씩 생성."""
    headlines = []
    for entry in week_data:
        for item in entry.get("news", []):
            cat = item.get("category", "")
            headline = item.get("headline", "")
            if headline:
                headlines.append(f"[{cat.upper()}] {headline}")

    if not headlines:
        return {"hot": "", "eco": "", "trd": ""}

    prompt = f"""아래는 이번 주(월~토) DO's TORY NEWS 헤드라인입니다.

{chr(10).join(headlines)}

위 헤드라인을 보고 이번 주의 흐름을 카테고리별로 요약해주세요.
각 카테고리에서 2~3개 주제를 쉼표로 나열하되, 각 주제는 읽는 사람이 무슨 일인지 바로 알 수 있도록 짧은 구(句) 형태로 써주세요.
단어 하나로 끝내지 말고, 핵심 행위나 결과가 담긴 명사구로 써주세요. (예: "李대통령 허위사실 엄단", "HBM4 수주 전쟁", "K팝 美 정규과목 채택")
전체 50자 이내, 이모지 없이.

반드시 위 헤드라인에 실제로 등장하는 사실·인물·사건만 사용하세요.
헤드라인에 없는 단어나 사건을 절대 만들어내지 마세요.

아래 JSON 형식으로만 응답하세요:
{{"hot": "주제1, 주제2, 주제3", "eco": "주제1, 주제2", "trd": "주제1, 주제2"}}"""

    import time
    for _ in range(3):
        result = _call_gemini(prompt)
        kw = {
            "hot": result.get("hot", ""),
            "eco": result.get("eco", ""),
            "trd": result.get("trd", ""),
        }
        if all(kw.values()):
            return kw
        missing = [k for k, v in kw.items() if not v]
        print(f"[curator] 주간 키워드 일부 빈값 ({missing}), 재시도...")
        time.sleep(3)
    return kw


FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"]
# 2026-07-02: gemini-1.5-flash가 구글에서 완전히 제거돼(404 NOT_FOUND) 앞의 두 모델이
# 일시 과부하(503)일 때 마지막 안전망까지 같이 죽는 사고가 있었음(저녁한입 AI합성 실패 →
# 규칙기반 폴백으로 대체됨). gemini-2.0-flash도 이미 404로 제거됨 확인 — 항상 최신을 가리키는
# gemini-flash-latest(alias)로 교체해 이후로도 모델명 노후화로 다시 안 죽게 함.

def _call_gemini(prompt: str) -> dict:
    import time
    for model_name in FALLBACK_MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw = response.text.strip()
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                return json.loads(raw.strip())
            except json.JSONDecodeError as e:
                print(f"[curator] JSON 파싱 실패 (시도 {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2)
                    continue
                break
            except Exception as e:
                err = str(e)
                if "503" in err or "UNAVAILABLE" in err:
                    wait = (attempt + 1) * 5
                    print(f"[curator] {model_name} 과부하, {wait}초 후 재시도...")
                    time.sleep(wait)
                else:
                    print(f"[curator] {model_name} 실패: {e}")
                    break
    print("[curator] 모든 모델 실패")
    return {}
