// ── AI agent ──────────────────────────────────────────────────────────────────
const AI = (() => {
  // ── Multi-chat state ──────────────────────────────────────────────────────────
  let chats = [];
  let currentChatIdx = -1;
  let streamCounter = 0;
  let currentStreamId = null;
  let stopRequested = false;
  let lastError = '';
  let errorBuffer = '';
  let lastEdit = null;
  let agentRunning = false;
  let mode = 'ask';

  // ── Context meter state ───────────────────────────────────────────────────────
  let contextWindowSize = 20000;
  let contextTokensUsed = 0;

  const modeLabels = { ask: 'Ask', agent: 'Agent', plan: 'Plan' };

  // ── Chat management ───────────────────────────────────────────────────────────
  function createChat() {
    const msgsEl = document.createElement('div');
    msgsEl.className = 'chat-session';
    msgsEl.style.display = 'none';
    document.getElementById('ai-messages').appendChild(msgsEl);
    chats.push({ name: `Chat ${chats.length + 1}`, history: [], msgsEl });
    return chats.length - 1;
  }

  function switchChat(idx) {
    if (currentChatIdx >= 0 && chats[currentChatIdx]) {
      chats[currentChatIdx].msgsEl.style.display = 'none';
    }
    currentChatIdx = idx;
    chats[idx].msgsEl.style.display = '';
    renderChatTabs();
  }

  function newChat() {
    const idx = createChat();
    switchChat(idx);
  }

  function renderChatTabs() {
    const bar = document.getElementById('ai-chats-bar');
    if (!bar) return;
    bar.innerHTML = '';
    chats.forEach((chat, i) => {
      const tab = document.createElement('button');
      tab.className = 'chat-tab' + (i === currentChatIdx ? ' active' : '');
      tab.textContent = chat.name;
      tab.onclick = () => { if (!agentRunning) switchChat(i); };
      bar.appendChild(tab);
    });
    const btn = document.createElement('button');
    btn.className = 'chat-tab chat-tab-new';
    btn.title = 'New Chat';
    btn.textContent = '+';
    btn.onclick = () => { if (!agentRunning) newChat(); };
    bar.appendChild(btn);
  }

  // ── Mode management ───────────────────────────────────────────────────────────
  function updateModeButtons() {
    document.querySelectorAll('.ai-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.aiMode === mode));
  }

  function setMode(nextMode) {
    if (!modeLabels[nextMode]) return;
    mode = nextMode;
    updateModeButtons();
  }

  // ── Error capture ─────────────────────────────────────────────────────────────
  function captureOutput(data) {
    errorBuffer += data;
    if (errorBuffer.length > 8000) errorBuffer = errorBuffer.slice(-8000);
    if (/error|exception|traceback|warning|failed|undefined|cannot|not found/i.test(data)) {
      lastError = errorBuffer.slice(-3000);
      document.getElementById('btn-explain-error').classList.remove('hidden');
    }
  }

  function clearErrorBuffer() {
    errorBuffer = '';
    lastError = '';
    document.getElementById('btn-explain-error').classList.add('hidden');
  }

  // ── System prompt ─────────────────────────────────────────────────────────────
  function buildSystemPrompt(currentMode) {
    const activeTab = state.tabs.find(t => t.path === state.activeTab);
    let ctx = 'You are Fallen AI 1.0 Super, an expert coding assistant built into Fallen IDE. You were created for the Fallen IDE project. Your name is Fallen AI and your version is 1.0 Super.\n';

    if (activeTab) {
      ctx += `\nCurrent file: ${activeTab.path}\nLanguage: ${App.detectLang(activeTab.path)}\n`;
      const code = activeTab.model.getValue();
      if (code.length < 6000) ctx += `\nFile contents:\n\`\`\`\n${code}\n\`\`\`\n`;
      else ctx += `\n(File too large to include fully — ${code.length} chars)\n`;
    }

    if (currentMode === 'plan') {
      ctx += `
You are in PLAN MODE.
- Produce a concise, practical plan only.
- Do not include file edits, code blocks, or terminal commands.
- If external context is needed, use WEB_SEARCH or FETCH_URL, then summarize the plan clearly.
`;
    } else if (currentMode === 'agent') {
      ctx += `
You are in AGENT MODE with full access to the file system and web.

File tools (use these to explore before editing):
<READ path="filepath" />                           — read any file's full contents
<LIST path="dirpath" />                            — list files in a directory
<SEARCH_FILES root="." pattern="*.js" />           — find files matching a name pattern
<GREP root="." query="text to find" />             — search text content across files

Edit / run tools:
<EDIT path="FILEPATH">
\`\`\`
<complete new file content>
\`\`\`
</EDIT>                                            — write a complete file (always output full content)
<RUN>command here</RUN>                            — run a PowerShell command (IMPORTANT: the terminal is Windows PowerShell, NOT cmd.exe — always use PowerShell syntax: Get-ChildItem, Select-String, $env:VAR, etc. — never use cmd.exe syntax like dir /s, findstr, set VAR, etc.)

Web tools:
<WEB_SEARCH query="search terms" />               — search the web
<FETCH_URL url="https://example.com" />            — fetch a web page's text content

Rules:
- Use READ before EDIT so you know what you are replacing.
- EDIT blocks must contain the COMPLETE file — never partial snippets.
- After any tool call, use the returned results and continue with your answer.
- Call tools one at a time; wait for each result before the next.
`;
    } else {
      ctx += '\nYou are in ASK MODE. Answer directly and clearly. You may use WEB_SEARCH and FETCH_URL when external information is needed.';
    }

    ctx += '\nCRITICAL: After any tool result is returned you MUST continue generating a complete user-facing response. After EDIT always write a brief summary of what changed. After RUN describe what happened. Never produce an empty or one-word reply after a tool — always complete your answer.\n';
    return ctx;
  }

  // ── Tool parsing ──────────────────────────────────────────────────────────────
  function parseToolCalls(response, currentMode) {
    const found = [];
    let m;

    // EDIT: code fences inside the block are optional — strip them if present
    const editRe = /<EDIT\s+path=(?:"([^"]+)"|'([^']+)')>([\s\S]*?)<\/EDIT>/gi;
    const runRe = /<RUN>([\s\S]*?)<\/RUN>/gi;
    const searchRe = /<WEB_SEARCH\s+query=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;
    const fetchRe = /<FETCH_URL\s+url=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;
    const readRe = /<READ\s+path=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;
    const listRe = /<LIST\s+path=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;
    const sfRe = /<SEARCH_FILES\s+root=(?:"([^"]+)"|'([^']+)')\s+pattern=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;
    const grepRe = /<GREP\s+root=(?:"([^"]+)"|'([^']+)')\s+query=(?:"([^"]+)"|'([^']+)')\s*\/?>/gi;

    while ((m = editRe.exec(response)) !== null) {
      const filePath = m[1] || m[2];
      let content = m[3];
      // Strip an optional wrapping code fence (```lang\n...\n```)
      const fenceMatch = content.match(/^\s*```[\w-]*\r?\n([\s\S]*?)```\s*$/);
      content = fenceMatch ? fenceMatch[1] : content.replace(/^\n/, '').replace(/\n$/, '');
      found.push({ index: m.index, type: 'EDIT', path: filePath, content });
    }
    while ((m = runRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'RUN', command: m[1].trim() });
    while ((m = searchRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'WEB_SEARCH', query: m[1] || m[2] });
    while ((m = fetchRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'FETCH_URL', url: m[1] || m[2] });
    while ((m = readRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'READ', path: m[1] || m[2] });
    while ((m = listRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'LIST', path: m[1] || m[2] });
    while ((m = sfRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'SEARCH_FILES', root: m[1] || m[2], pattern: m[3] || m[4] });
    while ((m = grepRe.exec(response)) !== null)
      found.push({ index: m.index, type: 'GREP', root: m[1] || m[2], query: m[3] || m[4] });

    const webOnly = new Set(['WEB_SEARCH', 'FETCH_URL']);
    return found.sort((a, b) => a.index - b.index).filter(tool =>
      currentMode === 'agent' || webOnly.has(tool.type)
    );
  }

  // ── Tool execution ────────────────────────────────────────────────────────────
  async function executeToolCalls(tools, currentMode) {
    const results = [];

    for (const tool of tools) {
      if (tool.type === 'WEB_SEARCH') {
        const result = await api.webSearch(tool.query);
        addSystemMessage(`Web search: "${tool.query}"`);
        results.push(`[WEB_SEARCH query="${tool.query}"]\n${result}`);
        continue;
      }

      if (tool.type === 'FETCH_URL') {
        const result = await api.webRead(tool.url);
        addSystemMessage(`Fetched: ${tool.url}`);
        results.push(`[FETCH_URL url="${tool.url}"]\n${result}`);
        continue;
      }

      if (tool.type === 'READ') {
        const result = await api.readFile(tool.path);
        addSystemMessage(`Read: ${tool.path}`);
        const content = typeof result === 'string' ? result.slice(0, 12000) : '(could not read file)';
        results.push(`[READ path="${tool.path}"]\n${content}`);
        continue;
      }

      if (tool.type === 'LIST') {
        const result = await api.readDir(tool.path);
        addSystemMessage(`Listed: ${tool.path}`);
        const listing = Array.isArray(result)
          ? result.map(e => `${e.isDir ? 'dir' : 'file'}  ${e.name}`).join('\n')
          : '(could not list directory)';
        results.push(`[LIST path="${tool.path}"]\n${listing}`);
        continue;
      }

      if (tool.type === 'SEARCH_FILES') {
        const root = state.rootPath || tool.root;
        const result = await api.searchFiles(root, tool.pattern);
        addSystemMessage(`Search files: "${tool.pattern}"`);
        results.push(`[SEARCH_FILES pattern="${tool.pattern}"]\n${Array.isArray(result) ? result.join('\n') : result}`);
        continue;
      }

      if (tool.type === 'GREP') {
        const root = state.rootPath || tool.root;
        const result = await api.grepFiles(root, tool.query);
        addSystemMessage(`Grep: "${tool.query}"`);
        const lines = Array.isArray(result)
          ? result.map(r => `${r.file}:${r.line}: ${r.content}`).join('\n')
          : String(result);
        results.push(`[GREP query="${tool.query}"]\n${lines}`);
        continue;
      }

      if (currentMode !== 'agent') continue;

      if (tool.type === 'EDIT') {
        await api.writeFile(tool.path, tool.content);
        const tab = state.tabs.find(t => t.path === tool.path);
        if (tab) {
          const pos = state.editor?.getPosition();
          tab.model.setValue(tool.content);
          tab.modified = false;
          if (state.activeTab === tool.path && pos) state.editor.setPosition(pos);
          App.renderTabs();
        }
        addSystemMessage(`Edited: ${tool.path}`);
        results.push(`[EDIT path="${tool.path}"]\nApplied successfully.`);
      } else if (tool.type === 'RUN') {
        addSystemMessage(`Running: ${tool.command}`);
        App.runInTerminal(tool.command);
        results.push(`[RUN]\n${tool.command}`);
      }
    }

    return results;
  }

  // ── Strip tool markup ─────────────────────────────────────────────────────────
  function stripToolMarkup(text) {
    return String(text || '')
      .replace(/<EDIT\s+path=(?:"[^"]+"|'[^']+')>[\s\S]*?<\/EDIT>/gi, '')
      .replace(/<RUN>[\s\S]*?<\/RUN>/gi, '')
      .replace(/<(?:WEB_SEARCH|FETCH_URL|READ|LIST|SEARCH_FILES|GREP)\s[^>]*\/?>/gi, '')
      .trim();
  }

  // ── Prepare text for display: strip tool tags + Qwen <think> blocks ───────────
  function prepareForDisplay(text) {
    return String(text || '')
      // Strip model chain-of-thought blocks (Qwen 3.x emits these)
      .replace(/<think>[\s\S]*?<\/think>/gi, '')
      // Replace EDIT blocks with a single annotation so code fences inside don't
      // trigger the "Generating code…" spinner during and after streaming
      .replace(/<EDIT\s+path=(?:"([^"]+)"|'([^']+)')>[\s\S]*?<\/EDIT>/gi,
        (_, p1, p2) => `\n*[Editing: ${p1 || p2}]*\n`)
      // Strip RUN blocks — terminal shows the command separately
      .replace(/<RUN>([\s\S]*?)<\/RUN>/gi,
        (_, cmd) => `\n*[Running: ${cmd.trim()}]*\n`)
      // Strip self-closing tool tags entirely
      .replace(/<(?:WEB_SEARCH|FETCH_URL|READ|LIST|SEARCH_FILES|GREP)\s[^>]*\/?>/gi, '')
      // Collapse excessive blank lines left by removal
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────────
  function escapeHtml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
          <span class="ai-code-label">${label}</span>
          <span class="ai-code-lines">${lineCount} line${lineCount === 1 ? '' : 's'}</span>
        </summary>
        <pre><code>${escapeHtml(code)}</code></pre>
      </details>
    `;
  }

  // ── Context meter helpers ─────────────────────────────────────────────────────
  function setContextWindow(size) {
    contextWindowSize = size || 20000;
    updateContextMeterUI();
  }

  function updateContextMeterUI() {
    const fill  = document.getElementById('context-meter-fill');
    const label = document.getElementById('context-meter-label');
    if (!fill || !label) return;
    const pct = Math.min(100, Math.round((contextTokensUsed / contextWindowSize) * 100));
    fill.style.width = pct + '%';
    fill.style.background = pct > 80 ? '#f44747' : pct > 50 ? '#ffa500' : '#0078d4';
    label.textContent = `${contextTokensUsed.toLocaleString()} / ${contextWindowSize.toLocaleString()} tokens`;
  }

  function updateContextFromUsage(usage) {
    if (usage?.total_tokens) {
      contextTokensUsed = usage.total_tokens;
      updateContextMeterUI();
    }
  }

  function estimateContextFromMessages(messages, extraResponse) {
    const chars = messages.reduce((s, m) => s + (m.content?.length || 0), 0) + (extraResponse?.length || 0);
    return Math.round(chars / 4);
  }

  function renderRichText(content) {
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
    // Detect an unclosed code fence (AI is still generating code)
    const partialIdx = remaining.indexOf('```');
    if (partialIdx !== -1) {
      html += renderInlineMarkup(remaining.slice(0, partialIdx));
      html += '<div class="ai-code-generating"><span class="ai-code-gen-spinner"></span> Generating code…<span class="ai-code-gen-hint">(click to expand when done)</span></div>';
    } else {
      html += renderInlineMarkup(remaining);
    }
    return html;
  }

  function currentMsgsEl() {
    return chats[currentChatIdx]?.msgsEl ?? document.getElementById('ai-messages');
  }

  function addMessage(role, content) {
    const wrapper = document.createElement('div');
    wrapper.className = `ai-msg-wrapper ${role}`;

    const label = document.createElement('span');
    label.className = 'ai-msg-label';
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    label.textContent = (role === 'user' ? 'You' : 'Fallen AI 1.0') + ' · ' + timestamp;
    wrapper.appendChild(label);

    const bubble = document.createElement('div');
    bubble.className = `ai-msg ${role}`;
    wrapper.appendChild(bubble);

    const contentEl = document.createElement('div');
    contentEl.className = 'ai-msg-content';
    contentEl.innerHTML = renderRichText(content);
    contentEl.dataset.raw = content;
    bubble.appendChild(contentEl);

    const copyBtn = document.createElement('button');
    copyBtn.className = 'ai-msg-copy-btn';
    copyBtn.title = 'Copy message';
    copyBtn.textContent = '⎘';
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(contentEl.dataset.raw || contentEl.innerText).then(() => {
        copyBtn.textContent = '✓';
        setTimeout(() => { copyBtn.textContent = '⎘'; }, 1500);
      });
    };
    bubble.appendChild(copyBtn);

    currentMsgsEl().appendChild(wrapper);
    wrapper.scrollIntoView({ behavior: 'smooth' });
    return contentEl;
  }

  function addSystemMessage(text) {
    const el = document.createElement('div');
    el.className = 'ai-msg system-msg';
    el.textContent = text;
    currentMsgsEl().appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
  }

  // ── Loading / stop ────────────────────────────────────────────────────────────
  function setLoading(on) {
    document.getElementById('ai-send').style.display = on ? 'none' : '';
    document.getElementById('ai-stop').style.display = on ? '' : 'none';
  }

  function stop() {
    if (currentStreamId !== null) {
      stopRequested = true;
      api.aiAbort(currentStreamId);
    }
  }

  // ── Streaming turn ────────────────────────────────────────────────────────────
  function streamTurn(messages) {
    return new Promise((resolve, reject) => {
      const id = ++streamCounter;
      currentStreamId = id;
      const msgEl = addMessage('assistant', '▋');
      let fullResponse = '';

      api.onAiChunk(id, chunk => {
        fullResponse += chunk;
        // Strip tool markup + think blocks before rendering so code fences
        // inside <EDIT> blocks never trigger the "Generating code…" spinner
        msgEl.innerHTML = renderRichText(prepareForDisplay(fullResponse)) + '<span style="opacity:.5">▋</span>';
        msgEl.dataset.raw = fullResponse;
        msgEl.scrollIntoView({ behavior: 'smooth' });
      });

      api.onAiUsage(id, usage => updateContextFromUsage(usage));

      api.onAiDone(id, err => {
        currentStreamId = null;
        api.removeAiListeners(id);
        if (err) {
          if (stopRequested) {
            msgEl.innerHTML = renderRichText(prepareForDisplay(fullResponse)) +
              '<span style="color:#858585;font-style:italic"> [stopped]</span>';
            msgEl.dataset.raw = fullResponse;
            stopRequested = false;
            resolve('__stopped__');
          } else {
            msgEl.innerHTML = `<span style="color:#f44747">Error: ${err}</span>`;
            reject(new Error(err));
          }
          return;
        }
        // Final render: strip tool markup so the display is clean
        msgEl.innerHTML = renderRichText(prepareForDisplay(fullResponse));
        msgEl.dataset.raw = fullResponse;
        resolve(fullResponse);
      });

      api.aiStream(id, messages);
    });
  }

  // ── Send message ──────────────────────────────────────────────────────────────
  async function send() {
    const input = document.getElementById('ai-input');
    const text = input.value.trim();
    if (!text || agentRunning) return;

    const currentMode = mode;
    const chat = chats[currentChatIdx];
    input.value = '';
    addMessage('user', text);
    chat.history.push({ role: 'user', content: text });

    const systemPrompt = buildSystemPrompt(currentMode);
    const systemMessage = { role: 'system', content: systemPrompt };
    setLoading(true);
    agentRunning = true;

    let messages = [systemMessage, ...chat.history];
    let finalResponse = '';

    try {
      for (let i = 0; i < 6; i++) {
        const response = await streamTurn(messages);
        if (response === '__stopped__') break;

        finalResponse = response;
        chat.history.push({ role: 'assistant', content: response });

        const tools = parseToolCalls(response, currentMode);
        if (!tools.length) break;

        addSystemMessage(`Running: ${tools.map(t => t.type).join(', ')}`);
        const toolResults = await executeToolCalls(tools, currentMode);
        if (!toolResults.length) break;

        const hasEdit = tools.some(t => t.type === 'EDIT');
        const hasRun  = tools.some(t => t.type === 'RUN');
        let contMsg = `Tool results:\n\n${toolResults.join('\n\n---\n\n')}\n\n`;
        contMsg += hasEdit
          ? 'The file was edited successfully. Write a clear, friendly summary of exactly what you changed and why, then ask if there is anything else to do.'
          : hasRun
          ? 'The command ran. Describe what happened and whether any follow-up is needed.'
          : 'Use these results to continue your answer.';
        messages = [
          systemMessage,
          ...chat.history,
          { role: 'user', content: contMsg },
        ];
      }

      const code = extractCodeBlock(finalResponse);
      if (code && state.activeTab) {
        lastEdit = { path: state.activeTab, newContent: code };
        document.getElementById('btn-apply-edit').classList.remove('hidden');
      }

      // Fallback estimate if LM Studio didn't return usage data
      const estimated = estimateContextFromMessages(messages, finalResponse);
      if (estimated > contextTokensUsed) {
        contextTokensUsed = estimated;
        updateContextMeterUI();
      }
    } catch (e) {
      addSystemMessage(`Error: ${e.message}`);
    } finally {
      setLoading(false);
      agentRunning = false;
    }
  }

  // ── Utilities ─────────────────────────────────────────────────────────────────
  function extractCodeBlock(response) {
    const m = String(response || '').match(/```[\w-]*\n([\s\S]*?)```/);
    return m ? m[1] : null;
  }

  async function applyLastEdit() {
    if (!lastEdit || !lastEdit.path) return;
    const tab = state.tabs.find(t => t.path === lastEdit.path);
    if (tab) {
      tab.model.setValue(lastEdit.newContent);
      tab.modified = true;
      App.renderTabs();
    } else {
      await api.writeFile(lastEdit.path, lastEdit.newContent);
    }
    document.getElementById('btn-apply-edit').classList.add('hidden');
    addSystemMessage(`Applied edit to: ${lastEdit.path.split(/[\\/]/).pop()}`);
    lastEdit = null;
  }

  async function explainError() {
    if (!lastError) return;
    document.getElementById('ai-panel').classList.remove('hidden');
    const activeTab = state.tabs.find(t => t.path === state.activeTab);
    let prompt = `I got the following error in my terminal:\n\n\`\`\`\n${lastError.slice(-2000)}\n\`\`\`\n\n`;
    prompt += activeTab
      ? `The current file is ${activeTab.name}. Please identify the bug and fix it.`
      : 'Please identify the issue and explain how to fix it.';
    document.getElementById('ai-input').value = prompt;
    setMode('agent');
    await send();
  }

  async function askAboutFile(filePath) {
    document.getElementById('ai-panel').classList.remove('hidden');
    const name = filePath.split(/[\\/]/).pop();
    document.getElementById('ai-input').value = `Explain what ${name} does and how it works.`;
    await App.openFile(filePath);
    await send();
  }

  // ── Clear chat ────────────────────────────────────────────────────────────────
  function clearCurrentChat() {
    if (agentRunning) return;
    const chat = chats[currentChatIdx];
    if (!chat) return;
    chat.history = [];
    chat.msgsEl.innerHTML = '';
    contextTokensUsed = 0;
    updateContextMeterUI();
    lastEdit = null;
    document.getElementById('btn-apply-edit').classList.add('hidden');
    document.getElementById('btn-explain-error').classList.add('hidden');
  }

  // ── Init ──────────────────────────────────────────────────────────────────────
  document.getElementById('ai-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  newChat();
  updateModeButtons();

  return { send, stop, newChat, applyLastEdit, explainError, askAboutFile, captureOutput, clearErrorBuffer, setMode, setContextWindow, clearCurrentChat };
})();
