/**
 * Cloudflare Worker — 텔레그램 버튼 콜백을 받아서 GitHub repository_dispatch API를 호출한다.
 *
 * 왜 필요한가:
 *   GitHub Actions는 "텔레그램에서 오는 요청을 상시 대기하며 받는" 서버가 될 수 없다
 *   (워크플로우는 트리거가 있어야만 실행된다). 그래서 텔레그램 쪽 webhook을 받아줄
 *   아주 작은 상시 서버가 하나 필요한데, 이를 위해 무료 티어로 상시 가동 가능한
 *   Cloudflare Worker를 쓴다(서버 유지비 없음, 요청 시에만 실행).
 *
 * 배포 방법 (요약 — 전체는 docs/github_actions_migration.md 참고):
 *   1) https://dash.cloudflare.com → Workers & Pages → Create Worker
 *   2) 이 파일 내용을 붙여넣고 Deploy
 *   3) Worker 설정 → Variables 에 다음 3개를 "Secret"으로 등록:
 *        TELEGRAM_BOT_TOKEN   (텔레그램 봇 토큰 — .env에 있는 값과 동일)
 *        GITHUB_TOKEN         (repo, workflow 권한의 GitHub PAT — 새로 발급)
 *        GITHUB_REPO          ("Do-tory-sign/Cardnews" 형식의 owner/repo)
 *   4) 배포된 Worker URL(https://xxx.workers.dev)을 cloud/set_telegram_webhook.py 로 등록
 *
 * 이 파일은 GitHub Actions에서 실행되지 않는다 — Cloudflare에 별도로 배포하는
 * 독립 서버리스 함수다. 저장소에는 "코드 보관 + 배포 안내용"으로만 둔다.
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad request", { status: 400 });
    }

    const cq = update.callback_query;
    if (!cq) {
      // 기사/카드 승인과 무관한 업데이트(피드백 답장 등)는 일단 200만 반환.
      // 피드백 답장 처리(force_reply)는 2단계 개선 과제로 남겨둠 — 우선은 버튼 흐름만 지원.
      return new Response("ok", { status: 200 });
    }

    const data = cq.data || "";
    const chatId = cq.message?.chat?.id;
    const messageId = cq.message?.message_id;

    // 콜백 데이터 형식: "art_approve|slot" / "art_regen|slot|category" / "art_reject|slot"
    //                  "card_approve|slot" / "card_regen|slot|cardname"
    const parts = data.split("|");
    const action = parts[0];
    const slot = parts[1];
    const extra = parts[2] || "";

    const EVENT_MAP = {
      art_approve: "article_approved",
      art_regen: "article_regen",
      art_reject: "article_rejected",
      card_approve: "cards_approved",
      card_regen: "card_regen",
      card_reject: "cards_rejected",
      image_regen: "image_regen",
    };
    const eventType = EVENT_MAP[action];

    // 텔레그램에 즉시 응답(로딩 스피너 제거) — GitHub 호출 결과와 무관하게 먼저 처리
    await telegramApi(env, "answerCallbackQuery", {
      callback_query_id: cq.id,
      text: eventType ? "처리 중..." : "알 수 없는 동작",
    });

    if (!eventType || !slot) {
      return new Response("ignored", { status: 200 });
    }

    // 버튼 눌린 메시지의 인라인 키보드 제거(중복 클릭 방지) — art_regen/card_regen은
    // 여러 카드에 각각 버튼이 있으므로 지우지 않고 그대로 둔다(다른 카드 재생성도 눌러야 하니까).
    if (action === "art_approve" || action === "art_reject" || action === "card_approve" || action === "card_reject") {
      await telegramApi(env, "editMessageReplyMarkup", {
        chat_id: chatId,
        message_id: messageId,
        reply_markup: JSON.stringify({}),
      });
    }

    const dispatchOk = await githubDispatch(env, eventType, { slot, extra });

    if (!dispatchOk) {
      await telegramApi(env, "sendMessage", {
        chat_id: chatId,
        text: `⚠️ GitHub Actions 트리거 실패 (${eventType}, slot=${slot}) — Actions 탭에서 수동 확인 필요`,
      });
    }

    return new Response("ok", { status: 200 });
  },
};

async function telegramApi(env, method, body) {
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.error(`telegramApi(${method}) failed`, e);
  }
}

async function githubDispatch(env, eventType, clientPayload) {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "dotory-news-telegram-worker",
        },
        body: JSON.stringify({
          event_type: eventType,
          client_payload: clientPayload,
        }),
      }
    );
    return res.status === 204;
  } catch (e) {
    console.error("githubDispatch failed", e);
    return false;
  }
}
