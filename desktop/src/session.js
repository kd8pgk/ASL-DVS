const fs = require('node:fs');
const path = require('node:path');

function createSessionMarker(file, now = Date.now) {
  function begin() {
    let crashed = false;
    try {
      fs.statSync(file);
      crashed = true;
    } catch {
      crashed = false;
    }
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, JSON.stringify({ pid: process.pid, at: now() }));
    } catch {
      return { crashed };
    }
    return { crashed };
  }

  function end() {
    try {
      fs.unlinkSync(file);
    } catch {
      return;
    }
  }

  return { begin, end };
}

module.exports = { createSessionMarker };
