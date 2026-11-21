import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const venvStreamlit = path.resolve('.venv/bin/streamlit');
const executable = fs.existsSync(venvStreamlit) ? venvStreamlit : 'streamlit';

const child = spawn(
  executable,
  [
    'run',
    'app.py',
    '--server.port=3000',
    '--server.address=0.0.0.0',
    '--server.headless=true',
    '--browser.gatherUsageStats=false',
    '--server.enableCORS=false',
    '--server.enableXsrfProtection=false',
  ],
  { stdio: 'inherit' }
);

child.on('exit', (code) => {
  process.exit(code ?? 0);
});
