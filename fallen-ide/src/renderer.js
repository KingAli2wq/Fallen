import * as monaco from 'monaco-editor';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import 'monaco-editor/esm/vs/editor/editor.all.js';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import JsonWorker   from 'monaco-editor/esm/vs/language/json/json.worker?worker';
import CssWorker    from 'monaco-editor/esm/vs/language/css/css.worker?worker';
import HtmlWorker   from 'monaco-editor/esm/vs/language/html/html.worker?worker';
import TsWorker     from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

self.MonacoEnvironment = {
  getWorker(_, label) {
    if (label === 'json')                                         return new JsonWorker();
    if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker();
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker();
    if (label === 'typescript' || label === 'javascript')        return new TsWorker();
    return new EditorWorker();
  }
};

const state = {
  rootPath: null,
  tabs: [],
  activeTab: null,
  editor: null,
  terminals: [],
  activeTermId: null,
  terminalSeq: 0,
  expandedDirs: new Set(),
};

// ── Custom dialogs (window.prompt/confirm/alert blocked by Monaco Editor) ────
function _dialog(msg, mode, def) {
  return new Promise(resolve => {
    const ov  = document.getElementById('dlg-overlay');
    const inp = document.getElementById('dlg-input');
    const ok  = document.getElementById('dlg-ok');
    const can = document.getElementById('dlg-cancel');
    document.getElementById('dlg-msg').textContent = msg;
    const isPrompt = mode === 'prompt';
    inp.style.display = isPrompt ? 'block' : 'none';
    can.style.display = mode === 'alert'  ? 'none' : '';
    if (isPrompt) inp.value = def ?? '';
    ov.style.display = 'flex';
    requestAnimationFrame(() => { (isPrompt ? inp : ok).focus(); if (isPrompt) inp.select(); });
    const done = v => { ov.style.display = 'none'; ok.onclick = can.onclick = inp.onkeydown = null; resolve(v); };
    ok.onclick  = () => done(isPrompt ? inp.value || null : true);
    can.onclick = () => done(null);
    if (isPrompt) inp.onkeydown = e => { if (e.key === 'Enter') ok.click(); if (e.key === 'Escape') can.click(); };
  });
}
const ask   = (msg, def) => _dialog(msg, 'prompt', def);
const tell  = msg         => _dialog(msg, 'alert');
const yesno = msg         => _dialog(msg, 'confirm').then(Boolean);

window.addEventListener('DOMContentLoaded', async () => {
  initEditor();
  initResizeHandle();
  Extensions.init();
  await initTerminal();
  checkAI();
});

function initResizeHandle() {
  const handle = document.getElementById('resize-handle');
  const panel  = document.getElementById('bottom-panel');
  if (!handle || !panel) return;

  let startY = 0, startH = 0;

  handle.addEventListener('mousedown', e => {
    e.preventDefault();
    startY = e.clientY;
    startH = panel.offsetHeight;
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp, { once: true });
  });

  function onMove(e) {
    const delta = startY - e.clientY;
    const maxH  = Math.floor(window.innerHeight * 0.7);
    const newH  = Math.max(120, Math.min(maxH, startH + delta));
    panel.style.height = newH + 'px';
    const t = getActiveTerminal();
    if (t && !t.closed) t.fitAddon.fit();
  }

  function onUp() {
    document.removeEventListener('mousemove', onMove);
    const t = getActiveTerminal();
    if (t && !t.closed) t.fitAddon.fit();
  }
}

function initEditor() {
  state.editor = monaco.editor.create(document.getElementById('monaco-editor'), {
    theme: 'vs-dark',
    automaticLayout: true,
    fontSize: 14,
    fontFamily: "'Cascadia Code', 'Consolas', monospace",
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    bracketPairColorization: { enabled: true },
  });
  state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => App.saveActive());
  state.editor.onDidChangeModelContent(() => {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (tab && !tab.modified) { tab.modified = true; renderTabs(); }
  });
  state.editor.onDidChangeCursorPosition(e => {
    const el = document.getElementById('status-pos');
    if (el) el.textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
  });
}

async function initTerminal() {
  await createTerminal(state.rootPath || null, { activate: true });
}

function getTerminal(id) {
  return state.terminals.find(t => t.id === id) || null;
}

function getActiveTerminal() {
  return getTerminal(state.activeTermId);
}

async function createTerminal(cwd = state.rootPath || null, options = {}) {
  const id = await api.termCreate(cwd);
  const label = options.label || `Terminal ${++state.terminalSeq}`;
  const container = document.getElementById('xterm-container');

  const pane = document.createElement('div');
  pane.className = 'terminal-pane';
  pane.dataset.termId = String(id);

  const mount = document.createElement('div');
  mount.className = 'terminal-mount';
  pane.appendChild(mount);
  container.appendChild(pane);

  const term = new Terminal({
    theme: { background: '#1e1e1e', foreground: '#d4d4d4', cursor: '#d4d4d4' },
    fontFamily: "'Cascadia Code', 'Consolas', monospace",
    fontSize: 13,
    convertEol: true,
    scrollback: 5000,
    scrollSensitivity: 3,
    fastScrollSensitivity: 10,
    fastScrollModifier: 'shift',
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(mount);

  // Intercept wheel events before xterm and call scrollLines() directly.
  // xterm's native wheel handling can silently fail in Electron's sandboxed renderer,
  // so we take ownership of scroll here and stop propagation so it doesn't double-fire.
  mount.addEventListener('wheel', e => {
    e.preventDefault();
    e.stopPropagation();
    const lines = Math.sign(e.deltaY) * Math.max(1, Math.ceil(Math.abs(e.deltaY) / 40));
    term.scrollLines(lines);
  }, { capture: true, passive: false });

  // Ctrl+Shift+C copies selection; Ctrl+Shift+V pastes from clipboard
  term.attachCustomKeyEventHandler(e => {
    if (e.ctrlKey && e.shiftKey && e.type === 'keydown') {
      if (e.key === 'C') { const s = term.getSelection(); if (s) navigator.clipboard.writeText(s); return false; }
      if (e.key === 'V') { navigator.clipboard.readText().then(t => term.paste(t)); return false; }
    }
    return true;
  });
  // Right-click: copy selection if any, otherwise paste from clipboard
  mount.addEventListener('contextmenu', e => {
    e.preventDefault();
    const sel = term.getSelection();
    if (sel) navigator.clipboard.writeText(sel);
    else navigator.clipboard.readText().then(t => term.paste(t));
  });

  const terminal = {
    id,
    label,
    term,
    fitAddon,
    pane,
    mount,
    inputDisposable: null,
    resizeObserver: null,
    exited: false,
    closed: false,
    pendingEcho: null,
  };
  state.terminals.push(terminal);

  // Line-buffered input: we accumulate typed chars locally and only send to the
  // process on Enter (as a complete \r\n-terminated line).  This means backspace
  // works reliably — we erase from our buffer before the line is ever sent, so
  // Python's input() never sees raw \b bytes that would corrupt int() parsing.
  // Ctrl+C / Tab / escape sequences bypass buffering and go to the process directly.
  let lineBuffer = '';

  terminal.inputDisposable = term.onData(data => {
    let i = 0;
    while (i < data.length) {
      const ch   = data[i];
      const code = data.charCodeAt(i);

      if (code === 0x1b) {
        // Escape sequence (arrow keys, fn-keys): forward to process immediately
        let seq = ch; i++;
        if (i < data.length && (data[i] === '[' || data[i] === 'O')) {
          seq += data[i]; i++;
          while (i < data.length && (data.charCodeAt(i) < 0x40 || data.charCodeAt(i) > 0x7e)) { seq += data[i]; i++; }
          if (i < data.length) { seq += data[i]; i++; }
        } else if (i < data.length) { seq += data[i]; i++; }
        api.termWrite(id, seq);
        continue;
      }

      if (ch === '\r') {
        // Enter: send the buffered line with \r\n, echo newline locally
        term.write('\r\n');
        api.termWrite(id, lineBuffer + '\r\n');
        lineBuffer = '';
      } else if (ch === '\x7f' || ch === '\b') {
        // Backspace: erase from local buffer only — never sent to process
        if (lineBuffer.length > 0) {
          lineBuffer = lineBuffer.slice(0, -1);
          term.write('\b \b');
        }
      } else if (code >= 0x20 && code < 0x7f) {
        // Printable: buffer and echo immediately
        lineBuffer += ch;
        term.write(ch);
      } else {
        // Other control chars (Ctrl+C = \x03, Tab = \x09, Ctrl+D = \x04): send directly
        api.termWrite(id, ch);
      }
      i++;
    }
  });

  api.onTermData(id, d => {
    if (terminal.closed) return;
    if (d.includes('\r') || d.includes('\n')) lineBuffer = '';
    let out = d.replace(/\x7f/g, '');
    // PowerShell echoes the command we sent via stdin — strip it to avoid double display.
    // pendingEcho is cleared after the first chunk regardless of whether we found the echo,
    // so it can't affect subsequent unrelated output.
    if (terminal.pendingEcho) {
      const idx = out.indexOf(terminal.pendingEcho);
      if (idx !== -1) out = out.slice(0, idx) + out.slice(idx + terminal.pendingEcho.length);
      terminal.pendingEcho = null;
    }
    if (out) term.write(out, () => term.scrollToBottom());
    AI.captureOutput(d);
  });
  api.onTermExit(id, () => {
    if (terminal.closed) return;
    terminal.exited = true;
    term.write('\r\n\x1b[33m[Process exited]\x1b[0m\r\n');
    renderTerminalTabs();
  });

  terminal.resizeObserver = new ResizeObserver(() => {
    if (terminal.closed || state.activeTermId !== id || pane.offsetParent === null) return;
    fitAddon.fit();
  });
  terminal.resizeObserver.observe(pane);

  renderTerminalTabs();
  if (options.activate !== false) {
    activateTerminal(id, { fit: true });
  }
  return terminal;
}

function renderTerminalTabs() {
  const bar = document.getElementById('terminal-tabs');
  if (!bar) return;

  bar.innerHTML = '';
  if (!state.terminals.length) {
    const empty = document.createElement('div');
    empty.className = 'terminal-tabs-empty';
    empty.textContent = 'No terminals open';
    bar.appendChild(empty);
    return;
  }

  for (const terminal of state.terminals) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'terminal-tab' + (terminal.id === state.activeTermId ? ' active' : '') + (terminal.exited ? ' exited' : '');
    tab.innerHTML = `
      <span class="terminal-tab-name">${escHtml(terminal.label)}</span>
      <span class="terminal-tab-close" aria-hidden="true">×</span>
    `;

    tab.addEventListener('click', (event) => {
      if (event.target.closest('.terminal-tab-close')) {
        event.stopPropagation();
        closeTerminal(terminal.id);
        return;
      }
      activateTerminal(terminal.id);
    });

    bar.appendChild(tab);
  }
}

function activateTerminal(id, options = {}) {
  const terminal = getTerminal(id);
  if (!terminal) return;

  state.activeTermId = id;
  for (const entry of state.terminals) {
    entry.pane.classList.toggle('active', entry.id === id);
    entry.pane.style.display = entry.id === id ? 'flex' : 'none';
  }
  renderTerminalTabs();

  if (options.fit !== false) {
    requestAnimationFrame(() => {
      if (state.activeTermId !== id || terminal.closed || terminal.pane.offsetParent === null) return;
      terminal.fitAddon.fit();
      terminal.term.focus();
    });
  }
}

function destroyTerminal(terminal, { killProcess = true } = {}) {
  if (!terminal || terminal.closed) return;
  terminal.closed = true;
  api.removeTermListeners?.(terminal.id);
  if (killProcess) api.termKill(terminal.id);
  terminal.inputDisposable?.dispose?.();
  terminal.resizeObserver?.disconnect?.();
  terminal.term.dispose();
  terminal.pane.remove();
}

function closeTerminal(id) {
  const index = state.terminals.findIndex(t => t.id === id);
  if (index === -1) return;

  const terminal = state.terminals[index];
  const wasActive = state.activeTermId === id;
  state.terminals.splice(index, 1);
  destroyTerminal(terminal, { killProcess: true });

  if (wasActive) {
    const next = state.terminals[index] || state.terminals[index - 1] || null;
    state.activeTermId = null;
    if (next) activateTerminal(next.id);
    else renderTerminalTabs();
  } else {
    renderTerminalTabs();
  }
}

async function newTerminal() {
  await createTerminal(state.rootPath || null, { activate: true });
}

async function checkAI() {
  const el = document.getElementById('ai-status');
  try {
    const result = await api.aiCheck();
    const ok = typeof result === 'object' ? result.ok : !!result;
    if (typeof result === 'object' && result.contextWindow) {
      AI.setContextWindow(result.contextWindow);
    }
    el.textContent = ok ? 'AI: Connected' : 'AI: Offline';
    el.style.color = ok ? '#4ec9b0' : '#f44747';
    if (ok) AI.populateModelPicker();
  } catch {
    el.textContent = 'AI: Offline';
    el.style.color = '#f44747';
  }
  setTimeout(checkAI, 30000);
}

// ── App ───────────────────────────────────────────────────────────────────────
window.App = {
  async openFolder() {
    const folderPath = await api.openFolder();
    if (!folderPath) return;
    state.rootPath = folderPath;
    document.getElementById('folder-name').textContent = folderPath.split(/[\\/]/).pop();
    await renderTree(folderPath, document.getElementById('file-tree'), 0);
    for (const terminal of [...state.terminals]) {
      destroyTerminal(terminal, { killProcess: true });
    }
    state.terminals = [];
    state.activeTermId = null;
    document.getElementById('xterm-container').innerHTML = '';
    renderTerminalTabs();
    await createTerminal(folderPath, { activate: true });
  },

  async newFile() {
    const filePath = await api.newFile(state.rootPath);
    if (!filePath) return;
    await openFile(filePath);
    if (state.rootPath) await renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  },

  async newFolder() {
    const base = state.rootPath;
    if (!base) { await tell('Open a folder first.'); return; }
    const name = await ask('New folder name:');
    if (!name) return;
    const sep = base.includes('\\') ? '\\' : '/';
    await api.mkdir(base + sep + name);
    await renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  },

  async saveActive() {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (!tab) return;
    const ok = await api.writeFile(tab.path, tab.model.getValue());
    if (ok) { tab.modified = false; renderTabs(); }
  },

  async runActive() {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (!tab) return;
    await App.saveActive();
    let cmd = await api.getRunCommand(tab.path);
    if (!cmd) {
      cmd = await ask('No runner for this file type. Enter command ({file} = path):', '"{file}"');
      if (!cmd) return;
      cmd = cmd.replace('{file}', tab.path);
    }
    runInTerminal(cmd);
  },

  async installPackage() {
    const pkg = await ask('Package name to install:');
    if (!pkg) return;
    let cmd = '';
    if (state.rootPath) {
      const entries = await api.readDir(state.rootPath);
      const names = new Set(entries.map(e => e.name));
      if (names.has('package.json'))                               cmd = `npm install ${pkg}`;
      else if (names.has('requirements.txt') || names.has('setup.py') || names.has('pyproject.toml')) cmd = `pip install ${pkg}`;
      else if (names.has('Cargo.toml'))                           cmd = `cargo add ${pkg}`;
      else if (names.has('go.mod'))                               cmd = `go get ${pkg}`;
      else if (names.has('Gemfile'))                              cmd = `gem install ${pkg}`;
      else if (names.has('pom.xml'))                              cmd = `mvn dependency:get -Dartifact=${pkg}`;
    }
    if (!cmd) {
      const type = await ask('Choose installer (npm / pip / cargo / go / gem):', 'pip');
      if (!type) return;
      const map = { npm: `npm install ${pkg}`, pip: `pip install ${pkg}`, cargo: `cargo add ${pkg}`, go: `go get ${pkg}`, gem: `gem install ${pkg}` };
      cmd = map[type.trim()] || `${type.trim()} install ${pkg}`;
    }
    switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
    runInTerminal(cmd);
  },

  showView(view, btn) {
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    btn?.classList.add('active');
    document.getElementById('view-files').style.display = view === 'files' ? 'flex' : 'none';
    document.getElementById('view-exts').style.display  = view === 'exts'  ? 'flex' : 'none';
    if (view === 'exts') Extensions.render();
  },

  newTerminal: () => newTerminal(),

  toggleAI()     { document.getElementById('ai-panel').classList.toggle('hidden'); },
  toggleBottom() {
    const bp = document.getElementById('bottom-panel');
    const wasHidden = bp.style.display === 'none';
    bp.style.display = wasHidden ? '' : 'none';
    if (wasHidden) {
      requestAnimationFrame(() => {
        const t = getActiveTerminal();
        if (t && !t.closed) { t.fitAddon.fit(); t.term.focus(); }
      });
    }
  },

  toggleWordWrap() {
    const cur = state.editor.getOption(monaco.editor.EditorOption.wordWrap);
    const next = cur === 'on' ? 'off' : 'on';
    state.editor.updateOptions({ wordWrap: next });
    document.getElementById('btn-wordwrap')?.classList.toggle('active', next === 'on');
  },
};

// ── Tree ──────────────────────────────────────────────────────────────────────
async function renderTree(dirPath, container, depth) {
  const entries = await api.readDir(dirPath);
  container.innerHTML = '';
  for (const entry of entries) {
    const item = document.createElement('div');
    item.className = 'tree-item' + (entry.isDir ? ' tree-dir' : '');
    item.style.paddingLeft = (8 + depth * 14) + 'px';
    item.innerHTML = `<span class="icon">${entry.isDir ? '📁' : fileIcon(entry.name)}</span>${escHtml(entry.name)}`;
    item.title = entry.path;
    if (entry.isDir) {
      const children = document.createElement('div');
      children.style.display = state.expandedDirs.has(entry.path) ? 'block' : 'none';
      item.onclick = async e => {
        e.stopPropagation();
        if (state.expandedDirs.has(entry.path)) {
          state.expandedDirs.delete(entry.path); children.style.display = 'none';
          item.querySelector('.icon').textContent = '📁';
        } else {
          state.expandedDirs.add(entry.path); children.style.display = 'block';
          item.querySelector('.icon').textContent = '📂';
          await renderTree(entry.path, children, depth + 1);
        }
      };
      item.oncontextmenu = e => { e.preventDefault(); showFileMenu(e, entry.path, true); };
      container.appendChild(item);
      container.appendChild(children);
      if (state.expandedDirs.has(entry.path)) {
        item.querySelector('.icon').textContent = '📂';
        await renderTree(entry.path, children, depth + 1);
      }
    } else {
      item.onclick = () => openFile(entry.path);
      item.oncontextmenu = e => { e.preventDefault(); showFileMenu(e, entry.path, false); };
      container.appendChild(item);
    }
  }
}

function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const m = { py:'🐍',js:'🟨',ts:'🔷',jsx:'🟨',tsx:'🔷',html:'🌐',css:'🎨',json:'📋',md:'📝',txt:'📄',c:'⚙️',cpp:'⚙️',h:'📎',sh:'💲',ps1:'💲',rb:'💎',go:'🐹',rs:'🦀',java:'☕',png:'🖼️',jpg:'🖼️',gif:'🖼️',svg:'🎨',env:'🔑',toml:'📋',yaml:'📋',yml:'📋',dockerfile:'🐳',gitignore:'🔧' };
  return m[ext] || '📄';
}
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function showFileMenu(e, filePath, isDir) {
  document.getElementById('ctx-menu')?.remove();
  const menu = document.createElement('div');
  menu.id = 'ctx-menu';
  menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;background:#252526;border:1px solid #3c3c3c;border-radius:4px;z-index:9999;min-width:170px;box-shadow:0 4px 14px #0009`;
  const sep = () => { const d = document.createElement('div'); d.style.cssText = 'height:1px;background:#3c3c3c;margin:2px 0'; menu.appendChild(d); };
  const btn = (label, fn) => {
    const b = document.createElement('div');
    b.textContent = label;
    b.style.cssText = 'padding:6px 14px;cursor:pointer;font-size:12px;';
    b.onmouseenter = () => b.style.background = '#0078d4';
    b.onmouseleave = () => b.style.background = '';
    b.onclick = () => { menu.remove(); fn(); };
    menu.appendChild(b);
  };
  if (isDir) {
    const sep2 = filePath.includes('\\') ? '\\' : '/';
    btn('New File Here', async () => {
      const name = await ask('File name:');
      if (!name) return;
      const full = filePath + sep2 + name;
      await api.writeFile(full, '');
      if (state.rootPath) await renderTree(state.rootPath, document.getElementById('file-tree'), 0);
      openFile(full);
    });
    btn('New Folder Here', async () => {
      const name = await ask('Folder name:');
      if (!name) return;
      await api.mkdir(filePath + sep2 + name);
      if (state.rootPath) await renderTree(state.rootPath, document.getElementById('file-tree'), 0);
    });
    btn('Open in Terminal', () => runInTerminal(`cd "${filePath}"`));
    sep();
  }
  btn(`Rename ${isDir ? 'Folder' : 'File'}`, async () => {
    const oldName = filePath.split(/[\\/]/).pop();
    const n = await ask('Rename to:', oldName);
    if (!n || n === oldName) return;
    const newPath = await api.renameFile(filePath, n);
    if (!newPath) { await tell('Rename failed — the file may be open or locked.'); return; }
    if (state.rootPath) renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  });
  btn(`Delete ${isDir ? 'Folder' : 'File'}`, async () => {
    if (await yesno(`Delete "${filePath.split(/[\\/]/).pop()}"? This moves it to the Recycle Bin.`)) {
      await api.deleteFile(filePath);
      if (!isDir) closeTab(filePath);
      if (state.rootPath) renderTree(state.rootPath, document.getElementById('file-tree'), 0);
    }
  });
  if (!isDir) { sep(); btn('Ask AI about file', () => AI.askAboutFile(filePath)); }
  document.body.appendChild(menu);
  document.addEventListener('click', () => menu.remove(), { once: true });
}

// ── Editor / Tabs ─────────────────────────────────────────────────────────────
function detectLang(filePath) {
  const ext = filePath.split('.').pop().toLowerCase();
  const m = { py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',html:'html',css:'css',json:'json',md:'markdown',c:'c',cpp:'cpp',h:'c',sh:'shell',ps1:'powershell',rb:'ruby',go:'go',rs:'rust',java:'java',xml:'xml',yaml:'yaml',yml:'yaml',sql:'sql',toml:'ini',vue:'html',cs:'csharp',php:'php' };
  return m[ext] || 'plaintext';
}

async function openFile(filePath) {
  const existing = state.tabs.find(t => t.path === filePath);
  if (existing) { activateTab(filePath); return; }
  const content = await api.readFile(filePath);
  if (content === null) return;
  const model = monaco.editor.createModel(content, detectLang(filePath));
  state.tabs.push({ path: filePath, name: filePath.split(/[\\/]/).pop(), model, modified: false });
  renderTabs();
  activateTab(filePath);
  document.getElementById('editor-placeholder').style.display = 'none';
}

function renderTabs() {
  const bar = document.getElementById('tabs-list');
  bar.innerHTML = '';
  for (const tab of state.tabs) {
    const el = document.createElement('div');
    el.className = 'tab' + (tab.path === state.activeTab ? ' active' : '') + (tab.modified ? ' modified' : '');
    el.innerHTML = `<span class="tab-name">${escHtml(tab.name)}</span><span class="tab-close">×</span>`;
    el.addEventListener('click', e => {
      if (e.target.classList.contains('tab-close')) closeTab(tab.path);
      else activateTab(tab.path);
    });
    bar.appendChild(el);
  }
}

function activateTab(filePath) {
  const tab = state.tabs.find(t => t.path === filePath);
  if (!tab) return;
  state.activeTab = filePath;
  state.editor.setModel(tab.model);
  renderTabs();
  const langEl = document.getElementById('status-lang');
  if (langEl) langEl.textContent = detectLang(filePath).toUpperCase();
}

function closeTab(filePath) {
  const idx = state.tabs.findIndex(t => t.path === filePath);
  if (idx === -1) return;
  state.tabs[idx].model.dispose();
  state.tabs.splice(idx, 1);
  if (state.activeTab === filePath) {
    const next = state.tabs[idx] || state.tabs[idx - 1];
    if (next) activateTab(next.path);
    else { state.activeTab = null; state.editor.setModel(null); document.getElementById('editor-placeholder').style.display = 'flex'; }
  }
  renderTabs();
}

async function runInTerminal(cmd) {
  let terminal = getActiveTerminal();
  if (!terminal || terminal.exited || terminal.closed) {
    terminal = await createTerminal(state.rootPath || null, { activate: true });
  }

  const bottomPanel = document.getElementById('bottom-panel');
  if (bottomPanel.style.display === 'none') bottomPanel.style.display = '';
  switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
  AI.clearErrorBuffer();
  activateTerminal(terminal.id, { fit: true });

  const label = cmd.length > 72 ? cmd.slice(0, 69) + '…' : cmd;
  terminal.term.write(`\r\n\x1b[2m\x1b[36m▶ ${label}\x1b[0m\r\n`);
  terminal.pendingEcho = cmd;          // PowerShell will echo cmd back to stdout; suppress it
  api.termWrite(terminal.id, cmd + '\r\n');
}

window.switchPanel = (name, btn) => {
  document.querySelectorAll('.panel-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.panel-tab').forEach(el => el.classList.remove('active'));
  document.getElementById(`panel-${name}`)?.classList.add('active');
  btn?.classList.add('active');

  if (name === 'terminal') {
    const terminal = getActiveTerminal();
    if (terminal && !terminal.closed) {
      requestAnimationFrame(() => {
        if (state.activeTermId !== terminal.id || terminal.pane.offsetParent === null) return;
        terminal.fitAddon.fit();
        terminal.term.focus();
      });
    }
  }
};

// ── AI ────────────────────────────────────────────────────────────────────────
window.AI = (() => {
  let mode = 'ask';
  let chats = [];
  let activeChatId = 0;
  let chatCounter = 0;
  let contextWindow = 4096;
  let streamCounter = 0;
  let lastError = '';
  let errorBuffer = '';
  let pendingPlan = null;
  let running = false;
  let selectedModel = localStorage.getItem('fallen_model') || '';
  let aiTemperature = parseFloat(localStorage.getItem('fallen_temp') || '0.2');

  // ── mode selector ────────────────────────────────────────────────────────
  function setMode(m) {
    mode = m;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
  }

  // ── multi-chat ───────────────────────────────────────────────────────────
  function getActiveChat() { return chats.find(c => c.id === activeChatId) || null; }
  function getActiveSession() { return document.querySelector(`.chat-session[data-chat-id="${activeChatId}"]`); }

  function createChat(name) {
    const id = ++chatCounter;
    const chat = { id, name: name || `Chat ${id}`, history: [] };
    chats.push(chat);
    const el = document.createElement('div');
    el.className = 'chat-session';
    el.dataset.chatId = id;
    document.getElementById('ai-messages').appendChild(el);
    return chat;
  }

  function switchChat(id) {
    activeChatId = id;
    document.querySelectorAll('.chat-session').forEach(el => el.classList.toggle('active', el.dataset.chatId == id));
    renderChatTabs();
    updateContextMeter();
    const s = getActiveSession();
    if (s) s.scrollTop = s.scrollHeight;
  }

  function deleteChat(id) {
    if (chats.length <= 1) return;
    const idx = chats.findIndex(c => c.id === id);
    if (idx === -1) return;
    document.querySelector(`.chat-session[data-chat-id="${id}"]`)?.remove();
    chats.splice(idx, 1);
    if (activeChatId === id) switchChat((chats[idx] || chats[idx - 1]).id);
    else renderChatTabs();
  }

  function renderChatTabs() {
    const bar = document.getElementById('chat-tabs');
    if (!bar) return;
    bar.innerHTML = '';
    for (const chat of chats) {
      const tab = document.createElement('div');
      tab.className = 'chat-tab' + (chat.id === activeChatId ? ' active' : '');
      tab.innerHTML = `<span class="chat-tab-name">${escHtml(chat.name)}</span>${chats.length > 1 ? '<span class="chat-tab-close" title="Close">×</span>' : ''}`;
      tab.addEventListener('click', e => {
        if (e.target.classList.contains('chat-tab-close')) { e.stopPropagation(); deleteChat(chat.id); }
        else switchChat(chat.id);
      });
      bar.appendChild(tab);
    }
  }

  function newChat() {
    if (running) return;
    const chat = createChat();
    switchChat(chat.id);
  }

  // ── context meter ────────────────────────────────────────────────────────
  let exactTokensUsed = 0; // last real count from LM Studio (0 = not received yet)

  function countTokens(msgs) {
    return Math.ceil(msgs.reduce((a, m) => a + (m.content?.length || 0), 0) / 3.5);
  }

  function updateContextMeterExact(tokens) {
    exactTokensUsed = tokens;
    _renderContextMeter(tokens);
  }

  function updateContextMeter() {
    const chat = getActiveChat();
    if (!chat) return;
    // Prefer exact LM Studio count; fall back to char-based estimate
    const estimated = countTokens([{ role: 'system', content: buildSystemPrompt(mode) }, ...chat.history]);
    const used = exactTokensUsed > estimated ? exactTokensUsed : estimated;
    _renderContextMeter(used);
  }

  function _renderContextMeter(used) {
    const pct = Math.min(100, Math.round(used / contextWindow * 100));
    const fill = document.getElementById('context-bar-fill');
    const label = document.getElementById('context-label');
    if (!fill || !label) return;
    fill.style.width = pct + '%';
    fill.style.background = pct > 80 ? '#f44747' : pct > 60 ? '#ffb900' : '#4ec9b0';
    label.textContent = `${used.toLocaleString()} / ${contextWindow.toLocaleString()} tokens (${pct}%)`;
  }

  // ── error capture ────────────────────────────────────────────────────────
  function captureOutput(data) {
    errorBuffer += data;
    if (errorBuffer.length > 8000) errorBuffer = errorBuffer.slice(-8000);
    if (/error|exception|traceback|warning|failed|cannot|undefined is not|syntaxerror/i.test(data)) {
      lastError = errorBuffer.slice(-3000);
      document.getElementById('btn-explain-error')?.classList.remove('hidden');
      const termTab = document.querySelector('.panel-tab[data-panel="terminal"]');
      if (termTab) termTab.setAttribute('data-error', '1');
    }
  }

  function clearErrorBuffer() {
    errorBuffer = ''; lastError = '';
    document.getElementById('btn-explain-error')?.classList.add('hidden');
    const termTab = document.querySelector('.panel-tab[data-panel="terminal"]');
    if (termTab) termTab.removeAttribute('data-error');
  }

  // ── system prompt ────────────────────────────────────────────────────────
  function buildSystemPrompt(forceMode) {
    const m = forceMode || mode;
    const activeTab = state.tabs.find(t => t.path === state.activeTab);
    let ctx = 'You are an expert coding assistant inside Fallen IDE.\n';
    if (state.rootPath) ctx += `\nProject root: ${state.rootPath}\n`;
    if (activeTab) {
      ctx += `\nCurrent file: ${activeTab.path}\nLanguage: ${detectLang(activeTab.path)}\n`;
      const code = activeTab.model.getValue();
      if (code.length < 6000) ctx += `\nFile content:\n\`\`\`\n${code}\n\`\`\`\n`;
      else ctx += `\n(File is large — use READ tool to fetch it)\n`;
    }

    if (m === 'agent') {
      ctx += `
AGENT MODE — use these tools to interact with the file system and web:

<READ path="FILEPATH"/>               — read any file on disk
<LIST path="DIRPATH"/>                — list directory contents
<SEARCH_FILES root="DIR" pattern="NAME"/>  — find files by name
<GREP root="DIR" query="TEXT"/>       — search text inside files
<EDIT path="FILEPATH">
\`\`\`
complete file content
\`\`\`
</EDIT>                               — create a new file OR overwrite an existing one (creates parent dirs automatically)
<DELETE path="FILEPATH"/>             — delete a file or folder (moves to Recycle Bin — safe and recoverable)
<COPY src="SRCPATH" dest="DESTPATH"/> — copy a file to a new location
<RUN>shell command</RUN>              — execute in terminal
<WEB_SEARCH query="your query"/>      — search the web for docs, errors, or current info
<WEB_READ url="https://..."/>         — fetch and read a specific web page
<MKDIR path="DIRPATH"/>               — create a directory (including parents)
<MOVE src="SRCPATH" dest="DESTPATH"/> — move or rename a file/directory

Rules:
- READ an existing file before editing it; for NEW files just use EDIT directly — no READ needed
- Use LIST/SEARCH_FILES/GREP to explore the project before making changes
- EDIT blocks must contain the COMPLETE file content (never partial snippets)
- Use WEB_SEARCH to look up docs, APIs, or error solutions you don't know
- Use WEB_READ to read a page found via WEB_SEARCH
- Chain as many tool calls as needed — I will feed results back
- Explain what you did when finished`;
    } else if (m === 'plan') {
      ctx += `
PLAN MODE — before taking any action, output a plan block:

<PLAN>
1. First step
2. Second step
...
</PLAN>

Then STOP and wait. The user will approve before you execute anything.`;
    }
    return ctx;
  }

  // ── tool parsing — order-preserving ─────────────────────────────────────
  function parseTools(response) {
    const found = [];
    let m;
    const readRe      = /<READ\s+path="([^"]+)"\s*\/?>/gi;
    const listRe      = /<LIST\s+path="([^"]+)"\s*\/?>/gi;
    const searchRe    = /<SEARCH_FILES\s+root="([^"]+)"\s+pattern="([^"]+)"\s*\/?>/gi;
    const grepRe      = /<GREP\s+root="([^"]+)"\s+query="([^"]+)"\s*\/?>/gi;
    const webSearchRe = /<WEB_SEARCH\s+query="([^"]+)"\s*\/?>/gi;
    const webReadRe   = /<WEB_READ\s+url="([^"]+)"\s*\/?>/gi;
    while ((m = readRe.exec(response)))      found.push({ pos: m.index, tool: { type: 'READ',         path: m[1] } });
    while ((m = listRe.exec(response)))      found.push({ pos: m.index, tool: { type: 'LIST',         path: m[1] } });
    while ((m = searchRe.exec(response)))    found.push({ pos: m.index, tool: { type: 'SEARCH_FILES', root: m[1], pattern: m[2] } });
    while ((m = grepRe.exec(response)))      found.push({ pos: m.index, tool: { type: 'GREP',         root: m[1], query: m[2] } });
    while ((m = webSearchRe.exec(response))) found.push({ pos: m.index, tool: { type: 'WEB_SEARCH',   query: m[1] } });
    while ((m = webReadRe.exec(response)))   found.push({ pos: m.index, tool: { type: 'WEB_READ',     url: m[1] } });
    const mkdirRe  = /<MKDIR\s+path="([^"]+)"\s*\/?>/gi;
    const moveRe   = /<MOVE\s+src="([^"]+)"\s+dest="([^"]+)"\s*\/?>/gi;
    const deleteRe = /<DELETE\s+path="([^"]+)"\s*\/?>/gi;
    const copyRe   = /<COPY\s+src="([^"]+)"\s+dest="([^"]+)"\s*\/?>/gi;
    while ((m = mkdirRe.exec(response)))  found.push({ pos: m.index, tool: { type: 'MKDIR',  path: m[1] } });
    while ((m = moveRe.exec(response)))   found.push({ pos: m.index, tool: { type: 'MOVE',   src: m[1], dest: m[2] } });
    while ((m = deleteRe.exec(response))) found.push({ pos: m.index, tool: { type: 'DELETE', path: m[1] } });
    while ((m = copyRe.exec(response)))   found.push({ pos: m.index, tool: { type: 'COPY',   src: m[1], dest: m[2] } });
    return found.sort((a, b) => a.pos - b.pos).map(f => f.tool);
  }

  async function executeTools(tools) {
    // Deduplicate identical requests within one batch
    const seen = new Set();
    const deduped = tools.filter(t => {
      const key = `${t.type}:${t.path || t.src || t.root || ''}:${t.pattern || t.query || t.url || t.dest || ''}`;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });

    const settled = await Promise.allSettled(deduped.map(async t => {
      let result = '';
      if (t.type === 'READ') {
        const content = await api.readFile(t.path);
        result = content !== null
          ? `File: ${t.path}\n\`\`\`\n${content.slice(0, 12000)}\n\`\`\``
          : `Error: cannot read "${t.path}"`;
      } else if (t.type === 'LIST') {
        const entries = await api.readDir(t.path);
        result = `Directory: ${t.path}\n` +
          entries.map(e => `  ${e.isDir ? '[DIR] ' : '      '}${e.name}`).join('\n');
      } else if (t.type === 'SEARCH_FILES') {
        const files = await api.searchFiles(t.root, t.pattern);
        result = `Found ${files.length} file(s) matching "${t.pattern}":\n${files.join('\n') || '(none)'}`;
      } else if (t.type === 'GREP') {
        const matches = await api.grepFiles(t.root, t.query);
        result = `Found ${matches.length} match(es) for "${t.query}":\n` +
          (matches.length ? matches.map(r => `  ${r.file}:${r.line}: ${r.content}`).join('\n') : '(none)');
      } else if (t.type === 'WEB_SEARCH') {
        result = `Web search: "${t.query}"\n\n${await api.webSearch(t.query)}`;
      } else if (t.type === 'WEB_READ') {
        result = `Web page: ${t.url}\n\n${await api.webRead(t.url)}`;
      } else if (t.type === 'MKDIR') {
        const ok = await api.mkdir(t.path);
        result = ok ? `Created directory: ${t.path}` : `Error: could not create directory "${t.path}"`;
      } else if (t.type === 'MOVE') {
        const ok = await api.moveFile(t.src, t.dest);
        result = ok ? `Moved: ${t.src} → ${t.dest}` : `Error: could not move "${t.src}"`;
      } else if (t.type === 'DELETE') {
        const ok = await api.deleteFile(t.path);
        result = ok ? `Deleted (Recycle Bin): ${t.path}` : `Error: could not delete "${t.path}"`;
        if (ok && state.rootPath) renderTree(state.rootPath, document.getElementById('file-tree'), 0);
      } else if (t.type === 'COPY') {
        const ok = await api.copyFile(t.src, t.dest);
        result = ok ? `Copied: ${t.src} → ${t.dest}` : `Error: could not copy "${t.src}"`;
      }
      addSystemMessage(`Tool: ${t.type} ${t.path || t.src || t.root || t.query || t.url || ''}`);
      return `[${t.type}]\n${result}`;
    }));

    return settled.map((s, i) =>
      s.status === 'fulfilled' ? s.value : `[${deduped[i].type} error]: ${s.reason?.message || s.reason}`
    );
  }

  // ── apply EDIT/RUN blocks ────────────────────────────────────────────────
  async function applyEdits(response) {
    // \r?\n handles both Windows (\r\n) and Unix (\n) line endings from the model
    const editRe = /<EDIT\s+path="([^"]+)">\r?\n(?:```[^\r\n]*\r?\n)?([\s\S]*?)(?:```\r?\n)?\s*<\/EDIT>/gi;
    let m; let count = 0;
    while ((m = editRe.exec(response)) !== null) {
      const [, filePath, content] = m;
      const ok = await api.writeFile(filePath, content);
      if (!ok) { addSystemMessage(`Error: could not write "${filePath}"`); continue; }
      const tab = state.tabs.find(t => t.path === filePath);
      if (tab) {
        tab.model.setValue(content);
        tab.modified = false;
        if (state.activeTab === filePath) state.editor.setModel(tab.model);
        renderTabs();
      }
      count++;
      addSystemMessage(`Edited: ${filePath.split(/[\\/]/).pop()}`);
    }
    const runRe = /<RUN>([\s\S]*?)<\/RUN>/gi;
    while ((m = runRe.exec(response)) !== null) {
      addSystemMessage(`Running: ${m[1].trim()}`);
      runInTerminal(m[1].trim());
    }
    if (count > 0 && state.rootPath) renderTree(state.rootPath, document.getElementById('file-tree'), 0);
    return count;
  }

  // ── message rendering ────────────────────────────────────────────────────
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function renderInlineMarkup(text) {
    return escapeHtml(text)
      .replace(/`([^`]+)`/g, '<code class="ai-inline-code">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }

  function renderCodeBlock(language, code) {
    const normalized = String(code).replace(/\r\n/g, '\n').replace(/\n$/, '');
    const lineCount = normalized ? normalized.split('\n').length : 0;
    const label = language ? escapeHtml(language) : 'text';
    return `
      <details class="ai-code-block">
        <summary class="ai-code-summary">
          <span class="ai-code-toggle">▶</span>
          <span class="ai-code-label">${label}</span>
          <span class="ai-code-lines">${lineCount} line${lineCount === 1 ? '' : 's'}</span>
        </summary>
        <pre><code>${escapeHtml(code)}</code></pre>
      </details>
    `;
  }

  function renderMsg(content) {
    const source = String(content ?? '').replace(/\r\n/g, '\n');
    const fenceRegex = /```([\w-]*)\n([\s\S]*?)```/g;
    let html = '';
    let lastIndex = 0;
    let match;

    while ((match = fenceRegex.exec(source)) !== null) {
      html += renderInlineMarkup(source.slice(lastIndex, match.index));
      html += renderCodeBlock(match[1], match[2]);
      lastIndex = match.index + match[0].length;
    }

    const remaining = source.slice(lastIndex);
    // Detect an unclosed code fence (AI is still generating code during streaming)
    const partialIdx = remaining.indexOf('```');
    if (partialIdx !== -1) {
      html += renderInlineMarkup(remaining.slice(0, partialIdx));
      html += `<div class="ai-code-generating"><span class="ai-code-gen-spinner"></span> Generating code…</div>`;
    } else {
      html += renderInlineMarkup(remaining);
    }
    return html;
  }

  function addMessage(role, content) {
    const el = document.createElement('div');
    el.className = `ai-msg ${role}`;
    el.innerHTML = renderMsg(content);
    (getActiveSession() || document.getElementById('ai-messages')).appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
    return el;
  }

  function addSystemMessage(text) {
    const el = document.createElement('div');
    el.className = 'ai-msg system-msg';
    el.textContent = text;
    (getActiveSession() || document.getElementById('ai-messages')).appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
  }

  function setRunning(v) {
    running = v;
    const btn = document.getElementById('ai-send');
    if (!btn) return;
    if (v) {
      btn.textContent = '■ Stop';
      btn.style.background = '#c0392b';
      btn.onclick = stop;
      btn.disabled = false;
    } else {
      btn.textContent = 'Send';
      btn.style.background = '';
      btn.onclick = send;
      btn.disabled = false;
    }
  }

  function stop() {
    if (!running) return;
    api.aiAbort(streamCounter);
    api.removeAiListeners(streamCounter);
    running = false;
    setRunning(false);
    addSystemMessage('Generation stopped.');
  }

  // ── model picker ─────────────────────────────────────────────────────────
  async function populateModelPicker() {
    const select = document.getElementById('ai-model-select');
    if (!select) return;
    try {
      const models = await api.aiGetModels?.();
      if (!models?.length) return;
      const prev = select.value || selectedModel;
      select.innerHTML = '';
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m.length > 28 ? m.slice(0, 26) + '…' : m;
        select.appendChild(opt);
      }
      if (prev && models.includes(prev)) {
        select.value = prev;
        selectedModel = prev;
      } else {
        selectedModel = select.value = models[0];
      }
      localStorage.setItem('fallen_model', selectedModel);
    } catch {}
  }

  // ── stream one AI turn, returns full raw response ────────────────────────
  function streamTurn(messages) {
    return new Promise((resolve, reject) => {
      const id = ++streamCounter;
      let full = '';
      const msgEl = addMessage('assistant', '▋');
      api.onAiChunk(id, chunk => {
        full += chunk;
        msgEl.innerHTML = renderMsg(full) + '<span style="opacity:.5">▋</span>';
        const msgsEl = getActiveSession() || document.getElementById('ai-messages');
        if (msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 80) {
          msgsEl.scrollTop = msgsEl.scrollHeight;
        }
      });
      // Update context meter with real token counts from LM Studio if available
      if (api.onAiUsage) {
        api.onAiUsage(id, usage => {
          if (usage?.total_tokens) updateContextMeterExact(usage.total_tokens);
        });
      }
      api.onAiDone(id, err => {
        api.removeAiListeners(id);
        if (err) { msgEl.innerHTML = `<span style="color:#f44747">Error: ${err}</span>`; reject(new Error(err)); return; }
        msgEl.innerHTML = renderMsg(full);
        const copyBtn = document.createElement('button');
        copyBtn.className = 'ai-copy-btn';
        copyBtn.title = 'Copy response';
        copyBtn.textContent = '⎘';
        copyBtn.onclick = () => {
          navigator.clipboard.writeText(full.trim()).then(() => {
            copyBtn.textContent = '✓';
            setTimeout(() => { copyBtn.textContent = '⎘'; }, 1500);
          });
        };
        msgEl.appendChild(copyBtn);
        resolve(full);
      });
      api.aiStream(id, messages, { model: selectedModel || undefined, temperature: aiTemperature });
    });
  }

  // ── modes ────────────────────────────────────────────────────────────────
  async function runAskMode() {
    const chat = getActiveChat();
    if (chat.history.length > 30) chat.history = chat.history.slice(-28);
    const msgs = [{ role: 'system', content: buildSystemPrompt('ask') }, ...chat.history];
    const response = await streamTurn(msgs);
    chat.history.push({ role: 'assistant', content: response });
    updateContextMeter();
  }

  async function runAgentLoop(forceMode) {
    const chat = getActiveChat();
    if (chat.history.length > 30) chat.history = chat.history.slice(-28);
    const systemPrompt = buildSystemPrompt(forceMode || 'agent');
    let msgs = [{ role: 'system', content: systemPrompt }, ...chat.history];
    let finalResponse = '';

    for (let i = 0; i < 10; i++) {
      const response = await streamTurn(msgs);
      msgs.push({ role: 'assistant', content: response });
      finalResponse = response;

      await applyEdits(response);
      const tools = parseTools(response);
      if (tools.length === 0) break;

      const results = await executeTools(tools);
      msgs.push({ role: 'user', content: results.join('\n\n---\n\n') });
    }
    chat.history.push({ role: 'assistant', content: finalResponse });
    updateContextMeter();
    if (state.rootPath) renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  }

  async function runPlanMode() {
    const chat = getActiveChat();
    if (chat.history.length > 30) chat.history = chat.history.slice(-28);
    const msgs = [{ role: 'system', content: buildSystemPrompt('plan') }, ...chat.history];
    const response = await streamTurn(msgs);
    chat.history.push({ role: 'assistant', content: response });
    updateContextMeter();
    const planMatch = response.match(/<PLAN>([\s\S]*?)<\/PLAN>/i);
    if (planMatch) {
      pendingPlan = planMatch[1].trim();
      showPlanApproval(pendingPlan);
    }
  }

  function showPlanApproval(planText) {
    const box = document.getElementById('plan-box');
    document.getElementById('plan-content').innerHTML =
      '<strong style="color:#4ec9b0">Proposed Plan:</strong><br><br>' +
      escHtml(planText)
        .replace(/^(\d+\..+)$/gm, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
    box.classList.remove('hidden');
  }

  async function approvePlan() {
    document.getElementById('plan-box').classList.add('hidden');
    if (!pendingPlan) return;
    const msg = 'Plan approved — please execute it now step by step using your agent tools.';
    addMessage('user', msg);
    getActiveChat().history.push({ role: 'user', content: msg });
    pendingPlan = null;
    setRunning(true);
    try { await runAgentLoop('agent'); }
    catch (e) { addSystemMessage(`Error: ${e.message}`); }
    finally { setRunning(false); }
  }

  function rejectPlan() {
    document.getElementById('plan-box').classList.add('hidden');
    pendingPlan = null;
    addSystemMessage('Plan rejected.');
  }

  // ── main send ────────────────────────────────────────────────────────────
  async function send() {
    const input = document.getElementById('ai-input');
    const text = input.value.trim();
    if (!text || running) return;
    input.value = '';
    addMessage('user', text);
    getActiveChat().history.push({ role: 'user', content: text });
    updateContextMeter();
    setRunning(true);
    try {
      if (mode === 'plan')       await runPlanMode();
      else if (mode === 'agent') await runAgentLoop();
      else                       await runAskMode();
    } catch (e) {
      addSystemMessage(`Error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  }

  async function explainError() {
    if (!lastError) return;
    document.getElementById('ai-panel').classList.remove('hidden');
    setMode('agent');
    const text = `I got this error:\n\`\`\`\n${lastError.slice(-2000)}\n\`\`\`\nPlease diagnose and fix it.`;
    document.getElementById('ai-input').value = text;
    await send();
  }

  async function askAboutFile(filePath) {
    document.getElementById('ai-panel').classList.remove('hidden');
    await openFile(filePath);
    document.getElementById('ai-input').value = `Explain what ${filePath.split(/[\\/]/).pop()} does and how it works.`;
    await send();
  }

  function clearHistory() {
    const chat = getActiveChat();
    if (chat) chat.history = [];
    const session = getActiveSession();
    if (session) session.innerHTML = '';
    addSystemMessage('Chat cleared.');
    updateContextMeter();
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('ai-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));

    const modelSel = document.getElementById('ai-model-select');
    if (modelSel) {
      if (selectedModel) modelSel.value = selectedModel;
      modelSel.addEventListener('change', () => {
        selectedModel = modelSel.value;
        localStorage.setItem('fallen_model', selectedModel);
      });
    }
    const tempInp = document.getElementById('ai-temp');
    if (tempInp) {
      tempInp.value = aiTemperature;
      tempInp.addEventListener('change', () => {
        const v = parseFloat(tempInp.value);
        if (!isNaN(v) && v >= 0 && v <= 1) { aiTemperature = v; localStorage.setItem('fallen_temp', v); }
      });
    }

    const first = createChat('Chat 1');
    switchChat(first.id);
  });

  return {
    send, stop, explainError, askAboutFile, captureOutput, clearErrorBuffer,
    approvePlan, rejectPlan, setMode, clearHistory, newChat, populateModelPicker,
    setContextWindow: w => { contextWindow = w; updateContextMeter(); },
  };
})();

// ── Extensions ────────────────────────────────────────────────────────────────
window.Extensions = (() => {
  const SK = 'fallen_extensions';

  const CATALOG = [
    // Themes
    { id:'th-dracula', name:'Dracula Theme',    publisher:'Zeno Rocha',       cat:'Themes',           icon:'🧛', desc:'Dark purple theme — the original Dracula',                themeId:'dracula' },
    { id:'th-monokai', name:'Monokai Pro',      publisher:'Wimer Hazenberg',  cat:'Themes',           icon:'🎨', desc:'Vibrant dark theme with colourful syntax highlighting',   themeId:'monokai' },
    { id:'th-onedark', name:'One Dark Pro',     publisher:'binaryify',        cat:'Themes',           icon:'🌙', desc:"Atom's iconic One Dark theme adapted for Monaco",         themeId:'onedark' },
    { id:'th-nord',    name:'Nord',             publisher:'Arctic Ice Studio', cat:'Themes',          icon:'❄️', desc:'Arctic north-bluish minimal colour scheme',               themeId:'nord' },
    // Formatters
    { id:'fmt-prettier', name:'Prettier',       publisher:'Prettier',         cat:'Formatters',       icon:'💅', desc:'Opinionated formatter for JS/TS/HTML/CSS/JSON',           installCmd:'npm install -g prettier' },
    { id:'fmt-black',    name:'Black',          publisher:'Python SF',        cat:'Formatters',       icon:'🐍', desc:'The uncompromising Python code formatter',                installCmd:'pip install black' },
    { id:'fmt-autopep8', name:'autopep8',       publisher:'hhatto',           cat:'Formatters',       icon:'🔧', desc:'Automatically formats Python to PEP 8 style',            installCmd:'pip install autopep8' },
    // Linters
    { id:'lint-eslint',  name:'ESLint',         publisher:'Microsoft',        cat:'Linters',          icon:'🔍', desc:'Pluggable static analysis for JS and TS',                installCmd:'npm install -g eslint' },
    { id:'lint-ruff',    name:'Ruff',           publisher:'Astral',           cat:'Linters',          icon:'⚡', desc:'Extremely fast Python linter written in Rust',           installCmd:'pip install ruff' },
    { id:'lint-pylint',  name:'Pylint',         publisher:'PyCQA',            cat:'Linters',          icon:'🔎', desc:'Full-featured Python static code analyser',              installCmd:'pip install pylint' },
    // Language Support
    { id:'lang-go',   name:'Go Tools',          publisher:'Google',           cat:'Language Support', icon:'🐹', desc:'gopls language server and core Go tools',                installCmd:'go install golang.org/x/tools/gopls@latest' },
    { id:'lang-rust', name:'Rust Analyzer',     publisher:'rust-lang',        cat:'Language Support', icon:'🦀', desc:'Rust language server with IntelliSense',                 installCmd:'rustup component add rust-analyzer' },
    // Utilities
    { id:'util-tsnode',  name:'ts-node',        publisher:'TypeStrong',       cat:'Utilities',        icon:'🔷', desc:'TypeScript execution and REPL for Node.js',              installCmd:'npm install -g ts-node typescript' },
    { id:'util-nodemon', name:'nodemon',        publisher:'Remy Sharp',       cat:'Utilities',        icon:'👁️', desc:'Auto-restart Node apps on file changes',                 installCmd:'npm install -g nodemon' },
    { id:'util-http',    name:'http-server',    publisher:'http-party',       cat:'Utilities',        icon:'🌐', desc:'Zero-config command-line HTTP server',                   installCmd:'npm install -g http-server' },
  ];

  const THEME_DATA = {
    dracula: {
      base:'vs-dark', inherit:true,
      rules:[
        { token:'comment',          foreground:'6272a4', fontStyle:'italic' },
        { token:'keyword',          foreground:'ff79c6' },
        { token:'keyword.operator', foreground:'ff79c6' },
        { token:'string',           foreground:'f1fa8c' },
        { token:'string.escape',    foreground:'ff79c6' },
        { token:'number',           foreground:'bd93f9' },
        { token:'regexp',           foreground:'f1fa8c' },
        { token:'operator',         foreground:'ff79c6' },
        { token:'type',             foreground:'8be9fd' },
        { token:'class',            foreground:'8be9fd' },
        { token:'function',         foreground:'50fa7b' },
        { token:'variable',         foreground:'f8f8f2' },
        { token:'constant',         foreground:'bd93f9' },
        { token:'tag',              foreground:'ff79c6' },
        { token:'attribute.name',   foreground:'50fa7b' },
        { token:'attribute.value',  foreground:'f1fa8c' },
      ],
      colors:{
        'editor.background':'#282a36',
        'editor.foreground':'#f8f8f2',
        'editor.lineHighlightBackground':'#44475a44',
        'editor.selectionBackground':'#44475a',
        'editor.inactiveSelectionBackground':'#44475a88',
        'editorCursor.foreground':'#f8f8f2',
        'editorLineNumber.foreground':'#6272a4',
        'editorLineNumber.activeForeground':'#f8f8f2',
        'editorIndentGuide.background1':'#44475a',
        'scrollbarSlider.background':'#44475a88',
      }
    },
    monokai: {
      base:'vs-dark', inherit:true,
      rules:[
        { token:'comment',          foreground:'75715e', fontStyle:'italic' },
        { token:'keyword',          foreground:'f92672' },
        { token:'keyword.operator', foreground:'f92672' },
        { token:'string',           foreground:'e6db74' },
        { token:'string.escape',    foreground:'ae81ff' },
        { token:'number',           foreground:'ae81ff' },
        { token:'regexp',           foreground:'e6db74' },
        { token:'operator',         foreground:'f92672' },
        { token:'type',             foreground:'66d9e8' },
        { token:'class',            foreground:'a6e22e' },
        { token:'function',         foreground:'a6e22e' },
        { token:'variable',         foreground:'f8f8f2' },
        { token:'constant',         foreground:'ae81ff' },
        { token:'tag',              foreground:'f92672' },
        { token:'attribute.name',   foreground:'a6e22e' },
        { token:'attribute.value',  foreground:'e6db74' },
      ],
      colors:{
        'editor.background':'#272822',
        'editor.foreground':'#f8f8f2',
        'editor.lineHighlightBackground':'#3e3d3266',
        'editor.selectionBackground':'#49483e',
        'editor.inactiveSelectionBackground':'#49483e88',
        'editorCursor.foreground':'#f8f8f0',
        'editorLineNumber.foreground':'#90908a',
        'editorLineNumber.activeForeground':'#f8f8f2',
        'scrollbarSlider.background':'#49483e88',
      }
    },
    onedark: {
      base:'vs-dark', inherit:true,
      rules:[
        { token:'comment',          foreground:'5c6370', fontStyle:'italic' },
        { token:'keyword',          foreground:'c678dd' },
        { token:'keyword.operator', foreground:'56b6c2' },
        { token:'string',           foreground:'98c379' },
        { token:'string.escape',    foreground:'56b6c2' },
        { token:'number',           foreground:'d19a66' },
        { token:'regexp',           foreground:'98c379' },
        { token:'operator',         foreground:'56b6c2' },
        { token:'type',             foreground:'e5c07b' },
        { token:'class',            foreground:'e5c07b' },
        { token:'function',         foreground:'61afef' },
        { token:'variable',         foreground:'abb2bf' },
        { token:'constant',         foreground:'d19a66' },
        { token:'tag',              foreground:'e06c75' },
        { token:'attribute.name',   foreground:'d19a66' },
        { token:'attribute.value',  foreground:'98c379' },
      ],
      colors:{
        'editor.background':'#282c34',
        'editor.foreground':'#abb2bf',
        'editor.lineHighlightBackground':'#2c323c',
        'editor.selectionBackground':'#3e4451',
        'editor.inactiveSelectionBackground':'#3e445188',
        'editorCursor.foreground':'#528bff',
        'editorLineNumber.foreground':'#4b5263',
        'editorLineNumber.activeForeground':'#abb2bf',
        'scrollbarSlider.background':'#3e445188',
      }
    },
    nord: {
      base:'vs-dark', inherit:true,
      rules:[
        { token:'comment',          foreground:'616e88', fontStyle:'italic' },
        { token:'keyword',          foreground:'81a1c1' },
        { token:'keyword.operator', foreground:'81a1c1' },
        { token:'string',           foreground:'a3be8c' },
        { token:'string.escape',    foreground:'ebcb8b' },
        { token:'number',           foreground:'b48ead' },
        { token:'regexp',           foreground:'a3be8c' },
        { token:'operator',         foreground:'81a1c1' },
        { token:'type',             foreground:'8fbcbb' },
        { token:'class',            foreground:'8fbcbb' },
        { token:'function',         foreground:'88c0d0' },
        { token:'variable',         foreground:'d8dee9' },
        { token:'constant',         foreground:'5e81ac' },
        { token:'tag',              foreground:'81a1c1' },
        { token:'attribute.name',   foreground:'8fbcbb' },
        { token:'attribute.value',  foreground:'a3be8c' },
      ],
      colors:{
        'editor.background':'#2e3440',
        'editor.foreground':'#d8dee9',
        'editor.lineHighlightBackground':'#3b425244',
        'editor.selectionBackground':'#434c5e',
        'editor.inactiveSelectionBackground':'#434c5e88',
        'editorCursor.foreground':'#d8dee9',
        'editorLineNumber.foreground':'#4c566a',
        'editorLineNumber.activeForeground':'#d8dee9',
        'scrollbarSlider.background':'#434c5e88',
      }
    },
  };

  function getState() { try { return JSON.parse(localStorage.getItem(SK) || '{}'); } catch { return {}; } }
  function setState(s) { localStorage.setItem(SK, JSON.stringify(s)); }

  function init() {
    for (const [id, data] of Object.entries(THEME_DATA)) monaco.editor.defineTheme(id, data);
    const s = getState();
    for (const ext of CATALOG) {
      if (ext.themeId && s[ext.id]?.installed && s[ext.id]?.enabled) {
        monaco.editor.setTheme(ext.themeId); break;
      }
    }
  }

  let query = '';
  function search(q) { query = q; render(); }

  function render() {
    const list = document.getElementById('ext-list');
    if (!list) return;
    const s = getState();
    const q = query.toLowerCase();
    const filtered = q
      ? CATALOG.filter(e => e.name.toLowerCase().includes(q) || e.desc.toLowerCase().includes(q) || e.cat.toLowerCase().includes(q))
      : CATALOG;

    const groups = {};
    for (const ext of filtered) (groups[ext.cat] = groups[ext.cat] || []).push(ext);

    list.innerHTML = '';
    if (!filtered.length) {
      list.innerHTML = '<div style="color:var(--text-dim);text-align:center;padding:24px 8px;font-size:12px">No extensions found</div>';
      return;
    }

    for (const [cat, exts] of Object.entries(groups)) {
      const hdr = document.createElement('div');
      hdr.className = 'ext-cat-hdr';
      hdr.textContent = cat;
      list.appendChild(hdr);

      for (const ext of exts) {
        const xs = s[ext.id] || { installed: false, enabled: false };
        let btns = '';
        if (!xs.installed) {
          btns = `<button class="ext-btn" onclick="Extensions.install('${ext.id}')">Install</button>`;
        } else {
          btns = `<button class="ext-btn${xs.enabled ? ' ext-btn-off' : ''}" onclick="Extensions.toggle('${ext.id}')">${xs.enabled ? 'Disable' : 'Enable'}</button>
                  <button class="ext-btn ext-btn-rm" onclick="Extensions.uninstall('${ext.id}')">Remove</button>`;
        }
        const badge = xs.installed
          ? `<span class="${xs.enabled ? 'ext-badge-on' : 'ext-badge-off'}">${xs.enabled ? '● on' : '○ off'}</span>`
          : '';

        const card = document.createElement('div');
        card.className = 'ext-card';
        card.innerHTML = `
          <div style="display:flex;gap:8px;align-items:flex-start">
            <div style="font-size:20px;line-height:1.2;flex-shrink:0">${ext.icon}</div>
            <div style="flex:1;min-width:0">
              <div style="font-size:12px;font-weight:bold;color:var(--text)">${escHtml(ext.name)}${badge}</div>
              <div style="font-size:10px;color:var(--text-dim);margin-bottom:3px">${escHtml(ext.publisher)}</div>
              <div style="font-size:11px;color:#9a9a9a;line-height:1.4">${escHtml(ext.desc)}</div>
            </div>
          </div>
          <div style="display:flex;gap:4px;justify-content:flex-end;margin-top:8px">${btns}</div>`;
        list.appendChild(card);
      }
    }
  }

  function install(id) {
    const ext = CATALOG.find(e => e.id === id);
    if (!ext) return;
    const s = getState();
    s[id] = { installed: true, enabled: true };
    if (ext.themeId) { _applyTheme(id, s); }
    setState(s);
    if (!ext.themeId && ext.installCmd) {
      switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
      runInTerminal(ext.installCmd);
    }
    render();
  }

  function toggle(id) {
    const ext = CATALOG.find(e => e.id === id);
    if (!ext) return;
    const s = getState();
    if (!s[id]) return;
    s[id].enabled = !s[id].enabled;
    if (ext.themeId) {
      if (s[id].enabled) _applyTheme(id, s);
      else monaco.editor.setTheme('vs-dark');
    }
    setState(s);
    render();
  }

  function uninstall(id) {
    const ext = CATALOG.find(e => e.id === id);
    if (!ext) return;
    const s = getState();
    delete s[id];
    setState(s);
    if (ext.themeId) monaco.editor.setTheme('vs-dark');
    render();
  }

  function _applyTheme(id, s) {
    const ext = CATALOG.find(e => e.id === id);
    if (!ext?.themeId) return;
    for (const e of CATALOG) { if (e.themeId && e.id !== id && s[e.id]?.enabled) s[e.id].enabled = false; }
    monaco.editor.setTheme(ext.themeId);
  }

  return { init, render, search, install, toggle, uninstall };
})();
