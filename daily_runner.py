"""하루 4슬롯(아침/점심/저녁/야식) 중 하나를 평소(컴퓨터가 제때 켜져 있는 날) 실행하는 진입점.

2026-07-02 재설계: 슬롯이 더 이상 카테고리(hot/economy/culture)에 고정되지 않는다.
그 시간대 전체 후보 중 가장 화제성 높은 뉴스 하나를 카테고리 무관하게 뽑되, 오늘 다른
슬롯에서 이미 쓴 카테고리는 제외해서 하루 안에 카테고리가 겹치지 않게 한다.
  - 아침(06:00 생성 → 06:55 게시)
  - 점심(11:00 생성 → 11:55 게시)
  - 저녁(16:00 생성 → 16:55 게시)
  - 야식(21:00 생성 → 21:55 게시)

각 슬롯은:
  1) 오늘 다른 슬롯이 이미 쓴 카테고리를 조회 (v2_articles_<slot>.json들에서)
  2) v2_main.py --slot <slot> --fresh --exclude <카테고리들> 로 뉴스/이미지 생성
  3) review.py --slot <slot> 로 텔레그램 승인 대기 (기준 마감 = 생성시각+55분,
     재생성 시 +10분 연장) → 마감 도달 시 review.py가 직접 main.py를 불러 빌드까지 끝냄

사용법: python daily_runner.py --slot morning|lunch|evening|night
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config

PY = sys.executable
BASE = Path(__file__).parent

SLOT_CONFIG = {
    "morning": {"hour": 6},
    "lunch":   {"hour": 11},
    "evening": {"hour": 16},
    "night":   {"hour": 21},
}

ALL_SLOTS = list(SLOT_CONFIG.keys())


def _done_today(slot: str) -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return (config.OUTPUT_DIR / today / f"build_done_{slot}.txt").exists()


def _used_categories_today(exclude_slot: str) -> list[str]:
    """오늘 다른 슬롯이 이미 선정한 카테고리 조회 — 하루 안 카테고리 중복 방지용."""
    today = datetime.now().strftime("%Y%m%d")
    run_dir = config.OUTPUT_DIR / today
    used = []
    for slot in ALL_SLOTS:
        if slot == exclude_slot:
            continue
        p = run_dir / f"v2_articles_{slot}.json"
        if not p.exists():
            continue
        try:
            articles = json.loads(p.read_text(encoding="utf-8")).get("articles", [])
            for a in articles:
                cat = a.get("category")
                if cat and cat not in used:
                    used.append(cat)
        except Exception:
            pass
    return used


def _run(args: list[str], label: str):
    print(f"[daily] {label} 시작: {' '.join(args)}")
    result = subprocess.run([PY, "-X", "utf8"] + args, cwd=BASE)
    print(f"[daily] {label} 종료 (code={result.returncode})")
    return result.returncode


def run_slot(slot: str, deadline_ts: datetime | None = None):
    """deadline_ts를 안 주면 평소대로 '슬롯 시각:55'를 마감으로 쓴다.
    catchup_runner.py처럼 이미 정규 시각이 지난 뒤에 뒤늦게 도는 경우엔 호출부에서
    '지금부터 N분' 같은 다른 마감을 넘겨준다."""
    cfg = SLOT_CONFIG[slot]

    if _done_today(slot):
        print(f"[daily] [{slot}] 오늘 작업 이미 완료됨 — 종료")
        return

    if deadline_ts is None:
        deadline_ts = datetime.now().replace(hour=cfg["hour"], minute=55, second=0, microsecond=0)
    exclude = _used_categories_today(slot)

    v2_args = ["v2_main.py", "--slot", slot, "--fresh"]
    if exclude:
        v2_args += ["--exclude", ",".join(exclude)]
    _run(v2_args, f"[{slot}] 1단계 (뉴스 수집 + 큐레이션 + 이미지 생성, 제외 카테고리: {exclude or '없음'})")
    if _done_today(slot):
        return
    rc = _run(["review.py", "--slot", slot, "--deadline-ts", deadline_ts.isoformat()],
               f"[{slot}] 텔레그램 승인 대기 + 마감 시 카드 빌드")
    # 2026-07-03: review.py가 PC 절전 등으로 도중에 죽으면(비정상 종료코드) 그 슬롯이
    # 통째로 누락되는데 아무 알림이 없었음 — daily_runner 레벨에서 한 번 더 감시.
    if rc != 0 and not _done_today(slot):
        try:
            from notify import notify_failure
            notify_failure(f"[{slot}] review.py가 비정상 종료(code={rc})됐고 아직 완료 안 됨 — 확인 필요")
        except Exception:
            pass


def main():
    if "--slot" not in sys.argv:
        print("사용법: python daily_runner.py --slot morning|lunch|evening|night")
        sys.exit(2)
    slot = sys.argv[sys.argv.index("--slot") + 1]
    if slot not in SLOT_CONFIG:
        print(f"알 수 없는 슬롯: {slot}")
        sys.exit(2)
    run_slot(slot)


if __name__ == "__main__":
    main()
