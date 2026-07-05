"""업로드 단독 테스트 스크립트 — 터미널에서 직접 실행"""
from instagram.uploader import upload_carousel
from pathlib import Path

image_paths = [
    Path('output/20260530/00_cover.png'),
    Path('output/20260530/01_hot.png'),
    Path('output/20260530/02_economy.png'),
    Path('output/20260530/03_culture.png'),
    Path('output/20260530/04_outro.png'),
]

curated = {
    'hot':     {'card_headline': '국민의힘, 투표지 노출 논란 관련 이 대통령 경찰 고발'},
    'economy': {'card_headline': '주식으로 번 돈 70% 부동산 갔다 한은 분석'},
    'culture': {'card_headline': '헤일리 비버가 필라테스는 끝났다라고 말했다?'},
}

print("Chrome 창이 열리면서 업로드를 진행합니다...")
result = upload_carousel(image_paths, curated)
print("최종 결과:", "성공" if result else "실패")
