"""텔레그램 승인 → 클라우드(stage3_publish) 발행 완료를 감지해서, 블로그만 로컬에서
자동으로 마저 발행하는 감시 스크립트.

시각 기준(예: "매일 21시") 대신, "클라우드가 방금 사이트+인스타 발행을 끝냈는가"를
기준으로 트리거하고 싶어서 만듦 — Windows 작업 스케줄러에 몇 분 간격(예: 3분)
반복 실행으로 등록해두면, 승인 직후 클라우드가 끝나는 대로 몇 분 안에 자동으로
run_blog_local.py가 뒤따라 실행된다.

텔레그램 자체를 직접 감시하지 않는 이유: 웹훅(cloud/telegram_webhook_worker.js)이
이미 봇의 업데이트 수신을 독점하고 있어서, 같은 봇에 대해 로컬에서 추가로 폴링
(getUpdates)을 걸면 웹훅과 충돌한다. 대신 "승인되면 클라우드가 곧바로 성공적으로
끝난다"는 동일한 신호를 GitHub Actions run 성공 여부로 감지한다.

상태 파일(cloud/.blog_watch_state.json)에 이미 처리한 run id를 기록해서 중복 발행을
막는다. 최초 실행 시에는 기존에 이미 끝나있던 run들을 발행 없이 "처리 완료"로만
표시한다(그렇지 않으면 처음 등록하는 순간 과거 slot들이 한꺼번에 발행됨).

사용법 (작업 스케줄러에 등록):
    python -X utf8 cloud/watch_and_publish_blog.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 2026-07-19: Task Scheduler의 Hidden 옵션 + CREATE_NO_WINDOW로도 콘솔 창이 완전히 안 잡혀서
# pythonw.exe(콘솔 서브시스템 자체가 없는 버전)로 등록을 바꿈. 그런데 pythonw.exe는 아무 데도
# 리다이렉트 안 된 상태에서 sys.stdout/stderr가 None이라 print()가 그대로 죽는다 — 파일로
# 리다이렉트해서 로그도 남기고 크래시도 막는다.
if sys.stdout is None or sys.stderr is None:
    _log = open(ROOT / "cloud" / ".blog_watch.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log

from pipeline_lock import pipeline_lock  # noqa: E402
from cloud.run_blog_local import _run, REPO, GH, _NO_WINDOW, _PYTHON_EXE  # noqa: E402
from notify import notify_failure  # noqa: E402

STATE_PATH = ROOT / "cloud" / ".blog_watch_state.json"
# main.py/v2_main.py의 .pipeline.lock과는 무관한 별개 락 — 저 둘은 로컬 카드 생성 파이프라인이고
# 이 스크립트는 클라우드 산출물을 받아 블로그만 발행하므로 같은 락을 공유하면 서로 불필요하게
# 막힘. 이 스크립트끼리(3분 간격 폴링이 이전 실행과 겹치는 경우)만 막으면 됨.
WATCH_LOCK_PATH = ROOT / "cloud" / ".blog_watch.lock"
ARTIFACT_RE = re.compile(r"^approved-cards-(morning|lunch|evening|night)$")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"processed_run_ids": [], "alerted_run_ids": []}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _slot_for_run(run_id: int) -> str | None:
    """이 run이 업로드한 approved-cards-<slot> 아티팩트 이름에서 슬롯을 알아낸다."""
    out = _run([GH, "api", f"repos/{REPO}/actions/runs/{run_id}/artifacts",
                "--jq", ".artifacts[].name"])
    for name in out.splitlines():
        m = ARTIFACT_RE.match(name.strip())
        if m:
            return m.group(1)
    return None


def _alert_once(state: dict, run_id: int, message: str) -> None:
    """같은 run에 대해 폴링마다 반복 알림이 가지 않도록, run당 한 번만 텔레그램 알림."""
    alerted = set(state.get("alerted_run_ids", []))
    if run_id in alerted:
        return
    try:
        notify_failure(message)
    except Exception as e:
        print(f"[watch_blog] 알림 전송 실패(무시): {e}")
    alerted.add(run_id)
    state["alerted_run_ids"] = sorted(alerted)


def _process_runs(state: dict) -> None:
    processed = set(state.get("processed_run_ids", []))

    out = _run([GH, "run", "list", "-R", REPO, "--workflow", "stage3_publish.yml",
                "--status", "success", "--limit", "10",
                "--json", "databaseId,createdAt"])
    runs = json.loads(out)
    if not runs:
        print("[watch_blog] 성공한 stage3 run 없음")
        return

    is_first_run = not STATE_PATH.exists()
    if is_first_run:
        # 최초 등록 시: 기존 run들은 발행 없이 '이미 처리됨'으로만 표시 (그대로 두면 new_runs가
        # 자연히 비어서 아래 처리 루프가 아무것도 안 함 — 별도의 조기 return 불필요)
        processed |= {r["databaseId"] for r in runs}
        print(f"[watch_blog] 최초 실행 — 기존 run {len(runs)}개를 처리 완료로 표시(발행 안 함). "
              "다음 폴링부터 새 run만 감지함")

    new_runs = [r for r in runs if r["databaseId"] not in processed]
    if not new_runs:
        if is_first_run:
            state["processed_run_ids"] = sorted(processed)
            _save_state(state)
        else:
            print("[watch_blog] 새로 발행할 run 없음")
        return

    # 오래된 것부터 순서대로 처리 (같은 날 여러 슬롯이 밀려있을 경우 순서 보장)
    for r in sorted(new_runs, key=lambda x: x["createdAt"]):
        run_id = r["databaseId"]
        slot = _slot_for_run(run_id)
        if not slot:
            msg = (f"⚠️ run {run_id}에서 approved-cards 아티팩트를 못 찾음 — 블로그 발행 "
                   "영구 건너뜀(2일 지나면 아티팩트가 만료돼서 재시도 불가)")
            print(f"[watch_blog] {msg}")
            _alert_once(state, run_id, msg)
            processed.add(run_id)
            state["processed_run_ids"] = sorted(processed)
            _save_state(state)  # run마다 즉시 저장 — 도중에 죽어도 이미 처리한 run은 재작업 안 함
            continue

        print(f"[watch_blog] run {run_id} ({slot}) — 블로그 발행 시작")
        try:
            # run_id를 명시적으로 넘긴다 — run_blog_local.py가 자체적으로 "가장 최근 성공 run"을
            # 다시 조회하면, 이 사이 다른 슬롯의 run이 먼저 성공해있을 때 엉뚱한 run에서
            # approved-cards-<slot>을 찾다 실패/불일치할 수 있음(2026-07-19 코드 리뷰에서 발견).
            subprocess.run(
                [_PYTHON_EXE, "-X", "utf8", "cloud/run_blog_local.py",
                 "--slot", slot, "--run-id", str(run_id)],
                cwd=ROOT, check=True, creationflags=_NO_WINDOW,
            )
            print(f"[watch_blog] run {run_id} ({slot}) — 블로그 발행 완료")
        except subprocess.CalledProcessError as e:
            msg = f"⚠️ [{slot}] 블로그 로컬 발행 실패(run {run_id}): {e}"
            print(f"[watch_blog] {msg}")
            print("[watch_blog] 다음 폴링에서 재시도됨(이번 run은 처리 완료로 표시하지 않음)")
            _alert_once(state, run_id, msg)
            _save_state(state)  # alerted_run_ids만 갱신 — processed는 그대로 두어 재시도되게 함
            continue

        processed.add(run_id)
        state["processed_run_ids"] = sorted(processed)
        _save_state(state)


def main():
    state = _load_state()
    # 3분 간격 폴링 중 이전 실행(느린 Selenium 네이버 발행 등)이 아직 안 끝났으면 이번 폴링은
    # 건너뜀 — main.py의 pipeline_lock과 동일한 메커니즘, 단 이 스크립트 전용 락 파일 사용.
    with pipeline_lock("watch_and_publish_blog.py", wait_seconds=5, lock_path=WATCH_LOCK_PATH) as got_lock:
        if not got_lock:
            print("[watch_blog] 이전 실행이 아직 진행 중 — 이번 폴링 건너뜀")
            return
        _process_runs(state)


if __name__ == "__main__":
    main()
