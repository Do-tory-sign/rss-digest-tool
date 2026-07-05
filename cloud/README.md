# cloud/ — GitHub Actions 전용 신규 스크립트 모음

이 폴더의 파일은 전부 **새로 추가된 파일**입니다. 기존 daily_runner.py / review.py /
main.py / v2_main.py 는 단 한 줄도 수정하지 않았고, 그 파일들이 제공하는 함수/CLI를
"읽기 전용으로" import/subprocess 호출만 합니다.

## 왜 review.py를 그대로 못 쓰는가

review.py는 프로세스가 계속 살아있으면서:
1. 텔레그램 `getUpdates` 롱폴링을 무한 반복하고
2. 카드 승인 후에는 슬롯 `:55`까지 `time.sleep()`으로 대기합니다.

GitHub Actions는:
- Job 하나가 보통 6시간 제한(그리고 무료 계정은 분당 과금이라 대기 자체가 낭비)이고
- "몇 시간 동안 계속 떠 있는 프로세스"라는 개념 자체가 클라우드 과금 모델과 안 맞습니다.

그래서 review.py의 역할을 **3개의 독립적인 워크플로우 실행(run)**으로 쪼갰습니다.
각 실행은 몇 분 안에 끝나고, 다음 단계로 넘어갈지는 텔레그램 버튼 클릭이
GitHub API(`repository_dispatch`)를 직접 호출해서 "다음 워크플로우를 지금 막 켜는" 방식으로 처리합니다.

## 새 파이프라인 흐름

```
[Stage 1: collect]  (cron 트리거, 슬롯 시각 정각)
  v2_main.py --slot X --fresh 실행 (기존 파일 그대로 재사용)
  → cloud/telegram_gate.py send-article  로 기사 승인 요청 전송 (승인/재생성/반려 버튼)
  → 워크플로우 종료 (대기 없음)

  [사람이 텔레그램 버튼 클릭]
  → Cloudflare Worker(cloud/telegram_webhook_worker.js)가 콜백을 받아서
    GitHub repository_dispatch API 호출:
      approve  → event_type="article_approved"   (Stage 2 트리거)
      regen    → event_type="article_regen"       (Stage 1 재실행, 피드백 반영)
      reject   → event_type="article_rejected"    (알림만 보내고 끝)

[Stage 2: cards]  (repository_dispatch: article_approved 트리거)
  main.py --slot X --dry-run 으로 카드 5장만 생성 (배포/업로드 없음, 기존 동작 그대로)
  → cloud/telegram_gate.py send-cards 로 카드 승인 요청 전송
  → 워크플로우 종료

  [사람이 텔레그램 버튼 클릭]
  → Worker가 repository_dispatch 호출:
      approve       → event_type="cards_approved"  (Stage 3 트리거)
      regen_<card>  → main.regenerate_single_card() 만 실행하는 별도 초경량 dispatch

[Stage 3: publish]  (repository_dispatch: cards_approved 트리거, 또는 cron 안전망)
  main.py --slot X --publish-only 실행 (사이트 배포 + 인스타 업로드 + 블로그, 기존 로직 그대로)
```

## 무기한 대기가 사라지는 대신 생기는 변화

- 기존: "재생성 5분 대기 후 자동 진행", "마감 도달 시 자동 카드 생성" 같은 **자동 타임아웃 진행**
  로직이 review.py 안에 있었습니다.
- 새 구조: 승인 자체가 **이벤트 기반**이라 시간제한이 없습니다(텔레그램 버튼을 누를 때까지
  워크플로우가 다시 켜지지 않을 뿐, 며칠이 지나도 버튼은 유효합니다).
- 다만 "완전 자동(무응답 시 진행)"을 원하면 `cloud/auto_advance.yml` 워크플로우가
  슬롯:50분에 한번 더 돌면서, 아직 승인 안 된 게 있으면 "마감 임박" 알림을 보내고
  slot:55에도 응답이 없으면 그 상태 그대로 자동 진행하도록 별도로 켤 수 있게 만들어뒀습니다
  (기본은 꺼짐 — docs/github_actions_migration.md 참고).

## 파일 목록

- `cloud/telegram_gate.py` — 기사/카드 승인 요청을 텔레그램으로 보내는 CLI (review.py의 전송 로직 일부를 참고해 새로 작성, review.py는 안 건드림)
- `cloud/dispatch_receiver.py` — repository_dispatch 페이로드를 받아서 어떤 동작을 할지 판단하는 헬퍼(워크플로우 안에서 사용)
- `cloud/telegram_webhook_worker.js` — Cloudflare Worker (텔레그램 웹훅 수신 → GitHub repository_dispatch 호출). Actions 밖에서 별도 배포 필요(무료 티어).
- `cloud/set_telegram_webhook.py` — 로컬에서 1회 실행, 텔레그램 봇의 webhook URL을 Worker 주소로 등록
- `cloud/extract_naver_cookies.py` — (2단계) 로컬 Chrome에서 네이버 로그인 쿠키 추출 → GitHub Secret 등록용 JSON 출력
- `cloud/naver_cookie_login.py` — (2단계) Actions 안에서 쿠키를 주입해 로그인 상태 복원(Playwright)
