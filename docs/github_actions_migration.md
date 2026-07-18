# GitHub Actions 마이그레이션 — 1단계 완료 보고 + 설정 가이드

작성일: 2026-07-05
범위: 카드뉴스 생성 + 텔레그램 승인 흐름 재설계 + 사이트 배포 + 인스타 업로드 (1단계, 완료)
      네이버 블로그 쿠키 기반 발행 (2단계, 설계만 완료 — 스캐폴딩은 아래 "2단계" 섹션 참고)

**이 문서와 함께 추가된 파일들은 전부 신규 파일입니다.** daily_runner.py, review.py, main.py,
v2_main.py, config.py, blog/ 안의 기존 파일은 단 한 줄도 수정하지 않았습니다.

---

## 1. 전체 그림

기존(로컬, PC 상시 구동):
```
Windows Task Scheduler(슬롯 시각) → daily_runner.py
  → v2_main.py (수집)
  → review.py (텔레그램 폴링 + 슬롯:55까지 sleep, 프로세스 하나가 계속 살아있음)
      → main.py (조립+배포+업로드+블로그)
```

신규(클라우드, PC 불필요):
```
GitHub Actions cron(슬롯 시각, KST→UTC 변환)
  → Stage 1 워크플로우: v2_main.py 수집 + 텔레그램 기사승인요청 전송 후 즉시 종료
       (사람이 텔레그램 버튼 클릭)
       → Cloudflare Worker가 웹훅으로 받아서 GitHub repository_dispatch 호출
  → Stage 2 워크플로우(article_approved 이벤트로 자동 기동): main.py --dry-run으로
       카드 5장 생성 + 텔레그램 카드승인요청 전송 후 즉시 종료
       (사람이 텔레그런 버튼 클릭)
       → Worker가 다시 repository_dispatch 호출
  → Stage 3 워크플로우(cards_approved 이벤트로 자동 기동): main.py --publish-only로
       실제 배포(Firebase 사이트 + 인스타그램 + 네이버 블로그 트리거)
```

핵심 포인트: **어느 워크플로우도 사람의 응답을 기다리며 대기하지 않습니다.**
버튼을 누르는 순간이 곧 "다음 워크플로우를 지금 막 시작시키는" 트리거입니다.
그래서 GitHub Actions의 과금/시간제한 모델과 자연스럽게 맞습니다.

---

## 2. 새로 생긴 파일 목록

```
.github/workflows/
  stage1_collect.yml       # cron(슬롯 시각) + article_regen dispatch로 트리거
  stage2_cards.yml         # article_approved dispatch로 트리거
  stage3_publish.yml       # cards_approved dispatch로 트리거
  article_rejected.yml     # article_rejected dispatch → 알림만 보내고 끝
  card_regen.yml           # card_regen dispatch → 카드 1장만 재생성

cloud/
  README.md                    # 이 폴더 자체의 설계 설명
  telegram_gate.py              # 텔레그런 승인 요청 "전송"만 담당하는 CLI (대기 로직 없음)
  dispatch_payload.py           # repository_dispatch의 client_payload(slot 등) 파싱 헬퍼
  regen_card_and_notify.py      # main.regenerate_single_card() 재사용 + 재전송
  telegram_webhook_worker.js    # Cloudflare Worker — 텔레그램 웹훅 수신 → GitHub dispatch 호출
  set_telegram_webhook.py       # 로컬 1회 실행 — 봇의 webhook을 Worker URL로 등록
  extract_naver_cookies.py      # (2단계 스캐폴딩) 네이버 로그인 쿠키 추출
  naver_cookie_login.py         # (2단계 스캐폴딩) Actions 안에서 쿠키 주입 로그인 복원

docs/
  github_actions_migration.md   # 이 문서
```

---

## 3. 지금 당장 해야 할 일 (사용자 액션 아이템)

### 3-1. GitHub Secrets 등록 (Settings → Secrets and variables → Actions → New repository secret)

| Secret 이름 | 값 | 비고 |
|---|---|---|
| `GEMINI_API_KEY` | .env의 GEMINI_API_KEY 값 | |
| `OPENAI_API_KEY` | .env의 OPENAI_API_KEY 값 | 없으면 그라디언트 배경으로 폴백(기존 로직) |
| `TELEGRAM_BOT_TOKEN` | .env의 TELEGRAM_BOT_TOKEN 값 | |
| `TELEGRAM_CHAT_ID` | .env의 TELEGRAM_CHAT_ID 값 | |
| `BRAND_NAME` | .env의 BRAND_NAME 값 | |
| `INSTAGRAM_GRAPH_TOKEN_JSON` | `instagram_graph_token.json` 파일 **전체 내용**(JSON 문자열 그대로) | `{"long_token": "...", "ig_user_id": "..."}` 형식 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 아래 3-2 참고 | Firebase 배포용 서비스 계정 키 JSON 전체 |

`INSTAGRAM_GRAPH_TOKEN_JSON`은 이렇게 만듭니다(PowerShell, 로컬에서):
```powershell
Get-Content instagram_graph_token.json -Raw | Set-Clipboard
```
그 다음 GitHub Secret 값 칸에 붙여넣기.

### 3-2. Firebase 배포 인증 준비

기존 main.py는 `firebase deploy --only hosting`을 그냥 shell로 실행합니다(로컬에서
이미 `firebase login`이 되어 있어서 동작). GitHub Actions는 로그인 상태가 없으므로
서비스 계정 키가 필요합니다.

```powershell
# 1) Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → "새 비공개 키 생성"으로 JSON 다운로드
# 2) 그 JSON 파일 전체 내용을 GitHub Secret FIREBASE_SERVICE_ACCOUNT_JSON 에 등록
```
`stage3_publish.yml`이 이 Secret을 파일로 복원하고 `GOOGLE_APPLICATION_CREDENTIALS`
환경변수로 지정합니다 — `firebase deploy`는 이 환경변수가 있으면 자동으로 서비스
계정 인증을 사용합니다(추가 코드 수정 없이 동작).

주의: 서비스 계정에 **Firebase Hosting Admin** 역할이 있어야 합니다(IAM에서 확인).

### 3-3. Cloudflare Worker 배포 (텔레그램 버튼 → GitHub 트리거 연결)

1. https://dash.cloudflare.com 무료 계정 생성(이미 있다면 로그인)
2. Workers & Pages → Create → Create Worker → 이름 예: `dotory-telegram-webhook`
3. 편집기에 `cloud/telegram_webhook_worker.js` 내용을 붙여넣고 Deploy
4. Worker → Settings → Variables and Secrets에 3개 등록(모두 "Secret" 타입으로):
   - `TELEGRAM_BOT_TOKEN` (.env와 동일 값)
   - `GITHUB_TOKEN` — 아래에서 새로 발급하는 PAT
   - `GITHUB_REPO` — `Do-tory-sign/Cardnews` 형식(실제 owner/repo 이름으로)
5. GitHub PAT 발급: GitHub → Settings → Developer settings → Personal access tokens
   → Fine-grained token, 이 저장소만 대상으로, **Contents: Read/Write**, **Actions: Read/Write**
   권한 부여 (repository_dispatch 호출에 필요)
6. 배포된 Worker 주소(`https://dotory-telegram-webhook.<계정>.workers.dev`)를 복사

### 3-4. 텔레그램 webhook 등록 (로컬에서 1회)

```powershell
python cloud/set_telegram_webhook.py https://dotory-telegram-webhook.<계정>.workers.dev
python cloud/set_telegram_webhook.py --check   # 등록 확인
```

**주의**: webhook을 등록하면 기존 review.py의 `getUpdates` 폴링 방식과 **동시에 쓸 수
없습니다**(텔레그램은 webhook 또는 polling 둘 중 하나만 허용). 로컬 파이프라인을
완전히 끄고 클라우드로 전환하는 시점에 등록하세요. 되돌리려면:
```powershell
python cloud/set_telegram_webhook.py --delete
```

### 3-5. 로컬 Task Scheduler 끄기 (전환 완료 후)

클라우드 쪽이 정상 동작을 몇 번 확인한 뒤, 기존 Windows Task Scheduler 작업(4개 슬롯)을
비활성화하세요. **주의: 로컬 daily_runner.py/review.py 파일 자체는 지우지 마세요** —
비상시 롤백용으로 남겨두고, Task Scheduler에서 "사용 안 함"으로만 바꾸는 걸 권장합니다.

---

## 4. Stage 2/3가 Stage 1의 산출물을 어떻게 이어받는가 (actions/cache 활용)

GitHub-hosted 러너는 매 워크플로우 실행마다 완전히 새로운 VM이라 로컬 파일이 남지
않습니다. `config.OUTPUT_DIR`이 `D:/Dotory/Cardnews/output`로 하드코딩되어 있어(수정
안 함) 이 경로 자체를 `actions/cache`로 저장/복원해 이어받습니다.

- Stage 1: 마지막에 `actions/cache/save`로 오늘자 산출물 저장 (완료)
- Stage 2: `actions/cache/restore`(restore-keys 접두사 매칭으로 Stage 1이 저장한
  캐시를 가져옴) → 카드 생성 후 다시 `cache/save`로 갱신 저장
- Stage 3: Stage 2가 저장한 캐시를 복원해 승인된 카드 이미지를 그대로 사용

## 5. 알려진 제약 / 다음에 손볼 부분 (1단계에서 의도적으로 남긴 것)

1. **actions/cache는 "정확히 같은 값 복원"을 보장하지 않음**: cache는 원래 CI 속도
   향상용이라 용량 제한(저장소당 10GB, 오래된 캐시 자동 삭제)이 있습니다. 안정성을
   더 높이려면 2단계에서 S3/Azure Blob 같은 실제 오브젝트 스토리지로 바꾸는 것을
   권장합니다. 지금은 "하루 안에 3단계가 빠르게 이어지는" 용도라 실용적으로 충분합니다.

3. **`article_regen`(기사 재생성) 피드백 텍스트 입력은 미지원**: 기존 review.py는
   재생성 버튼을 누르면 "피드백을 답장으로 입력해주세요"라고 물어보고 답장(message)을
   기다립니다. Cloudflare Worker는 지금 `callback_query`만 처리하고 일반 `message`
   업데이트(피드백 답장)는 무시합니다. 1단계에서는 "피드백 없이 재생성"만 동작합니다.
   피드백 입력까지 지원하려면 Worker에 조건부 로직(force_reply 답장 매칭)을 추가하고,
   그 텍스트를 client_payload로 실어 repository_dispatch에 넘기는 작업이 필요합니다.

4. **동시 슬롯 충돌 방지(pipeline_lock.py)는 클라우드에서 무의미**: 로컬은 파일 락으로
   동시 실행을 막았지만, GitHub Actions는 워크플로우별로 별도 VM이라 파일 락이 서로
   안 보입니다. 지금은 슬롯 간 시간 간격(5시간)이 넉넉해서 실질적 충돌 위험은 낮지만,
   완전한 재현을 원하면 GitHub Actions의 `concurrency:` 키(워크플로우 yaml에 추가)로
   같은 slot이 동시에 두 번 못 돌게 막는 것을 권장합니다.

5. **자동 타임아웃 진행 없음**: 기존 review.py는 마감 시간이 지나면 승인 없이도 자동
   진행했습니다. 새 구조는 순수 이벤트 기반이라 사람이 버튼을 누르기 전까지 다음
   단계로 못 넘어갑니다(단, 버튼은 시간 제한 없이 계속 유효합니다). "무응답 시
   자동 진행" 기능이 필요하면 `stage_auto_advance.yml`(가칭)을 슬롯:50분에 한번 더
   cron으로 돌려 "아직 승인 대기 중이면 그 상태로 자동 진행" 로직을 추가하는 걸
   2차 작업으로 제안합니다.

6. **Windows 러너 필수**: `blog/naver_engine`, PIL 폰트 경로(`config.WINDOWS_FONT_PATH`
   등)가 Windows 전용이라 `windows-latest` 러너를 그대로 씁니다. GitHub-hosted
   windows 러너는 무료 티어에서 리눅스보다 소진 속도가 2배 빠르게 계산되니
   (분당 크레딧 소모 2배) 사용량을 docs 하단 "비용" 섹션에서 확인하세요.

---

## 6. 2단계 설계 — 네이버 블로그 (쿠키 기반, 스캐폴딩만 완료) — ⚠️ 2026-07-19 폐기됨

> 아래 설계로 실제 구현(`cloud/naver_cookie_login.py`, `cloud/extract_naver_cookies.py`,
> `cloud/refresh_naver_cookies.py`)까지 완료했었으나, (1) 네이버 이용약관상 자동화된
> 수단의 로그인/게시가 명시적으로 금지돼 있고 (2) 클라우드 러너는 매 실행마다 새 IP·기기
> 지문이라 실제 로그인 절차 없이 쿠키만 주입하는 이 방식이 세션 하이재킹형 이상탐지에
> 특히 취약하다는 판단 하에 전량 삭제하고 하이브리드 구조로 되돌림: 사이트+인스타는
> 계속 클라우드(`stage3_publish.yml`, `SKIP_BLOG=1`)에서 처리하고, 블로그만
> `cloud/run_blog_local.py`로 로컬 PC의 실제 로그인 세션을 이용해 발행한다. 아래 내용은
> 그 판단이 나오기 전의 설계 기록으로만 남겨둠.



### 왜 기존 naver_engine을 그대로 못 쓰는가

`blog/naver_engine/login_chrome.py`와 `naver_engine.py`를 읽어보면:
- 실제 로컬 Chrome을 `--remote-debugging-port`로 띄우고 CDP로 붙는 방식(Selenium이
  아니라 기존에 로그인된 사용자 프로필을 그대로 재사용)
- `settings.py`의 `editor_x/y`, `publish_button1_x/y` 등 **화면 좌표 클릭** 기반 로직이
  섞여 있음(마우스 좌표 자동화 — headless 환경에서는 좌표 개념 자체가 다름)
- 비밀번호는 Windows Credential Manager(`win32cred`)에 저장 — 클라우드 러너에 없음

이 방식은 "사람이 한 번 로그인해둔 크롬 창을 계속 재사용"하는 데스크톱 자동화라
GitHub Actions(headless, 매번 새 VM)에는 그대로 이식 불가능합니다.

### 2단계 설계 방향

1. **쿠키 추출 (로컬, 1회 + 만료 시 재실행)**: `cloud/extract_naver_cookies.py`
   (스캐폴딩 완료, 아래 참고) — 로컬 Chrome의 네이버 로그인 세션에서
   `NID_AUT`, `NID_SES` 등 인증 쿠키를 추출해 JSON으로 저장.
2. **GitHub Secret 등록**: 추출된 쿠키 JSON을 `NAVER_COOKIES_JSON` Secret으로 등록.
3. **Actions 안에서 로그인 복원**: `cloud/naver_cookie_login.py`(스캐폴딩 완료) —
   Playwright로 headless Chromium을 띄우고, 쿠키를 주입한 뒤 네이버 블로그 글쓰기
   페이지로 이동. 좌표 클릭 대신 **CSS 선택자/역할(role) 기반**으로 스마트에디터를
   조작하도록 새로 작성해야 함(기존 naver_engine.py의 좌표 클릭 로직은 재사용 불가 —
   에디터 DOM 구조를 다시 분석해서 selector 기반 스크립트를 새로 짜야 합니다. 이 부분은
   시간 관계상 이번 세션에서는 완성하지 못했습니다).
4. **쿠키 만료 감지**: 로그인 확인 실패 시(에디터 페이지 대신 로그인 페이지로 리다이렉트
   되는 경우) 워크플로우가 실패하고 텔레그램으로 "네이버 쿠키 갱신 필요" 알림을 보냄
   (`cloud/naver_cookie_login.py`에 실패 시 알림 훅 자리 표시만 해둠 — notify 연동은
   다음 작업).
5. **쿠키 갱신 절차(사용자용)**: `python cloud/extract_naver_cookies.py` 재실행 →
   출력된 JSON을 `NAVER_COOKIES_JSON` Secret에 다시 붙여넣기.

### 2단계에서 아직 안 된 것 (다음 세션 작업 권장)

- 스마트에디터 DOM selector 조사 및 `naver_cookie_login.py` 안의 글쓰기 자동화 완성
- 이미지 업로드 자동화(에디터의 파일첨부 컨트롤은 보통 hidden input이라 Playwright의
  `set_input_files`로 가능할 가능성이 높음 — 검증 필요)
- 발행 여부(임시저장 vs 발행) 워크플로우 옵션화
- Stage 3 워크플로우에 네이버 블로그 스텝 추가(현재는 main.py --publish-only가
  로컬 방식 그대로 blog/dotory_blog_draft.py + dotory_blog_publish.py를 호출하는데,
  이건 클라우드에서 그대로 두면 크롬이 없어서 실패합니다 — 실패해도 사이트/인스타
  배포는 이미 끝난 뒤라 전체 파이프라인이 죽지는 않지만, 블로그만 계속 실패 알림이
  갈 것입니다. 2단계 완성 전까지는 이 실패를 "예상된 것"으로 안내 필요)

---

## 7. 비용 개요 (참고용, 확정 아님)

- GitHub Actions 무료 티어: 개인 계정 월 2,000분(private repo 기준), public repo는 무제한.
  Windows 러너는 1분 실행 = 2분 차감(2배 소모).
  슬롯당 3개 워크플로우(수집/카드/배포) × 각 3~8분 예상 × 4슬롯/일 × 30일 ≈
  월 200~400분 실행(Windows 배율 적용 시 400~800분) — 무료 한도 안에서 충분히 커버 가능한 규모.
- Cloudflare Workers 무료 티어: 일 10만 요청까지 무료 — 텔레그램 버튼 클릭 빈도로는
  전혀 문제 없음.
- Firebase Hosting: 기존과 동일(무료 티어 그대로 사용 가능).

---

## 8. 테스트 방법 (push 없이 로컬에서 확인 가능한 것)

이번 세션에서는 실제 GitHub Actions 실행(push/트리거)은 하지 않았습니다. 로컬에서
확인 가능한 것만 검증했습니다:
- 5개 workflow yaml 모두 `yaml.safe_load()`로 문법 검증 통과
- `cloud/*.py` 전부 `python -m py_compile` 통과(문법 오류 없음)

실제 동작 검증(다음 단계, 사용자가 Secrets 등록 후 진행 권장):
1. `workflow_dispatch`로 `stage1_collect.yml`을 GitHub Actions 탭에서 수동 실행
   (slot 선택) → 텔레그램에 기사 승인 요청이 오는지 확인
2. Cloudflare Worker + webhook 등록 후, 승인 버튼 클릭 → Stage 2가 자동 기동되는지
   Actions 탭에서 확인
3. 카드 승인 버튼 클릭 → Stage 3가 자동 기동되어 실제 배포되는지 확인
