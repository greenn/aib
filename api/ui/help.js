const modelSelect = document.getElementById('modelSelect');
const commandText = document.getElementById('commandText');
const refreshButton = document.getElementById('refreshButton');
const outputTitle = document.getElementById('outputTitle');
const outputStatus = document.getElementById('outputStatus');
const outputText = document.getElementById('outputText');
const modelsSummary = document.getElementById('modelsSummary');

let modelData = [];
let currentParts = { full: '', system: '', template: '', parameter: '', adapter: '' };
let currentPart = 'full';

const partLabels = {
  full: 'Full Modelfile',
  system: 'SYSTEM',
  template: 'TEMPLATE',
  parameter: 'PARAMETER',
  adapter: 'ADAPTER'
};

function setOutputStatus(text) {
  outputStatus.textContent = text;
}

function sectionForDirective(modelfile, directive) {
  if (!modelfile) return '';
  const lines = modelfile.split(/\r?\n/);
  const wanted = directive.toUpperCase();
  const chunks = [];

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed.toUpperCase().startsWith(`${wanted} `) && trimmed.toUpperCase() !== wanted) continue;

    const collected = [line];
    const after = trimmed.slice(wanted.length).trimStart();
    const triple = after.startsWith('"""');
    const closesSameLine = triple && after.slice(3).includes('"""');

    if (triple && !closesSameLine) {
      for (let j = i + 1; j < lines.length; j += 1) {
        collected.push(lines[j]);
        i = j;
        if (lines[j].includes('"""')) break;
      }
    }
    chunks.push(collected.join('\n'));
  }
  return chunks.join('\n\n');
}

function normalizeParts(data) {
  const modelfile = data.modelfile || '';
  return {
    full: modelfile,
    system: data.system || sectionForDirective(modelfile, 'SYSTEM'),
    template: data.template || sectionForDirective(modelfile, 'TEMPLATE'),
    parameter: data.parameters || sectionForDirective(modelfile, 'PARAMETER'),
    adapter: sectionForDirective(modelfile, 'ADAPTER')
  };
}

function renderPart() {
  outputTitle.textContent = partLabels[currentPart];
  const value = currentParts[currentPart] || '';
  outputText.textContent = value || `No ${partLabels[currentPart]} section is present for this model.`;

  document.querySelectorAll('.part-tab').forEach(button => {
    const part = button.dataset.part;
    button.classList.toggle('active', part === currentPart);
    button.classList.toggle('empty', part !== 'full' && !currentParts[part]);
  });
}

function ollamaShowUrls() {
  const host = window.location.hostname || '127.0.0.1';
  const hosts = [host, '127.0.0.1', 'localhost'];
  return [...new Set(hosts)].map(item => `http://${item}:11434/api/show`);
}

async function fetchOllamaShow(model) {
  let lastError = null;
  for (const url of ollamaShowUrls()) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, verbose: true })
      });
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error('Unable to reach Ollama');
}

async function loadModelfile() {
  const model = modelSelect.value;
  if (!model) return;

  commandText.textContent = `ollama show --modelfile ${model}`;
  refreshButton.disabled = true;
  setOutputStatus('Loading…');
  outputText.textContent = 'Loading…';

  try {
    const data = await fetchOllamaShow(model);
    currentParts = normalizeParts(data);
    renderPart();
    setOutputStatus('live from local Ollama');
  } catch (error) {
    currentParts = { full: '', system: '', template: '', parameter: '', adapter: '' };
    renderPart();
    outputText.textContent = `Could not read the local Ollama Modelfile.\n\n${error.message}\n\nYou can still run this command manually:\n${commandText.textContent}`;
    setOutputStatus('Ollama request failed');
  } finally {
    refreshButton.disabled = false;
  }
}

function renderModelsSummary() {
  modelsSummary.replaceChildren();
  if (!modelData.length) {
    modelsSummary.textContent = 'No configured local models found.';
    return;
  }

  for (const model of modelData) {
    const row = document.createElement('div');
    row.className = 'model-row';

    const name = document.createElement('div');
    name.className = 'model-name';
    name.textContent = model.name;

    const meta = document.createElement('div');
    meta.className = 'model-meta';
    const bits = [model.developer, model.parameters, model.ollama_size, model.role, model.description].filter(Boolean);
    meta.textContent = bits.join(' · ');

    row.append(name, meta);
    modelsSummary.appendChild(row);
  }
}

async function loadModels() {
  const response = await fetch('/models', { cache: 'no-store' });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  modelData = (data.configured || []).filter(model => model.installed);

  modelSelect.replaceChildren();
  for (const model of modelData) {
    const option = document.createElement('option');
    option.value = model.name;
    option.textContent = `${model.name} · ${model.role}`;
    if (model.name === data.default) option.selected = true;
    modelSelect.appendChild(option);
  }
  renderModelsSummary();
}

function showHelpSection(name) {
  document.querySelectorAll('.help-section').forEach(section => {
    section.hidden = section.id !== `section-${name}`;
  });
  document.querySelectorAll('.menu-item').forEach(button => {
    button.classList.toggle('active', button.dataset.section === name);
  });
}

document.querySelectorAll('.menu-item').forEach(button => {
  button.addEventListener('click', () => showHelpSection(button.dataset.section));
});

document.querySelectorAll('.part-tab').forEach(button => {
  button.addEventListener('click', () => {
    currentPart = button.dataset.part;
    renderPart();
  });
});

modelSelect.addEventListener('change', loadModelfile);
refreshButton.addEventListener('click', loadModelfile);

loadModels()
  .then(loadModelfile)
  .catch(error => {
    setOutputStatus('Model list failed');
    outputText.textContent = `Could not load local model list.\n\n${error.message}`;
  });
