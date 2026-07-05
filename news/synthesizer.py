"""v2 팩트 합성 — 여러 소스의 공통 팩트만 모아 해요체 도토리뉴스 기사로 재작성"""
import json
import time

from news.curator import client, FALLBACK_MODELS

_VALID_EMOTIONS = {"angry", "cheering", "confused", "disappointed", "excited",
                    "happy", "sad", "surprised", "thinking", "worried"}


def _sources_text(sources: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(f"[소스 {i} | {s['outlet']}] 제목: {s['title']}\n{s['body'][:2500]}")
    return "\n\n---\n\n".join(parts)


SYNTH_PROMPT = """당신은 'DO's TORY NEWS'(도토리뉴스)의 에디터입니다.
도토리뉴스는 2030 MZ세대를 위한 신뢰할 수 있는 뉴스 페이지입니다.
아래는 같은 사건을 다룬 여러 언론사의 기사입니다. 이를 바탕으로 도토리뉴스만의 기사 하나를 작성하세요.

{sources}

작성 규칙 (반드시 지킬 것):
1. **팩트만**: 여러 소스에서 공통으로 확인되는 사실 위주로 작성하세요. 한 소스에만 있는 내용은 핵심 수치·발언처럼 구체적인 사실일 때만 포함하고, 추측·전망·'~할 것으로 보인다' 류의 카더라는 모두 제외하세요. 단, 공식 발표된 계획·일정은 사실이므로 포함 가능합니다.
2. **소스에 없는 내용 창작 절대 금지**: 소스에 없는 사실, 수치, 발언을 지어내지 마세요.
3. **문체**: 해요체 기본, 전언체는 필요한 곳에만.
   - **확인된 사실**은 해요체로 명료하게: '~했어요', '~예요', '~있어요', '~이에요'
     (예: "비트코인이 6만 달러 아래로 떨어졌어요.")
   - **누군가의 발언·주장·전망·계획**은 전언체로: '~한대요', '~했대요', '~라고 해요', '~전망이래요'
     (예: "전문가들은 추가 하락 가능성이 있다고 해요.")
   - 전언체를 모든 문장에 남발하면 사실도 루머처럼 들리므로 금지
   - 같은 어미가 두 문장 연속 반복되지 않게 변화를 줄 것
   - 반말('~했어', '~야') 금지
   - 합쇼체('~합니다', '~했습니다', '~입니다') 금지 — 모든 문장은 '~요'로 끝나야 합니다
   - 제목에 느낌표(!) 금지
4. **초등학생도 이해할 수 있게 꼭꼭 씹어서 쓸 것 (매우 중요)**: 카드뉴스뿐 아니라 블로그
   글에도 그대로 쓰이는 본문이므로, 전문용어·업계 용어·약어는 절대 그대로 두지 말고 초등학생도
   알아들을 수 있는 쉬운 말로 풀어 쓰세요.
   - AI·반도체·금융·법률 등 전문 분야 용어는 특히 더 신경 써서 풀어줄 것
     (나쁜 예: "AI 반도체 수요 폭증으로 4나노 공정이 완판되고 얼로케이션에 돌입했어요" —
      초등학생은 "4나노 공정", "얼로케이션"이 뭔지 전혀 모름
      좋은 예: "인공지능(AI)에 쓰이는 칩을 만드는 공장이 너무 바빠져서, 이제 아무 주문이나
      다 받지 않고 좋은 주문만 골라서 받고 있어요")
   - 괄호로 용어 정의만 툭 붙이는 방식("수율(정상 작동하는 비율)")보다는, 가능하면 문장
     자체를 쉬운 말로 다시 쓰는 쪽을 우선하세요. 정 어려우면 괄호 설명도 괜찮지만, 그 경우에도
     설명 자체가 또 어려우면 안 됩니다.
   - 영문 약어(AI, IPO, GDP 등)는 처음 나올 때 무엇의 줄임말인지 간단히 밝히거나 우리말로
     바꿔 쓸 것. 숫자로 된 전문 스펙(나노 공정, 금리 %p 등)은 꼭 필요한 게 아니면 생략하고
     "더 좋은/빠른/작은" 같은 체감되는 표현으로 바꿔도 좋음.
   - 이 규칙은 body뿐 아니라 card_summary, why_it_matters, outlook 등 모든 텍스트 필드에
     동일하게 적용됩니다.
5. **구조**: 본문은 3~5개 문단. 첫 문단은 무슨 일인지 핵심부터, 중간은 구체적 사실·배경, 마지막은 확인된 의미나 다음 일정.
6. 이모지, 마크다운, 과장 표현("충격", "경악") 금지.

7. **제목 정확성 (가장 중요)**: 제목은 기사의 핵심 사실 '하나'만 담으세요.
   - 서로 다른 사건·사실을 한 문장으로 묶어 인과관계처럼 보이게 하지 마세요.
     (나쁜 예: "행정 마비에 책임자들 사임" — 행정 마비와 사임이 별개 사실이면 왜곡)
   - 본문을 읽고 나서 "제목이 과장됐네"라는 느낌이 들면 안 됩니다.
   - 호기심 유발은 환영하지만, 방법은 과장이 아니라 '궁금증을 남기는 표현'으로.
     (좋은 예: "젠슨 황 다녀간 식당, 지금 무슨 일이 벌어지고 있을까요?")

8. **왜 중요한지(why_it_matters)**: 이 사실이 독자에게/사회적으로 왜 의미가 있는지 한두 문장.
   단순 재요약이 아니라 "그래서 어떤 영향이 있는지"를 짚을 것. 가능하면 **독자(우리)와의 직접적인
   연관**도 같이 짚을 것 — 예: 생활비/물가에 영향, 내가 쓰는 서비스에 영향, 다음 선거·정책에 영향
   등 "그래서 나랑 무슨 상관인지"가 드러나게. 직접 연관을 찾기 어려운 사안(예: 먼 나라 사건)이면
   사회적 의미만 짚어도 괜찮음 — 억지로 끼워맞추지 말 것.
9. **전망(outlook)**: 다음에 무슨 일이 있을지, 무엇을 지켜봐야 하는지 한 문장. 소스에 근거 없는
   추측은 금지 — 예정된 일정(다음 재판, 다음 발표 등)이나 소스가 직접 언급한 전망만 사용.
   확실한 다음 일정이 없으면 "이후 상황을 계속 지켜봐야 해요" 같은 일반적 문장도 괜찮음.
10. **시각 차이(has_viewpoint_diff)**: 이 사안에 대해 **서로 다른 이해관계자(예: 정부 vs 단체,
    여당 vs 야당, 기업 vs 소비자단체)가 공개적으로 다른 입장을 밝힌 경우만** true로 표시하세요.
    단순히 "사람들 반응이 갈린다" 같은 건 해당 안 됨 — 소스에 두 입장이 명확히 인용돼 있어야 함.
    확실하지 않으면 false로 두세요.
11. **캐릭터 리액션(reaction_fact/why/outlook)**: 마스코트 '도토리'가 직접 말하는 것처럼
    각 카드 옆 말풍선에 들어갈 아주 짧은 한마디(각 25자 이내, 해요체, 구어체).
    - reaction_fact: 방금 사실을 접하고 놀라거나 궁금해하는 반응. (예: "우와, 진짜 그만큼 든대요?")
    - reaction_why: 왜 중요한지 듣고 납득하거나 되묻는 반응. (예: "그럼 우리한테도 좋은 거네요?")
    - reaction_outlook: 앞으로가 궁금하거나 기대/걱정하는 반응. (예: "다음엔 또 어떻게 될지 궁금해요!")
    딱딱한 요약투 금지, 실제 대화처럼 자연스럽게.
12. **캐릭터 표정(emotion_fact/why/outlook)**: 각 카드에서 도토리가 지을 표정을 실제
    내용에 맞게 골라주세요. 아래 10종 중 하나만 정확히 그대로 쓸 것:
    angry, cheering, confused, disappointed, excited, happy, sad, surprised, thinking, worried
    - emotion_fact: 방금 사실을 접했을 때 어울리는 표정 (충격적이면 surprised, 좋은 소식이면
      excited/happy, 안타까운 소식이면 sad/worried 등 — 내용의 실제 성격에 맞출 것)
    - emotion_why: 왜 중요한지 설명을 들었을 때 어울리는 표정
    - emotion_outlook: 앞으로 전망을 들었을 때 어울리는 표정 (불확실하면 thinking/confused,
      기대되면 excited/cheering, 우려되면 worried 등)
    세 카드가 다 같은 표정일 필요 없음 — 오히려 내용 흐름에 따라 자연스럽게 바뀌는 게 좋음.

아래 JSON 형식으로만 응답하세요:
{{
  "title": "도토리뉴스 기사 제목 (해요체 또는 명사형, 35자 이내, 핵심 사실 하나만, 낚시성 금지)",
  "card_headline": "인스타 카드용 짧은 제목 (20자 이내)",
  "lead": "기사 요약 한두 문장 (해요체, 80자 이내) — 메인 페이지 카드에 표시",
  "body": ["문단1", "문단2", "문단3"],
  "card_summary": "인스타 카드용 요약 (해요체, 3~4문장, 300자 이내, 줄바꿈으로 문장 구분)",
  "hashtags": "#태그1 #태그2 #태그3 #태그4 #태그5",
  "why_it_matters": "왜 중요한지 (해요체, 70자 이내)",
  "outlook": "앞으로 어떻게 될지/뭘 지켜봐야 하는지 (해요체, 70자 이내)",
  "has_viewpoint_diff": false,
  "viewpoint_a_label": "입장1 주체 (예: 협회 측, 없으면 빈 문자열)",
  "viewpoint_a_quote": "입장1 핵심 (해요체 인용, 없으면 빈 문자열)",
  "viewpoint_b_label": "입장2 주체 (없으면 빈 문자열)",
  "viewpoint_b_quote": "입장2 핵심 (없으면 빈 문자열)",
  "viewpoint_summary": "결국 핵심 쟁점 한 줄 (has_viewpoint_diff가 false면 빈 문자열)",
  "reaction_fact": "도토리가 사실을 보고 하는 짧은 리액션 (해요체, 25자 이내)",
  "reaction_why": "도토리가 왜중요한지 듣고 하는 짧은 리액션 (해요체, 25자 이내)",
  "reaction_outlook": "도토리가 전망을 듣고 하는 짧은 리액션 (해요체, 25자 이내)",
  "emotion_fact": "10종 중 하나 (angry/cheering/confused/disappointed/excited/happy/sad/surprised/thinking/worried)",
  "emotion_why": "10종 중 하나",
  "emotion_outlook": "10종 중 하나"
}}"""


_HAEYO_MAP = [
    ("라고 합니다", "라고 해요"), ("다고 합니다", "다고 해요"),
    ("했습니다", "했어요"), ("있습니다", "있어요"), ("없습니다", "없어요"),
    ("입니다", "이에요"), ("합니다", "해요"), ("됩니다", "돼요"),
    ("바 있습니다", "바 있어요"), ("답니다", "대요"),
]


def _to_haeyo(text: str) -> str:
    """합쇼체 잔여분 → 해요체 후처리 (Gemini가 규칙을 어긴 경우 안전망)"""
    for fr, to in _HAEYO_MAP:
        text = text.replace(fr, to)
    return text


def synthesize(sources: list[dict]) -> dict:
    """소스 N개 → 도토리뉴스 합성 기사. 실패 시 빈 dict."""
    if not sources:
        return {}

    prompt = SYNTH_PROMPT.format(sources=_sources_text(sources))

    for model in FALLBACK_MODELS:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                raw = resp.text.strip()
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                result = json.loads(raw.strip())
                # 최소 품질 검증
                body = result.get("body", [])
                if isinstance(body, str):
                    body = [p for p in body.split("\n") if p.strip()]
                    result["body"] = body
                if not result.get("title") or len(body) < 2:
                    raise ValueError("title/body 부족")
                result["title"] = result["title"].replace("! ", ", ").replace("!", "").strip()
                result["body"] = [_to_haeyo(p) for p in body]
                for key in ("lead", "card_summary", "why_it_matters", "outlook",
                            "viewpoint_a_quote", "viewpoint_b_quote", "viewpoint_summary",
                            "reaction_fact", "reaction_why", "reaction_outlook"):
                    if result.get(key):
                        result[key] = _to_haeyo(result[key])
                result["has_viewpoint_diff"] = bool(result.get("has_viewpoint_diff")) and bool(
                    result.get("viewpoint_a_quote")) and bool(result.get("viewpoint_b_quote"))
                for key, default in (("emotion_fact", "surprised"), ("emotion_why", "thinking"),
                                     ("emotion_outlook", "thinking")):
                    if result.get(key) not in _VALID_EMOTIONS:
                        result[key] = default
                result["outlets"] = [s["outlet"] for s in sources]
                result["source_count"] = len(sources)
                result["source_links"] = [{"outlet": s.get("outlet", ""), "link": s.get("link", "")} for s in sources]
                return result
            except json.JSONDecodeError as e:
                print(f"[synthesizer] JSON 파싱 실패 ({model}, {attempt+1}): {e}")
                time.sleep(2)
            except ValueError as e:
                print(f"[synthesizer] 품질 미달 ({model}, {attempt+1}): {e}")
                time.sleep(2)
            except Exception as e:
                err = str(e)
                if "503" in err or "UNAVAILABLE" in err:
                    time.sleep((attempt + 1) * 5)
                else:
                    print(f"[synthesizer] {model} 실패: {e}")
                    break
    print("[synthesizer] 모든 모델 실패")
    return {}


def _easy_impact_line(text: str) -> str:
    """GSoul(지솔이슈)의 키워드 기반 '쉬운 임팩트 한 줄' 폴백 로직을 참고해 이식.
    API 호출 없이 즉시 만들 수 있어서, Gemini가 완전히 죽었을 때도 뭔가는 나가게 한다."""
    if any(w in text for w in ("전기", "요금", "물가", "금리", "가격", "돈", "재산")):
        return "결국 내 지갑과 생활비에 연결될 수 있어요."
    if any(w in text for w in ("비", "태풍", "폭염", "날씨", "구호", "피해", "지진")):
        return "안전과 이동 계획을 먼저 확인해야 해요."
    if any(w in text for w in ("AI", "인공지능", "반도체", "데이터", "기술")):
        return "편리한 기술 뒤에 필요한 비용과 영향을 봐야 해요."
    if any(w in text for w in ("정치", "정부", "국회", "대통령", "공직자", "여당", "야당")):
        return "숫자보다 왜 이런 결정이 나왔는지를 보는 게 중요해요."
    return "우리 생활에 어떤 변화가 생길지 지켜보는 게 핵심이에요."


def fallback_synthesis(sources: list[dict]) -> dict:
    """Gemini 합성이 전부 실패했을 때 쓰는 규칙 기반(API 호출 없음) 비상용 기사.
    GSoul(지솔이슈) gsoul_issue_pipeline.py의 fallback_script()를 참고해 도토리뉴스
    스키마(사실/왜중요/전망)에 맞게 다시 짰다. 품질은 AI 합성보다 낮지만, 그날 슬롯이
    완전히 빈 채로 넘어가는 것보다는 낫다."""
    if not sources:
        return {}
    primary = sources[0]
    title = (primary.get("title") or "오늘의 뉴스").strip()
    body_text = (primary.get("body") or "").strip()
    first_sentence = next((s.strip() for s in body_text.split(".") if len(s.strip()) > 10), body_text[:80])
    lead = _to_haeyo(f"{first_sentence}.".replace("..", "."))

    return {
        "title": _to_haeyo(title),
        "card_headline": title[:20],
        "lead": lead,
        "body": [lead] + ([_to_haeyo(body_text[:200])] if len(body_text) > 80 else []),
        "card_summary": lead,
        "hashtags": "#도토리뉴스",
        "why_it_matters": _easy_impact_line(f"{title} {body_text}"),
        "outlook": "이후 상황을 계속 지켜봐야 해요.",
        "has_viewpoint_diff": False,
        "viewpoint_a_label": "", "viewpoint_a_quote": "",
        "viewpoint_b_label": "", "viewpoint_b_quote": "",
        "viewpoint_summary": "",
        "reaction_fact": "우와, 정말요?",
        "reaction_why": "그렇구나, 이해했어요!",
        "reaction_outlook": "다음 소식도 지켜볼게요!",
        "emotion_fact": "surprised",
        "emotion_why": "thinking",
        "emotion_outlook": "thinking",
        "outlets": [s.get("outlet", "") for s in sources],
        "source_count": len(sources),
        "source_links": [{"outlet": s.get("outlet", ""), "link": s.get("link", "")} for s in sources],
        "_fallback_used": True,
    }


def synthesize_or_fallback(sources: list[dict]) -> dict:
    """평소엔 synthesize()(Gemini)와 동일. Gemini가 완전히 실패한 경우에만
    fallback_synthesis()로 대체해서, 그날 슬롯이 통째로 비는 것을 막는다."""
    result = synthesize(sources)
    if result:
        return result
    print("[synthesizer] AI 합성 실패 — 규칙 기반 쉬운설명 폴백 사용")
    return fallback_synthesis(sources)
