"""파이프라인(main.py / v2_main.py) 동시 실행 방지용 lock 파일.

노트북이 늦게 켜져서 밀린 Task Scheduler 작업이 한꺼번에 실행되거나,
수동 실행과 스케줄 실행이 겹칠 때 같은 파일(web/v2/data.json, 이미지 등)을
동시에 덮어써서 데이터가 꼬이는 사고를 막는다.
"""
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE = Path(__file__).parent / ".pipeline.lock"
STALE_SECONDS = 30 * 60  # PID 생존 확인이 안 될 때(옛날 형식 락 등)만 쓰는 최후 판단 기준
# 2026-07-22: 순수 시간 기준(30분)만으로 "죽은 프로세스"라고 판단했다가, 네트워크 지연 등으로
# 정상적으로 오래 걸리는(예: GitHub API 재시도가 겹친) 프로세스의 락을 살아있는데도 빼앗아서
# 같은 크롬 세션을 두 프로세스가 동시에 조작하다 충돌하는 사고가 실제로 있었음(블로그 발행
# 중복). 이제 나이가 아니라 "그 PID가 실제로 살아있는가"로 판단한다 — 살아있으면 아무리
# 오래돼도 기다리고, 죽었으면 1분만 지나도 바로 재획득한다.
HARD_STALE_SECONDS = 6 * 60 * 60  # PID 확인 자체가 안 될 때의 최후 안전장치(6시간)


def _pid_alive(pid: int) -> bool:
    """Windows에서 해당 PID의 프로세스가 아직 살아있는지 확인. 확인 실패 시 True(보수적으로
    '살아있다'고 가정 — 살아있는 프로세스의 락을 잘못 빼앗는 것보다, 죽은 락을 몇 초 더
    기다리는 게 훨씬 안전하다)."""
    try:
        # 2026-07-22: text=True(기본 UTF-8 디코딩)로 했다가 tasklist 출력이 시스템 코드페이지
        # (한글 Windows면 cp949)라 UnicodeDecodeError가 나서 예외 분기로 빠졌고, 그러면
        # "확인 실패 시 보수적으로 살아있다고 간주"가 매번 발동해 PID 체크가 사실상 무력화돼
        # 있었음(죽은 프로세스도 계속 "살아있다"로 판정) — errors="replace"로 디코딩 자체가
        # 절대 실패하지 않게 한다(숫자 PID는 어떤 코드페이지에서도 ASCII로 안전하게 남음).
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).stdout
        return str(pid) in out
    except Exception:
        return True


@contextmanager
def pipeline_lock(name: str, wait_seconds: int = 120, poll_seconds: int = 5,
                   lock_path: Path = LOCK_FILE):
    """다른 파이프라인이 lock을 들고 있으면 wait_seconds까지 대기 후 포기.
    획득 성공 시 True, 실패 시 False를 yield — 호출부는 False면 작업을 건너뛸 것.
    lock_path: 기본은 main.py/v2_main.py가 공유하는 락 파일 — 서로 무관한 파이프라인
    (예: 블로그 감시 스크립트)이 같은 락을 쓰면 불필요하게 서로 막으니 별도 경로를 넘길 것."""
    deadline = time.time() + wait_seconds
    acquired = False

    while time.time() < deadline:
        if lock_path.exists():
            try:
                lines = lock_path.read_text(encoding="utf-8").splitlines()
                holder, ts = lines[0], lines[1]
                pid = int(lines[2]) if len(lines) > 2 else None
                age = time.time() - float(ts)
            except Exception:
                holder, age, pid = "알수없음", HARD_STALE_SECONDS + 1, None

            is_stale = (not _pid_alive(pid)) if pid is not None else (age > STALE_SECONDS)
            is_stale = is_stale or age > HARD_STALE_SECONDS  # PID가 재사용됐을 극단적 경우 대비

            if is_stale:
                print(f"[lock] 오래된 lock 발견 ({holder}, {age/60:.0f}분 전, pid={pid}) — "
                      "프로세스 죽음 확인, 무시하고 재획득")
                lock_path.unlink(missing_ok=True)
            else:
                print(f"[lock] '{name}' 대기 중 — '{holder}'가 실행 중 (pid={pid}, {age:.0f}초 전부터)")
                time.sleep(poll_seconds)
                continue

        try:
            lock_path.write_text(f"{name}\n{time.time()}\n{os.getpid()}", encoding="utf-8")
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
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
