import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from pathlib import Path
from news.article_image import generate_article_image

title = "윤 전 대통령, '반란 우두머리' 혐의로 2차 특검 조사받아요"
lead = "윤석열 전 대통령이 반란 우두머리 혐의로 2차 종합특검에 다시 출석했어요. 군형법상 반란 혐의를 두고 특검과 윤 전 대통령 측이 강하게 맞서고 있대요."

out_path = Path("web/v2/img/20260613_hot.png")
for attempt in range(3):
    print(f"\n[시도 {attempt+1}] 재생성 중...")
    style, scene = generate_article_image("hot", title, lead, out_path)
    print(f"씬: {scene}")
    print(f"결과: style={style}")
    if style and style != 'F':
        break
