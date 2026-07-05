"""v2 기사 이미지 스타일 테스트 — 도토리 의인화 vs 무인물 상징 일러스트 비교 샘플"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
from pathlib import Path

from google import genai
from google.genai import types
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-2.5-flash-image"

BASE = Path(__file__).parent
OUT = BASE / "output_image_test"
OUT.mkdir(exist_ok=True)

HERO = (BASE / "web" / "hero.png").read_bytes()

STYLE_BASE = """스타일 규칙 (반드시 지킬 것):
- 에디토리얼 뉴스 일러스트. 플랫 그래픽 스타일, 낮은 채도
- 색상 팔레트: 크림(#FBF8F2), 호박색(#D97706), 갈색(#7C4A1E), 베이지 계열로 통일
- 알록달록한 색, 웹툰체, 과장된 표정, 개그 연출 금지
- 텍스트, 글자, 숫자를 이미지 안에 넣지 말 것
- 깔끔한 단색 배경, 잡지 에디토리얼 일러스트 느낌
- 가로형 16:10 구도"""

from datetime import datetime
import config
_today = datetime.now().strftime("%Y%m%d")
ARTICLES = json.loads((config.OUTPUT_DIR / _today / "v2_articles.json").read_text(encoding="utf-8"))["articles"]


def gen(name: str, prompt: str, use_character: bool):
    contents = []
    if use_character:
        contents.append(types.Part.from_bytes(data=HERO, mime_type="image/png"))
        prompt = "첨부된 도토리 캐릭터와 동일한 캐릭터 디자인을 유지하면서 그려주세요.\n\n" + prompt
    contents.append(prompt)
    try:
        resp = client.models.generate_content(model=MODEL, contents=contents)
        for part in resp.candidates[0].content.parts:
            if part.inline_data:
                path = OUT / f"{name}.png"
                path.write_bytes(part.inline_data.data)
                print(f"[OK] {path.name} ({len(part.inline_data.data)//1024} KB)")
                return
        print(f"[FAIL] {name}: 이미지 파트 없음 — {resp.candidates[0].content.parts[0].text[:100] if resp.candidates[0].content.parts else 'empty'}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")


for i, a in enumerate(ARTICLES):
    title = a["title"]
    lead = a["lead"]
    print(f"\n=== {a['cat_code']}: {title} ===")

    # 스타일 1: 도토리 의인화
    gen(f"{i}_{a['category']}_A_dotory",
        f"""뉴스 기사 일러스트를 그려주세요.

기사 제목: {title}
기사 요약: {lead}

이 뉴스 장면을 도토리 캐릭터가 등장하는 에디토리얼 일러스트로 표현하세요.
- 실존 인물 대신 도토리 캐릭터가 그 역할을 담백하게 수행 (예: 기자회견하는 도토리, 공장을 둘러보는 도토리)
- 캐릭터는 1~2마리만, 절제된 연출

{STYLE_BASE}""", use_character=True)

    # 스타일 2: 무인물 상징 일러스트
    gen(f"{i}_{a['category']}_B_symbol",
        f"""뉴스 기사 일러스트를 그려주세요.

기사 제목: {title}
기사 요약: {lead}

이 뉴스의 핵심을 사람이나 캐릭터 없이 사물·상징물만으로 표현하는 에디토리얼 일러스트.
(예: 반도체 기사면 칩과 공장 실루엣, 환불 기사면 티켓과 동전)

{STYLE_BASE}""", use_character=False)

print("\n완료. 폴더:", OUT)
