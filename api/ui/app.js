const modelSelect = document.getElementById('modelSelect');
const newChatButton = document.getElementById('newChatButton');
const statusBar = document.getElementById('statusBar');
const messagesEl = document.getElementById('messages');
const emptyState = document.getElementById('emptyState');
const metricsEl = document.getElementById('metrics');
const chatForm = document.getElementById('chatForm');
const promptInput = document.getElementById('promptInput');
const sendButton = document.getElementById('sendButton');

const history = [];
let busy = false;

function secondsFromNs(value) {
  if (!value) return 0;
  return Number(value) / 1e9;
}

function fmtSeconds(value) {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(value < 10 ? 2 : 1)} s`;
}

function addMessage(role, text, pending = false) {
  emptyState.hidden = true;
  const node = document.createElement('div');
  node.className = `message ${role}${pending ? ' pending' : ''}`;
  node.textContent = text;
  messagesEl.appendChild(node);
  node.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return node;
}

function setStatus(text, kind = '') {
  statusBar.textContent = text;
  statusBar.className = `status-bar ${kind}`.trim();
}

function updateMetrics(data, wallSeconds) {
  const load = secondsFromNs(data.load_duration);
  const generation = secondsFromNs(data.eval_duration);
  const evalCount = Number(data.eval_count || 0);
  const tps = generation > 0 ? evalCount / generation : 0;
  const memory = data.memory || {};

  document.getElementById('metricModel').textContent = `model ${data.model || modelSelect.value}`;
  document.getElementById('metricWall').textContent = `wall ${fmtSeconds(wallSeconds)}`;
  document.getElementById('metricLoad').textContent = `load ${fmtSeconds(load)}`;
  document.getElementById('metricGeneration').textContent = `generation ${fmtSeconds(generation)}`;
  document.getElementById('metricTps').textContent = tps ? `${tps.toFixed(2)} tok/s` : 'tok/s —';
  document.getElementById('metricRam').textContent = memory.used_gb != null
    ? `RAM ${memory.used_gb.toFixed(1)}/${memory.total_gb.toFixed(1)} GB (${memory.percent.toFixed(0)}%)`
    : 'RAM —';
  metricsEl.hidden = false;
}

async function loadModels() {
  try {
    const response = await fetch('/models');
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    const configured = (data.configured || []).filter(item => item.installed && item.role !== 'embedding');

    modelSelect.replaceChildren();
    for (const model of configured) {
      const option = document.createElement('option');
      option.value = model.name;
      option.textContent = `${model.name} · ${model.role}`;
      if (model.name === data.default) option.selected = true;
      modelSelect.appendChild(option);
    }

    if (!configured.length) {
      throw new Error('No chat models are available');
    }
    setStatus(`Local · ${configured.length} chat models available`, 'ok');
  } catch (error) {
    setStatus(`Model check failed: ${error.message}`, 'error');
  }
}

async function sendMessage(prompt) {
  if (busy || !prompt.trim()) return;
  busy = true;
  sendButton.disabled = true;
  promptInput.disabled = true;

  const previousHistory = history.slice();
  addMessage('user', prompt);
  history.push({ role: 'user', content: prompt });
  const assistantNode = addMessage('assistant', 'Thinking…', true);

  const started = performance.now();
  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model: modelSelect.value,
        history: previousHistory,
        temperature: 0.2,
        keep_alive: '30m'
      })
    });

    if (!response.ok) {
      let detail = await response.text();
      try {
        const parsed = JSON.parse(detail);
        detail = parsed.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const data = await response.json();
    const answer = data.response || '(empty response)';
    assistantNode.textContent = answer;
    assistantNode.classList.remove('pending');
    history.push({ role: 'assistant', content: answer });
    updateMetrics(data, (performance.now() - started) / 1000);
    setStatus(`Local · ${modelSelect.value}`, 'ok');
  } catch (error) {
    assistantNode.textContent = `Error: ${error.message}`;
    assistantNode.classList.remove('pending');
    assistantNode.classList.add('error');
    history.pop();
    setStatus('Request failed', 'error');
  } finally {
    busy = false;
    sendButton.disabled = false;
    promptInput.disabled = false;
    promptInput.focus();
  }
}

chatForm.addEventListener('submit', event => {
  event.preventDefault();
  const prompt = promptInput.value.trim();
  if (!prompt) return;
  promptInput.value = '';
  promptInput.style.height = 'auto';
  sendMessage(prompt);
});

promptInput.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

promptInput.addEventListener('input', () => {
  promptInput.style.height = 'auto';
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 180)}px`;
});

newChatButton.addEventListener('click', () => {
  history.length = 0;
  messagesEl.querySelectorAll('.message').forEach(node => node.remove());
  emptyState.hidden = false;
  metricsEl.hidden = true;
  promptInput.focus();
});

modelSelect.addEventListener('change', () => {
  setStatus(`Local · ${modelSelect.value}`, 'ok');
});

loadModels();
promptInput.focus();
