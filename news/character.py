"""도토리 캐릭터 표정 자동매칭.

카드 종류(사실확인/시각차이/왜중요/전망/커버) + 기사 톤(heavy/light)을 보고
assets/dotory_poses/{emotion}_{facing}.png 중 적합한 표정을 골라준다.

표정 세트(2026-07-01 기준, 10종 × left/front/right):
  angry, cheering, confused, disappointed, excited, happy, sad, surprised, thinking, worried
"""
from pathlib import Path

POSES_DIR = Path(__file__).parent.parent / "assets" / "dotory_poses"

# 카드 종류별 (heavy 기사용 표정, light 기사용 표정)
_CARD_EMOTION = {
    "cover":      ("worried", "cheering"),
    "fact":       ("surprised", "excited"),
    "why":        ("worried", "happy"),
    "outlook":    ("thinking", "thinking"),
    "viewpoint":  ("confused", "confused"),
}

_FALLBACK_ORDER = ["thinking", "surprised", "happy", "worried"]

# facing 방향별 우선순위
_FACING_PRIORITY = {
    "left":  ("left", "front", "right"),
    "front": ("front", "left", "right"),
    "right": ("right", "front", "left"),
}


def pick_emotion(card_variant: str, tone: str = "heavy") -> str:
    """카드 종류 + 톤(heavy/light) -> 감정 이름."""
    heavy_e, light_e = _CARD_EMOTION.get(card_variant, ("thinking", "thinking"))
    return light_e if tone == "light" else heavy_e


def pose_path(emotion: str, facing: str = "front") -> Path | None:
    """감정+방향 -> 실제 파일 경로. 없으면 다른 방향, 그래도 없으면 폴백 감정 순서로 시도."""
    candidates = [emotion] + [e for e in _FALLBACK_ORDER if e != emotion]
    priority = _FACING_PRIORITY.get(facing, ("front", "left", "right"))
    for e in candidates:
        for f in priority:
            p = POSES_DIR / f"{e}_{f}.png"
            if p.exists():
                return p
    return None


def pick_pose(card_variant: str, tone: str = "heavy", facing: str = "front") -> Path | None:
    """카드 종류+톤으로 감정을 고르고, 실제 존재하는 파일 경로까지 반환."""
    emotion = pick_emotion(card_variant, tone)
    return pose_path(emotion, facing)
