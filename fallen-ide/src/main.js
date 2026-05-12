import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import squirrelStartup from 'electron-squirrel-startup';
import path from 'node:path';
import fs from 'node:fs';
import cp from 'node:child_process';
import http from 'node:http';
import https from 'node:https';
import os from 'node:os';

if (squirrelStartup) app.quit();

// In dev mode the renderer files are plain <script> tags with no Vite HMR;
// disable Electron's HTTP cache so every launch picks up the latest files on disk.
if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
  app.commandLine.appendSwitch('disable-http-cache');
}

const AI_HOST = 'http://10.0.0.80:1234';
let mainWindow;
const terminals = {};
let termIdCounter = 0;

const createWindow = () => {
  mainWindow = new BrowserWindow({
    width: 1400, height: 900, minWidth: 800, minHeight: 500,
    backgroundColor: '#1e1e1e', frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }
};

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });

// Window controls
ipcMain.on('win:minimize', () => mainWindow.minimize());
ipcMain.on('win:maximize', () => mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize());
ipcMain.on('win:close',    () => mainWindow.close());

// File system
ipcMain.handle('fs:openFolder', async () => {
  const r = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('fs:readDir', async (_, dirPath) => {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true })
      .map(e => ({ name: e.name, path: path.join(dirPath, e.name), isDir: e.isDirectory() }))
      .sort((a, b) => a.isDir !== b.isDir ? (a.isDir ? -1 : 1) : a.name.localeCompare(b.name));
  } catch { return []; }
});
ipcMain.handle('fs:readFile',  async (_, p) => { try { return fs.readFileSync(p, 'utf8'); } catch { return null; } });
ipcMain.handle('fs:writeFile', async (_, p, c) => { try { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, c, 'utf8'); return true; } catch { return false; } });
ipcMain.handle('fs:newFile', async (_, dirPath) => {
  const r = await dialog.showSaveDialog(mainWindow, { defaultPath: path.join(dirPath || os.homedir(), 'untitled.txt') });
  if (r.canceled) return null;
  fs.writeFileSync(r.filePath, '', 'utf8');
  return r.filePath;
});
ipcMain.handle('fs:deleteFile', async (_, p) => { try { await shell.trashItem(p); return true; } catch { return false; } });
ipcMain.handle('fs:rename', async (_, oldPath, newName) => {
  const newPath = path.join(path.dirname(oldPath), newName);
  try { fs.renameSync(oldPath, newPath); return newPath; } catch { return null; }
});

// Terminal
ipcMain.handle('term:create', async (_, cwd) => {
  const id = ++termIdCounter;
  // On Windows, start PowerShell with UTF-8 encoding set before the interactive session
  // so that Unicode file paths (e.g. Arabic/Persian) are passed correctly to child processes.
  const isWin = process.platform === 'win32';
  const sh   = isWin ? 'powershell.exe' : 'bash';
  const args = isWin
    ? ['-NoLogo', '-NoExit', '-Command',
       'chcp 65001 | Out-Null; [Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8']
    : [];
  const proc = cp.spawn(sh, args, {
    cwd: cwd || os.homedir(),
    env: { ...process.env, TERM: 'xterm-256color', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    windowsHide: true,
  });
  terminals[id] = proc;
  proc.stdout.on('data', d => mainWindow.webContents.send(`term:data:${id}`, d.toString('utf8')));
  proc.stderr.on('data', d => mainWindow.webContents.send(`term:data:${id}`, d.toString('utf8')));
  proc.on('exit', () => { mainWindow.webContents.send(`term:exit:${id}`); delete terminals[id]; });
  return id;
});
ipcMain.on('term:write', (_, id, data) => { if (terminals[id]) terminals[id].stdin.write(data, 'utf8'); });
ipcMain.on('term:kill',  (_, id)       => { if (terminals[id]) { terminals[id].kill(); delete terminals[id]; } });

// Run
const runners = {
  '.py':   f => `python "${f}"`,
  '.js':   f => `node "${f}"`,
  '.ts':   f => `npx ts-node "${f}"`,
  '.c':    f => `gcc "${f}" -o "${f}.out" && "${f}.out"`,
  '.cpp':  f => `g++ "${f}" -o "${f}.out" && "${f}.out"`,
  '.sh':   f => `bash "${f}"`,
  '.ps1':  f => `powershell -File "${f}"`,
  '.rb':   f => `ruby "${f}"`,
  '.go':   f => `go run "${f}"`,
  '.rs':   f => `rustc "${f}" -o "${f}.out" && "${f}.out"`,
  '.java': f => `javac "${f}" && java -cp "${path.dirname(f)}" "${path.basename(f, '.java')}"`,
};
ipcMain.handle('run:getCommand', async (_, filePath) => {
  const ext = path.extname(filePath).toLowerCase();
  return runners[ext] ? runners[ext](filePath) : null;
});

// Universal app launcher — works for any file that opens a window (GUI app, game, anything).
// Compiled languages (C/C++/Rust) are built first, then the binary is spawned directly.
// All stdout/stderr pipes back to the renderer Output panel via 'game:output'.
const activeApps = new Map();

ipcMain.handle('run:launchAsApp', async (_, filePath, cwd) => {
  const ext = path.extname(filePath).toLowerCase();
  const dir  = cwd || path.dirname(filePath);
  const base = path.basename(filePath, ext);
  const outBin = path.join(path.dirname(filePath), base + (process.platform === 'win32' ? '.exe' : '.out'));
  const send = d => mainWindow?.webContents.send('game:output', d.toString('utf8'));

  // ── Compiled languages: build first, then run the binary ──────────────────
  const compileCmd = {
    '.c':   `gcc "${filePath}" -o "${outBin}"`,
    '.cpp': `g++ "${filePath}" -o "${outBin}"`,
    '.rs':  `rustc "${filePath}" -o "${outBin}"`,
  }[ext];

  if (compileCmd) {
    send(`[Compiling ${path.basename(filePath)}…]\n`);
    const buildOk = await new Promise(resolve => {
      cp.exec(compileCmd, { cwd: dir }, (err, stdout, stderr) => {
        if (stdout) send(stdout);
        if (stderr) send(stderr);
        resolve(!err);
      });
    });
    if (!buildOk) return { ok: false, error: 'Compilation failed — see Output panel.' };
    send(`[Build OK — launching ${path.basename(outBin)}…]\n`);
    try {
      const proc = cp.spawn(outBin, [], { cwd: dir, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
      activeApps.set(proc.pid, proc);
      proc.stdout.on('data', send);
      proc.stderr.on('data', send);
      proc.on('exit', code => { activeApps.delete(proc.pid); send(`\n[Exited with code ${code}]\n`); });
      return { ok: true, pid: proc.pid };
    } catch (e) { return { ok: false, error: e.message }; }
  }

  // ── Interpreted languages: run directly ───────────────────────────────────
  const runners2 = {
    '.py':  ['python', [filePath]],
    '.js':  ['node',   [filePath]],
    '.ts':  ['npx',    ['ts-node', filePath]],
    '.rb':  ['ruby',   [filePath]],
    '.go':  ['go',     ['run', filePath]],
    '.java': ['java',  [base]],
  };
  const runner = runners2[ext];
  if (!runner) return { ok: false, error: `No launcher for ${ext} files.` };

  const runCwd = ext === '.java' ? path.dirname(filePath) : dir;
  try {
    const proc = cp.spawn(runner[0], runner[1], {
      cwd: runCwd,
      env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    activeApps.set(proc.pid, proc);
    proc.stdout.on('data', send);
    proc.stderr.on('data', send);
    proc.on('exit', code => { activeApps.delete(proc.pid); send(`\n[Exited with code ${code}]\n`); });
    return { ok: true, pid: proc.pid };
  } catch (e) { return { ok: false, error: e.message }; }
});

// AI health check — fast GET /v1/models with 5s timeout
// Fetch context window from LM Studio, trying multiple endpoints/fields.
function fetchContextWindow() {
  const pick = m => m?.context_length || m?.max_context_length || m?.n_ctx || m?.context_window || 0;
  const get = path => new Promise(resolve => {
    const u = new URL(`${AI_HOST}${path}`);
    const req = http.request({ hostname: u.hostname, port: u.port || 80, path: u.pathname, method: 'GET' }, res => {
      let d = '';
      res.on('data', c => { d += c; });
      res.on('end', () => {
        try {
          const j = JSON.parse(d);
          // OpenAI-style: { data: [...] }  OR  LM Studio native: [...]
          const list = Array.isArray(j) ? j : (j.data || []);
          const best = list.reduce((acc, m) => Math.max(acc, pick(m)), 0);
          resolve(best || 0);
        } catch { resolve(0); }
      });
    });
    req.on('error', () => resolve(0));
    req.setTimeout(4000, () => { req.destroy(); resolve(0); });
    req.end();
  });

  return Promise.all([get('/v1/models'), get('/api/v0/models')]).then(([a, b]) => Math.max(a, b) || 8192);
}

ipcMain.handle('ai:check', async () => {
  return new Promise(resolve => {
    const url = new URL(`${AI_HOST}/v1/models`);
    const req = http.request({ hostname: url.hostname, port: url.port || 80, path: url.pathname, method: 'GET' }, res => {
      res.on('data', () => {});
      res.on('end', () => {
        const ok = res.statusCode >= 200 && res.statusCode < 300;
        fetchContextWindow().then(contextWindow => resolve({ ok, contextWindow }));
      });
    });
    req.on('error', () => resolve({ ok: false, contextWindow: 8192 }));
    req.setTimeout(5000, () => { req.destroy(); resolve({ ok: false, contextWindow: 8192 }); });
    req.end();
  });
});

// Web search via DuckDuckGo HTML (real search results)
ipcMain.handle('web:search', async (_, query) => {
  return new Promise(resolve => {
    const encoded = encodeURIComponent(query);
    const req = https.request({
      hostname: 'html.duckduckgo.com',
      path: `/html/?q=${encoded}&kl=us-en`,
      method: 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html',
        'Accept-Language': 'en-US,en;q=0.9',
      },
    }, res => {
      let data = '';
      res.on('data', c => { data += c; if (data.length > 500000) req.destroy(); });
      res.on('end', () => {
        try {
          const titleRe = /<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g;
          const snippetRe = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
          const clean = s => s.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').trim();

          const titles = [];
          let m;
          while ((m = titleRe.exec(data)) !== null && titles.length < 8) {
            let url = m[1];
            const uddg = url.match(/uddg=([^&]+)/);
            if (uddg) url = decodeURIComponent(uddg[1]);
            const title = clean(m[2]);
            if (title && url.startsWith('http')) titles.push({ url, title });
          }

          const snippets = [];
          while ((m = snippetRe.exec(data)) !== null && snippets.length < 8) {
            const s = clean(m[1]);
            if (s) snippets.push(s);
          }

          const results = [];
          for (let i = 0; i < Math.min(titles.length, 5); i++) {
            const snip = snippets[i] ? `\n   ${snippets[i]}` : '';
            results.push(`${i + 1}. ${titles[i].title}\n   ${titles[i].url}${snip}`);
          }

          resolve(results.length
            ? `Search results for "${query}":\n\n${results.join('\n\n')}`
            : `No results found for "${query}".`);
        } catch (e) { resolve(`Search parse error: ${e.message}`); }
      });
    });
    req.on('error', e => resolve(`Search error: ${e.message}`));
    req.setTimeout(12000, () => { req.destroy(); resolve('Search timed out.'); });
    req.end();
  });
});

// Fetch and strip a web page to plain text (follows up to 5 redirects)
ipcMain.handle('web:read', async (_, targetUrl) => {
  const fetchUrl = (urlStr, redirectsLeft) => new Promise(resolve => {
    try {
      const parsed = new URL(urlStr);
      const lib = parsed.protocol === 'https:' ? https : http;
      const req = lib.request({
        hostname: parsed.hostname, port: parsed.port || undefined,
        path: parsed.pathname + parsed.search, method: 'GET',
        headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'text/html,text/plain' },
      }, res => {
        if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && redirectsLeft > 0) {
          req.destroy();
          const next = res.headers.location.startsWith('http') ? res.headers.location : new URL(res.headers.location, urlStr).href;
          resolve(fetchUrl(next, redirectsLeft - 1));
          return;
        }
        let data = '';
        res.on('data', c => { data += c; if (data.length > 300000) req.destroy(); });
        res.on('end', () => {
          const text = data
            .replace(/<script[\s\S]*?<\/script>/gi, '')
            .replace(/<style[\s\S]*?<\/style>/gi, '')
            .replace(/<[^>]+>/g, ' ')
            .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
            .replace(/\s+/g, ' ').trim().slice(0, 20000);
          resolve(text || '(empty page)');
        });
      });
      req.on('error', e => resolve(`Fetch error: ${e.message}`));
      req.setTimeout(12000, () => { req.destroy(); resolve('Fetch timed out.'); });
      req.end();
    } catch (e) { resolve(`Invalid URL: ${e.message}`); }
  });
  return fetchUrl(targetUrl, 5);
});

// AI
const activeStreams = new Map();

function sendAI(messages, streamId, config = {}) {
  return new Promise((resolve, reject) => {
    const payload = { model: config.model || 'local-model', messages, max_tokens: 8192, temperature: config.temperature ?? 0.2, stream: !!streamId };
    if (streamId) payload.stream_options = { include_usage: true };
    const body = JSON.stringify(payload);
    const url = new URL(`${AI_HOST}/v1/chat/completions`);
    const req = http.request({
      hostname: url.hostname, port: url.port || 80, path: url.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let data = '';
      let sseBuffer = '';
      res.on('data', chunk => {
        if (streamId) {
          // Buffer across chunk boundaries so SSE lines are never split mid-parse
          sseBuffer += chunk.toString();
          const lines = sseBuffer.split('\n');
          sseBuffer = lines.pop(); // last element may be an incomplete line — keep it
          lines.filter(l => l.startsWith('data: ')).forEach(line => {
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') { activeStreams.delete(streamId); mainWindow.webContents.send(`ai:stream:done:${streamId}`); return; }
            try {
              const parsed = JSON.parse(raw);
              const delta = parsed.choices?.[0]?.delta?.content || '';
              if (delta) mainWindow.webContents.send(`ai:stream:chunk:${streamId}`, delta);
              if (parsed.usage) mainWindow.webContents.send(`ai:stream:usage:${streamId}`, parsed.usage);
            } catch {}
          });
        } else { data += chunk; }
      });
      res.on('end', () => {
        if (streamId) {
          // Flush any remaining buffered line (e.g. if server omitted trailing \n)
          if (sseBuffer.startsWith('data: ')) {
            const raw = sseBuffer.slice(6).trim();
            if (raw && raw !== '[DONE]') {
              try { const delta = JSON.parse(raw).choices?.[0]?.delta?.content || ''; if (delta) mainWindow.webContents.send(`ai:stream:chunk:${streamId}`, delta); } catch {}
            }
          }
          activeStreams.delete(streamId); mainWindow.webContents.send(`ai:stream:done:${streamId}`); resolve();
        }
        else { try { resolve(JSON.parse(data).choices?.[0]?.message?.content || ''); } catch (e) { reject(e.message); } }
      });
    });
    req.on('error', e => {
      activeStreams.delete(streamId);
      if (streamId) mainWindow.webContents.send(`ai:stream:done:${streamId}`, e.message);
      else reject(e.message);
    });
    req.setTimeout(120000, () => req.destroy());
    if (streamId) activeStreams.set(streamId, req);
    req.write(body); req.end();
  });
}
ipcMain.handle('ai:chat', (_, messages, config) => sendAI(messages, null, config));
ipcMain.on('ai:stream', (_, id, messages, config) => sendAI(messages, id, config).catch(() => {}));
ipcMain.on('ai:stream:abort', (_, id) => {
  const req = activeStreams.get(id);
  if (req) { req.destroy(); activeStreams.delete(id); }
  mainWindow.webContents.send(`ai:stream:done:${id}`, 'aborted');
});

// Directory creation
ipcMain.handle('fs:mkdir', async (_, dirPath) => {
  try { fs.mkdirSync(dirPath, { recursive: true }); return true; } catch { return false; }
});

// Move / rename across directories
ipcMain.handle('fs:move', async (_, srcPath, destPath) => {
  try { fs.renameSync(srcPath, destPath); return true; } catch { return false; }
});

// Copy a file to a new location
ipcMain.handle('fs:copy', async (_, srcPath, destPath) => {
  try { fs.mkdirSync(path.dirname(destPath), { recursive: true }); fs.copyFileSync(srcPath, destPath); return true; } catch { return false; }
});

// List available models from LM Studio
ipcMain.handle('ai:getModels', async () => {
  return new Promise(resolve => {
    const url = new URL(`${AI_HOST}/v1/models`);
    const req = http.request({ hostname: url.hostname, port: url.port || 80, path: url.pathname, method: 'GET' }, res => {
      let d = '';
      res.on('data', c => { d += c; });
      res.on('end', () => {
        try {
          const j = JSON.parse(d);
          const list = Array.isArray(j) ? j : (j.data || []);
          resolve(list.map(m => m.id || m.name).filter(Boolean));
        } catch { resolve([]); }
      });
    });
    req.on('error', () => resolve([]));
    req.setTimeout(4000, () => { req.destroy(); resolve([]); });
    req.end();
  });
});

// Find files by name pattern (skips heavy dirs); supports globs like *.py or plain substrings
ipcMain.handle('fs:searchFiles', async (_, rootPath, pattern) => {
  const results = [];
  const skip = new Set(['node_modules', '.git', '__pycache__', '.venv', 'dist', 'build', '.next', 'target']);
  // Convert glob pattern to regex: * → .*, ? → ., escape other special chars
  const isGlob = /[*?]/.test(pattern);
  const reStr = isGlob
    ? pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')
    : null;
  const re = reStr ? new RegExp(`^${reStr}$`, 'i') : null;
  function match(name) {
    return re ? re.test(name) : name.toLowerCase().includes(pattern.toLowerCase());
  }
  function walk(dir, depth) {
    if (depth > 8 || results.length >= 50) return;
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (skip.has(e.name)) continue;
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full, depth + 1);
        else if (match(e.name)) results.push(full);
      }
    } catch {}
  }
  try { walk(rootPath, 0); } catch {}
  return results;
});

// Search text inside source files
ipcMain.handle('fs:grepFiles', async (_, rootPath, query) => {
  const results = [];
  const skip = new Set(['node_modules', '.git', '__pycache__', '.venv', 'dist', 'build', '.next', 'target']);
  const srcExts = new Set(['js','ts','py','c','cpp','h','go','rs','java','rb','sh','json','md','txt','html','css','yaml','yml','toml','jsx','tsx','vue','cs','php']);
  const qLow = query.toLowerCase();
  function walk(dir, depth) {
    if (depth > 6 || results.length >= 100) return;
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (skip.has(e.name)) continue;
        const full = path.join(dir, e.name);
        if (e.isDirectory()) { walk(full, depth + 1); continue; }
        if (!srcExts.has(path.extname(e.name).slice(1).toLowerCase())) continue;
        try {
          const lines = fs.readFileSync(full, 'utf8').split('\n');
          for (let i = 0; i < lines.length && results.length < 100; i++) {
            if (lines[i].toLowerCase().includes(qLow))
              results.push({ file: full, line: i + 1, content: lines[i].trim().slice(0, 120) });
          }
        } catch {}
      }
    } catch {}
  }
  try { walk(rootPath, 0); } catch {}
  return results;
});
