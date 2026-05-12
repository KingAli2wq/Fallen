const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  winMinimize: ()          => ipcRenderer.send('win:minimize'),
  winMaximize: ()          => ipcRenderer.send('win:maximize'),
  winClose:    ()          => ipcRenderer.send('win:close'),

  openFolder:  ()          => ipcRenderer.invoke('fs:openFolder'),
  readDir:     p           => ipcRenderer.invoke('fs:readDir', p),
  readFile:    p           => ipcRenderer.invoke('fs:readFile', p),
  writeFile:   (p, c)      => ipcRenderer.invoke('fs:writeFile', p, c),
  newFile:     dir         => ipcRenderer.invoke('fs:newFile', dir),
  deleteFile:  p           => ipcRenderer.invoke('fs:deleteFile', p),
  renameFile:  (p, n)      => ipcRenderer.invoke('fs:rename', p, n),

  termCreate:  cwd         => ipcRenderer.invoke('term:create', cwd),
  termWrite:   (id, data)  => ipcRenderer.send('term:write', id, data),
  termKill:    id          => ipcRenderer.send('term:kill', id),
  onTermData:  (id, fn)    => ipcRenderer.on(`term:data:${id}`, (_, d) => fn(d)),
  onTermExit:  (id, fn)    => ipcRenderer.once(`term:exit:${id}`, fn),
  removeTermListeners: id  => {
    ipcRenderer.removeAllListeners(`term:data:${id}`);
    ipcRenderer.removeAllListeners(`term:exit:${id}`);
  },

  mkdir:         p           => ipcRenderer.invoke('fs:mkdir', p),
  moveFile:      (src, dest) => ipcRenderer.invoke('fs:move', src, dest),
  copyFile:      (src, dest) => ipcRenderer.invoke('fs:copy', src, dest),
  searchFiles:   (root, pat) => ipcRenderer.invoke('fs:searchFiles', root, pat),
  grepFiles:     (root, q)   => ipcRenderer.invoke('fs:grepFiles', root, q),

  getRunCommand: p         => ipcRenderer.invoke('run:getCommand', p),
  launchAsApp:      (p, cwd) => ipcRenderer.invoke('run:launchAsApp', p, cwd),
  onGameOutput:     fn       => ipcRenderer.on('game:output', (_, d) => fn(d)),
  removeGameListeners: ()    => ipcRenderer.removeAllListeners('game:output'),

  aiCheck:     ()             => ipcRenderer.invoke('ai:check'),
  aiGetModels: ()             => ipcRenderer.invoke('ai:getModels'),
  webSearch:   q              => ipcRenderer.invoke('web:search', q),
  webRead:     url            => ipcRenderer.invoke('web:read', url),

  aiChat:      (messages, cfg)     => ipcRenderer.invoke('ai:chat', messages, cfg),
  aiStream:    (id, msgs, cfg)     => ipcRenderer.send('ai:stream', id, msgs, cfg),
  aiAbort:     id          => ipcRenderer.send('ai:stream:abort', id),
  onAiChunk:   (id, fn)    => ipcRenderer.on(`ai:stream:chunk:${id}`, (_, c) => fn(c)),
  onAiDone:    (id, fn)    => ipcRenderer.once(`ai:stream:done:${id}`, (_, err) => fn(err)),
  onAiUsage:   (id, fn)    => ipcRenderer.on(`ai:stream:usage:${id}`, (_, u) => fn(u)),
  removeAiListeners: id    => {
    ipcRenderer.removeAllListeners(`ai:stream:chunk:${id}`);
    ipcRenderer.removeAllListeners(`ai:stream:done:${id}`);
    ipcRenderer.removeAllListeners(`ai:stream:usage:${id}`);
  },
});
