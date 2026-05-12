const e = require('electron');
console.log('type:', typeof e);
console.log('keys:', Object.keys(e || {}).slice(0, 10));
console.log('app:', e.app);
process.exit(0);
