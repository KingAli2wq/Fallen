'use strict';
const { contextBridge, ipcRenderer } = require('electron/renderer');

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

  getRunCommand: p         => ipcRenderer.invoke('run:getCommand', p),

  webSearch:   q           => ipcRenderer.invoke('tool:webSearch', q),
  fetchUrl:    url         => ipcRenderer.invoke('tool:fetchUrl', url),

  aiChat:      messages    => ipcRenderer.invoke('ai:chat', messages),
  aiStream:    (id, msgs)  => ipcRenderer.send('ai:stream', id, msgs),
  onAiChunk:   (id, fn)    => ipcRenderer.on(`ai:stream:chunk:${id}`, (_, c) => fn(c)),
  onAiDone:    (id, fn)    => ipcRenderer.once(`ai:stream:done:${id}`, (_, err) => fn(err)),
  removeAiListeners: id    => {
    ipcRenderer.removeAllListeners(`ai:stream:chunk:${id}`);
    ipcRenderer.removeAllListeners(`ai:stream:done:${id}`);
  },
});
