# D:\GSoul 폴더 검토 (2026-07-01)

지인에게서 받은 인스타그램 자동화 노하우 작업물 전체 검토 기록. **원본 폴더는 읽기만 했고
수정·삭제하지 않았다.** 필요한 부분만 도토리뉴스 프로젝트로 복사/이식했고, 이식한 코드는
`Cardnews/blog/`, `Cardnews/news/character.py` 등 별도 파일이라 원본과 무관하게 독립적으로 동작한다.

## 폴더 전체 구조 한눈에

```
D:\GSoul\
├── README.md, MIGRATION_REPORT.md      이 폴더 자체의 운영 기록 (지인이 F:\Gsoul_issue에서 이전한 것)
├── chrome_web_uploader.py              인스타 웹 업로드 보조 (브라우저 자동화)
├── shared/
│   ├── instagram_graph_uploader.py     Instagram Graph API 공용 업로더
│   └── OPERATIONS_STRUCTURE.md         폴더 운영 정책 문서
├── ops/                                 여러 계정(gsoul_issue/gloomy/ideal 등) 공용 승인·업로드 파이프라인
│   ├── approval_prepare.py / approval_upload.py / approval_check.py / approval_resend.py
│   ├── telegram_approval_bot.py        텔레그램으로 승인받는 봇 (계정 공용)
│   ├── instagram_graph_*.py            Graph API 토큰/연결/사전점검 도구 모음
│   ├── accounts.json                   계정별 설정 등록
│   └── thread_handoffs/                작업 인수인계 기록 (이전 세션 메모)
└── Gsoul_issue/                         "@gsoul_issue" 계정 전용 — 우리가 참고한 핵심
    ├── gsoul_issue_pipeline.py (1571줄)  카드뉴스 생성 전체 로직 (제일 중요한 파일)
    ├── collect_gsoul_issue_news.py       뉴스 수집
    ├── JISOL_ISSUE_STYLE_GUIDE.md        디자인 규칙 문서
    ├── docs/bubble_repertoire_v1.md, gemini_image_design.md   말풍선/이미지 설계 메모
    ├── jisol_issue_prototype/assets/     지솔이 캐릭터 표정 이미지 원본들
    └── blog/                             네이버 블로그 자동 발행 (우리가 이식한 부분)
        ├── gsoul_blog_draft.py           기사→블로그 초안 변환
        ├── gsoul_blog_save_draft.py / gsoul_blog_package.py
        └── gsoul_blofit/                 실제 네이버 발행 엔진 (Selenium 기반, 2695줄)
            ├── trot_naver_engine.py      네이버 블로그 에디터 DOM 자동조작 (핵심)
            ├── trot_config.py / trot_settings.py   포트/프로필/자격증명 설정
            └── login_chrome.py           최초 1회 수동 로그인용 전용 크롬 실행
```

## 요청하신 3가지 항목 검토 결과

### 1. 뉴스 분석 → 쉽게 풀어주기(설명톤)

`gsoul_issue_pipeline.py`의 `build_with_gemini()`([gsoul_issue_pipeline.py:339](D:\GSoul\Gsoul_issue\gsoul_issue_pipeline.py))가 핵심.
"초등학생도 이해하게 설명하라", "어려운 용어는 생활 단어로 풀어라", "사실→왜 중요한지→생활에 어떤
영향인지" 순서로 짜라는 지시가 프롬프트에 명시돼 있음. 이건 우리 `synthesizer.py`에 이미 비슷한
구조(사실/왜중요/전망)로 들어가 있어서 **추가 이식은 불필요**했음.

대신 **Gemini API가 완전히 죽었을 때 대비한 키워드 기반 규칙 폴백**(`fallback_script()`,
[gsoul_issue_pipeline.py:285](D:\GSoul\Gsoul_issue\gsoul_issue_pipeline.py))은 우리한테 없던 안전장치라
이식함 → `news/synthesizer.py`의 `fallback_synthesis()` / `synthesize_or_fallback()`.
`v2_main.py`가 이제 이걸 사용해서, AI 합성이 통째로 실패해도 그날 슬롯이 완전히 비지 않고
간단한 규칙 기반 기사로라도 채워짐 (텔레그램에 "⚠️ 규칙기반 폴백" 표시가 붙어서 사람이 알아볼 수 있음).

### 2. 각 상황에 맞는 표정 이미지 사용

`jisol_expression()` / `pick_pose_for_text()`([gsoul_issue_pipeline.py:503,1309](D:\GSoul\Gsoul_issue\gsoul_issue_pipeline.py))가
지솔이 캐릭터 표정 이미지를 텍스트 내용에 맞춰 고르는 로직. 직접 포팅하기보다 **같은 아이디어를
우리 도토리 캐릭터(10개 표정)에 맞게 새로 설계**해서 적용함:
- 신규: `news/character.py` — 카드종류(사실/시각차이/왜중요/전망/커버) × 기사톤(무거움/가벼움)
  조합으로 적합한 표정을 자동으로 고름
- `html_composer.py`/카드 템플릿에 표정 배지 추가, `main.py`가 카드 만들 때마다 자동 적용
- (참고만 함, 코드는 그대로 가져오지 않음 — 우리 캐릭터 자산이 GSoul과 디자인이 달라서 직접
  이식보다 같은 패턴으로 새로 만드는 게 맞았음)

### 3. 네이버 블로그 포스팅 (뉴스페이지 대체)

`Gsoul_issue/blog/gsoul_blofit/`의 Selenium 기반 네이버 블로그 자동 발행 엔진을 **그대로 복사**해서
`Cardnews/blog/naver_engine/`에 이식함 (포트/Chrome 프로필/자격증명 prefix만 도토리뉴스 전용으로
분리해서 GSoul 쪽 자동화와 절대 충돌 안 나게 함). 새로 만든 파일:

- `blog/naver_engine/` — 엔진 사본 (`naver_engine.py`, `config.py`, `settings.py`, `login_chrome.py`)
- `blog/dotory_blog_draft.py` — 우리 카드뉴스 기사 데이터(`v2_articles_<카테고리>.json`)를 블로그
  초안(제목/본문/사진)으로 변환. 실제 오늘자 데이터로 테스트 완료, 정상 동작 확인.
- `blog/dotory_blog_publish.py` — 초안을 네이버 블로그에 임시저장(기본) 또는 발행(`--publish`)

**아직 안 끝난 부분 — 직접 하셔야 하는 1회성 설정**:
1. `python blog/naver_engine/login_chrome.py` 로 전용 크롬을 띄우고 거기서 네이버에 직접 로그인 (최초 1회, 제가 대신 할 수 없는 부분)
2. `python blog/dotory_blog_publish.py --set-id <네이버블로그ID>` 로 블로그 ID 등록
3. 이후 `python blog/dotory_blog_draft.py --category hot` → `python blog/dotory_blog_publish.py --draft <경로>` 순서로 사용

**뉴스페이지를 없애고 블로그로 완전히 대체하는 것은 아직 안 했습니다** — 위 1회성 로그인 설정이
끝나서 실제 발행이 정상 작동하는 걸 확인하신 뒤에, 기존 사이트(dotory-news.web.app)를 끌지 결정하시는 게
안전할 것 같아 그 결정은 보류해뒀습니다.

## 그 외 폴더에서 발견한, 나중에 참고하면 좋을 것들

- **`ops/` 의 다계정 승인 파이프라인**: 우리는 지금 카테고리별 텔레그램 승인을 `review.py` 하나가
  다 하고 있는데, GSoul은 계정이 여러 개(`accounts.json`)라 승인 로직이 공용 모듈로 분리돼 있음.
  나중에 도토리뉴스 계정이 여러 개로 늘어나면 이 구조를 참고할 만함.
- **`shared/instagram_graph_uploader.py`**: 우리 `instagram/uploader_graph.py`와 같은 역할. 업로드
  실패 시 재시도/로그 패턴이 더 꼼꼼하게 짜여 있어서, 지금 우리가 겪고 있는 "인스타 업로드 며칠째
  실패" 문제 디버깅할 때 비교해볼 가치 있음.
- **`Gsoul_issue/docs/gemini_image_design.md`, `bubble_repertoire_v1.md`**: 이미지/말풍선 디자인을
  체계적으로 문서화해둔 방식 — 우리도 카드 디자인 규칙을 이런 식으로 별도 문서화해두면 나중에
  편할 듯.
- **`MIGRATION_REPORT.md`**: 다른 컴퓨터로 옮길 때 체크리스트(Python/Node 설치, .env 키, 예약작업
  재등록, Chrome 경로, 네이버 재로그인 등)가 정리돼 있어서, 우리 프로젝트도 나중에 PC를 옮기게
  되면 이 체크리스트 형식을 그대로 따라 하면 됨.

## 포팅(이식) 시 항상 챙겨야 할 것

GSoul 폴더 안의 어떤 모듈을 더 가져오든 공통으로 확인할 것:
1. 경로 상수(F:\Gsoul_issue 등 절대경로)가 박혀있는지 — 있으면 우리 프로젝트 경로로 교체
2. 포트 번호(Chrome debug port 등)가 우리가 이미 쓰는 것과 안 겹치는지
3. `.env`/Windows 자격증명에 의존하는 키가 있는지 — 있으면 우리 `.env`에 맞게 추가
4. "지솔이슈/Gsoul" 같은 계정 고유명사가 메시지·파일명에 박혀있는지 — 텔레그램 알림 등 사람이 보는
   문구는 헷갈리지 않게 도토리뉴스용으로 바꿔야 함
