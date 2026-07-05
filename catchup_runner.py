"""노트북이 늦게 켜져서 새벽 자동화를 놓쳤을 때, 로그온 시점 기준으로 같은 흐름을 재현한다.

2026-06-29 재설계: 하루 4슬롯(아침 06시/점심 11시/저녁 16시/야식 21시) 중
"이미 시작 시각이 지났는데 아직 안 끝난" 슬롯들을 순서대로(동시에 X) 따라잡는다.
  - 슬롯 시작 시각이 아직 안 됐으면 "놓친 게" 아니라 "아직 시작 안 된 것" — 건너뜀
  - 이미 끝난 슬롯도 건너뜀
  - 그 외(시작 시각은 지났는데 안 끝남) 슬롯만, 로그온 + 5분부터 시작해서 차례로 처리.
    각 슬롯 마감은 "그 슬롯 캐치업 시작 + 60분"

2026-07-02 재설계: 슬롯이 더 이상 카테고리에 고정되지 않음 — daily_runner.py와 동일하게
카테고리 무관 선정 + 오늘 다른 슬롯이 쓴 카테고리 제외 로직을 그대로 재사용한다
(daily_runner.run_slot()을 그대로 호출).

Windows Task Scheduler의 "놓친 작업 즉시 실행"(StartWhenAvailable) 기능은 대상 작업들을
동시에 몰아서 실행시켜 데이터 충돌을 일으키므로 사용하지 않고, 이 스크립트를 "로그온할 때"
트리거 작업 하나로 등록해서 대체한다.
"""
import sys
import time
from datetime import datetime, timedelta

import daily_runner

START_DELAY_MIN = 5       # 로그온 후 이만큼 지나야 캐치업 시작
DEADLINE_OFFSET_MIN = 60  # 캐치업 시작 + 60분 = 마감


def _missed_slots() -> list[str]:
    now = datetime.now()
    missed = []
    for slot, cfg in daily_runner.SLOT_CONFIG.items():  # dict 선언 순서 = 아침→점심→저녁→야식
        if now.hour < cfg["hour"]:
            continue  # 아직 시작 시각이 안 됨 — 놓친 게 아님
        if daily_runner._done_today(slot):
            continue  # 이미 끝남
        missed.append(slot)
    return missed


def catch_up_slot(slot: str):
    print(f"[catchup] [{slot}] {START_DELAY_MIN}분 후 시작")
    time.sleep(START_DELAY_MIN * 60)
    if daily_runner._done_today(slot):
        print(f"[catchup] [{slot}] 대기 중 이미 완료됨 — 건너뜀")
        return
    deadline_ts = datetime.now() + timedelta(minutes=DEADLINE_OFFSET_MIN)
    daily_runner.run_slot(slot, deadline_ts=deadline_ts)


def main():
    missed = _missed_slots()
    if not missed:
        print("[catchup] 놓친 슬롯 없음 — 종료")
        return
    print(f"[catchup] 놓친 슬롯: {missed} — 순서대로 따라잡기 시작")
    for slot in missed:
        catch_up_slot(slot)
    # 처리하는 동안 그 사이 시작 시각이 된 슬롯이 또 있을 수 있어 재확인
    remaining = _missed_slots()
    if remaining:
        print(f"[catchup] 처리 후에도 남은 슬롯: {remaining} — 한 번 더 처리")
        for slot in remaining:
            catch_up_slot(slot)


if __name__ == "__main__":
    main()
