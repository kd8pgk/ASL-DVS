const fs = require('node:fs');
const path = require('node:path');

function createLog(file, { max = 200000, now = () => new Date(), echo = (line) => process.stderr.write(line) } = {}) {
  let ready = false;
  let size = -1;

  function write(text) {
    const line = `${now().toISOString()} ${text}\n`;
    echo(line);
    try {
      if (!ready) {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        ready = true;
      }
      if (size < 0) {
        try {
          size = fs.statSync(file).size;
        } catch {
          size = 0;
        }
      }
      if (size + line.length > max) {
        try {
          fs.renameSync(file, `${file}.1`);
        } catch {
          fs.writeFileSync(file, '');
        }
        size = 0;
      }
      fs.appendFileSync(file, line);
      size += Buffer.byteLength(line);
    } catch {
      size = -1;
    }
  }

  return { write };
}

module.exports = { createLog };
