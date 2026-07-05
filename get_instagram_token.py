"""Instagram Login OAuth 토큰 발급 스크립트 (새 Instagram API)"""
import webbrowser
import urllib.parse
import urllib.request
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

APP_ID = "3955097377955454"
APP_SECRET = "49be582deb242d3966289c904393087e"
REDIRECT_URI = "http://localhost:8080/"
SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments"

auth_code = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>OK - 인증 완료! 이 창 닫아도 됩니다.</h1>".encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"error: " + self.path.encode())

    def log_message(self, *args):
        pass


def post(url, data: dict):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.request.urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def main():
    # Instagram Login OAuth URL (Facebook 아님!)
    auth_url = (
        f"https://api.instagram.com/oauth/authorize"
        f"?client_id={APP_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={SCOPES}"
        f"&response_type=code"
    )

    print("브라우저에서 Instagram 로그인 창이 열립니다...")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), Handler)
    print("인증 대기 중... (브라우저에서 허용 눌러줘)")
    server.handle_request()

    if not auth_code:
        print("[ERROR] 인증 코드를 받지 못했습니다.")
        return

    print("[OK] 인증 코드 수신!")

    # 단기 토큰 교환 (Instagram API 엔드포인트)
    token_data = post(
        "https://api.instagram.com/oauth/access_token",
        {
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": auth_code,
        },
    )
    print("[단기 토큰]", token_data)

    if "access_token" not in token_data:
        print("[ERROR] 단기 토큰 발급 실패:", token_data)
        return

    short_token = token_data["access_token"]
    ig_user_id = str(token_data.get("user_id", ""))

    # 장기 토큰 교환 (60일)
    lt_url = (
        f"https://graph.instagram.com/access_token"
        f"?grant_type=ig_exchange_token"
        f"&client_id={APP_ID}"
        f"&client_secret={APP_SECRET}"
        f"&access_token={short_token}"
    )
    lt_data = get(lt_url)
    print("[장기 토큰]", lt_data)

    long_token = lt_data.get("access_token", short_token)
    expires = lt_data.get("expires_in", 0) // 86400
    print(f"[OK] 장기 토큰 발급 완료 (만료: {expires}일 후)")

    # Instagram 계정 정보 확인
    me = get(f"https://graph.instagram.com/v19.0/me?fields=id,username&access_token={long_token}")
    print("[계정]", me)

    if not ig_user_id:
        ig_user_id = me.get("id", "17841436557727225")

    # 결과 저장
    from datetime import date
    result = {
        "long_token": long_token,
        "ig_user_id": ig_user_id,
        "expires_days": expires,
        "issued_at": date.today().isoformat(),
        "username": me.get("username", "do.tory_news"),
    }
    with open("instagram_graph_token.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n=== 저장 완료: instagram_graph_token.json ===")
    print(f"  IG User ID : {ig_user_id}")
    print(f"  Username   : {me.get('username')}")
    print(f"  Token      : {long_token[:60]}...")


if __name__ == "__main__":
    main()
