/* nugget web frontend */

let currentSessionId = null;

// ── API helpers ────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) throw new Error(`${method} ${path} → ${resp.status}`);
  return resp.json();
}

// ── Session list ───────────────────────────────────────────────────────────

async function loadSessions() {
  const sessions = await api('GET', '/api/sessions');
  renderSessionList(sessions);
}

function renderSessionList(sessions) {
  const list = document.getElementById('session-list');
  list.innerHTML = '';
  if (!sessions.length) {
    list.innerHTML = '<div style="padding:12px 14px;color:var(--dim);font-size:12px">No sessions yet</div>';
    return;
  }
  for (const s of sessions) {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.id === currentSessionId ? ' active' : '');
    item.dataset.id = s.id;
    item.innerHTML = `
      <div class="session-id">${s.id}</div>
      <div class="session-meta">${s.updated_at.slice(0, 16).replace('T', ' ')} · ${s.turns} turn${s.turns !== 1 ? 's' : ''}</div>
      <div class="session-preview">${escHtml(s.preview)}</div>
    `;
    item.addEventListener('click', () => openSession(s.id));
    list.appendChild(item);
  }
}

function setActiveSession(id) {
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });
}

// ── Open session ───────────────────────────────────────────────────────────

async function openSession(id) {
  currentSessionId = id;
  setActiveSession(id);
  const data = await api('GET', `/api/sessions/${id}`);
  renderMessages(data.messages);
}

function renderMessages(messages) {
  const container = document.getElementById('messages');
  container.innerHTML = '';
  for (const msg of messages) {
    if (msg.role === 'user') {
      appendUserMessage(msg.content);
    } else if (msg.role === 'assistant') {
      const bubble = appendAssistantBubble();
      if (msg.thinking) {
        appendThinkingBlock(bubble, msg.thinking);
      }
      for (const tc of (msg.tool_calls || [])) {
        appendToolCall(bubble, tc.name, tc.args);
        appendToolResult(bubble, tc.name, tc.result);
      }
      if (msg.content) {
        bubble.querySelector('.message-content').textContent = msg.content;
      }
    }
  }
  scrollToBottom();
}

// ── Message builders ───────────────────────────────────────────────────────

function appendUserMessage(text) {
  const container = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = 'message user';
  el.innerHTML = `<div class="message-role">you</div><div class="message-content">${escHtml(text)}</div>`;
  container.appendChild(el);
  scrollToBottom();
  return el;
}

function appendAssistantBubble() {
  const container = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-role">assistant</div><div class="message-content"></div>`;
  container.appendChild(el);
  scrollToBottom();
  return el;
}

function appendThinkingBlock(bubble, text) {
  const block = document.createElement('div');
  block.className = 'thinking-block';
  block.innerHTML = `
    <div class="thinking-toggle">▶ thinking</div>
    <div class="thinking-content">${escHtml(text)}</div>
  `;
  block.querySelector('.thinking-toggle').addEventListener('click', () => {
    block.classList.toggle('open');
    block.querySelector('.thinking-toggle').textContent =
      (block.classList.contains('open') ? '▼' : '▶') + ' thinking';
  });
  bubble.appendChild(block);
  return block;
}

function appendToolCall(bubble, name, args) {
  const block = document.createElement('div');
  block.className = 'tool-block';
  block.innerHTML = `
    <div class="tool-header tool-call-header">→ <span class="tool-name">${escHtml(name)}</span></div>
    <div class="tool-body">${escHtml(JSON.stringify(args, null, 2))}</div>
  `;
  bubble.appendChild(block);
  return block;
}

function appendToolResult(bubble, name, result) {
  const block = document.createElement('div');
  block.className = 'tool-block';
  block.innerHTML = `
    <div class="tool-header tool-result-header">← <span class="tool-name">${escHtml(name)}</span></div>
    <div class="tool-body">${escHtml(typeof result === 'string' ? result : JSON.stringify(result, null, 2))}</div>
  `;
  bubble.appendChild(block);
  return block;
}

function appendToolDenied(bubble, name, reason) {
  const block = document.createElement('div');
  block.className = 'tool-block';
  block.innerHTML = `
    <div class="tool-header tool-denied-header">✗ <span class="tool-name">${escHtml(name)}</span> denied</div>
    <div class="tool-body">${escHtml(reason)}</div>
  `;
  bubble.appendChild(block);
  return block;
}

// ── Send message ───────────────────────────────────────────────────────────

async function sendMessage() {
  if (!currentSessionId) return;
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = '';
  document.getElementById('send-btn').disabled = true;

  appendUserMessage(text);
  const bubble = appendAssistantBubble();
  const contentEl = bubble.querySelector('.message-content');
  let thinkingBlock = null;
  let pendingThinking = null;

  try {
    const resp = await fetch(`/api/sessions/${currentSessionId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // Split on double-newline (SSE event boundary)
      const parts = buf.split('\n\n');
      buf = parts.pop() ?? '';
      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }
          handleEvent(event, bubble, contentEl, { thinkingBlock, set: v => thinkingBlock = v });
        }
      }
    }
  } catch (err) {
    contentEl.textContent = `Error: ${err.message}`;
    contentEl.style.color = 'var(--red)';
  }

  document.getElementById('send-btn').disabled = false;
  await loadSessions();
}

function handleEvent(event, bubble, contentEl, thinkingRef) {
  if (event.type === 'token') {
    contentEl.textContent += event.text;
    scrollToBottom();
  } else if (event.type === 'thinking') {
    if (!thinkingRef.thinkingBlock) {
      thinkingRef.set(appendThinkingBlock(bubble, event.text));
    } else {
      thinkingRef.thinkingBlock.querySelector('.thinking-content').textContent = event.text;
    }
    bubble.insertBefore(thinkingRef.thinkingBlock, contentEl);
    scrollToBottom();
  } else if (event.type === 'tool_call') {
    appendToolCall(bubble, event.name, event.args);
    scrollToBottom();
  } else if (event.type === 'tool_result') {
    appendToolResult(bubble, event.name, event.result);
    scrollToBottom();
  } else if (event.type === 'tool_denied') {
    appendToolDenied(bubble, event.name, event.reason);
    scrollToBottom();
  } else if (event.type === 'error') {
    contentEl.textContent = `Error: ${event.message}`;
    contentEl.style.color = 'var(--red)';
  }
}

// ── New session ────────────────────────────────────────────────────────────

async function createNewSession() {
  const data = await api('POST', '/api/sessions');
  currentSessionId = data.id;
  document.getElementById('messages').innerHTML = '';
  await loadSessions();
  setActiveSession(currentSessionId);
}

// ── Utilities ──────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function scrollToBottom() {
  const el = document.getElementById('messages');
  el.scrollTop = el.scrollHeight;
}

// ── Auto-grow textarea ────────────────────────────────────────────────────

function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send-btn');

  input.addEventListener('input', () => autoGrow(input));
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener('click', sendMessage);
  document.getElementById('new-session-btn').addEventListener('click', createNewSession);

  await loadSessions();

  // Open most recent session automatically
  const sessions = await api('GET', '/api/sessions');
  if (sessions.length) {
    openSession(sessions[0].id);
  }
});
