const $ = (selector) => document.querySelector(selector);

const state = {
  sending: false,
  apiBase: localStorage.getItem("day12-api-base") || window.location.origin,
};

const clientIdInput = $("#client-id");
const tokenInput = $("#api-token");
const apiBaseInput = $("#api-base");
const messageInput = $("#message-input");
const messageList = $("#message-list");
const welcomeCard = $("#welcome-card");
const requestError = $("#request-error");
const sendButton = $("#send-button");
const charCount = $("#char-count");

clientIdInput.value = localStorage.getItem("day12-client-id") || "sv-test";
apiBaseInput.value = state.apiBase;

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, "") || window.location.origin;
}

function setApiBase() {
  state.apiBase = normalizeBaseUrl(apiBaseInput.value);
  apiBaseInput.value = state.apiBase;
  localStorage.setItem("day12-api-base", state.apiBase);
}

function showError(message) {
  requestError.textContent = message;
  requestError.hidden = false;
}

function clearError() {
  requestError.hidden = true;
  requestError.textContent = "";
}

function setGlobalStatus(label, tone) {
  const status = $("#global-status");
  status.className = `status-chip status-${tone}`;
  status.innerHTML = `<span class="status-dot" aria-hidden="true"></span>${label}`;
}

function setHealthRow(prefix, label, tone) {
  const dot = $(`#${prefix}-dot`);
  const value = $(`#${prefix}-value`);
  dot.className = `health-dot ${tone}`;
  value.className = `health-value ${tone}`;
  value.textContent = label;
}

async function readEndpoint(path) {
  const response = await fetch(`${state.apiBase}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  let body = null;
  try { body = await response.json(); } catch (_) { /* no JSON body */ }
  return { ok: response.ok, body };
}

async function refreshHealth() {
  setGlobalStatus("Đang kiểm tra service", "loading");
  setHealthRow("health", "Đang kiểm tra", "pending");
  setHealthRow("ready", "Đang kiểm tra", "pending");

  const [health, ready] = await Promise.allSettled([
    readEndpoint("/healthz"),
    readEndpoint("/readyz"),
  ]);

  const healthOk = health.status === "fulfilled" && health.value.ok;
  const readyOk = ready.status === "fulfilled" && ready.value.ok;
  setHealthRow("health", healthOk ? "OK" : "Unavailable", healthOk ? "ok" : "error");
  setHealthRow("ready", readyOk ? "Ready" : "Not ready", readyOk ? "ok" : "error");

  if (healthOk && readyOk) {
    setGlobalStatus("Service online", "ok");
  } else {
    setGlobalStatus("Service cần kiểm tra", "error");
  }
}

function addMessage(role, text, meta = []) {
  welcomeCard.hidden = true;
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "Bạn / request" : "Service / response";

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  article.append(label, body);
  if (meta.length) {
    const metadata = document.createElement("div");
    metadata.className = "message-meta";
    metadata.textContent = meta.join("  ·  ");
    article.append(metadata);
  }
  messageList.append(article);
  messageList.scrollTop = messageList.scrollHeight;
  return article;
}

function addLoadingMessage() {
  welcomeCard.hidden = true;
  const article = document.createElement("article");
  article.className = "message assistant message-loading";
  article.innerHTML = `
    <div class="message-label">Service / processing</div>
    <div class="message-body" aria-label="Đang xử lý">
      <div class="loading-line"></div>
      <div class="loading-line short"></div>
    </div>`;
  messageList.append(article);
  messageList.scrollTop = messageList.scrollHeight;
  return article;
}

function setSending(sending) {
  state.sending = sending;
  sendButton.disabled = sending;
  sendButton.innerHTML = sending ? "Đang gửi…" : 'Gửi request <span aria-hidden="true">↗</span>';
}

function explainApiError(status, body) {
  const detail = typeof body?.detail === "string" ? body.detail : "Service trả về lỗi không xác định.";
  if (status === 401) return "Token chưa đúng hoặc còn trống. Hãy kiểm tra API token trong bảng cấu hình bên trái.";
  if (status === 402) return "Client đã chạm daily budget. Hãy thử lại sau khi ngân sách ngày được reset.";
  if (status === 422) return "Body request chưa đúng định dạng. Nội dung phải dài từ 1 đến 2000 ký tự.";
  if (status === 429) return "Rate limit đang hoạt động. Chờ một chút rồi gửi lại request.";
  if (status === 503) return "Service chưa sẵn sàng hoặc đang draining. Kiểm tra Readiness ở sidebar.";
  return `${detail} (HTTP ${status})`;
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.sending) return;

  const message = messageInput.value.trim();
  const token = tokenInput.value.trim();
  const clientId = clientIdInput.value.trim() || "anonymous";
  setApiBase();
  localStorage.setItem("day12-client-id", clientId);
  clearError();

  if (!token) {
    showError("Hãy nhập API token trước khi gửi request.");
    tokenInput.focus();
    return;
  }
  if (!message) {
    showError("Hãy nhập một câu hỏi trước khi gửi.");
    messageInput.focus();
    return;
  }

  addMessage("user", message);
  messageInput.value = "";
  updateCharCount();
  const loadingMessage = addLoadingMessage();
  setSending(true);

  try {
    const response = await fetch(`${state.apiBase}/chat`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Client-Id": clientId,
      },
      body: JSON.stringify({ message }),
    });
    let body = null;
    try { body = await response.json(); } catch (_) { /* handled below */ }
    loadingMessage.remove();
    if (!response.ok) {
      showError(explainApiError(response.status, body));
      return;
    }

    const usage = body.usage || {};
    const cost = typeof body.usd_cost === "number" ? `$${body.usd_cost.toFixed(6)}` : "cost n/a";
    addMessage("assistant", body.reply || "Service không trả về nội dung.", [
      `${body.turns_before ?? 0} turns trước`,
      `prompt ${usage.prompt ?? 0}`,
      `completion ${usage.completion ?? 0}`,
      cost,
    ]);
  } catch (error) {
    loadingMessage.remove();
    showError(`Không kết nối được API tại ${state.apiBase}. ${error.message}`);
  } finally {
    setSending(false);
  }
}

function updateCharCount() {
  charCount.textContent = `${messageInput.value.length} / 2000`;
}

$("#chat-form").addEventListener("submit", sendMessage);
$("#refresh-health").addEventListener("click", refreshHealth);
apiBaseInput.addEventListener("change", setApiBase);
clientIdInput.addEventListener("change", () => localStorage.setItem("day12-client-id", clientIdInput.value.trim() || "anonymous"));
messageInput.addEventListener("input", updateCharCount);
messageInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    $("#chat-form").requestSubmit();
  }
});

$("#toggle-token").addEventListener("click", () => {
  const visible = tokenInput.type === "text";
  tokenInput.type = visible ? "password" : "text";
  $("#toggle-token").textContent = visible ? "Hiện" : "Ẩn";
  $("#toggle-token").setAttribute("aria-label", visible ? "Hiện token" : "Ẩn token");
});

$("#clear-chat").addEventListener("click", () => {
  messageList.querySelectorAll(".message").forEach((message) => message.remove());
  welcomeCard.hidden = false;
  clearError();
  messageInput.focus();
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.prompt;
    updateCharCount();
    messageInput.focus();
  });
});

updateCharCount();
refreshHealth();
