"""클라우드(GitHub Actions) stage3가 사이트+인스타까지 끝낸 뒤, 블로그만 로컬에서
마저 처리하는 스크립트.

2026-07-06: 카드+인스타+사이트는 클라우드로 이전(main.py의 SKIP_BLOG=1 처리),
네이버 블로그는 로그인 세션이 필요해 당분간 로컬 담당. stage3가 승인된 카드 이미지를
GitHub Actions 아티팩트로 올려두므로, 이 스크립트가 최신 성공 아티팩트를 받아와서
output/<date>/<slot>_*.png 로 복원한 뒤 blog/dotory_blog_draft.py + dotory_blog_publish.py를
그대로 호출한다.

사용법:
    python -X utf8 cloud/run_blog_local.py --slot night
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPO = "Do-tory-sign/rss-digest-tool"
GH = r"C:\Program Files\GitHub CLI\gh.exe"


def _run(args: list) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"명령 실패: {args}")
    return result.stdout


def main():
    if "--slot" not in sys.argv:
        print("사용법: python cloud/run_blog_local.py --slot morning|lunch|evening|night")
        sys.exit(2)
    slot = sys.argv[sys.argv.index("--slot") + 1]

    print(f"[run_blog_local] [{slot}] stage3 최신 성공 run 조회 중...")
    out = _run([GH, "run", "list", "-R", REPO, "--workflow", "stage3_publish.yml",
                "--status", "success", "--limit", "5",
                "--json", "databaseId,createdAt"])
    import json
    runs = json.loads(out)
    if not runs:
        raise RuntimeError("성공한 stage3 run이 없음")
    run_id = runs[0]["databaseId"]

    dest = ROOT / "cloud" / "_artifact_tmp"
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[run_blog_local] run {run_id} 아티팩트 다운로드 중 (approved-cards-{slot})...")
    _run([GH, "run", "download", str(run_id), "-R", REPO,
          "-n", f"approved-cards-{slot}", "-D", str(dest)])

    # 아티팩트 구조: dest/<date>/<slot>_*.png, v2_*_<slot>.json -> config.OUTPUT_DIR/<date>/ 로 복사
    # (blog/dotory_blog_draft.py가 config.OUTPUT_DIR 기준으로 카드 이미지 + JSON을 찾음 —
    # 예전엔 여기 ROOT/"output"으로 복사해서 실제 경로와 안 맞아 JSON을 못 찾는 버그가 있었음)
    import config
    for date_dir in dest.iterdir():
        if not date_dir.is_dir():
            continue
        target = config.OUTPUT_DIR / date_dir.name
        target.mkdir(parents=True, exist_ok=True)
        patterns = [f"{slot}_*.png", f"v2_articles_{slot}.json", f"v2_curated_{slot}.json"]
        for pattern in patterns:
            for f in date_dir.glob(pattern):
                (target / f.name).write_bytes(f.read_bytes())
                print(f"[run_blog_local]   복사: {f.name}")

    print(f"[run_blog_local] [{slot}] 블로그 초안 작성 중...")
    blog_dir = ROOT / "blog"
    draft_result = subprocess.run(
        [sys.executable, "-X", "utf8", "dotory_blog_draft.py", "--slot", slot],
        cwd=blog_dir, capture_output=True, text=True,
    )
    draft_path = None
    for line in draft_result.stdout.splitlines():
        if line.startswith("[BLOG_DRAFT]"):
            draft_path = line.split("[BLOG_DRAFT]", 1)[1].strip()
    print(draft_result.stdout)
    if not draft_path:
        print(draft_result.stderr)
        raise RuntimeError("블로그 초안 생성 실패")

    subprocess.run(
        [sys.executable, "-X", "utf8", "dotory_blog_publish.py", "--draft", draft_path],
        cwd=blog_dir,
    )


if __name__ == "__main__":
    main()
