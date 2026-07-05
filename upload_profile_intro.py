"""프로필 고정 포스트 업로드 (1회성)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from instagram.uploader import upload_carousel

CAPTION = """DO's TORY NEWS 🐿
매일 오전 6시, 꼭 읽어야 할 뉴스만 담았습니다.

HOT 핫이슈 | ECO 경제·IT | TRD 트렌드
세 가지 카테고리로 오늘의 뉴스를 정리해드려요.

원문은 프로필 링크에서 확인하세요.

#도토리뉴스 #오늘의뉴스 #카드뉴스 #뉴스요약 #뉴스계정"""

if __name__ == "__main__":
    image = Path(__file__).parent / "output" / "profile_intro.png"
    if not image.exists():
        print(f"이미지 없음: {image}")
        sys.exit(1)

    print("프로필 인트로 이미지 업로드 중...")
    result = upload_carousel([image], {}, caption=CAPTION)
    print("결과:", "성공" if result else "실패")
