const modelSelect = document.getElementById('modelSelect');
const presetSelect = document.getElementById('presetSelect');
const thinkSelect = document.getElementById('thinkSelect');
const promptsButton = document.getElementById('promptsButton');
const newChatButton = document.getElementById('newChatButton');
const statusBar = document.getElementById('statusBar');
const runPanel = document.getElementById('runPanel');
const runState = document.getElementById('runState');
const runElapsed = document.getElementById('runElapsed');
const runCpu = document.getElementById('runCpu');
const runRam = document.getElementById('runRam');
const runModelRam = document.getElementById('runModelRam');

const promptEditor = document.getElementById('promptEditor');
const closePromptsButton = document.getElementById('closePromptsButton');
const useSystemPrompt = document.getElementById('useSystemPrompt');
const useRuntimePrompt = document.getElementById('useRuntimePrompt');
const systemPromptInput = document.getElementById('systemPromptInput');
const runtimePromptInput = document.getElementById('runtimePromptInput');
const savePromptsButton = document.getElementById('savePromptsButton');
const resetPromptsButton = document.getElementById('resetPromptsButton');
const promptSaveState = document.getElementById('promptSaveState');

const messagesEl = document.getElementById('messages');
const emptyState = document.getElementById('emptyState');
const reasoningState = document.getElementById('reasoningState');
const reasoningContent = document.getElementById('reasoningContent');
const metricsEl = document.getElementById('metrics');
const chatForm = document.getElementById('chatForm');
const promptInput = document.getElementById('promptInput');
const sendButton = document.getElementById('sendButton');
const stopButton = document.getElementById('stopButton');

const chatModeButton = document.getElementById('chatModeButton');
const visionModeButton = document.getElementById('visionModeButton');
const chatWorkspace = document.getElementById('chatWorkspace');
const composerFooter = document.getElementById('composerFooter');
const visionPanel = document.getElementById('visionPanel');
const visionModelSelect = document.getElementById('visionModelSelect');
const imageDropZone = document.getElementById('imageDropZone');
const imageInput = document.getElementById('imageInput');
const imageMeta = document.getElementById('imageMeta');
const imagePreview = document.getElementById('imagePreview');
const visionPromptInput = document.getElementById('visionPromptInput');
const analyzeImageButton = document.getElementById('analyzeImageButton');
const copyVisionJsonButton = document.getElementById('copyVisionJsonButton');
const visionJsonOutput = document.getElementById('visionJsonOutput');

const history = [];
let busy = false;
let currentController = null;
let runStartedAt = 0;
let timerId = null;
let resourcePollId = null;
let modelCapabilities = new Map();
let promptConfigLoaded = false;
let activeMode = 'chat';
let selectedImageFile = null;
let imagePreviewUrl = null;
let hasChatMetrics = false;

function secondsFromNs(value) {
  if (!value) return 0;
  return Number(value) / 1e9;
}

function fmtSeconds(value) {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(value < 10 ? 2 : 1)} s`;
}

function scrollChatToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setReasoning(text, state = null, placeholder = false) {
  reasoningContent.textContent = text;
  reasoningContent.dataset.placeholder = placeholder ? 'true' : 'false';
  if (state) reasoningState.textContent = state;
  reasoningContent.scrollTop = reasoningContent.scrollHeight;
}

function appendReasoning(text) {
  if (!text) return;
  if (reasoningContent.dataset.placeholder === 'true') {
    reasoningContent.textContent = '';
    reasoningContent.dataset.placeholder = 'false';
  }
  reasoningContent.textContent += text;
  reasoningContent.scrollTop = reasoningContent.scrollHeight;
}

function resetReasoningForRun(thinkEnabled) {
  if (thinkEnabled) {
    setReasoning('Waiting for reasoning…', 'waiting', true);
  } else {
    setReasoning('Thinking is disabled for this request.', 'off', true);
  }
}

function addMessage(role, text, pending = false) {
  emptyState.hidden = true;
  const node = document.createElement('div');
  node.className = `message ${role}${pending ? ' pending' : ''}`;
  node.textContent = text;
  messagesEl.appendChild(node);
  scrollChatToBottom();
  return node;
}

function setStatus(text, kind = '') {
  statusBar.textContent = text;
  statusBar.className = `status-bar ${kind}`.trim();
}

function setPromptSaveState(text, kind = '') {
  promptSaveState.textContent = text;
  promptSaveState.className = `prompt-save-state ${kind}`.trim();
}

function supportsThinking(model) {
  return Boolean(modelCapabilities.get(model)?.thinking);
}

function currentThinkEnabled() {
  return supportsThinking(modelSelect.value) && thinkSelect.value === 'true';
}

function activePreset() {
  return presetSelect.value || 'general';
}

function presetLabel() {
  const option = presetSelect.options[presetSelect.selectedIndex];
  return option ? option.textContent : activePreset();
}

function syncThinkingControl() {
  const supported = supportsThinking(modelSelect.value);
  if (!supported) thinkSelect.value = 'false';
  thinkSelect.disabled = busy || !supported;
  thinkSelect.title = supported
    ? 'Enable or disable model reasoning mode'
    : 'This model does not expose a thinking mode';

  if (!busy) {
    if (!supported || thinkSelect.value !== 'true') {
      setReasoning('Enable Thinking to show model reasoning here.', 'off', true);
    } else {
      setReasoning('Reasoning will appear here on the next request.', 'ready', true);
    }
  }
}

function syncPresetControl() {
  const isCustom = activePreset() === 'custom';
  const isRaw = activePreset() === 'raw';

  useSystemPrompt.disabled = busy || !isCustom;
  useRuntimePrompt.disabled = busy || !isCustom;

  if (isRaw) {
    promptsButton.title = 'Raw mode adds no aib system/runtime prompts. Prompts opens the Custom preset editor.';
  } else if (isCustom) {
    promptsButton.title = 'Edit the active Custom prompt preset';
  } else {
    promptsButton.title = 'Edit the Custom preset. General uses repository defaults.';
  }
}

function syncVisionAnalyzeButton() {
  analyzeImageButton.disabled = busy || !selectedImageFile || !visionModelSelect.value;
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  modelSelect.disabled = value;
  presetSelect.disabled = value;
  thinkSelect.disabled = value || !supportsThinking(modelSelect.value);
  promptsButton.disabled = value;
  newChatButton.disabled = value;
  savePromptsButton.disabled = value;
  resetPromptsButton.disabled = value;
  chatModeButton.disabled = value;
  visionModeButton.disabled = value;
  visionModelSelect.disabled = value;
  imageInput.disabled = value;
  visionPromptInput.disabled = value;
  copyVisionJsonButton.disabled = value;
  stopButton.hidden = !value;
  promptInput.disabled = false;
  syncVisionAnalyzeButton();
  syncPresetControl();
}

function updateLiveResources(data) {
  if (!data) return;
  const cpu = Number(data.system_cpu_percent);
  const ramUsed = Number(data.system_ram_used_gb);
  const ramTotal = Number(data.system_ram_total_gb);
  const modelRam = Number(data.model?.rss_gb);

  runCpu.textContent = Number.isFinite(cpu) ? `CPU ${cpu.toFixed(0)}%` : 'CPU —';
  runRam.textContent = Number.isFinite(ramUsed) && Number.isFinite(ramTotal)
    ? `RAM ${ramUsed.toFixed(1)}/${ramTotal.toFixed(1)} GB`
    : 'RAM —';
  runModelRam.textContent = Number.isFinite(modelRam)
    ? `model RAM ${modelRam.toFixed(2)} GB`
    : 'model RAM —';
}

async function pollResources() {
  if (!busy) return;
  try {
    const response = await fetch('/resources', { cache: 'no-store' });
    if (response.ok) updateLiveResources(await response.json());
  } catch (_) {}
}

function startRunPanel(label = null) {
  runStartedAt = performance.now();
  runPanel.hidden = false;
  runState.textContent = label || (currentThinkEnabled() ? 'Thinking / generating' : 'Generating');
  runElapsed.textContent = '0.0 s';
  runCpu.textContent = 'CPU —';
  runRam.textContent = 'RAM —';
  runModelRam.textContent = 'model RAM —';

  timerId = window.setInterval(() => {
    runElapsed.textContent = fmtSeconds((performance.now() - runStartedAt) / 1000);
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
  const promptDuration = secondsFromNs(data.prompt_eval_duration);
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
  const layers = data.prompt_layers || {};
  const layerNames = [];
  if (layers.use_system_prompt) layerNames.push('system');
  if (layers.use_runtime_prompt) layerNames.push('runtime');
  if (layers.request_system_extra) layerNames.push('request-extra');
  const preset = layers.preset || activePreset();

  document.getElementById('metricModel').textContent = `model ${data.model || modelSelect.value}`;
  document.getElementById('metricMode').textContent = `thinking ${thinkEnabled ? 'on' : 'off'}`;
  document.getElementById('metricPrompts').textContent = preset === 'raw'
    ? 'preset raw · aib prompts off'
    : `preset ${preset} · ${layerNames.length ? layerNames.join('+') : 'aib prompts off'}`;
  document.getElementById('metricWall').textContent = `elapsed ${fmtSeconds(wallSeconds)}`;
  document.getElementById('metricTotal').textContent = `model total ${fmtSeconds(total)}`;
  document.getElementById('metricLoad').textContent = `load ${fmtSeconds(load)}`;
  document.getElementById('metricPrompt').textContent = `prompt ${fmtSeconds(promptDuration)} · ${promptCount} tok`;
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
  hasChatMetrics = true;
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

    const visionModels = configured.filter(item => (item.modalities || []).includes('image'));
    visionModelSelect.replaceChildren();
    for (const model of visionModels) {
      const option = document.createElement('option');
      option.value = model.name;
      option.textContent = `${model.name} · ${model.role}`;
      if (model.name === data.vision_default) option.selected = true;
      visionModelSelect.appendChild(option);
    }
    if (!visionModels.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No installed vision model';
      visionModelSelect.appendChild(option);
    }

    syncThinkingControl();
    syncVisionAnalyzeButton();
    setStatus(`Local · ${configured.length} chat models · ${visionModels.length} vision models · ${presetLabel()}`, 'ok');
  } catch (error) {
    setStatus(`Model check failed: ${error.message}`, 'error');
  }
}

async function loadPromptConfig() {
  try {
    const model = encodeURIComponent(modelSelect.value || 'qwen3:4b');
    const response = await fetch(`/prompt-config?model=${model}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    systemPromptInput.value = data.current?.system_prompt || '';
    runtimePromptInput.value = data.current?.runtime_prompt || '';
    promptConfigLoaded = true;
    setPromptSaveState(
      data.local_override_exists
        ? 'Custom preset loaded from local/prompt-config.json.'
        : 'Custom currently matches General repository defaults.',
      'ok'
    );
  } catch (error) {
    promptConfigLoaded = false;
    setPromptSaveState(`Prompt config error: ${error.message}`, 'error');
  }
}

async function savePromptConfig() {
  setPromptSaveState('Saving…');
  try {
    const response = await fetch('/prompt-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_prompt: systemPromptInput.value,
        runtime_prompt: runtimePromptInput.value
      })
    });
    if (!response.ok) throw new Error(await response.text());
    promptConfigLoaded = true;
    setPromptSaveState('Custom preset saved to local/prompt-config.json.', 'ok');
  } catch (error) {
    setPromptSaveState(`Save failed: ${error.message}`, 'error');
  }
}

async function resetPromptConfig() {
  setPromptSaveState('Resetting…');
  try {
    const response = await fetch('/prompt-config', { method: 'DELETE' });
    if (!response.ok) throw new Error(await response.text());
    await loadPromptConfig();
    setPromptSaveState('Custom reset to General repository prompts.', 'ok');
  } catch (error) {
    setPromptSaveState(`Reset failed: ${error.message}`, 'error');
  }
}

function promptOverridesForRequest() {
  const preset = activePreset();

  if (preset === 'raw') {
    return {
      prompt_preset: 'raw',
      use_system_prompt: false,
      use_runtime_prompt: false,
      system_prompt: null,
      runtime_prompt: null
    };
  }

  if (preset === 'general') {
    return {
      prompt_preset: 'general',
      use_system_prompt: true,
      use_runtime_prompt: true,
      system_prompt: null,
      runtime_prompt: null
    };
  }

  if (!promptConfigLoaded) {
    return {
      prompt_preset: 'custom',
      use_system_prompt: useSystemPrompt.checked,
      use_runtime_prompt: useRuntimePrompt.checked,
      system_prompt: null,
      runtime_prompt: null
    };
  }

  return {
    prompt_preset: 'custom',
    use_system_prompt: useSystemPrompt.checked,
    use_runtime_prompt: useRuntimePrompt.checked,
    system_prompt: systemPromptInput.value,
    runtime_prompt: runtimePromptInput.value
  };
}

function handleStreamEvent(event, assistantNode, state) {
  if (!event || typeof event !== 'object') return;

  if (event.type === 'start') {
    state.promptLayers = event.prompt_layers || null;
    if (event.resources) updateLiveResources(event.resources);
    return;
  }

  if (event.type === 'thinking') {
    state.thinkingSeen = true;
    state.reasoning += event.text || '';
    appendReasoning(event.text || '');
    reasoningState.textContent = 'thinking';
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
    scrollChatToBottom();
    return;
  }

  if (event.type === 'done') {
    state.done = event;
    if (state.thinkingSeen) reasoningState.textContent = 'done';
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

function setMode(mode) {
  activeMode = mode === 'vision' ? 'vision' : 'chat';
  const vision = activeMode === 'vision';

  chatModeButton.classList.toggle('active', !vision);
  visionModeButton.classList.toggle('active', vision);
  chatWorkspace.hidden = vision;
  composerFooter.hidden = vision;
  visionPanel.hidden = !vision;
  metricsEl.hidden = vision || !hasChatMetrics;

  if (vision) {
    promptEditor.hidden = true;
    setStatus(
      visionModelSelect.value
        ? `Local · ${visionModelSelect.value} · Image → JSON`
        : 'No installed vision model',
      visionModelSelect.value ? 'ok' : 'error'
    );
  } else {
    setStatus(`Local · ${modelSelect.value} · ${activePreset()}`, 'ok');
    promptInput.focus();
  }
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function clearImagePreviewUrl() {
  if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
  imagePreviewUrl = null;
}

function setVisionFile(file) {
  if (!file) {
    selectedImageFile = null;
    clearImagePreviewUrl();
    imagePreview.hidden = true;
    imagePreview.removeAttribute('src');
    imageMeta.textContent = 'Файл не выбран.';
    syncVisionAnalyzeButton();
    return;
  }

  const allowed = ['image/jpeg', 'image/png', 'image/webp'];
  if (!allowed.includes(file.type)) {
    setStatus('Unsupported image type. Use JPEG, PNG or WebP.', 'error');
    imageInput.value = '';
    setVisionFile(null);
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    setStatus('Image is too large. Maximum size is 15 MB.', 'error');
    imageInput.value = '';
    setVisionFile(null);
    return;
  }

  selectedImageFile = file;
  clearImagePreviewUrl();
  imagePreviewUrl = URL.createObjectURL(file);
  imagePreview.src = imagePreviewUrl;
  imagePreview.hidden = false;
  imageMeta.textContent = `${file.name} · ${file.type} · ${formatBytes(file.size)}`;
  visionJsonOutput.textContent = '{}';
  setStatus(`Ready · ${visionModelSelect.value || 'vision model'} · ${file.name}`, 'ok');
  syncVisionAnalyzeButton();
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read the image file'));
    reader.onload = () => {
      const value = String(reader.result || '');
      const comma = value.indexOf(',');
      if (comma < 0) {
        reject(new Error('Could not encode the image'));
        return;
      }
      resolve(value.slice(comma + 1));
    };
    reader.readAsDataURL(file);
  });
}

async function analyzeImage() {
  if (busy || !selectedImageFile || !visionModelSelect.value) return;

  const file = selectedImageFile;
  const selectedModel = visionModelSelect.value;
  const controller = new AbortController();
  currentController = controller;
  setBusy(true);
  startRunPanel('Analyzing image');
  setStatus(`Local · ${selectedModel} · analyzing ${file.name}`, 'ok');
  visionJsonOutput.textContent = '{\n  "status": "analyzing"\n}';

  try {
    const imageBase64 = await fileToBase64(file);
    const response = await fetch('/vision/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        image_base64: imageBase64,
        mime_type: file.type,
        filename: file.name,
        model: selectedModel,
        prompt: visionPromptInput.value.trim() || null,
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
    visionJsonOutput.textContent = JSON.stringify(data.analysis || {}, null, 2);
    const elapsed = stopRunPanel('Done');
    setStatus(`Local · ${selectedModel} · image analyzed in ${fmtSeconds(elapsed)}`, 'ok');
  } catch (error) {
    if (error.name === 'AbortError') {
      stopRunPanel('Stopped');
      visionJsonOutput.textContent = JSON.stringify({ error: 'stopped' }, null, 2);
      setStatus('Vision analysis stopped');
    } else {
      stopRunPanel('Error');
      visionJsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
      setStatus(`Vision analysis failed: ${error.message}`, 'error');
    }
  } finally {
    currentController = null;
    setBusy(false);
  }
}

async function sendMessage(prompt) {
  if (busy || !prompt.trim()) return;

  const previousHistory = history.slice();
  const selectedModel = modelSelect.value;
  const selectedPreset = activePreset();
  const thinkingSupported = supportsThinking(selectedModel);
  const thinkEnabled = currentThinkEnabled();
  const controller = new AbortController();
  currentController = controller;
  setBusy(true);
  resetReasoningForRun(thinkEnabled);

  addMessage('user', prompt);
  const assistantNode = addMessage('assistant', thinkEnabled ? 'Thinking…' : 'Starting…', true);
  const state = { answer: '', reasoning: '', thinkingSeen: false, done: null, promptLayers: null };
  startRunPanel();
  setStatus(`Local · ${selectedModel} · ${selectedPreset} · running`, 'ok');

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
        think: thinkingSupported ? thinkEnabled : null,
        ...promptOverridesForRequest()
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
    if (thinkEnabled && !state.thinkingSeen) {
      setReasoning('The model did not return a separate reasoning stream for this request.', 'none', true);
    }
    setStatus(`Local · ${selectedModel} · ${selectedPreset} · done in ${fmtSeconds(wallSeconds)}`, 'ok');
    scrollChatToBottom();
  } catch (error) {
    if (error.name === 'AbortError') {
      const wallSeconds = stopRunPanel('Stopped');
      assistantNode.textContent = state.answer ? `${state.answer}\n\n[stopped]` : 'Stopped.';
      assistantNode.classList.remove('pending');
      if (thinkEnabled) reasoningState.textContent = 'stopped';
      setStatus(`Stopped after ${fmtSeconds(wallSeconds)}`);
    } else {
      stopRunPanel('Error');
      assistantNode.textContent = `Error: ${error.message}`;
      assistantNode.classList.remove('pending');
      assistantNode.classList.add('error');
      if (thinkEnabled) reasoningState.textContent = 'error';
      setStatus('Request failed', 'error');
    }
    scrollChatToBottom();
  } finally {
    currentController = null;
    setBusy(false);
    syncThinkingControl();
    syncPresetControl();
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
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 160)}px`;
});

stopButton.addEventListener('click', () => {
  if (currentController) currentController.abort();
});

promptsButton.addEventListener('click', () => {
  promptEditor.hidden = !promptEditor.hidden;
});

closePromptsButton.addEventListener('click', () => {
  promptEditor.hidden = true;
});

savePromptsButton.addEventListener('click', savePromptConfig);
resetPromptsButton.addEventListener('click', resetPromptConfig);

newChatButton.addEventListener('click', () => {
  history.length = 0;
  messagesEl.querySelectorAll('.message').forEach(node => node.remove());
  emptyState.hidden = false;
  hasChatMetrics = false;
  metricsEl.hidden = true;
  runPanel.hidden = true;
  syncThinkingControl();
  syncPresetControl();
  setStatus(`Local · ${modelSelect.value} · ${activePreset()}`, 'ok');
  promptInput.focus();
});

modelSelect.addEventListener('change', () => {
  syncThinkingControl();
  setStatus(`Local · ${modelSelect.value} · ${activePreset()}`, 'ok');
});

presetSelect.addEventListener('change', () => {
  syncPresetControl();
  const preset = activePreset();
  if (preset === 'raw') {
    setStatus(`Local · ${modelSelect.value} · raw · no aib prompts`, 'ok');
  } else {
    setStatus(`Local · ${modelSelect.value} · ${preset}`, 'ok');
  }
});

thinkSelect.addEventListener('change', () => {
  syncThinkingControl();
  setStatus(
    `Local · ${modelSelect.value} · ${activePreset()} · thinking ${currentThinkEnabled() ? 'on' : 'off'}`,
    'ok'
  );
});

chatModeButton.addEventListener('click', () => setMode('chat'));
visionModeButton.addEventListener('click', () => setMode('vision'));

visionModelSelect.addEventListener('change', () => {
  syncVisionAnalyzeButton();
  if (activeMode === 'vision') {
    setStatus(
      visionModelSelect.value
        ? `Local · ${visionModelSelect.value} · Image → JSON`
        : 'No installed vision model',
      visionModelSelect.value ? 'ok' : 'error'
    );
  }
});

imageInput.addEventListener('change', () => {
  setVisionFile(imageInput.files?.[0] || null);
});

imageDropZone.addEventListener('dragover', event => {
  event.preventDefault();
  if (!busy) imageDropZone.classList.add('dragover');
});

imageDropZone.addEventListener('dragleave', () => {
  imageDropZone.classList.remove('dragover');
});

imageDropZone.addEventListener('drop', event => {
  event.preventDefault();
  imageDropZone.classList.remove('dragover');
  if (busy) return;
  const file = event.dataTransfer?.files?.[0] || null;
  if (file) setVisionFile(file);
});

analyzeImageButton.addEventListener('click', analyzeImage);

copyVisionJsonButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(visionJsonOutput.textContent || '{}');
    setStatus('JSON copied to clipboard.', 'ok');
  } catch (error) {
    setStatus(`Could not copy JSON: ${error.message}`, 'error');
  }
});

syncPresetControl();
Promise.all([loadModels(), loadPromptConfig()]).finally(() => {
  syncPresetControl();
  syncVisionAnalyzeButton();
  setMode('chat');
});
