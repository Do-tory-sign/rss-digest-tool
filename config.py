import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8", override=True)

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """한국 시간 기준 현재 시각.
    2026-07-06: GitHub Actions 러너는 UTC로 동작해서, 예전처럼 datetime.now()를 그대로 쓰면
    한국 기준 새벽~아침(UTC로는 아직 전날) 시간대에 날짜가 하루 밀려서 표시되고, 그 날짜를
    파일명 키로 쓰는 이미지/데이터 경로까지 전날 것과 충돌하는 문제가 있었음(로컬 PC는 항상
    KST라 이 버그가 지금까지 안 보였음). 파일명/화면 표시용 '오늘'은 전부 이 함수로 통일."""
    return datetime.now(KST)

BASE_DIR = Path(__file__).parent

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME") or ""
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD") or ""
BRAND_NAME = os.getenv("BRAND_NAME", "두나두나뉴스")

OUTPUT_DIR = Path("D:/Dotory/Cardnews/output")
FONTS_DIR = BASE_DIR / "fonts"

IMAGE_SIZE = (1080, 1080)

CATEGORIES = {
    "hot": {
        "label": "HOT  핫뉴스",
        "color": (220, 50, 50),
        "bg_color": (30, 10, 10),
        "accent": (255, 80, 80),
    },
    "economy": {
        "label": "ECO  경제·IT",
        "color": (37, 99, 235),
        "bg_color": (10, 15, 35),
        "accent": (96, 165, 250),
    },
    "culture": {
        "label": "TRD  트렌드",
        "color": (124, 58, 237),
        "bg_color": (15, 10, 35),
        "accent": (167, 139, 250),
    },
}

# 연합뉴스 RSS — KST(+0900) 타임스탬프, 당일 기사 정확히 반영
YONHAP_RSS = {
    "politics":      "https://www.yna.co.kr/rss/politics.xml",
    "economy":       "https://www.yna.co.kr/rss/economy.xml",
    "industry":      "https://www.yna.co.kr/rss/industry.xml",
    "society":       "https://www.yna.co.kr/rss/society.xml",
    "entertainment": "https://www.yna.co.kr/rss/entertainment.xml",
    "sports":        "https://www.yna.co.kr/rss/sports.xml",
}

# Google News RSS — 다양한 언론사 확보용 (KST 변환 필터 적용)
_W = "when:1d"
GOOGLE_NEWS_RSS = {
    "hot_google":     f"https://news.google.com/rss/search?q=사건+사고+이슈+화제+{_W}&hl=ko&gl=KR&ceid=KR:ko",
    "tech":           f"https://news.google.com/rss/search?q=IT+AI+스타트업+테크+반도체+{_W}&hl=ko&gl=KR&ceid=KR:ko",
    "culture_google": f"https://news.google.com/rss/search?q=연예+드라마+영화+아이돌+스포츠+{_W}&hl=ko&gl=KR&ceid=KR:ko",
}

WINDOWS_FONT_PATH = "C:/Windows/Fonts/malgunbd.ttf"
WINDOWS_FONT_REGULAR = "C:/Windows/Fonts/malgun.ttf"
