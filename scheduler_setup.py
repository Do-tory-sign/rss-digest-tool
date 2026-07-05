"""Windows 작업 스케줄러 등록 — 매일 06:55 자동 실행
- 컴퓨터가 꺼져 있다가 켜지면 즉시 실행 (StartWhenAvailable)
- 최고 권한 실행 (HIGHEST)
"""
import sys
import subprocess
from pathlib import Path

SCRIPT_DIR        = Path(__file__).parent
PYTHON            = sys.executable
MAIN_PY           = SCRIPT_DIR / "main.py"
SESSION_CHECK_PY  = SCRIPT_DIR / "instagram_session_check.py"
TOKEN_CHECK_PY    = SCRIPT_DIR / "token_check.py"
TASK_NAME         = "CardNewsAutoPost"
TASK_SESSION      = "CardNewsSessionCheck"
TASK_TOKEN        = "CardNewsTokenCheck"
SCHEDULE_TIME     = "06:55"
SESSION_CHECK_TIME = "00:05"
TOKEN_CHECK_TIME  = "07:10"


def register_task():
    ps = f"""
$action = New-ScheduledTaskAction `
    -Execute '{PYTHON}' `
    -Argument '-X utf8 "{MAIN_PY}"' `
    -WorkingDirectory '{SCRIPT_DIR}'

$trigger = New-ScheduledTaskTrigger -Daily -At '{SCHEDULE_TIME}'

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName '{TASK_NAME}' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "등록 완료"
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅ 스케줄러 등록 완료: {TASK_NAME}")
        print(f"   · 매일 {SCHEDULE_TIME} 자동 실행")
        print(f"   · 컴퓨터 꺼져 있다가 켜지면 즉시 실행")
    else:
        print(f"❌ 등록 실패:\n{result.stderr}")


def register_session_check():
    ps = f"""
$action = New-ScheduledTaskAction `
    -Execute '{PYTHON}' `
    -Argument '-X utf8 "{SESSION_CHECK_PY}"' `
    -WorkingDirectory '{SCRIPT_DIR}'

$trigger = New-ScheduledTaskTrigger -Daily -At '{SESSION_CHECK_TIME}'

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName '{TASK_SESSION}' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "등록 완료"
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅ 세션 체크 스케줄러 등록 완료: {TASK_SESSION}")
        print(f"   · 매일 {SESSION_CHECK_TIME} 세션 확인")
        print(f"   · 만료 시 텔레그램 알림 발송")
    else:
        print(f"❌ 등록 실패:\n{result.stderr}")


def register_token_check():
    ps = f"""
$action = New-ScheduledTaskAction `
    -Execute '{PYTHON}' `
    -Argument '-X utf8 "{TOKEN_CHECK_PY}"' `
    -WorkingDirectory '{SCRIPT_DIR}'

$trigger = New-ScheduledTaskTrigger -Daily -At '{TOKEN_CHECK_TIME}'

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName '{TASK_TOKEN}' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "등록 완료"
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅ 토큰 만료 체크 스케줄러 등록 완료: {TASK_TOKEN}")
        print(f"   · 매일 {TOKEN_CHECK_TIME} 만료일 확인")
        print(f"   · 14일 이하 남으면 텔레그램 경고")
    else:
        print(f"❌ 등록 실패:\n{result.stderr}")


def unregister_task():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✅ 삭제 완료: {TASK_NAME}")
    else:
        print(f"❌ 삭제 실패:\n{result.stderr}")


def check_task():
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print("❌ 등록된 작업 없음")


def register_test_tasks():
    """오늘 지정 시간 3회 테스트 스케줄 등록 — 각각 다른 폴더"""
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    tests = [
        ("22:20", "test1"),
        ("22:32", "test2"),
        ("22:47", "test3"),
    ]
    test_script = SCRIPT_DIR / "test_upload_scheduled.py"

    for i, (t, folder) in enumerate(tests, 1):
        name = f"CardNewsTest{i}"
        cmd = [
            "schtasks", "/Create",
            "/TN", name,
            "/TR", f'"{PYTHON}" -X utf8 "{test_script}" {folder}',
            "/SC", "ONCE",
            "/ST", t,
            "/SD", today,
            "/F",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
        if result.returncode == 0:
            print(f"  ✅ CardNewsTest{i} — 오늘 {t} / 폴더: output/{folder}")
        else:
            print(f"  ❌ CardNewsTest{i} 실패: {result.stderr.strip()}")


def delete_test_tasks():
    for i in range(1, 4):
        subprocess.run(["schtasks", "/Delete", "/TN", f"CardNewsTest{i}", "/F"],
                       capture_output=True)
    print("테스트 스케줄 3개 삭제 완료")


if __name__ == "__main__":
    if "--delete" in sys.argv:
        unregister_task()
    elif "--check" in sys.argv:
        check_task()
    elif "--test" in sys.argv:
        print("=" * 50)
        print("  테스트 예약 등록 (오늘 3회)")
        print("=" * 50)
        register_test_tasks()
        print()
        print("테스트 완료 후 삭제: python scheduler_setup.py --delete-test")
    elif "--delete-test" in sys.argv:
        delete_test_tasks()
    else:
        print("=" * 50)
        print("  카드뉴스 자동화 스케줄러 등록")
        print("=" * 50)
        print(f"  Python : {PYTHON}")
        print(f"  스크립트: {MAIN_PY}")
        print(f"  실행 시간: 매일 {SCHEDULE_TIME}")
        print(f"  놓친 작업: 컴퓨터 켜지면 즉시 실행")
        print()
        register_task()
        print()
        register_session_check()
        print()
        register_token_check()
