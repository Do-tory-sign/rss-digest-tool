"""고정 포스트용 프로필 소개 이미지 생성"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from image.html_composer import compose_profile_intro

if __name__ == "__main__":
    out = compose_profile_intro(Path("output/profile_intro.png"))
    print(f"완료: {out.resolve()}")
