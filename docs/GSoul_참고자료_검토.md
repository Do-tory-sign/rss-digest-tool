# GSoul 폴더 전체 검토 — 포팅 가이드

검토일: 2026-07-01  
대상: `D:\GSoul\Gsoul_issue\` (읽기 전용 검토, 수정 없음)  
도토리뉴스: `C:\Users\또야\Documents\Do.tory\Cardnews\`

---

## 폴더 구조

```
D:\GSoul\
├── Gsoul_issue\                    ← 메인 작업 폴더
│   ├── collect_gsoul_issue_news.py     뉴스 수집 + 스코어링 + Gemini 카드데이터 생성
│   ├── gsoul_issue_pipeline.py         PIL 기반 이미지 렌더러 (메인 카드 생성)
│   ├── build_gsoul_issue_assets.py     HTML 기반 카드 빌더
│   ├── render_gsoul_issue_cards.js     Puppeteer HTML→PNG 렌더러
│   ├── gsoul_issue_story_designer.py   인스타 스토리 수직 이미지 생성
│   ├── gsoul_issue_story_uploader.py   ADB로 안드로이드 태블릿에 스토리 업로드
│   ├── gsoul_issue_web_upload_runner.py Chrome 웹자동화로 피드 업로드
│   ├── scheduled_gsoul_issue_pipeline.py 전체 파이프라인 진행자 (수집→빌드→업로드)
│   ├── gsoul_issue_comment_manager.py  댓글 감시 + AI 스팸 분류 + 텔레그램 승인
│   ├── instagram_comment_manager_common.py 댓글관리 공통 엔진
│   ├── gsoul_issue_brand.py            브랜드 상수 (표시명, 프로필 소개)
│   ├── gsoul_issue_profile_setup.py    프로필 사진 + 소개글 자동 설정
│   ├── image_processor.py              뉴스 OG 이미지 다운로드 + 얼굴 블러 처리
│   ├── adb_helper.py                   ADB 기반 태블릿 제어 유틸리티
│   ├── instagram_account_selector.py   ADB로 인스타 계정 전환
│   ├── generate_5_versions.py          5가지 디자인 테마 일괄 생성기
│   ├── experiment_ai_scene_card_to_telegram.py  AI 생성 씬 실험
│   ├── JISOL_ISSUE_STYLE_GUIDE.md      캐릭터/디자인 스타일 가이드
│   ├── Jua-Regular.ttf                 한글 폰트
│   ├── blog\                           네이버 블로그 자동화
│   │   ├── gsoul_blog_draft.py             블로그 초안 생성 (기사 크롤링 + 구조화)
│   │   ├── gsoul_blog_package.py           초안→블로그 패키지 변환
│   │   ├── gsoul_blog_save_draft.py        Chrome으로 Smart Editor에 임시저장
│   │   ├── gsoul_blog_publish_for_toon.py  발행 실행
│   │   ├── gsoul_blog_telegram.py          블로그 텔레그램 알림
│   │   ├── gsoul_blog_telegram_bot.py      텔레그램 봇 (로그인 끊김 시 재개)
│   │   └── data/packages/                  발행 완료된 패키지들
│   └── jisol_issue_prototype\          캐릭터 프로토타입 + 에셋
│       ├── CHARACTER_GUIDE.md              지솔이 캐릭터 가이드
│       └── assets\
│           ├── jisol_expression_sheet_v1.png  6종 표정 시트 (2행 3열)
│           ├── jisol_cutouts_active_v4\        6종 컷아웃 PNG
│           └── jisol_master_profile_fixed_v1.png
├── ops\                                공통 운영 도구
│   ├── approval_prepare.py             텔레그램 승인 요청 준비
│   ├── approval_upload.py              승인된 콘텐츠 인스타 업로드
│   ├── telegram_approval_bot.py        승인/거절 콜백 처리 봇
│   ├── shared\
│   │   └── instagram_graph_uploader.py Instagram Graph API 업로드
│   └── approvals\                      일별 승인 manifest JSON
└── shared\                             공유 모듈
```

---

## 파일별 내용 요약

### collect_gsoul_issue_news.py
- **역할**: RSS 17개 피드 수집 → 관심도 스코어링 → Gemini 2.5 Pro로 카드뉴스 JSON 생성
- **핵심 기능**:
  - `FEEDS`: 뉴시스/매일경제/SBS/연합뉴스/구글뉴스 17개 RSS 소스
  - `interest_score()`: 신선도+키워드+카테고리+주목도 가중합산
  - `ATTENTION_KEYWORDS` / `PENALTY_KEYWORDS` / `NICHE_PENALTY_KEYWORDS`: 3단 키워드 테이블
  - `choose_articles()`: 카테고리 다양성 보장하며 8개 선발
  - `build_with_gemini()`: 뉴닉 스타일 친근한 설명 + 이모지 + 500자 이상 캡션 생성
  - `fetch_og_image()`: 기사 OG 이미지 자동 수집

### gsoul_issue_pipeline.py
- **역할**: PIL 직접 렌더링으로 카드 이미지 생성
- **핵심 기능**:
  - `apply_feed_safe_padding()`: 인스타 프로필 그리드 클리핑 방지용 안전 여백
  - `jisol_expression()`: 표정 시트에서 개별 표정 크롭
  - `paste_jisol()`: 지솔이 캐릭터 합성
  - `draw_speech()`: 말풍선 렌더링
  - `generate_ai_scene()` / `generate_gemini_scene()`: DALL-E / Gemini로 배경 씬 AI 생성
  - `remove_generated_text_marks()`: AI 생성 이미지에서 불필요한 텍스트 제거
  - `ai_scene_prompt()` / `gemini_scene_prompt()`: 씬 생성 프롬프트 빌더
  - 기-승-전-결 4슬라이드 구조 렌더링

### build_gsoul_issue_assets.py
- **역할**: JSON 데이터→HTML 카드 빌더 (CSS 변수 기반 테마 시스템)
- **핵심 기능**:
  - `render_cover()`: 상위 이슈 이미지+오버레이 커버 카드
  - `render_body()`: 기사별 본문 카드 (OG 이미지 포함)
  - `render_ending()`: CTA 엔딩 카드
  - CSS 변수(`--c-accent`, `--c-bg` 등)로 테마 교체 가능

### generate_5_versions.py
- **역할**: 5가지 디자인 테마(클래식/글래스모피즘/매거진/네온다크/소프트파스텔) 일괄 생성
- **핵심**: 테마별 CSS 변수 + 커버 타이틀 텍스트를 파라미터로 주입

### image_processor.py
- **역할**: 뉴스 기사 OG 이미지 다운로드 + 얼굴 자동 블러 처리
- **핵심**: OpenCV Haar Cascade로 얼굴 감지 → GaussianBlur 적용 → 로컬 캐시

### gsoul_issue_story_designer.py
- **역할**: 인스타 스토리용 1080x1920 수직 이미지 생성
- **핵심**: 그라디언트 배경 + 카드 썸네일 합성 + 훅 카피 텍스트 오버레이

### instagram_comment_manager_common.py
- **역할**: 인스타 댓글 감시 → Gemini로 스팸 분류 → 텔레그램 인라인 버튼으로 답글/삭제/건너뛰기
- **핵심**: `instagrapi` 기반, `telegram.ext` 봇으로 승인 UI 구현

### blog/gsoul_blog_draft.py
- **역할**: 기사 URL 크롤링 → BeautifulSoup 파싱 → 블로그 초안 구조 생성
- **핵심**: `fetch_article()` 멀티 셀렉터 크롤러, 문장 분할 + 폴백 문장 자동 채우기

### blog/gsoul_blog_save_draft.py / gsoul_blog_publish_for_toon.py
- **역할**: Selenium/Chrome으로 네이버 Smart Editor에 임시저장 및 발행

### ops/approval_prepare.py + approval_upload.py + telegram_approval_bot.py
- **역할**: 텔레그램으로 콘텐츠 승인 요청 → 인라인 버튼으로 승인/거절 → 승인 시 자동 업로드
- **핵심**: manifest JSON 기반 상태관리, 인스타 Graph API 업로드

---

## 포팅 가능 기능 목록

| 기능명 | GSoul 파일 | 도토리 적용 위치 | 이미 적용? | 우선순위 | 메모 |
|--------|-----------|-----------------|-----------|---------|------|
| 뉴스 쉽게 풀어주기 (설명톤) | `collect_gsoul_issue_news.py` `build_with_gemini()` | `news/synthesizer.py` | **완료** | — | fallback_synthesis()로 이식됨 |
| 캐릭터 표정 선택 | `gsoul_issue_pipeline.py` `jisol_expression()` | `news/character.py` | **완료** | — | character.py로 이식됨 |
| 네이버 블로그 포스팅 | `blog/gsoul_blog_*.py` | `blog/` | 조사됨 | — | 도토리 blog/ 폴더에 구현됨 |
| 기사 OG 이미지 수집 | `collect_gsoul_issue_news.py` `fetch_og_image()` | `news/collector.py` | **미적용** | 높음 | 기사 대표 이미지를 카드에 삽입 가능 |
| OG 이미지 얼굴 블러 처리 | `image_processor.py` | `news/` 신규 모듈 | **미적용** | 중간 | 초상권 보호, OpenCV 필요 |
| 관심도 스코어링 (3단 키워드 테이블) | `collect_gsoul_issue_news.py` `interest_score()` | `news/curator.py` | **미적용** | 높음 | 현재 도토리 curator가 단순 선발 — GSoul의 가중합 공식이 훨씬 정교함 |
| RSS 소스 확장 (17개 피드) | `collect_gsoul_issue_news.py` `FEEDS` | `news/collector.py` | **미적용** | 높음 | 현재 도토리는 소수 피드만 수집 |
| 카테고리 다양성 보장 선발 | `collect_gsoul_issue_news.py` `choose_articles()` | `news/curator.py` | **미적용** | 높음 | 같은 카테고리 3개 초과 방지 |
| 인스타 스토리 수직 이미지 자동 생성 | `gsoul_issue_story_designer.py` | `image/` 신규 모듈 | **미적용** | 높음 | 피드 업로드 후 스토리도 자동 발행 |
| 5가지 디자인 테마 전환 | `generate_5_versions.py` + `build_gsoul_issue_assets.py` CSS 변수 시스템 | `image/html_composer.py` | **미적용** | 중간 | CSS 변수만 교체로 디자인 다변화 |
| 텔레그램 인라인 버튼 승인 | `ops/approval_prepare.py` + `telegram_approval_bot.py` | `notify.py` + `main.py` | **미적용** | 높음 | 현재 도토리는 텔레그램 피드백만 있고 인라인 버튼 승인은 없음 |
| AI 댓글 자동 관리 (스팸 분류 + 답글 초안) | `instagram_comment_manager_common.py` | 신규 `instagram/comment_manager.py` | **미적용** | 중간 | Gemini로 스팸 판별 + 텔레그램 인라인 버튼 답글 승인 |
| feed_safe_padding (프로필 그리드 안전여백) | `gsoul_issue_pipeline.py` `apply_feed_safe_padding()` | `image/composer.py` | **미적용** | 낮음 | HTML 렌더러 사용 시 CSS padding으로 대체 가능 |
| 인스타 Graph API 업로드 | `ops/shared/instagram_graph_uploader.py` | `instagram/uploader_graph.py` | 부분 적용 | 낮음 | 도토리에 uploader_graph.py 있음, GSoul ops/shared가 더 완성도 높음 |
| 블로그 텔레그램 봇 (로그인 끊김 재개) | `blog/gsoul_blog_telegram_bot.py` | `blog/` | **미적용** | 중간 | "블로그" 메시지 보내면 pending job 재실행 |
| 카테고리별 관심 보너스 | `collect_gsoul_issue_news.py` `_people_impact_bonus()` / `_broad_interest_bonus()` | `news/curator.py` | **미적용** | 중간 | 생활(LIFE) +4, 경제(ECONOMY) +3 등 카테고리 가중치 |
| 뉴스 소스 리포트 자동 생성 | `collect_gsoul_issue_news.py` `write_report()` | 신규 `news/reporter.py` | **미적용** | 낮음 | 후보 전체 + 선발 이유 마크다운 리포트 |

---

## 주요 기능 상세 (미적용 — 포팅 우선순위 순)

---

### 1. 기사 OG 이미지 수집 및 카드 삽입

**설명**: 뉴스 기사 URL에서 `og:image` 메타태그로 대표 이미지를 가져와 카드에 삽입한다. 현재 도토리뉴스는 AI 생성 이미지만 사용하는데, OG 이미지를 병행하면 실제 뉴스 맥락이 시각적으로 전달된다.

**핵심 코드** (`collect_gsoul_issue_news.py`):
```python
def fetch_og_image(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ..."})
    with urllib.request.urlopen(req, timeout=5) as response:
        html_content = response.read().decode("utf-8", errors="ignore")
        match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if match:
            img_url = match.group(1)
            reject_patterns = ["logo", "default", "blank", "icon", "no_image"]
            if any(p in img_url.lower() for p in reject_patterns):
                return ""
            return img_url
    return ""
```

**포팅 방법**: `news/collector.py`의 `fetch_articles()`에서 기사 URL 수집 후 `fetch_og_image(url)` 호출, 결과를 article dict의 `"image_url"` 키에 저장. HTML 카드 템플릿(`image/templates/card_v2.html`)에서 `{{ image_url }}`로 표시.

**포팅 난이도**: 낮음 (30줄 이하, 추가 의존성 없음)

---

### 2. 관심도 스코어링 (3단 키워드 테이블)

**설명**: 현재 도토리 `curator.py`는 단순 카테고리 기반 선발. GSoul은 신선도+주목 키워드+카테고리 보너스+광범위 관심 보너스-패널티를 합산해 점수가 낮은 기사는 아예 탈락시킨다.

**핵심 코드** (`collect_gsoul_issue_news.py`):
```python
ATTENTION_KEYWORDS = {
    7: ["사기", "보이스피싱", "해킹", ...],
    6: ["속보", "긴급", "사망", "관세", "해고", ...],
    5: ["금리", "물가", "집값", "반도체", "ai", ...],
}
PENALTY_KEYWORDS = {
    6: ["행사", "축제", "개막", "공모전", "협약 체결", ...],
}
NICHE_PENALTY_KEYWORDS = {
    8: ["오늘의운세", "운세", "띠별", "별자리"],
    7: ["학술지", "연구팀", "브랜드", "팝업", ...],
}

def interest_score(article):
    score = _freshness_score(article["published_at"])  # 최신 2시간: +8
    score += _keyword_score(blob, ATTENTION_KEYWORDS)
    score += _people_impact_bonus(article["category"])  # LIFE: +4
    score += _broad_interest_bonus(blob)  # 돈/안전/정책/빅테크 각 +3
    score -= _keyword_score(blob, PENALTY_KEYWORDS)
    score -= _keyword_score(blob, NICHE_PENALTY_KEYWORDS)
    if "단독" in title: score += 3
    if "왜" in title or "어떻게" in title: score += 2
    if _same_day(article): score += 5
    return score
```

**포팅 방법**: `news/curator.py`에 `ATTENTION_KEYWORDS`, `PENALTY_KEYWORDS`, `NICHE_PENALTY_KEYWORDS` 테이블 추가 후 `interest_score()` 함수 이식. 기존 `score_article()` 대체 또는 병행.

**포팅 난이도**: 낮음 (순수 Python, 의존성 없음)

---

### 3. 카테고리 다양성 보장 뉴스 선발

**설명**: 같은 카테고리 뉴스가 3개 이상 몰리지 않도록, 첫 선발 라운드에서 각 카테고리 대표를 먼저 뽑고 나머지 슬롯을 채운다.

**핵심 코드**:
```python
def choose_articles(articles):
    # 1라운드: 카테고리별 1개씩 선발 (커버용 4개)
    for article in candidate_pool:
        if article["category"] not in seen_categories:
            chosen.append(article)
            seen_categories.add(article["category"])
        if len(chosen) >= COVER_TOTAL: break

    # 2라운드: 남은 슬롯, 같은 카테고리 3개 초과 금지
    for article in candidate_pool:
        if category_counts.get(article["category"], 0) >= 3: continue
        chosen.append(article)
        if len(chosen) >= TARGET_TOTAL: break
```

**포팅 방법**: `news/curator.py`의 선발 로직을 이 방식으로 교체.

**포팅 난이도**: 낮음

---

### 4. 인스타 스토리 수직 이미지 자동 생성

**설명**: 피드 업로드 후 같은 날 스토리도 올리면 계정 노출이 크게 늘어난다. GSoul은 커버 카드를 860x860으로 축소해 1080x1920 그라디언트 배경에 합성하고 훅 카피를 오버레이해 스토리 이미지를 만든다.

**핵심 코드** (`gsoul_issue_story_designer.py`):
```python
def create_story(source: Path, output_dir: Path) -> Path:
    base = gradient_background((1080, 1920)).convert("RGBA")
    card = Image.open(source).convert("RGBA").resize((860, 860), ...)
    # 그림자 합성
    shadow_draw.rounded_rectangle((24,24,896,896), radius=58, fill=(0,0,0,95))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(shadow, dest=(82, 286))
    # 텍스트 오버레이
    draw.text((96, 110), "오늘 안 보면 후회할 핵심 뉴스", ...)
    draw.rounded_rectangle((96, 1238, 984, 1412), ...)  # CTA 박스
```

**포팅 방법**: `image/story_designer.py`로 이식, `daily_runner.py`에서 피드 업로드 성공 후 호출. 브랜드 텍스트만 "도토리뉴스"로 변경.

**포팅 난이도**: 낮음 (PIL만 사용, 이미 설치됨)

---

### 5. 텔레그램 인라인 버튼 승인 시스템

**설명**: 현재 도토리 `notify.py`는 `force_reply`로 피드백만 받는다. GSoul은 텔레그램 인라인 키보드([승인] [거절] [재생성])를 띄우고 콜백으로 업로드까지 자동 실행한다.

**GSoul 구조**:
- `ops/approval_prepare.py`: 이미지+캡션을 텔레그램으로 전송, manifest JSON 생성
- `ops/telegram_approval_bot.py`: 콜백 처리, 승인 시 `approval_upload.py` 실행
- `ops/approval_upload.py`: manifest에서 승인된 이미지 읽어 Graph API로 업로드

**핵심 코드**:
```python
keyboard = {
    "inline_keyboard": [[
        {"text": "승인 업로드", "callback_data": f"approve:{key}"},
        {"text": "거절", "callback_data": f"reject:{key}"},
        {"text": "재생성", "callback_data": f"regen:{key}"},
    ]]
}
```

**포팅 방법**:
1. `notify.py`에 `send_approval_request(images, caption)` 함수 추가 — 카드 이미지들을 미디어그룹으로 전송 + 인라인 버튼
2. `daily_runner.py`에 승인 대기 루프 추가 또는 별도 봇 프로세스로 분리
3. 승인 콜백 수신 시 `instagram/uploader_graph.py` 호출

**포팅 난이도**: 중간 (python-telegram-bot 패키지 추가 필요, 비동기 처리)

---

### 6. AI 댓글 자동 관리

**설명**: instagrapi로 최근 게시물 댓글을 주기적으로 폴링 → Gemini로 스팸 여부 판별 + 답글 초안 생성 → 텔레그램 인라인 버튼으로 사람이 최종 확인.

**핵심 코드** (`instagram_comment_manager_common.py`):
```python
def analyze_comment(comment_text, author, display_name, tone_prompt, gemini_api_key, logger):
    prompt = f"""
인스타그램 계정 '{display_name}' 댓글 관리용 분류.
스팸 기준: 광고성 링크, 반복 이모지, 욕설/도배
JSON만 반환: {{"is_spam": false, "reason": "...", "reply": "..."}}
"""
    response = client.models.generate_content(model="gemini-flash", contents=prompt)
    return json.loads(response.text...)

# 텔레그램 인라인 버튼으로 답글 확인
keyboard = {
    "inline_keyboard": [[
        {"text": "답글 게시", "callback_data": f"reply:{key}"},
        {"text": "댓글 삭제", "callback_data": f"delete:{key}"},
        {"text": "건너뛰기", "callback_data": f"skip:{key}"},
    ]]
}
```

**포팅 방법**: `instagram/comment_manager.py` 신규 파일로 이식, `.env`에 `IG_USERNAME` / `IG_PASSWORD` 추가, `scheduler_setup.py`에서 댓글 관리 스케줄 등록.

**포팅 난이도**: 중간 (instagrapi + aiohttp + python-telegram-bot 의존성)

---

### 7. OG 이미지 얼굴 블러 처리

**설명**: 뉴스 OG 이미지에 실제 인물 얼굴이 포함된 경우 초상권 문제가 생길 수 있다. OpenCV Haar Cascade로 얼굴을 감지해 GaussianBlur 처리 후 로컬 캐시.

**핵심 코드** (`image_processor.py`):
```python
def apply_face_blur(img):
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    for (x,y,w,h) in faces:
        k_size = max(w//2, h//2) | 1  # 홀수 보장
        blurred = cv2.GaussianBlur(face_roi, (k_size, k_size), 30)
        img[y:y+h, x:x+w] = blurred
    return img
```

**포팅 방법**: `news/image_processor.py`로 그대로 이식. OG 이미지 수집 후 자동 적용. `requirements.txt`에 `opencv-python-headless` 추가.

**포팅 난이도**: 낮음 (단 opencv-python 설치 필요)

---

### 8. RSS 소스 확장

**설명**: 현재 도토리뉴스 RSS 소스를 GSoul의 17개 피드 목록으로 보강한다.

**추가할 소스** (도토리에 없는 것):
- SBS 정치/경제/사회/국제 RSS
- 연합뉴스TV 헤드라인
- 매일경제 부동산
- 구글뉴스 핫토픽 (`https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko`)

**포팅 난이도**: 매우 낮음 (리스트 추가만)

---

### 9. 블로그 텔레그램 봇 (로그인 끊김 재개)

**설명**: 네이버 블로그 포스팅 중 로그인이 끊기면 pending job을 저장해두고, 사용자가 로그인 후 텔레그램에 "블로그"라고 보내면 자동으로 이어서 실행.

**핵심 코드** (`blog/gsoul_blog_telegram_bot.py`):
```python
def handle_text(text):
    if text.strip().lower() not in {"블로그", "/blog"}:
        return
    job = pop_next_pending_job()
    if job:
        result = run_pending_blog(job)
        send_blog_telegram("완료" if result.returncode == 0 else "실패")
```

**포팅 방법**: 도토리 `blog/` 폴더에 `dotory_blog_telegram_bot.py` 신규 파일로 이식, pending job 저장 경로를 도토리 경로로 변경.

**포팅 난이도**: 중간

---

## 포팅 권장 순서

### 즉시 적용 가능 (1일 이내, 코드 이식만)
1. RSS 소스 확장 → `news/collector.py`
2. 관심도 스코어링 3단 키워드 테이블 → `news/curator.py`
3. 카테고리 다양성 선발 로직 → `news/curator.py`
4. OG 이미지 수집 (`fetch_og_image`) → `news/collector.py`

### 단기 적용 (2~3일)
5. 인스타 스토리 수직 이미지 생성 → `image/story_designer.py`
6. 텔레그램 인라인 버튼 승인 → `notify.py` + `daily_runner.py`

### 중기 적용 (1주)
7. OG 이미지 얼굴 블러 (`opencv-python-headless` 설치 필요)
8. AI 댓글 자동 관리 (`instagrapi` + 비동기 처리)
9. 블로그 텔레그램 봇

### 선택적 적용
- 5가지 디자인 테마 전환 (현재 도토리 디자인 안정화 후)
- feed_safe_padding (CSS padding으로 이미 처리 가능)
