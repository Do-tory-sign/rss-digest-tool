"""v2 기사 일러스트 생성 — Gemini Nano Banana
기본 B스타일(무인물 상징), 가벼운 주제만 A스타일(도토리 캐릭터).
이미지 내 텍스트 금지. 실패 시 카테고리 기본 일러스트 폴백 (모든 기사 1장 보장).
"""
import time
from pathlib import Path

from google import genai
from google.genai import types
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)
IMAGE_MODEL = "gemini-2.5-flash-image"
CLASSIFY_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]

BASE = Path(__file__).parent.parent
HERO_PATH = BASE / "web" / "hero.png"
HERO_PATH2 = BASE.parent / "Assets" / "brand" / "[Do.tory] 이미지_포켓.png"
FALLBACK_DIR = BASE / "assets" / "v2_fallback"

MIN_IMAGE_BYTES = 30 * 1024   # 30KB 미만이면 품질 미달로 재시도

NO_TEXT_RULE = """- ABSOLUTELY NO text, letters, words, numbers, signs, logos, speech bubbles,
  banners with writing, or typography of any kind anywhere in the image.
  No Korean characters, no English letters. Pure illustration only."""

STYLE_BASE = f"""스타일 규칙 (반드시 지킬 것):
- 시사 주간지 표지 수준의 에디토리얼 뉴스 일러스트. 플랫 그래픽 스타일, 낮은 채도
- 색상 팔레트: 크림(#FBF8F2), 호박색(#D97706), 갈색(#7C4A1E), 베이지 계열로 통일
- 장면을 풍부하게: 주제 오브제 + 배경 환경 + 보조 디테일까지 화면을 꽉 채운 완성된 장면
  (오브제 하나만 덩그러니 있는 아이콘식 구성 금지)
- 가로 와이드 구도. 장면이 이미지 네 변(상하좌우) 모두에 닿아야 함 —
  테두리(흰색·검은색·다른 색 모두 포함), 액자식 여백, 카드 형태 구성 절대 금지.
  풀블리드(full-bleed)로 네 변 끝까지 꽉 채울 것 — 어떤 색의 띠/프레임도 가장자리에 남기지 말 것
- 알록달록한 색, 웹툰체, 과장된 표정, 개그 연출 금지
{NO_TEXT_RULE}
- 예외: 국가 간 소식일 때는 관련 국가들의 국기를 정확한 디자인으로 포함 가능
  (태극기는 흰 바탕에 빨강·파랑 태극 문양과 검은 4괘를 정확하게. 왜곡되면 안 됨)
- 제목의 비유 표현('칼 대다', '철퇴', '폭탄' 등)을 문자 그대로 그리지 말 것 — 실제 의미를 그릴 것
- 칼, 무기, 피, 폭력적 소재 금지"""


def classify_tone(title: str, lead: str) -> str:
    """기사가 'light'(트렌드·라이프스타일·연예·훈훈한 소식)인지
    'heavy'(정치·사건사고·경제·재난·법적분쟁)인지 분류. 애매하면 heavy."""
    prompt = f"""다음 뉴스가 가벼운 주제인지 무거운 주제인지 분류하세요.

제목: {title}
요약: {lead}

- light: 트렌드, 라이프스타일, 연예(밝은 소식), 스포츠, 음식, 유행, 훈훈한 이야기
- heavy: 정치, 사건사고, 범죄, 재난, 사망, 경제, 기업, 법적 분쟁, 갈등, 논란

"light" 또는 "heavy" 한 단어만 출력하세요. 애매하면 heavy."""
    for model in CLASSIFY_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            answer = resp.text.strip().lower()
            if "light" in answer:
                return "light"
            if "heavy" in answer:
                return "heavy"
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(5)
            else:
                break
    return "heavy"   # 분류 실패 시 안전하게 heavy


def _scene_description(title: str, lead: str, body: str = "", avoid: list[str] = None) -> dict:
    """기사 → 구조화된 장면 설계 (setting / key_objects / action / forbidden).
    고유명사·숫자·글자 요소를 제거해 이미지 모델이 텍스트를 그려넣을 빌미를 없앤다."""
    import json as _json

    avoid_text = ""
    if avoid:
        joined = "\n".join(f"- {s}" for s in avoid)
        avoid_text = f"""
- 아래는 같은 날 다른 기사에 이미 사용된 장면들입니다. 구도·핵심 모티프가
  겹치지 않게 완전히 다른 장면을 구성하세요:
{joined}"""

    body_section = f"\n본문: {body[:400]}" if body else ""

    prompt = f"""다음 뉴스를 에디토리얼 일러스트로 표현하기 위한 장면을 설계하세요.

제목: {title}
요약: {lead}{body_section}

아래 JSON 형식으로만 출력하세요:
{{
  "setting": "장면이 펼쳐지는 구체적인 장소/공간",
  "key_objects": ["이 기사를 대표하는 핵심 오브제 1", "핵심 오브제 2", "핵심 오브제 3"],
  "action": "공간 안에서 무슨 일이 일어나고 있는지 한 문장",
  "forbidden": "이 기사에서 특히 오해하기 쉬운 그림 요소"
}}

규칙:
- setting은 이 기사에서만 나올 법한 구체적 공간. 기자회견장·회의실 같은 범용 공간 금지
  예: 국회 본청 앞 광장, 반도체 공장 클린룸, 법원 판결문 낭독실, 경기장 선수 터널
- key_objects는 기사 내용에 실제 등장하는 사물·장면 (추상 기호·밧줄·저울·톱니바퀴 금지)
- 사건·사고·법적 분쟁 기사는 key_objects에 그 사건의 정체를 한눈에 알 수 있는 구체적 단서를
  반드시 1개 이상 포함할 것 (예: 도박 의혹 → 화투패·포커칩, 음주운전 → 음주측정기·경찰 검문,
  뇌물·횡령 → 봉투·서류뭉치). "유흥가 뒷골목", "어두운 사무실"처럼 사건 종류를 특정할 수 없는
  막연한 장면은 금지
- 비유 표현 직역 금지 ('칼 대다' → 칼 ❌, 실제 상황인 협상장 ✅)
- 일자리·취업 기사: 로봇·자동화 이미지 절대 금지
- 국기는 기사 본문에 명시적으로 등장하는 나라만. 추론으로 넣지 말 것
- 인명·지명·회사명·숫자 포함 금지{avoid_text}"""

    # Gemini가 일시적으로 과부하(503)일 때 큐레이션처럼 끝까지 버티고 재시도.
    # 예전엔 모델 2개 한 바퀴만 돌고 바로 포기해서, API가 잠깐 과부하인 날엔
    # 장면 설계가 실패해 항상 똑같은 폴백 그림(예: economy.png 고정 저울 그림)으로
    # 떨어지는 일이 잦았다 (2026-06-27 발견).
    for round_num in range(3):
        for model in CLASSIFY_MODELS:
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                raw = resp.text.strip()
                if "```" in raw:
                    raw = raw.split("```")[1]
                    raw = raw.lstrip("jsonJSON \n")
                scene = _json.loads(raw.strip())
                if scene.get("setting") and scene.get("key_objects") and scene.get("action"):
                    return scene
            except Exception as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                    print(f"[article_image] 장면 설계 과부하 — {(round_num + 1) * 5}초 후 재시도")
                    time.sleep((round_num + 1) * 5)
                # JSON 파싱 실패 등 다른 에러는 같은 라운드의 다음 모델로 즉시 넘어감
    return {}


def _build_scene_text(scene: dict) -> str:
    """구조화된 장면 dict → 이미지 프롬프트용 텍스트 블록"""
    objects = ", ".join(scene.get("key_objects", []))
    lines = [
        f"장소: {scene.get('setting', '')}",
        f"반드시 포함할 요소: {objects}",
        f"상황: {scene.get('action', '')}",
    ]
    forbidden = scene.get("forbidden", "")
    if forbidden:
        lines.append(f"절대 그리지 말 것: {forbidden}")
    return "\n".join(lines)


def _feedback_block(feedback: str) -> str:
    if not feedback:
        return ""
    return f"\n사용자 피드백 (반드시 우선 반영할 것): {feedback}\n"


def _prompt_symbol(scene: dict, feedback: str = "") -> str:
    scene_text = _build_scene_text(scene)
    return f"""에디토리얼 뉴스 일러스트를 그려주세요. 반드시 이미지를 생성하세요.

{scene_text}
{_feedback_block(feedback)}
사람이나 캐릭터 없이 사물·공간·상황만으로 표현하세요.

{STYLE_BASE}"""


def _prompt_dotory(scene: dict, feedback: str = "") -> str:
    scene_text = _build_scene_text(scene)
    return f"""첨부된 도토리 캐릭터들과 동일한 캐릭터 디자인을 유지하면서 그려주세요.
반드시 이미지를 생성하세요.

{scene_text}
{_feedback_block(feedback)}
이 장면을 도토리 캐릭터가 주인공으로 등장하는 에디토리얼 일러스트로 표현하세요.
- 주인공 도토리는 1~2마리만. 모든 등장인물이 도토리일 필요는 없음 —
  주변 인물은 이목구비를 단순화한 인형 같은 사람들로 그려도 좋음
- 도토리가 여러 마리면 각자 포인트를 다르게 — 단, 장면과 무관한 액세서리(머리띠, 운동복 등)를
  아무 맥락 없이 끼워 넣지 말 것. 장면에 어울리면 안경 정도로만 구분하고,
  아니면 그냥 같은 디자인으로 두는 게 나음 (기본 디자인은 동일하게)
- 도토리 캐릭터 디자인 규칙:
  * 몸통 아래쪽은 부드럽고 둥글게 (뾰족하게 그리지 말 것)
  * 꼬리 절대 금지 — 다람쥐처럼 꼬리를 달지 말 것
  * 배경의 케이블·전선·끈·로프 등 길게 구불거리는 선이 캐릭터 몸 뒤에서 튀어나오거나
    겹쳐서 마치 꼬리처럼 보이지 않게 할 것 — 배경 사물은 캐릭터와 충분히 떨어뜨려 그릴 것
  * 머리 위나 머리띠에 작은 도토리 알갱이를 여러 개 얹는 장식 금지 (작은 원형 무늬가 모여있는 패턴 일절 금지)
  * 도토리가 2마리 이상이면 키/크기를 똑같이 — 한쪽을 작게 그려서 부모-자식처럼 보이게 하지 말 것.
    실제 인물들이 동등한 관계(동료, 친구, 또래)라면 캐릭터도 동등한 성인 크기로 그릴 것
- 실존 인물이 등장하는 장면에서 성별이 명확하면 (여성 배우/인물 등) 캐릭터도 그 성별 특징을 살려서
  그릴 것 (머리 길이, 액세서리 등으로 구분 — 남성형 기본 디자인을 무조건 쓰지 말 것)
- 국기·태극문양 등 국가 상징물은 기사 내용과 직접 관련 없으면 일절 사용하지 말 것
  (신분증·서류·카드 등의 장식으로도 넣지 말 것)
- 장면의 환경(사무실·거리·매장 등)을 현실감 있게 살릴 것

{STYLE_BASE}"""


def _has_text(image_bytes: bytes) -> bool:
    """생성 이미지에 글자가 들어갔는지 Gemini 비전으로 검사. 판단 불가 시 통과(False)."""
    try:
        resp = client.models.generate_content(
            model=CLASSIFY_MODELS[0],
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                "이 이미지 안에 글자(한글, 영어, 숫자, 문자처럼 보이는 표기)가 있나요? "
                "단, 국기 문양(태극기의 검은 4괘 막대 포함)은 글자가 아니므로 제외하고 판단하세요. "
                "'yes' 또는 'no' 한 단어만 답하세요.",
            ],
        )
        return "yes" in resp.text.strip().lower()
    except Exception:
        return False


def _remove_text_inpaint(image_bytes: bytes) -> bytes | None:
    """이미지에 글자가 감지됐을 때, 전체를 다시 그리지 않고 글자만 지우는 부분 편집 시도.
    2026-06-28 테스트(4/4 성공) 결과 전체 재생성보다 구도·인물·색감 유지율이 훨씬 높아서
    글자 감지 시 1순위로 시도. 실패하면 호출부가 기존 전체 재생성으로 폴백한다."""
    try:
        resp = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                "이 이미지에서 글자·문구·자막·숫자 표기 부분만 지워주세요. 글자가 있던 자리는 "
                "같은 배경 톤·질감으로 자연스럽게 채우고, 나머지 구도·인물·색감·조명은 전부 "
                "그대로 유지하세요. 어떤 문자도 남기지 마세요.",
            ],
            config=types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio="16:9")),
        )
        for part in resp.candidates[0].content.parts:
            if part.inline_data and len(part.inline_data.data) >= MIN_IMAGE_BYTES:
                return part.inline_data.data
    except Exception as e:
        print(f"[article_image] 글자 인페인팅 편집 실패: {e}")
    return None


def _trim_and_widen(image_bytes: bytes, ratio: float = 16 / 9) -> bytes:
    """배경 여백 자동 크롭 후 중앙 기준 16:9로 잘라내기"""
    import io
    from PIL import Image, ImageChops

    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # 1) 모서리 배경색 기준 여백 트림 (오차 허용)
    bg = Image.new("RGB", im.size, im.getpixel((2, 2)))
    diff = ImageChops.difference(im, bg)
    bbox = diff.point(lambda p: 255 if p > 16 else 0).getbbox()
    if bbox:
        pad = 24  # 장면 주변 숨 쉴 여백
        left = max(bbox[0] - pad, 0)
        top = max(bbox[1] - pad, 0)
        right = min(bbox[2] + pad, im.width)
        bottom = min(bbox[3] + pad, im.height)
        im = im.crop((left, top, right, bottom))

    # 2) 중앙 기준 16:9 크롭 (세로가 길면 위아래 자르고, 가로가 너무 길면 좌우 자름)
    w, h = im.size
    if w / h < ratio:       # 너무 정사각/세로형 → 위아래 자르기
        new_h = int(w / ratio)
        top = (h - new_h) // 2
        im = im.crop((0, top, w, top + new_h))
    elif w / h > ratio * 1.3:  # 지나치게 길면 좌우만 살짝
        new_w = int(h * ratio)
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _flags_wrong(image_data: bytes, context: str = "") -> bool:
    """이미지 속 국기가 부정확하거나 기사 맥락과 다른 나라인지 검사 (국기가 없으면 False)"""
    ctx = ""
    if context:
        ctx = (f"참고로 이 이미지는 다음 뉴스의 일러스트입니다: \"{context}\" "
               "그려진 국기가 이 뉴스에 등장하는 나라가 아닌 다른 나라 국기라면 "
               "(예: 일본·대만 기사인데 미국·중국 국기) 그것도 'wrong'입니다. ")
    try:
        resp = client.models.generate_content(
            model=CLASSIFY_MODELS[0],
            contents=[
                types.Part.from_bytes(data=image_data, mime_type="image/png"),
                "이 이미지에 국기·기관 깃발이 그려져 있나요? 있다면 각각 실제 어느 나라(기관) 깃발인지 "
                "식별하고, 실제 디자인과 비교해 정확한지 엄격하게 판단하세요. "
                "기준: (1) 실존하는 국기·깃발과 명확히 일치해야 함 — 색 배열, 문양 위치·개수까지. "
                "(2) 어느 나라인지 알 수 없는 창작 깃발이나 두 국기를 섞은 듯한 깃발은 부정확. "
                "(3) 태극기 예시: 흰 바탕 + 빨강(위)·파랑(아래) 태극 1개 + 네 모서리 검은 4괘. 다르면 부정확. "
                + ctx +
                "국기가 없으면 'no_flag', 모두 정확하면 'accurate', 하나라도 부정확하거나 "
                "엉뚱한 나라면 'wrong' 한 단어만 답하세요.",
            ],
        )
        return "wrong" in resp.text.strip().lower()
    except Exception:
        return False  # 검사 실패 시 통과 (글자 검사는 별도)


def _content_mismatch(image_bytes: bytes, title: str, lead: str) -> bool:
    """완성된 그림이 기사 내용과 의미적으로 잘 맞는지 점검 (텍스트/국기와 달리 자동 재생성은
    하지 않음 — 의심스러우면 표시만 달아서 사람이 텔레그램에서 직접 판단하게 한다.
    판단 불가 시 의심 없음(False)으로 처리해 불필요한 경고가 남발되지 않게 함."""
    try:
        resp = client.models.generate_content(
            model=CLASSIFY_MODELS[0],
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                f"이 일러스트는 다음 뉴스 기사를 표현하기 위해 그려졌습니다.\n"
                f"제목: {title}\n요약: {lead}\n\n"
                "그림의 장소·오브제·상황이 이 기사 내용과 합리적으로 어울리나요? "
                "에디토리얼 일러스트라 비유적·상징적 표현은 괜찮습니다. "
                "다만 기사 내용과 명백히 동떨어지거나 엉뚱한 장면이면 부적합입니다. "
                "적합하면 'match', 명백히 부적합하면 'mismatch' 한 단어만 답하세요.",
            ],
        )
        return "mismatch" in resp.text.strip().lower()
    except Exception:
        return False


_NO_TEXT_REINFORCEMENT = """
CRITICAL REMINDER — this is the most important rule:
Do NOT draw ANY text, letters, words, numbers, labels, captions, signs, or typography.
No Korean. No English. No digits. No symbols that look like writing.
Pure visual illustration only. If you feel the urge to add text, replace it with a visual symbol instead."""


def _generate(prompt: str, out_path: Path, use_character: bool, retries: int = 3,
              flag_context: str = "") -> bool:
    contents: list = []
    if use_character:
        for ref in (HERO_PATH, HERO_PATH2):
            if ref.exists():
                contents.append(types.Part.from_bytes(data=ref.read_bytes(), mime_type="image/png"))
    contents.append(prompt)

    config = types.GenerateContentConfig(
        image_config=types.ImageConfig(aspect_ratio="16:9"),
    )

    MAX_OVERLOAD_RETRIES = 5  # 503/429 같은 일시적 과부하는 콘텐츠 재시도 횟수를 깎지 않고 따로 버팀

    for attempt in range(retries):
        # 글자 감지로 재시도할 때마다 no-text 강조 문구 추가
        current_contents = list(contents)
        if attempt > 0:
            current_contents[-1] = prompt + _NO_TEXT_REINFORCEMENT * attempt

        image_data = None
        for overload_try in range(MAX_OVERLOAD_RETRIES):
            try:
                resp = client.models.generate_content(
                    model=IMAGE_MODEL, contents=current_contents, config=config)
                for part in resp.candidates[0].content.parts:
                    if part.inline_data and len(part.inline_data.data) >= MIN_IMAGE_BYTES:
                        image_data = part.inline_data.data
                        break
                break  # 응답은 받았음 (이미지 유무와 무관하게 과부하 루프는 끝)
            except Exception as e:
                err = str(e)
                is_overload = "503" in err or "UNAVAILABLE" in err or "429" in err
                if is_overload and overload_try < MAX_OVERLOAD_RETRIES - 1:
                    wait = (overload_try + 1) * 8
                    print(f"[article_image] 과부하(시도 {attempt+1}-{overload_try+1}) — {wait}초 후 재시도")
                    time.sleep(wait)
                    continue
                print(f"[article_image] 생성 실패 (시도 {attempt+1}): {err[:120]}")
                break

        if image_data is None:
            print(f"[article_image] 이미지 파트 없음/품질 미달 (시도 {attempt+1})")
            time.sleep(1)
            continue

        if _has_text(image_data):
            print("[article_image] 이미지에 글자 감지 — 전체 재생성 대신 부분 편집(인페인팅) 먼저 시도")
            edited = _remove_text_inpaint(image_data)
            if edited is not None and not _has_text(edited):
                print("[article_image] 인페인팅으로 글자 제거 성공 — 구도 유지한 채 저장")
                image_data = edited
            else:
                print(f"[article_image] 인페인팅 실패/글자 남음 → 전체 재생성 (시도 {attempt+1}, no-text 강조)")
                time.sleep(1)
                continue

        if _flags_wrong(image_data, context=flag_context):
            print(f"[article_image] 국기 부정확/엉뚱한 나라 → 재생성 (시도 {attempt+1})")
            time.sleep(1)
            continue

        try:
            image_data = _trim_and_widen(image_data)
        except Exception as e:
            print(f"[article_image] 크롭 실패(원본 사용): {e}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image_data)
        return True
    return False


def _prompt_keyword(point: str) -> str:
    """장면 설계 없이 핵심 단어 하나만으로 그리는 최후의 시도용 프롬프트.
    카테고리 라벨처럼 막연한 게 아니라 기사의 포인트 단어 자체로 그려서, 폴백(항상 똑같은
    고정 이미지)보다는 매번 다른 그림이 나오게 함."""
    return f"""에디토리얼 뉴스 일러스트를 그려주세요. 반드시 이미지를 생성하세요.

다음 핵심 단어를 중심으로 한 장면을 자유롭게 구성하세요: {point}

사람이나 캐릭터 없이 사물·공간·상황만으로 표현하세요.

{STYLE_BASE}"""


def _fallback(category: str, out_path: Path) -> bool:
    src = FALLBACK_DIR / f"{category}.png"
    if src.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(src.read_bytes())
        print(f"[article_image] 폴백 일러스트 사용: {src.name}")
        return True
    print(f"[article_image] 폴백 일러스트도 없음: {src}")
    return False


def _check_mismatch(out_path: Path, title: str, lead: str) -> bool:
    try:
        mismatch = _content_mismatch(out_path.read_bytes(), title, lead)
        if mismatch:
            print(f"[article_image] ⚠️ 내용 적합성 의심 — 그대로 저장하되 표시만 남김")
        return mismatch
    except Exception:
        return False


def generate_article_image(category: str, title: str, lead: str, out_path: Path,
                           body: str = "", avoid_scenes: list[str] = None,
                           feedback: str = "", reuse_scene: dict = None,
                           scene_out: dict = None) -> tuple[str, str, bool, str]:
    """기사 일러스트 생성.
    feedback: 사용자가 텔레그램으로 입력한 재생성 피드백 (있으면 프롬프트에 우선 반영)
    reuse_scene: 이전에 쓴 장면(setting/key_objects/action)을 그대로 재사용 — 재생성 버튼을
      누를 때마다 장면 자체를 새로 설계해서 구도가 매번 바뀌는 문제(2026-07-03) 방지용.
      "이 이미지 마음에 드는데 이 부분만 고쳐줘" 같은 미세조정 피드백에서 씀.
    scene_out: 넘기면 이번에 실제로 쓴 장면 dict를 여기에 채워 넣어줌(호출부가 다음 재생성에
      reuse_scene으로 다시 넘길 수 있게, 반환 튜플 구조를 안 바꾸려고 out-파라미터로 뺌).
    Returns:
        (style, scene, mismatch_suspected, tone)
        - style: 'A'(도토리) / 'B'(상징) / 'F'(폴백) / ''(실패)
        - scene은 같은 날 다른 기사와의 구도 중복 방지용으로 호출자가 누적 전달
        - mismatch_suspected: 그림이 기사 내용과 안 맞을 수 있다고 AI가 의심하면 True.
          자동 재생성은 하지 않음 — 최종 판단은 텔레그램에서 사람이 함
        - tone: 'heavy'/'light' — 도토리 표정 자동매칭(news/character.py)에 재사용
    """
    tone = classify_tone(title, lead)
    scene = reuse_scene if reuse_scene else _scene_description(title, lead, body=body, avoid=avoid_scenes)
    if scene_out is not None:
        scene_out.update(scene)
    scene_summary = scene.get("action", "") or scene.get("setting", "")
    print(f"[article_image] {category}: tone={tone} / 장소={scene.get('setting', '')[:50]}")
    if feedback:
        print(f"[article_image] 사용자 피드백 반영: {feedback}")
    if not scene:
        # 장면 설계 자체가 실패한 경우 — 그래도 고정 폴백 직전에 제목을 포인트 단어로 써서
        # 한 번 더 가볍게 시도 (성공하면 매번 다른 그림, 실패하면 그제서야 고정 폴백)
        if _generate(_prompt_keyword(title), out_path, use_character=False, retries=2):
            return "B", "", True, tone
        return ("F" if _fallback(category, out_path) else "", "", True, tone)

    # 국기 검증에 충분한 맥락 전달 (lead 전체 + body 앞부분)
    fctx = f"{title} — {lead} {body[:150]}".strip()

    if tone == "light":
        if _generate(_prompt_dotory(scene, feedback), out_path, use_character=True, flag_context=fctx):
            return "A", scene_summary, _check_mismatch(out_path, title, lead), tone
        print("[article_image] A스타일 실패 → B스타일 시도")

    if _generate(_prompt_symbol(scene, feedback), out_path, use_character=False, flag_context=fctx):
        return "B", scene_summary, _check_mismatch(out_path, title, lead), tone

    # 국기 장면이 검증을 계속 통과 못 하면 국기 없는 구성으로 재시도
    scene_all_text = " ".join([
        " ".join(scene.get("key_objects", [])),
        scene.get("setting", ""),
        scene.get("action", ""),
        scene.get("forbidden", ""),
    ])
    if "국기" in scene_all_text or "태극기" in scene_all_text:
        scene_no_flag = dict(scene)
        scene_no_flag["forbidden"] = (scene.get("forbidden", "") + " 국기 일절 금지. 다른 상징물로 대체할 것").strip()
        print("[article_image] 국기 제외 구성으로 재시도")
        if _generate(_prompt_symbol(scene_no_flag, feedback), out_path, use_character=False):
            return "B", scene_summary, _check_mismatch(out_path, title, lead), tone

    # 정식 장면(A/B/국기제외)이 다 실패했을 때도 고정 폴백 직전에 핵심 단어로 한 번 더 시도
    point = (scene.get("key_objects") or [title])[0]
    if _generate(_prompt_keyword(point), out_path, use_character=False, retries=2):
        return "B", scene_summary, True, tone

    return ("F" if _fallback(category, out_path) else "", scene_summary, True, tone)
