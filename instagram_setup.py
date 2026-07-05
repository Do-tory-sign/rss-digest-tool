"""Instagram sessionid 저장 스크립트 — 세션 만료 시 재실행"""
import json
import urllib.parse
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "instagram_session.json"

print("=" * 50)
print("  Instagram sessionid 갱신")
print("=" * 50)
print()
print("[ Chrome에서 sessionid 추출 방법 ]")
print("  1. instagram.com 접속 (로그인 상태)")
print("  2. F12 → Application → Cookies")
print("     → https://www.instagram.com")
print("  3. 'sessionid' 행의 Value 복사")
print()

raw = input("sessionid 붙여넣기: ").strip()
sessionid = urllib.parse.unquote(raw)
ds_user_id = sessionid.split(":")[0]

data = {"sessionid": sessionid, "ds_user_id": ds_user_id}
SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

print()
print(f"✅ 세션 저장 완료!")
print(f"   계정 ID : {ds_user_id}")
print(f"   저장 위치: {SESSION_FILE}")
print()
print("이제 main.py를 실행하면 자동 업로드됩니다.")
