"""카드 승인 후 슬롯:55에 딱 한 번 실행되는 배포 트리거.

2026-07-05: 예전엔 review.py 프로세스가 time.sleep(수십분)으로 :55까지 직접 대기하다가
main.py --publish-only를 호출했는데, 그 긴 sleep 도중 프로세스가 어떤 이유로든(강제종료,
PC 절전, 크래시 등) 죽으면 배포 자체가 통째로 누락되고 알림도 안 갔음(실제로 2026-07-05
저녁한입에서 발생). Windows 작업 스케줄러에 정확한 시각의 1회성 작업으로 이 스크립트를
등록해두면, review.py 프로세스의 생존 여부와 완전히 무관하게 OS가 대신 실행해준다.

review.py::_wait_until_slot_deadline_and_publish()가 카드 승인 직후 이 스크립트를
schtasks로 예약하고 자기 자신은 바로 종료한다 — 더 이상 오래 살아있을 필요가 없다.

사용법 (직접 실행할 일은 거의 없음 — schtasks가 대신 호출):
    python -X utf8 scheduled_publish.py --slot evening
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

VALID_SLOTS = ("morning", "lunch", "evening", "night")


def main():
    slot = None
    if "--slot" in sys.argv:
        idx = sys.argv.index("--slot")
        if idx + 1 < len(sys.argv):
            slot = sys.argv[idx + 1]
    if slot not in VALID_SLOTS:
        print(f"사용법: python scheduled_publish.py --slot {'|'.join(VALID_SLOTS)}")
        sys.exit(2)

    import run_log
    run_log.enable(f"scheduled_publish_{slot}")

    from notify import send

    print(f"[scheduled_publish] [{slot}] 예약된 배포 실행 (--publish-only)")
    args = [sys.executable, "-X", "utf8", "main.py", "--slot", slot, "--publish-only"]
    result = subprocess.run(args, cwd=Path(__file__).parent)

    if result.returncode == 0:
        send(f"✅ 도토리뉴스 [{slot}] 사이트+인스타 업로드 완료! (블로그는 별도 알림 확인)")
    else:
        send(f"⚠️ [{slot}] 예약 배포 실패 (exit code {result.returncode}) — 로그 확인 필요")

    # 1회성 스케줄 작업이므로 실행 후 자기 자신을 스케줄러에서 삭제(다음날 같은 이름 재등록 대비)
    try:
        task_name = f"DotoryPublish_{slot}"
        subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"],
                       capture_output=True, text=True, encoding="cp949", errors="replace")
    except Exception:
        pass

    sys.exit(0 if result.returncode == 0 else 1)


if __name__ == "__main__":
    main()
