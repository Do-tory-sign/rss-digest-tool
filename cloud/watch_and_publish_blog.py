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
표시하고 종료한다(그렇지 않으면 처음 등록하는 순간 과거 slot들이 한꺼번에 발행됨).

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
REPO = "Do-tory-sign/rss-digest-tool"
GH = r"C:\Program Files\GitHub CLI\gh.exe"
STATE_PATH = ROOT / "cloud" / ".blog_watch_state.json"
ARTIFACT_RE = re.compile(r"^approved-cards-(morning|lunch|evening|night)$")


def _run(args: list) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"명령 실패: {args}")
    return result.stdout


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"processed_run_ids": []}


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


def main():
    state = _load_state()
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
        # 최초 등록 시: 기존 run들은 발행 없이 '이미 처리됨'으로만 표시하고 끝냄
        for r in runs:
            processed.add(r["databaseId"])
        state["processed_run_ids"] = sorted(processed)
        _save_state(state)
        print(f"[watch_blog] 최초 실행 — 기존 run {len(runs)}개를 처리 완료로 표시(발행 안 함). "
              "다음 폴링부터 새 run만 감지함")
        return

    new_runs = [r for r in runs if r["databaseId"] not in processed]
    if not new_runs:
        print("[watch_blog] 새로 발행할 run 없음")
        return

    # 오래된 것부터 순서대로 처리 (같은 날 여러 슬롯이 밀려있을 경우 순서 보장)
    for r in sorted(new_runs, key=lambda x: x["createdAt"]):
        run_id = r["databaseId"]
        slot = _slot_for_run(run_id)
        if not slot:
            print(f"[watch_blog] run {run_id}: approved-cards 아티팩트 없음 — 건너뜀")
            processed.add(run_id)
            continue
        print(f"[watch_blog] run {run_id} ({slot}) — 블로그 발행 시작")
        try:
            subprocess.run(
                [sys.executable, "-X", "utf8", "cloud/run_blog_local.py", "--slot", slot],
                cwd=ROOT, check=True,
            )
            print(f"[watch_blog] run {run_id} ({slot}) — 블로그 발행 완료")
        except subprocess.CalledProcessError as e:
            print(f"[watch_blog] run {run_id} ({slot}) — 블로그 발행 실패: {e}")
            print("[watch_blog] 다음 폴링에서 재시도됨(이번 run은 처리 완료로 표시하지 않음)")
            continue
        processed.add(run_id)

    state["processed_run_ids"] = sorted(processed)
    _save_state(state)


if __name__ == "__main__":
    main()
