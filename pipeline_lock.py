"""파이프라인(main.py / v2_main.py) 동시 실행 방지용 lock 파일.

노트북이 늦게 켜져서 밀린 Task Scheduler 작업이 한꺼번에 실행되거나,
수동 실행과 스케줄 실행이 겹칠 때 같은 파일(web/v2/data.json, 이미지 등)을
동시에 덮어써서 데이터가 꼬이는 사고를 막는다.
"""
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE = Path(__file__).parent / ".pipeline.lock"
STALE_SECONDS = 30 * 60  # 30분 넘으면 멈춘 프로세스로 간주하고 무시


@contextmanager
def pipeline_lock(name: str, wait_seconds: int = 120, poll_seconds: int = 5):
    """다른 파이프라인이 lock을 들고 있으면 wait_seconds까지 대기 후 포기.
    획득 성공 시 True, 실패 시 False를 yield — 호출부는 False면 작업을 건너뛸 것."""
    deadline = time.time() + wait_seconds
    acquired = False

    while time.time() < deadline:
        if LOCK_FILE.exists():
            try:
                holder, ts = LOCK_FILE.read_text(encoding="utf-8").splitlines()[:2]
                age = time.time() - float(ts)
            except Exception:
                holder, age = "알수없음", STALE_SECONDS + 1

            if age > STALE_SECONDS:
                print(f"[lock] 오래된 lock 발견 ({holder}, {age/60:.0f}분 전) — 무시하고 재획득")
                LOCK_FILE.unlink(missing_ok=True)
            else:
                print(f"[lock] '{name}' 대기 중 — '{holder}'가 실행 중 ({age:.0f}초 전부터)")
                time.sleep(poll_seconds)
                continue

        try:
            LOCK_FILE.write_text(f"{name}\n{time.time()}", encoding="utf-8")
            acquired = True
            break
        except Exception:
            time.sleep(poll_seconds)

    if not acquired:
        print(f"[lock] '{name}' 락 획득 실패 — 건너뜀 (다른 파이프라인과 충돌 방지)")
        yield False
        return

    try:
        yield True
    finally:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
