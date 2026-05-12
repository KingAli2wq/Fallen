import * as electronMain from 'electron/main';
const { app, BrowserWindow, ipcMain, dialog, shell } = electronMain;
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import cp from 'node:child_process';
import http from 'node:http';
import os from 'node:os';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AI_HOST = 'http://10.0.0.80:1234';
const WEB_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) FallenIDE/1.0 Chrome/122.0.0.0 Safari/537.36';

let mainWindow;
const terminals = {};
let termIdCounter = 0;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 500,
    backgroundColor: '#1e1e1e',
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

// ── Window controls ──────────────────────────────────────────────────────────
ipcMain.on('win:minimize', () => mainWindow.minimize());
ipcMain.on('win:maximize', () => mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize());
ipcMain.on('win:close',    () => mainWindow.close());

// ── File system ──────────────────────────────────────────────────────────────
ipcMain.handle('fs:openFolder', async () => {
  const r = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle('fs:readDir', async (_, dirPath) => {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true })
      .map(e => ({ name: e.name, path: path.join(dirPath, e.name), isDir: e.isDirectory() }))
      .sort((a, b) => (a.isDir !== b.isDir ? (a.isDir ? -1 : 1) : a.name.localeCompare(b.name)));
  } catch { return []; }
});

ipcMain.handle('fs:readFile',  async (_, p) => { try { return fs.readFileSync(p, 'utf8'); } catch { return null; } });
ipcMain.handle('fs:writeFile', async (_, p, c) => { try { fs.writeFileSync(p, c, 'utf8'); return true; } catch { return false; } });

ipcMain.handle('fs:newFile', async (_, dirPath) => {
  const r = await dialog.showSaveDialog(mainWindow, { defaultPath: path.join(dirPath || os.homedir(), 'untitled.txt') });
  if (r.canceled) return null;
  fs.writeFileSync(r.filePath, '', 'utf8');
  return r.filePath;
});

ipcMain.handle('fs:deleteFile', async (_, p) => { try { shell.trashItem(p); return true; } catch { return false; } });
ipcMain.handle('fs:rename', async (_, oldPath, newName) => {
  const newPath = path.join(path.dirname(oldPath), newName);
  try { fs.renameSync(oldPath, newPath); return newPath; } catch { return null; }
});

// ── Terminal ─────────────────────────────────────────────────────────────────
ipcMain.handle('term:create', async (_, cwd) => {
  const id = ++termIdCounter;
  const shell = process.platform === 'win32' ? 'powershell.exe' : 'bash';
  const proc = cp.spawn(shell, [], {
    cwd: cwd || os.homedir(),
    env: { ...process.env, TERM: 'xterm-256color' },
    windowsHide: false,
  });
  terminals[id] = proc;
  proc.stdout.on('data', d => mainWindow.webContents.send(`term:data:${id}`, d.toString()));
  proc.stderr.on('data', d => mainWindow.webContents.send(`term:data:${id}`, d.toString()));
  proc.on('exit', () => { mainWindow.webContents.send(`term:exit:${id}`); delete terminals[id]; });
  return id;
});

ipcMain.on('term:write', (_, id, data) => { if (terminals[id]) terminals[id].stdin.write(data); });
ipcMain.on('term:kill',  (_, id)       => { if (terminals[id]) { terminals[id].kill(); delete terminals[id]; } });

// ── Run ───────────────────────────────────────────────────────────────────────
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

// ── Web tools ────────────────────────────────────────────────────────────────
function cleanHtml(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&#39;/gi, "'")
    .replace(/&quot;/gi, '"')
    .replace(/\s+/g, ' ')
    .trim();
}

async function fetchText(url, timeoutMs = 15000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        'user-agent': WEB_USER_AGENT,
        accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.text();
  } finally {
    clearTimeout(timeout);
  }
}

function normalizeHttpUrl(rawUrl) {
  const trimmed = String(rawUrl || '').trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^\/\//.test(trimmed)) return `https:${trimmed}`;
  return null;
}

function parseDuckDuckGoResults(html) {
  const results = [];
  const seen = new Set();
  const linkRegex = /<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  let match;

  while ((match = linkRegex.exec(html)) !== null) {
    const rawHref = match[1].replace(/&amp;/g, '&');
    let href = rawHref;
    try {
      const parsed = new URL(rawHref, 'https://duckduckgo.com');
      const decoded = parsed.searchParams.get('uddg');
      if (decoded) href = decodeURIComponent(decoded);
    } catch {}
    const title = cleanHtml(match[2]);
    if (!title || seen.has(href)) continue;
    seen.add(href);
    results.push({ title, url: href, snippet: '' });
    if (results.length >= 5) break;
  }

  return results;
}

ipcMain.handle('tool:webSearch', async (_, query) => {
  const q = String(query || '').trim();
  if (!q) return 'Error: empty web search query';

  try {
    const searchUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`;
    const html = await fetchText(searchUrl, 20000);
    const results = parseDuckDuckGoResults(html);
    if (!results.length) return `No web results found for: ${q}`;

    return [
      `Web search results for: ${q}`,
      ...results.map((result, index) => `${index + 1}. ${result.title}\n   ${result.url}`),
    ].join('\n');
  } catch (error) {
    return `Error: web search failed for "${q}" - ${error.message}`;
  }
});

ipcMain.handle('tool:fetchUrl', async (_, rawUrl) => {
  const url = normalizeHttpUrl(rawUrl);
  if (!url) return `Error: invalid URL "${rawUrl}"`;

  try {
    const html = await fetchText(url, 20000);
    const text = cleanHtml(html);
    return [
      `Fetched URL: ${url}`,
      text.slice(0, 12000) || '(empty response body)',
    ].join('\n\n');
  } catch (error) {
    return `Error: fetch failed for "${url}" - ${error.message}`;
  }
});

// ── AI ────────────────────────────────────────────────────────────────────────
ipcMain.handle('ai:chat', (_, messages) => sendAI(messages, false));

function sendAI(messages, streamId) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ model: 'local-model', messages, max_tokens: 2048, temperature: 0.3, stream: !!streamId });
    const url = new URL(`${AI_HOST}/v1/chat/completions`);
    const req = http.request({
      hostname: url.hostname, port: url.port || 80, path: url.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let data = '';
      res.on('data', chunk => {
        if (streamId) {
          for (const line of chunk.toString().split('\n').filter(l => l.startsWith('data: '))) {
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') { mainWindow.webContents.send(`ai:stream:done:${streamId}`); return; }
            try {
              const delta = JSON.parse(raw).choices?.[0]?.delta?.content || '';
              if (delta) mainWindow.webContents.send(`ai:stream:chunk:${streamId}`, delta);
            } catch {}
          }
        } else { data += chunk; }
      });
      res.on('end', () => {
        if (streamId) { mainWindow.webContents.send(`ai:stream:done:${streamId}`); resolve(); }
        else { try { resolve(JSON.parse(data).choices?.[0]?.message?.content || ''); } catch (e) { reject(e.message); } }
      });
    });
    req.on('error', e => { if (streamId) mainWindow.webContents.send(`ai:stream:done:${streamId}`, e.message); reject(e.message); });
    req.setTimeout(120000, () => req.destroy());
    req.write(body);
    req.end();
  });
}

ipcMain.on('ai:stream', (_, id, messages) => sendAI(messages, id).catch(() => {}));
