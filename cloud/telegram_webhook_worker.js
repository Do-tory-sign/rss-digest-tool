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

    // 2026-07-17: "피드백 남기고 다시 그리기" 버튼 → force_reply로 텍스트를 받아서,
    // 그 답장(callback_query가 아니라 일반 message 업데이트)을 여기서 처리한다.
    // 상태 저장소 없이(서버리스라 KV 없이도 되게) 우리가 보낸 프롬프트 메시지 자체에
    // 마커([[FB|eventType|slot]])를 심어두고, reply_to_message.text에서 그 마커를
    // 다시 읽어 어떤 재생성인지 복원한다.
    const msg = update.message;
    if (msg && !update.callback_query) {
      await handleFeedbackReply(env, msg);
      return new Response("ok", { status: 200 });
    }

    const cq = update.callback_query;
    if (!cq) {
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
      art_image_regen: "article_image_regen",
      card_approve: "cards_approved",
      card_regen: "card_regen",
      card_reject: "cards_rejected",
      image_regen: "image_regen",
    };
    // 피드백 프롬프트를 띄우기만 하는 버튼(실제 재생성 이벤트가 아님) — 눌리면
    // force_reply 메시지를 보내고 끝. 실제 재생성은 사용자가 답장했을 때 일어난다.
    const FEEDBACK_PROMPT_MAP = {
      art_image_fb: "article_image_regen",
      image_fb: "image_regen",
    };
    if (FEEDBACK_PROMPT_MAP[action]) {
      await telegramApi(env, "answerCallbackQuery", { callback_query_id: cq.id });
      await telegramApi(env, "sendMessage", {
        chat_id: chatId,
        text:
          `📝 [${slot}] 그림에 반영할 피드백을 이 메시지에 "답장(reply)"으로 입력해주세요.\n\n` +
          `예: "도토리 꼬리/돌기 없애줘", "배경을 사무실 대신 법원으로", "인물을 여성으로 바꿔줘"\n` +
          `구체적인 시각 요소 하나를 한 문장으로 지목할수록 잘 반영돼요.\n\n` +
          `[[FB|${FEEDBACK_PROMPT_MAP[action]}|${slot}]]`,
        reply_markup: JSON.stringify({ force_reply: true, selective: true }),
      });
      return new Response("ok", { status: 200 });
    }

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

async function handleFeedbackReply(env, msg) {
  const replyTo = msg.reply_to_message;
  const feedbackText = (msg.text || "").trim();
  if (!replyTo || !replyTo.text || !feedbackText) return;
  // 2026-07-17 보안 수정(코드 리뷰로 발견): 마커 정규식만 검사하면, 채팅방 안의 아무
  // 메시지(포워딩된 텍스트, 다른 사람이 마커 문자열을 그대로 인용한 메시지 등)에 답장해도
  // 트리거될 수 있었음 — 반드시 "봇 자신이 보낸 메시지"에 대한 답장일 때만 처리한다.
  if (!replyTo.from?.is_bot) return;

  const m = replyTo.text.match(/\[\[FB\|([a-z_]+)\|([a-z_]+)\]\]/);
  if (!m) return; // 우리가 심어둔 마커가 있는 메시지에 대한 답장이 아니면 무시

  const eventType = m[1];
  const slot = m[2];

  await telegramApi(env, "sendMessage", {
    chat_id: msg.chat.id,
    text: `🎨 피드백 반영해서 다시 그릴게요: "${feedbackText}"`,
  });

  const dispatchOk = await githubDispatch(env, eventType, { slot, feedback: feedbackText });
  if (!dispatchOk) {
    await telegramApi(env, "sendMessage", {
      chat_id: msg.chat.id,
      text: `⚠️ GitHub Actions 트리거 실패 (${eventType}, slot=${slot}) — Actions 탭에서 수동 확인 필요`,
    });
  }
}

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
