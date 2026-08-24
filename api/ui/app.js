const modelSelect = document.getElementById('modelSelect');
const thinkSelect = document.getElementById('thinkSelect');
const newChatButton = document.getElementById('newChatButton');
const statusBar = document.getElementById('statusBar');
const runPanel = document.getElementById('runPanel');
const runState = document.getElementById('runState');
const runElapsed = document.getElementById('runElapsed');
const runCpu = document.getElementById('runCpu');
const runRam = document.getElementById('runRam');
const runModelRam = document.getElementById('runModelRam');
const messagesEl = document.getElementById('messages');
const emptyState = document.getElementById('emptyState');
const metricsEl = document.getElementById('metrics');
const chatForm = document.getElementById('chatForm');
const promptInput = document.getElementById('promptInput');
const sendButton = document.getElementById('sendButton');
const stopButton = document.getElementById('stopButton');

const history = [];
let busy = false;
let currentController = null;
let runStartedAt = 0;
let timerId = null;
let resourcePollId = null;
let lastResources = null;
let modelCapabilities = new Map();

function secondsFromNs(value) {
  if (!value) return 0;
  return Number(value) / 1e9;
}

function fmtSeconds(value) {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(value < 10 ? 2 : 1)} s`;
}

function fmtGb(value, digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)} GB` : '—';
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

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  modelSelect.disabled = value;
  thinkSelect.disabled = value || !supportsThinking(modelSelect.value);
  newChatButton.disabled = value;
  stopButton.hidden = !value;
  promptInput.disabled = false;
}

function supportsThinking(model) {
  return Boolean(modelCapabilities.get(model)?.thinking);
}

function syncThinkingControl() {
  const supported = supportsThinking(modelSelect.value);
  if (!supported) thinkSelect.value = 'false';
  thinkSelect.disabled = busy || !supported;
  thinkSelect.title = supported ? 'Enable or disable model reasoning mode' : 'This model does not expose a thinking mode';
}

function currentThinkEnabled() {
  return supportsThinking(modelSelect.value) && thinkSelect.value === 'true';
}

function updateLiveResources(data) {
  if (!data) return;
  lastResources = data;
  const cpu = Number(data.system_cpu_percent);
  const ramUsed = Number(data.system_ram_used_gb);
  const ramTotal = Number(data.system_ram_total_gb);
  const modelRam = Number(data.model?.rss_gb);

  runCpu.textContent = Number.isFinite(cpu) ? `CPU ${cpu.toFixed(0)}%` : 'CPU —';
  runRam.textContent = Number.isFinite(ramUsed) && Number.isFinite(ramTotal)
    ? `RAM ${ramUsed.toFixed(1)}/${ramTotal.toFixed(1)} GB`
    : 'RAM —';
  runModelRam.textContent = Number.isFinite(modelRam) ? `model RAM ${modelRam.toFixed(2)} GB` : 'model RAM —';
}

async function pollResources() {
  if (!busy) return;
  try {
    const response = await fetch('/resources', { cache: 'no-store' });
    if (response.ok) updateLiveResources(await response.json());
  } catch (_) {}
}

function startRunPanel() {
  runStartedAt = performance.now();
  runPanel.hidden = false;
  runState.textContent = currentThinkEnabled() ? 'Thinking / generating' : 'Generating';
  runElapsed.textContent = '0.0 s';
  runCpu.textContent = 'CPU —';
  runRam.textContent = 'RAM —';
  runModelRam.textContent = 'model RAM —';

  timerId = window.setInterval(() => {
    const elapsed = (performance.now() - runStartedAt) / 1000;
    runElapsed.textContent = fmtSeconds(elapsed);
  }, 100);

  pollResources();
  resourcePollId = window.setInterval(pollResources, 1000);
}

function stopRunPanel(finalState = null) {
  if (timerId) window.clearInterval(timerId);
  if (resourcePollId) window.clearInterval(resourcePollId);
  timerId = null;
  resourcePollId = null;

  const elapsed = runStartedAt ? (performance.now() - runStartedAt) / 1000 : 0;
  runElapsed.textContent = fmtSeconds(elapsed);
  if (finalState) runState.textContent = finalState;
  return elapsed;
}

function updateMetrics(data, wallSeconds, thinkEnabled) {
  const load = secondsFromNs(data.load_duration);
  const total = secondsFromNs(data.total_duration);
  const prompt = secondsFromNs(data.prompt_eval_duration);
  const generation = secondsFromNs(data.eval_duration);
  const evalCount = Number(data.eval_count || 0);
  const promptCount = Number(data.prompt_eval_count || 0);
  const tps = generation > 0 ? evalCount / generation : 0;
  const resources = data.resources || {};
  const start = resources.start || {};
  const end = resources.end || {};
  const startRam = Number(start.system_ram_used_gb);
  const endRam = Number(end.system_ram_used_gb);
  const cpuWork = Number(resources.model_cpu_work_seconds);
  const peakModelRam = Number(resources.model_ram_peak_gb);

  document.getElementById('metricModel').textContent = `model ${data.model || modelSelect.value}`;
  document.getElementById('metricMode').textContent = `thinking ${thinkEnabled ? 'on' : 'off'}`;
  document.getElementById('metricWall').textContent = `elapsed ${fmtSeconds(wallSeconds)}`;
  document.getElementById('metricTotal').textContent = `model total ${fmtSeconds(total)}`;
  document.getElementById('metricLoad').textContent = `load ${fmtSeconds(load)}`;
  document.getElementById('metricPrompt').textContent = `prompt ${fmtSeconds(prompt)} · ${promptCount} tok`;
  document.getElementById('metricGeneration').textContent = `generation ${fmtSeconds(generation)}`;
  document.getElementById('metricTokens').textContent = `output ${evalCount} tok`;
  document.getElementById('metricTps').textContent = tps ? `${tps.toFixed(2)} tok/s` : 'tok/s —';
  document.getElementById('metricCpuWork').textContent = Number.isFinite(cpuWork)
    ? `CPU work ${cpuWork.toFixed(1)} core-s`
    : 'CPU work —';
  document.getElementById('metricRam').textContent = Number.isFinite(startRam) && Number.isFinite(endRam)
    ? `system RAM ${startRam.toFixed(1)} → ${endRam.toFixed(1)} GB`
    : 'system RAM —';
  document.getElementById('metricModelRam').textContent = Number.isFinite(peakModelRam)
    ? `model RAM peak ${peakModelRam.toFixed(2)} GB`
    : 'model RAM peak —';
  metricsEl.hidden = false;
}

async function loadModels() {
  try {
    const response = await fetch('/models', { cache: 'no-store' });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    const configured = (data.configured || []).filter(item => item.installed && item.role !== 'embedding');

    modelCapabilities = new Map(configured.map(item => [item.name, item]));
    modelSelect.replaceChildren();
    for (const model of configured) {
      const option = document.createElement('option');
      option.value = model.name;
      option.textContent = `${model.name} · ${model.role}`;
      if (model.name === data.default) option.selected = true;
      modelSelect.appendChild(option);
    }

    if (!configured.length) throw new Error('No chat models are available');
    syncThinkingControl();
    setStatus(`Local · ${configured.length} chat models available`, 'ok');
  } catch (error) {
    setStatus(`Model check failed: ${error.message}`, 'error');
  }
}

function handleStreamEvent(event, assistantNode, state) {
  if (!event || typeof event !== 'object') return;

  if (event.type === 'start') {
    if (event.resources) updateLiveResources(event.resources);
    return;
  }

  if (event.type === 'thinking') {
    state.thinkingSeen = true;
    if (!state.answer) {
      assistantNode.textContent = 'Thinking…';
      assistantNode.classList.add('pending');
    }
    runState.textContent = 'Thinking';
    return;
  }

  if (event.type === 'token') {
    state.answer += event.text || '';
    assistantNode.textContent = state.answer || 'Generating…';
    assistantNode.classList.remove('pending');
    runState.textContent = 'Generating';
    assistantNode.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return;
  }

  if (event.type === 'done') {
    state.done = event;
    return;
  }

  if (event.type === 'error') {
    throw new Error(event.detail || 'Streaming request failed');
  }
}

async function consumeNdjson(response, assistantNode, state) {
  if (!response.body) throw new Error('Streaming is not supported by this browser');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;
      handleStreamEvent(JSON.parse(line), assistantNode, state);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) handleStreamEvent(JSON.parse(buffer), assistantNode, state);
}

async function sendMessage(prompt) {
  if (busy || !prompt.trim()) return;

  const previousHistory = history.slice();
  const selectedModel = modelSelect.value;
  const thinkEnabled = currentThinkEnabled();
  const controller = new AbortController();
  currentController = controller;
  setBusy(true);

  addMessage('user', prompt);
  const assistantNode = addMessage('assistant', thinkEnabled ? 'Thinking…' : 'Starting…', true);
  const state = { answer: '', thinkingSeen: false, done: null };
  startRunPanel();
  setStatus(`Local · ${selectedModel} · running`, 'ok');

  try {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        prompt,
        model: selectedModel,
        history: previousHistory,
        temperature: 0.2,
        keep_alive: '30m',
        think: thinkEnabled
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

    await consumeNdjson(response, assistantNode, state);

    if (!state.done) throw new Error('Stream ended before the model reported completion');

    const answer = state.answer || '(empty response)';
    assistantNode.textContent = answer;
    assistantNode.classList.remove('pending');
    history.push({ role: 'user', content: prompt });
    history.push({ role: 'assistant', content: answer });

    const wallSeconds = stopRunPanel('Done');
    updateMetrics(state.done, wallSeconds, thinkEnabled);
    setStatus(`Local · ${selectedModel} · done in ${fmtSeconds(wallSeconds)}`, 'ok');
  } catch (error) {
    if (error.name === 'AbortError') {
      const wallSeconds = stopRunPanel('Stopped');
      if (!state.answer) {
        assistantNode.textContent = 'Stopped.';
      } else {
        assistantNode.textContent = `${state.answer}\n\n[stopped]`;
      }
      assistantNode.classList.remove('pending');
      setStatus(`Stopped after ${fmtSeconds(wallSeconds)}`);
    } else {
      stopRunPanel('Error');
      assistantNode.textContent = `Error: ${error.message}`;
      assistantNode.classList.remove('pending');
      assistantNode.classList.add('error');
      setStatus('Request failed', 'error');
    }
  } finally {
    currentController = null;
    setBusy(false);
    syncThinkingControl();
    promptInput.focus();
  }
}

chatForm.addEventListener('submit', event => {
  event.preventDefault();
  const prompt = promptInput.value.trim();
  if (!prompt || busy) return;
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

stopButton.addEventListener('click', () => {
  if (currentController) currentController.abort();
});

newChatButton.addEventListener('click', () => {
  history.length = 0;
  messagesEl.querySelectorAll('.message').forEach(node => node.remove());
  emptyState.hidden = false;
  metricsEl.hidden = true;
  runPanel.hidden = true;
  setStatus(`Local · ${modelSelect.value}`, 'ok');
  promptInput.focus();
});

modelSelect.addEventListener('change', () => {
  syncThinkingControl();
  setStatus(`Local · ${modelSelect.value}`, 'ok');
});

thinkSelect.addEventListener('change', () => {
  setStatus(`Local · ${modelSelect.value} · thinking ${currentThinkEnabled() ? 'on' : 'off'}`, 'ok');
});

loadModels();
promptInput.focus();
