"""스케줄러 테스트용 업로드 스크립트 — 폴더명을 인자로 받음"""
import sys
import logging
from datetime import datetime
from pathlib import Path

# 로그 파일 저장
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
folder = sys.argv[1] if len(sys.argv) > 1 else "test1"
log_file = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{folder}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger()

from instagram.uploader import upload_carousel

base = Path(__file__).parent / "output" / folder
image_paths = sorted(base.glob("*.png"))

if not image_paths:
    log.error(f"이미지 없음: {base}")
    sys.exit(1)

log.info(f"폴더: {folder} / 이미지: {len(image_paths)}장")

curated = {
    "hot":     {"card_headline": "[테스트] 스케줄러 정상 작동 확인"},
    "economy": {"card_headline": "[테스트] 자동 업로드 테스트 중"},
    "culture": {"card_headline": f"[테스트] 폴더: {folder}"},
}

result = upload_carousel(image_paths, curated)
log.info(f"결과: {'성공' if result else '실패'}")
