// ── Custom dialogs (window.prompt/confirm/alert blocked by Monaco Editor) ─────
function _dlg(msg, mode, def) {
  return new Promise(resolve => {
    const ov  = document.getElementById('dlg-overlay');
    const inp = document.getElementById('dlg-input');
    const ok  = document.getElementById('dlg-ok');
    const can = document.getElementById('dlg-cancel');
    document.getElementById('dlg-msg').textContent = msg;
    const isPrompt = mode === 'prompt';
    inp.style.display  = isPrompt ? 'block' : 'none';
    can.style.display  = mode === 'alert' ? 'none' : '';
    if (isPrompt) { inp.value = def ?? ''; }
    ov.style.display = 'flex';
    requestAnimationFrame(() => { (isPrompt ? inp : ok).focus(); if (isPrompt) inp.select(); });
    const done = v => { ov.style.display = 'none'; ok.onclick = can.onclick = inp.onkeydown = null; resolve(v); };
    ok.onclick  = () => done(isPrompt ? (inp.value || null) : true);
    can.onclick = () => done(null);
    if (isPrompt) inp.onkeydown = e => { if (e.key === 'Enter') ok.click(); if (e.key === 'Escape') can.click(); };
  });
}
const ask   = (msg, def) => _dlg(msg, 'prompt', def);
const tell  = msg         => _dlg(msg, 'alert');
const yesno = msg         => _dlg(msg, 'confirm').then(Boolean);

// ── Global state ──────────────────────────────────────────────────────────────
const state = {
  rootPath: null,
  tabs: [],
  activeTab: null,
  editor: null,
  terminals: [],
  activeTermId: null,
  terminalSeq: 0,
  expandedDirs: new Set(),
  wordWrap: 'off',
};

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener('monaco-ready', async () => {
  App.initEditor();
  App.initResizeHandle();
  Extensions.init();
  await App.initTerminal();
  App.checkAI();
});

// ── App namespace ─────────────────────────────────────────────────────────────
const App = {

  // ── Editor ──────────────────────────────────────────────────────────────────
  initEditor() {
    state.editor = monaco.editor.create(document.getElementById('monaco-editor'), {
      theme: 'vs-dark',
      automaticLayout: true,
      fontSize: 14,
      fontFamily: "'Cascadia Code', 'Consolas', monospace",
      fontLigatures: true,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      wordWrap: 'off',
      renderWhitespace: 'selection',
      bracketPairColorization: { enabled: true },
      suggest: { showSnippets: true },
    });

    state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => App.saveActive());

    state.editor.onDidChangeModelContent(() => {
      const tab = state.tabs.find(t => t.path === state.activeTab);
      if (tab && !tab.modified) { tab.modified = true; App.renderTabs(); }
    });

    state.editor.onDidChangeCursorPosition(e => {
      const el = document.getElementById('status-pos');
      if (el) el.textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
    });
  },

  // ── Resize handle (drag bottom panel) ──────────────────────────────────────
  initResizeHandle() {
    const handle = document.getElementById('resize-handle');
    const panel  = document.getElementById('bottom-panel');
    if (!handle || !panel) return;
    let startY = 0, startH = 0;
    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      startY = e.clientY;
      startH = panel.offsetHeight;
      const onMove = e2 => {
        const delta = startY - e2.clientY;
        const maxH  = Math.floor(window.innerHeight * 0.7);
        panel.style.height = Math.max(80, Math.min(maxH, startH + delta)) + 'px';
        const t = App.getActiveTerminal();
        if (t && !t.closed) t.fitAddon.fit();
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', () => {
        document.removeEventListener('mousemove', onMove);
        const t = App.getActiveTerminal();
        if (t && !t.closed) t.fitAddon.fit();
      }, { once: true });
    });
  },

  // ── Terminal ─────────────────────────────────────────────────────────────────
  async initTerminal() {
    await App.createTerminal(state.rootPath || null, { activate: true });
  },

  getTerminal(id) { return state.terminals.find(t => t.id === id) || null; },
  getActiveTerminal() { return App.getTerminal(state.activeTermId); },

  async createTerminal(cwd = null, options = {}) {
    const id    = await api.termCreate(cwd);
    const label = options.label || `Terminal ${++state.terminalSeq}`;
    const cont  = document.getElementById('xterm-container');

    const pane  = document.createElement('div');
    pane.className = 'terminal-pane';
    pane.dataset.termId = String(id);

    const mount = document.createElement('div');
    mount.className = 'terminal-mount';
    pane.appendChild(mount);
    cont.appendChild(pane);

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
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(mount);

    // Custom mouse-wheel scroll (more reliable in sandboxed Electron)
    mount.addEventListener('wheel', e => {
      e.preventDefault();
      e.stopPropagation();
      term.scrollLines(Math.sign(e.deltaY) * Math.max(1, Math.ceil(Math.abs(e.deltaY) / 40)));
    }, { capture: true, passive: false });

    // Ctrl+Shift+C copies selection; Ctrl+Shift+V pastes
    term.attachCustomKeyEventHandler(e => {
      if (e.ctrlKey && e.shiftKey && e.type === 'keydown') {
        if (e.key === 'C') { const s = term.getSelection(); if (s) navigator.clipboard.writeText(s); return false; }
        if (e.key === 'V') { navigator.clipboard.readText().then(t => term.paste(t)); return false; }
      }
      return true;
    });

    // Right-click: copy selection or paste
    mount.addEventListener('contextmenu', e => {
      e.preventDefault();
      const sel = term.getSelection();
      if (sel) navigator.clipboard.writeText(sel);
      else navigator.clipboard.readText().then(t => term.paste(t));
    });

    const terminal = { id, label, cwd: cwd || null, term, fitAddon, pane, mount,
                       inputDisposable: null, resizeObserver: null,
                       exited: false, closed: false, pendingEcho: null };
    state.terminals.push(terminal);

    // ── Line-buffered input ──────────────────────────────────────────────────
    // Buffer typed chars locally; send to process on Enter as a complete line.
    // Backspace erases from the local buffer before it's ever sent — Python
    // input() works correctly and never sees raw \b bytes.
    let lineBuffer = '';

    terminal.inputDisposable = term.onData(data => {
      let i = 0;
      while (i < data.length) {
        const ch   = data[i];
        const code = data.charCodeAt(i);

        if (code === 0x1b) {
          // Escape sequence (arrows, fn-keys): forward immediately
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
          term.write('\r\n');
          api.termWrite(id, lineBuffer + '\r\n');
          lineBuffer = '';
        } else if (ch === '\x7f' || ch === '\b') {
          if (lineBuffer.length > 0) { lineBuffer = lineBuffer.slice(0, -1); term.write('\b \b'); }
        } else if (code >= 0x20 && code < 0x7f) {
          lineBuffer += ch;
          term.write(ch);
        } else {
          // Ctrl+C (\x03), Tab (\x09), Ctrl+D (\x04), etc.: pass through
          api.termWrite(id, ch);
        }
        i++;
      }
    });

    api.onTermData(id, d => {
      if (terminal.closed) return;
      if (d.includes('\r') || d.includes('\n')) lineBuffer = '';
      let out = d.replace(/\x7f/g, '');
      // Strip PowerShell's echo of the command we sent (pendingEcho)
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
      api.removeTermListeners(id);
      App.renderTerminalTabs();
    });

    terminal.resizeObserver = new ResizeObserver(() => {
      if (terminal.closed || state.activeTermId !== id || pane.offsetParent === null) return;
      fitAddon.fit();
      term.scrollToBottom();
    });
    terminal.resizeObserver.observe(pane);

    App.renderTerminalTabs();
    if (options.activate !== false) App.activateTerminal(id, { fit: true });
    return terminal;
  },

  renderTerminalTabs() {
    const bar = document.getElementById('terminal-tabs');
    if (!bar) return;
    bar.innerHTML = '';
    if (!state.terminals.length) {
      const e = document.createElement('div');
      e.className = 'terminal-tabs-empty';
      e.textContent = 'No terminals open';
      bar.appendChild(e);
      return;
    }
    for (const t of state.terminals) {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'terminal-tab' + (t.id === state.activeTermId ? ' active' : '') + (t.exited ? ' exited' : '');
      tab.innerHTML = `<span class="terminal-tab-name">${App.escHtml(t.label)}</span><span class="terminal-tab-close" aria-hidden="true">×</span>`;
      tab.addEventListener('click', ev => {
        if (ev.target.closest('.terminal-tab-close')) { ev.stopPropagation(); App.closeTerminal(t.id); return; }
        App.activateTerminal(t.id);
      });
      bar.appendChild(tab);
    }
  },

  activateTerminal(id, options = {}) {
    const terminal = App.getTerminal(id);
    if (!terminal) return;
    state.activeTermId = id;
    for (const e of state.terminals) {
      e.pane.classList.toggle('active', e.id === id);
      e.pane.style.display = e.id === id ? 'flex' : 'none';
    }
    App.renderTerminalTabs();
    if (options.fit !== false) {
      requestAnimationFrame(() => {
        if (state.activeTermId !== id || terminal.closed || terminal.pane.offsetParent === null) return;
        terminal.fitAddon.fit();
        terminal.term.scrollToBottom();
        terminal.term.focus();
      });
    }
  },

  destroyTerminal(terminal, { killProcess = true } = {}) {
    if (!terminal || terminal.closed) return;
    terminal.closed = true;
    api.removeTermListeners?.(terminal.id);
    if (killProcess) api.termKill(terminal.id);
    terminal.inputDisposable?.dispose?.();
    terminal.resizeObserver?.disconnect?.();
    terminal.term.dispose();
    terminal.pane.remove();
  },

  closeTerminal(id) {
    const idx = state.terminals.findIndex(t => t.id === id);
    if (idx === -1) return;
    const terminal = state.terminals[idx];
    const wasActive = state.activeTermId === id;
    state.terminals.splice(idx, 1);
    App.destroyTerminal(terminal, { killProcess: true });
    if (wasActive) {
      const next = state.terminals[idx] || state.terminals[idx - 1] || null;
      state.activeTermId = null;
      if (next) App.activateTerminal(next.id);
      else App.renderTerminalTabs();
    } else {
      App.renderTerminalTabs();
    }
  },

  async newTerminal() {
    await App.createTerminal(state.rootPath || null, { activate: true });
  },

  // ── AI check ─────────────────────────────────────────────────────────────────
  async checkAI() {
    const el     = document.getElementById('ai-connection-status');
    const phEl   = document.getElementById('ai-status');
    if (!el) return;
    el.textContent = 'AI checking…';
    el.style.color = '';
    try {
      const result = await api.aiCheck();
      if (result?.ok) {
        el.textContent = 'AI connected';
        el.style.color = '#4ec9b0';
        if (phEl) { phEl.textContent = 'connected'; phEl.style.color = '#4ec9b0'; }
        AI.setContextWindow(result.contextWindow || 20000);
      } else throw new Error('not ok');
    } catch {
      el.textContent = 'AI offline';
      el.style.color = '#f44747';
      if (phEl) { phEl.textContent = 'offline'; phEl.style.color = '#f44747'; }
    }
    setTimeout(() => App.checkAI(), 30000);
  },

  // ── Sidebar views ────────────────────────────────────────────────────────────
  showView(view, btn) {
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    btn?.classList.add('active');
    document.getElementById('view-files').style.display = view === 'files' ? 'flex' : 'none';
    document.getElementById('view-exts').style.display  = view === 'exts'  ? 'flex' : 'none';
    if (view === 'exts') Extensions.render();
  },

  // ── Folder ───────────────────────────────────────────────────────────────────
  async openFolder() {
    const folderPath = await api.openFolder();
    if (!folderPath) return;
    state.rootPath = folderPath;
    document.getElementById('folder-name').textContent = folderPath.split(/[\\/]/).pop();
    await App.renderTree(folderPath, document.getElementById('file-tree'), 0);
    for (const t of [...state.terminals]) App.destroyTerminal(t, { killProcess: true });
    state.terminals = [];
    state.activeTermId = null;
    state.terminalSeq = 0;
    document.getElementById('xterm-container').innerHTML = '';
    App.renderTerminalTabs();
    await App.createTerminal(folderPath, { activate: true });
  },

  // ── File tree ─────────────────────────────────────────────────────────────────
  async renderTree(dirPath, container, depth) {
    const entries = await api.readDir(dirPath);
    container.innerHTML = '';
    for (const entry of entries) {
      const item = document.createElement('div');
      item.className = 'tree-item' + (entry.isDir ? ' tree-dir' : '');
      item.style.paddingLeft = (8 + depth * 14) + 'px';
      item.innerHTML = `<span class="icon">${entry.isDir ? '📁' : App.fileIcon(entry.name)}</span>${App.escHtml(entry.name)}`;
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
            await App.renderTree(entry.path, children, depth + 1);
          }
        };
        item.oncontextmenu = e => { e.preventDefault(); App.showContextMenu(e, entry.path, true); };
        container.appendChild(item);
        container.appendChild(children);
        if (state.expandedDirs.has(entry.path)) {
          item.querySelector('.icon').textContent = '📂';
          await App.renderTree(entry.path, children, depth + 1);
        }
      } else {
        item.onclick = () => App.openFile(entry.path);
        item.oncontextmenu = e => { e.preventDefault(); App.showContextMenu(e, entry.path, false); };
        container.appendChild(item);
      }
    }
  },

  fileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const m = { py:'🐍',js:'🟨',ts:'🔷',jsx:'🟨',tsx:'🔷',html:'🌐',css:'🎨',
                json:'📋',md:'📝',txt:'📄',c:'⚙️',cpp:'⚙️',h:'📎',sh:'💲',
                ps1:'💲',rb:'💎',go:'🐹',rs:'🦀',java:'☕',png:'🖼️',jpg:'🖼️',
                gif:'🖼️',svg:'🎨',env:'🔑',toml:'📋',yaml:'📋',yml:'📋',
                dockerfile:'🐳',gitignore:'🔧' };
    return m[ext] || '📄';
  },

  escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },

  // ── Context menu ──────────────────────────────────────────────────────────────
  showContextMenu(e, filePath, isDir) {
    document.getElementById('ctx-menu')?.remove();
    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;background:#252526;border:1px solid #3c3c3c;border-radius:4px;z-index:9999;min-width:170px;box-shadow:0 4px 14px #0009`;
    const sep = () => { const d = document.createElement('div'); d.style.cssText='height:1px;background:#3c3c3c;margin:2px 0'; menu.appendChild(d); };
    const btn = (label, fn) => {
      const b = document.createElement('div');
      b.textContent = label;
      b.style.cssText = 'padding:6px 14px;cursor:pointer;font-size:12px;';
      b.onmouseenter = () => b.style.background = '#0078d4';
      b.onmouseleave = () => b.style.background = '';
      b.onclick = () => { menu.remove(); fn(); };
      menu.appendChild(b);
    };
    const pathSep = filePath.includes('\\') ? '\\' : '/';
    if (isDir) {
      btn('New File Here', async () => {
        const name = await ask('File name:');
        if (!name) return;
        const full = filePath + pathSep + name;
        await api.writeFile(full, '');
        App.openFile(full);
        if (state.rootPath) App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
      });
      btn('New Folder Here', async () => {
        const name = await ask('Folder name:');
        if (!name) return;
        await api.mkdir(filePath + pathSep + name);
        if (state.rootPath) App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
      });
      btn('Open in Terminal', () => App.runInTerminal(`cd "${filePath}"`));
      sep();
    }
    btn(`Rename ${isDir ? 'Folder' : 'File'}`, async () => {
      const oldName = filePath.split(/[\\/]/).pop();
      const n = await ask('Rename to:', oldName);
      if (!n || n === oldName) return;
      const newPath = await api.renameFile(filePath, n);
      if (!newPath) { await tell('Rename failed — the file may be open or locked.'); return; }
      if (state.rootPath) App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
    });
    btn(`Delete ${isDir ? 'Folder' : 'File'}`, async () => {
      if (await yesno(`Delete "${filePath.split(/[\\/]/).pop()}"? This moves it to the Recycle Bin.`)) {
        await api.deleteFile(filePath);
        if (!isDir) App.closeTab(filePath);
        if (state.rootPath) App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
      }
    });
    if (!isDir) { sep(); btn('Ask AI about file', () => AI.askAboutFile(filePath)); }
    document.body.appendChild(menu);
    document.addEventListener('click', () => menu.remove(), { once: true });
  },

  // ── Open file ─────────────────────────────────────────────────────────────────
  async openFile(filePath) {
    const existing = state.tabs.find(t => t.path === filePath);
    if (existing) { App.activateTab(filePath); return; }
    const content = await api.readFile(filePath);
    if (content === null) return;
    const lang  = App.detectLang(filePath);
    const model = monaco.editor.createModel(content, lang);
    state.tabs.push({ path: filePath, name: filePath.split(/[\\/]/).pop(), model, modified: false });
    App.renderTabs();
    App.activateTab(filePath);
    document.getElementById('editor-placeholder').style.display = 'none';
    document.querySelectorAll('.tree-item').forEach(el => el.classList.toggle('active', el.title === filePath));
  },

  detectLang(filePath) {
    const ext = filePath.split('.').pop().toLowerCase();
    const m = { py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',
                html:'html',css:'css',json:'json',md:'markdown',c:'c',cpp:'cpp',h:'c',
                sh:'shell',ps1:'powershell',rb:'ruby',go:'go',rs:'rust',java:'java',
                xml:'xml',yaml:'yaml',yml:'yaml',toml:'ini',vue:'html',cs:'csharp',
                php:'php',sql:'sql' };
    return m[ext] || 'plaintext';
  },

  // ── Tabs ──────────────────────────────────────────────────────────────────────
  renderTabs() {
    const bar = document.getElementById('tabs-list');
    bar.innerHTML = '';
    for (const tab of state.tabs) {
      const el = document.createElement('div');
      el.className = 'tab' + (tab.path === state.activeTab ? ' active' : '') + (tab.modified ? ' modified' : '');
      el.innerHTML = `<span class="tab-name">${App.escHtml(tab.name)}</span><span class="tab-close">×</span>`;
      el.addEventListener('click', e => {
        if (e.target.classList.contains('tab-close')) App.closeTab(tab.path);
        else App.activateTab(tab.path);
      });
      bar.appendChild(el);
    }
  },

  activateTab(filePath) {
    const tab = state.tabs.find(t => t.path === filePath);
    if (!tab) return;
    state.activeTab = filePath;
    state.editor.setModel(tab.model);
    App.renderTabs();
    const langEl = document.getElementById('status-lang');
    if (langEl) langEl.textContent = App.detectLang(filePath).toUpperCase();
  },

  closeTab(filePath) {
    const idx = state.tabs.findIndex(t => t.path === filePath);
    if (idx === -1) return;
    state.tabs[idx].model.dispose();
    state.tabs.splice(idx, 1);
    if (state.activeTab === filePath) {
      const next = state.tabs[idx] || state.tabs[idx - 1];
      if (next) App.activateTab(next.path);
      else { state.activeTab = null; state.editor.setModel(null); document.getElementById('editor-placeholder').style.display = 'flex'; }
    }
    App.renderTabs();
  },

  // ── Save ─────────────────────────────────────────────────────────────────────
  async saveActive() {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (!tab) return;
    const ok = await api.writeFile(tab.path, tab.model.getValue());
    if (ok) { tab.modified = false; App.renderTabs(); }
  },

  // ── New file ──────────────────────────────────────────────────────────────────
  async newFile() {
    const filePath = await api.newFile(state.rootPath);
    if (!filePath) return;
    await App.openFile(filePath);
    if (state.rootPath) await App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  },

  async newFolder() {
    const base = state.rootPath;
    if (!base) { await tell('Open a folder first.'); return; }
    const name = await ask('New folder name:');
    if (!name) return;
    const sep = base.includes('\\') ? '\\' : '/';
    await api.mkdir(base + sep + name);
    await App.renderTree(state.rootPath, document.getElementById('file-tree'), 0);
  },

  // ── Install package ───────────────────────────────────────────────────────────
  async installPackage() {
    const pkg = await ask('Package name to install:');
    if (!pkg) return;
    let cmd = '';
    if (state.rootPath) {
      try {
        const entries = await api.readDir(state.rootPath);
        const names = new Set(entries.map(e => e.name));
        if (names.has('package.json'))                               cmd = `npm install ${pkg}`;
        else if (names.has('requirements.txt') || names.has('setup.py') || names.has('pyproject.toml')) cmd = `pip install ${pkg}`;
        else if (names.has('Cargo.toml'))                           cmd = `cargo add ${pkg}`;
        else if (names.has('go.mod'))                               cmd = `go get ${pkg}`;
        else if (names.has('Gemfile'))                              cmd = `gem install ${pkg}`;
        else if (names.has('pom.xml'))                              cmd = `mvn dependency:get -Dartifact=${pkg}`;
      } catch {}
    }
    if (!cmd) {
      const type = await ask('Choose installer (npm / pip / cargo / go / gem):', 'pip');
      if (!type) return;
      const map = { npm:`npm install ${pkg}`, pip:`pip install ${pkg}`, cargo:`cargo add ${pkg}`, go:`go get ${pkg}`, gem:`gem install ${pkg}` };
      cmd = map[type.trim()] || `${type.trim()} install ${pkg}`;
    }
    App.switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
    App.runInTerminal(cmd);
  },

  // ── Run / Launch ──────────────────────────────────────────────────────────────
  async runActive() {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (!tab) return;
    await App.saveActive();
    let cmd = await api.getRunCommand(tab.path);
    if (!cmd) {
      cmd = await ask('No runner for this file type.\nEnter command ({file} = path):', `"${tab.path}"`);
      if (!cmd) return;
      cmd = cmd.replace('{file}', tab.path);
    }
    App.runInTerminal(cmd);
  },

  async launchActive() {
    const tab = state.tabs.find(t => t.path === state.activeTab);
    if (!tab) return;
    await App.saveActive();
    const outputEl = document.getElementById('output-text');
    if (outputEl) outputEl.textContent = '';
    App.switchPanel('output', document.querySelector('.panel-tab[data-panel="output"]'));
    api.removeGameListeners?.();
    api.onGameOutput?.(data => {
      const el = document.getElementById('output-text');
      if (el) { el.textContent += data; el.scrollTop = el.scrollHeight; AI.captureOutput(data); }
    });
    const result = await api.launchAsApp(tab.path, state.rootPath);
    if (!result?.ok) {
      const el = document.getElementById('output-text');
      if (el) el.textContent = `[Launch failed: ${result?.error}]\n`;
    }
  },

  async runInTerminal(cmd) {
    let terminal = App.getActiveTerminal();
    if (!terminal || terminal.exited || terminal.closed) {
      terminal = await App.createTerminal(state.rootPath || null, { activate: true });
    }
    const bp = document.getElementById('bottom-panel');
    if (bp.style.display === 'none') {
      bp.style.display = '';
      const rh = document.getElementById('resize-handle');
      if (rh) rh.style.display = '';
    }
    App.switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
    AI.clearErrorBuffer();
    App.activateTerminal(terminal.id, { fit: true });

    // Visual command indicator
    const label = cmd.length > 72 ? cmd.slice(0, 69) + '…' : cmd;
    terminal.term.write(`\r\n\x1b[2m\x1b[36m▶ ${label}\x1b[0m\r\n`);
    terminal.pendingEcho = cmd;
    api.termWrite(terminal.id, cmd + '\r\n');
  },

  // ── Word wrap toggle ──────────────────────────────────────────────────────────
  toggleWordWrap() {
    if (!state.editor) return;
    state.wordWrap = state.wordWrap === 'on' ? 'off' : 'on';
    state.editor.updateOptions({ wordWrap: state.wordWrap });
    document.getElementById('btn-wordwrap')?.classList.toggle('active', state.wordWrap === 'on');
  },

  // ── Panel switching ───────────────────────────────────────────────────────────
  switchPanel(name, btn) {
    document.querySelectorAll('.panel-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.panel-tab').forEach(el => el.classList.remove('active'));
    document.getElementById(`panel-${name}`)?.classList.add('active');
    btn?.classList.add('active');
    if (name === 'terminal') {
      const t = App.getActiveTerminal();
      if (t && !t.closed) {
        requestAnimationFrame(() => {
          if (state.activeTermId !== t.id || t.pane.offsetParent === null) return;
          t.fitAddon.fit();
          t.term.scrollToBottom();
          t.term.focus();
        });
      }
    }
  },

  togglePanel(name) {
    if (name === 'ai') {
      document.getElementById('ai-panel').classList.toggle('hidden');
    } else if (name === 'terminal') {
      const bp = document.getElementById('bottom-panel');
      const rh = document.getElementById('resize-handle');
      const wasHidden = bp.style.display === 'none';
      bp.style.display = wasHidden ? '' : 'none';
      if (rh) rh.style.display = wasHidden ? '' : 'none';
      if (wasHidden) App.switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
    }
  },

  focusActiveTerminal() {
    const t = App.getActiveTerminal();
    if (t && !t.closed && !t.exited) { t.fitAddon.fit(); t.term.focus(); }
  },
};

// ── Terminal panel mousedown → focus ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('panel-terminal')?.addEventListener('mousedown', e => {
    if (e.target.closest('#terminal-toolbar')) return;
    App.focusActiveTerminal();
  });
});

// ── Extensions ────────────────────────────────────────────────────────────────
const Extensions = (() => {
  const SK = 'fallen_extensions';

  const CATALOG = [
    { id:'th-dracula', name:'Dracula Theme',    publisher:'Zeno Rocha',        cat:'Themes',           icon:'🧛', desc:'Dark purple theme — the original Dracula',                themeId:'dracula' },
    { id:'th-monokai', name:'Monokai Pro',      publisher:'Wimer Hazenberg',   cat:'Themes',           icon:'🎨', desc:'Vibrant dark theme with colourful syntax highlighting',   themeId:'monokai' },
    { id:'th-onedark', name:'One Dark Pro',     publisher:'binaryify',         cat:'Themes',           icon:'🌙', desc:"Atom's iconic One Dark theme for Monaco",                 themeId:'onedark' },
    { id:'th-nord',    name:'Nord',             publisher:'Arctic Ice Studio',  cat:'Themes',           icon:'❄️', desc:'Arctic north-bluish minimal colour scheme',               themeId:'nord' },
    { id:'fmt-prettier',name:'Prettier',        publisher:'Prettier',          cat:'Formatters',       icon:'💅', desc:'Opinionated formatter for JS/TS/HTML/CSS/JSON',           installCmd:'npm install -g prettier' },
    { id:'fmt-black',  name:'Black',            publisher:'Python SF',         cat:'Formatters',       icon:'🐍', desc:'The uncompromising Python code formatter',                installCmd:'pip install black' },
    { id:'fmt-autopep8',name:'autopep8',        publisher:'hhatto',            cat:'Formatters',       icon:'🔧', desc:'Automatically formats Python to PEP 8 style',            installCmd:'pip install autopep8' },
    { id:'lint-eslint',name:'ESLint',           publisher:'Microsoft',         cat:'Linters',          icon:'🔍', desc:'Pluggable static analysis for JS and TS',                installCmd:'npm install -g eslint' },
    { id:'lint-ruff',  name:'Ruff',             publisher:'Astral',            cat:'Linters',          icon:'⚡', desc:'Extremely fast Python linter written in Rust',           installCmd:'pip install ruff' },
    { id:'lint-pylint',name:'Pylint',           publisher:'PyCQA',             cat:'Linters',          icon:'🔎', desc:'Full-featured Python static code analyser',              installCmd:'pip install pylint' },
    { id:'lang-go',    name:'Go Tools',         publisher:'Google',            cat:'Language Support', icon:'🐹', desc:'gopls language server and core Go tools',                installCmd:'go install golang.org/x/tools/gopls@latest' },
    { id:'lang-rust',  name:'Rust Analyzer',    publisher:'rust-lang',         cat:'Language Support', icon:'🦀', desc:'Rust language server with IntelliSense',                 installCmd:'rustup component add rust-analyzer' },
    { id:'util-tsnode',name:'ts-node',          publisher:'TypeStrong',        cat:'Utilities',        icon:'🔷', desc:'TypeScript execution and REPL for Node.js',              installCmd:'npm install -g ts-node typescript' },
    { id:'util-nodemon',name:'nodemon',         publisher:'Remy Sharp',        cat:'Utilities',        icon:'👁️', desc:'Auto-restart Node apps on file changes',                 installCmd:'npm install -g nodemon' },
    { id:'util-http',  name:'http-server',      publisher:'http-party',        cat:'Utilities',        icon:'🌐', desc:'Zero-config command-line HTTP server',                   installCmd:'npm install -g http-server' },
  ];

  const THEMES = {
    dracula: { base:'vs-dark', inherit:true,
      rules:[{token:'comment',foreground:'6272a4',fontStyle:'italic'},{token:'keyword',foreground:'ff79c6'},{token:'string',foreground:'f1fa8c'},{token:'number',foreground:'bd93f9'},{token:'function',foreground:'50fa7b'},{token:'type',foreground:'8be9fd'}],
      colors:{'editor.background':'#282a36','editor.foreground':'#f8f8f2','editor.selectionBackground':'#44475a','editorCursor.foreground':'#f8f8f2','editorLineNumber.foreground':'#6272a4'} },
    monokai: { base:'vs-dark', inherit:true,
      rules:[{token:'comment',foreground:'75715e',fontStyle:'italic'},{token:'keyword',foreground:'f92672'},{token:'string',foreground:'e6db74'},{token:'number',foreground:'ae81ff'},{token:'function',foreground:'a6e22e'},{token:'type',foreground:'66d9e8'}],
      colors:{'editor.background':'#272822','editor.foreground':'#f8f8f2','editor.selectionBackground':'#49483e','editorCursor.foreground':'#f8f8f0','editorLineNumber.foreground':'#90908a'} },
    onedark: { base:'vs-dark', inherit:true,
      rules:[{token:'comment',foreground:'5c6370',fontStyle:'italic'},{token:'keyword',foreground:'c678dd'},{token:'string',foreground:'98c379'},{token:'number',foreground:'d19a66'},{token:'function',foreground:'61afef'},{token:'type',foreground:'e5c07b'}],
      colors:{'editor.background':'#282c34','editor.foreground':'#abb2bf','editor.selectionBackground':'#3e4451','editorCursor.foreground':'#528bff','editorLineNumber.foreground':'#4b5263'} },
    nord: { base:'vs-dark', inherit:true,
      rules:[{token:'comment',foreground:'616e88',fontStyle:'italic'},{token:'keyword',foreground:'81a1c1'},{token:'string',foreground:'a3be8c'},{token:'number',foreground:'b48ead'},{token:'function',foreground:'88c0d0'},{token:'type',foreground:'8fbcbb'}],
      colors:{'editor.background':'#2e3440','editor.foreground':'#d8dee9','editor.selectionBackground':'#434c5e','editorCursor.foreground':'#d8dee9','editorLineNumber.foreground':'#4c566a'} },
  };

  const getState = () => { try { return JSON.parse(localStorage.getItem(SK) || '{}'); } catch { return {}; } };
  const setState = s => localStorage.setItem(SK, JSON.stringify(s));

  let query = '';

  function init() {
    for (const [id, data] of Object.entries(THEMES)) monaco.editor.defineTheme(id, data);
    const s = getState();
    for (const ext of CATALOG) {
      if (ext.themeId && s[ext.id]?.installed && s[ext.id]?.enabled) {
        monaco.editor.setTheme(ext.themeId); break;
      }
    }
  }

  function search(q) { query = q; render(); }

  function render() {
    const list = document.getElementById('ext-list');
    if (!list) return;
    const s = getState();
    const q = query.toLowerCase();
    const filtered = q ? CATALOG.filter(e => e.name.toLowerCase().includes(q) || e.desc.toLowerCase().includes(q) || e.cat.toLowerCase().includes(q)) : CATALOG;
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
        const es = s[ext.id] || {};
        const card = document.createElement('div');
        card.className = 'ext-card';
        const badge = es.installed ? (es.enabled ? '<span class="ext-badge enabled">Enabled</span>' : '<span class="ext-badge disabled">Disabled</span>') : '';
        card.innerHTML = `
          <div class="ext-card-top">
            <span class="ext-icon">${ext.icon}</span>
            <div class="ext-info">
              <div class="ext-name">${ext.name} ${badge}</div>
              <div class="ext-pub">${ext.publisher} · ${ext.cat}</div>
            </div>
          </div>
          <div class="ext-desc">${ext.desc}</div>
          <div class="ext-actions"></div>`;
        const acts = card.querySelector('.ext-actions');

        if (ext.themeId) {
          if (!es.installed) {
            const b = document.createElement('button');
            b.textContent = 'Apply Theme';
            b.onclick = () => {
              monaco.editor.setTheme(ext.themeId);
              const ns = getState();
              for (const e2 of CATALOG) if (e2.themeId) { const s2 = ns[e2.id] || {}; s2.installed = true; s2.enabled = false; ns[e2.id] = s2; }
              ns[ext.id] = { installed: true, enabled: true };
              setState(ns);
              render();
            };
            acts.appendChild(b);
          } else {
            if (!es.enabled) {
              const b = document.createElement('button');
              b.textContent = 'Apply';
              b.onclick = () => {
                monaco.editor.setTheme(ext.themeId);
                const ns = getState();
                for (const e2 of CATALOG) if (e2.themeId && ns[e2.id]) ns[e2.id].enabled = false;
                ns[ext.id] = { installed: true, enabled: true };
                setState(ns); render();
              };
              acts.appendChild(b);
            }
            const r = document.createElement('button');
            r.textContent = 'Reset to Default';
            r.onclick = () => {
              monaco.editor.setTheme('vs-dark');
              const ns = getState();
              for (const e2 of CATALOG) if (e2.themeId && ns[e2.id]) ns[e2.id].enabled = false;
              setState(ns); render();
            };
            acts.appendChild(r);
          }
        } else if (ext.installCmd) {
          if (!es.installed) {
            const b = document.createElement('button');
            b.textContent = 'Install';
            b.onclick = () => {
              App.switchPanel('terminal', document.querySelector('.panel-tab[data-panel="terminal"]'));
              App.runInTerminal(ext.installCmd);
              const ns = getState(); ns[ext.id] = { installed: true, enabled: true }; setState(ns); render();
            };
            acts.appendChild(b);
          } else {
            if (es.enabled) {
              const b = document.createElement('button'); b.textContent = 'Disable';
              b.onclick = () => { const ns = getState(); ns[ext.id].enabled = false; setState(ns); render(); };
              acts.appendChild(b);
            } else {
              const b = document.createElement('button'); b.textContent = 'Enable';
              b.onclick = () => { const ns = getState(); ns[ext.id].enabled = true; setState(ns); render(); };
              acts.appendChild(b);
            }
            const r = document.createElement('button'); r.textContent = 'Remove';
            r.onclick = () => { const ns = getState(); delete ns[ext.id]; setState(ns); render(); };
            acts.appendChild(r);
          }
        }
        list.appendChild(card);
      }
    }
  }

  return { init, render, search };
})();
