#!/usr/bin/env node
'use strict';

/**
 * Does the installer survive a destination path containing spaces and
 * non-ASCII characters?
 *
 * The path is built inside Node and passed via spawnSync's argv array, so no
 * shell is involved. Testing this from bash would be meaningless on Windows:
 * Git Bash rewrites non-ASCII arguments before node.exe ever sees them, which
 * produces false failures that have nothing to do with the installer.
 */

const assert = require('node:assert');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PKG_ROOT = path.resolve(__dirname, '..');
const INSTALLER = path.join(PKG_ROOT, 'bin', 'install.js');
const PAYLOAD = ['SKILL.md', 'scripts/svg2png.py', 'references/renderer-comparison.md'];

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (err) {
    failures += 1;
    console.log('FAIL ' + name);
    console.log('     ' + (err && err.message ? err.message : String(err)));
  }
}

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'svg-to-png-wb-unicode-'));

// A directory name with spaces, CJK characters, and a non-BMP emoji - the
// three things most likely to break naive path handling.
const awkwardName = '带 空格 和中文 \u{1F680} 的目录';
const dest = path.join(sandbox, awkwardName, 'skill 目录');

console.log('dest: ' + dest + '\n');

check('the destination name really is non-ASCII', () => {
  assert.ok(/[^\x00-\x7F]/.test(dest), 'expected non-ASCII characters in the path');
  assert.ok(dest.includes(' '), 'expected spaces in the path');
});

check('install succeeds', () => {
  const out = spawnSync(process.execPath, [INSTALLER, '--dest', dest], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
  });
  assert.strictEqual(out.status, 0, out.stderr || out.stdout);
});

check('every payload file landed, with identical content', () => {
  for (const rel of PAYLOAD) {
    const installed = path.join(dest, rel);
    assert.ok(fs.existsSync(installed), 'missing: ' + rel);
    assert.ok(
      fs.readFileSync(installed).equals(fs.readFileSync(path.join(PKG_ROOT, rel))),
      'content differs: ' + rel
    );
  }
});

check('the installed script renders from that path', () => {
  const script = path.join(dest, 'scripts', 'svg2png.py');

  let python = null;
  for (const exe of ['python3', 'python']) {
    const probe = spawnSync(exe, ['-c', 'pass'], { encoding: 'utf8' });
    if (!probe.error && probe.status === 0) {
      python = exe;
      break;
    }
  }
  if (!python) {
    console.log('     (skipped: no python on PATH)');
    return;
  }

  // svg2png.py exits 2 when it cannot find a browser; skip rather than fail.
  if (spawnSync(python, [script, '--list-browsers'], { encoding: 'utf8' }).status !== 0) {
    console.log('     (skipped: no Chromium-family browser)');
    return;
  }

  const work = path.join(dest, 'work');
  fs.mkdirSync(work, { recursive: true });
  const svg = path.join(work, '测 试.svg');
  const png = path.join(work, '输 出.png');
  fs.writeFileSync(svg,
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">' +
    '<rect width="120" height="80" fill="#3366cc"/></svg>', 'utf8');

  const out = spawnSync(python, [script, svg, '-o', png], { encoding: 'utf8' });
  assert.strictEqual(out.status, 0, (out.stdout || '') + (out.stderr || ''));
  assert.ok(fs.existsSync(png), 'no PNG produced');
});

check('uninstall removes it', () => {
  const out = spawnSync(process.execPath, [INSTALLER, '--uninstall', '--dest', dest], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
  });
  assert.strictEqual(out.status, 0, out.stderr || out.stdout);
  assert.ok(!fs.existsSync(dest), 'destination still exists');
});

fs.rmSync(sandbox, { recursive: true, force: true });

console.log('\n' + (failures ? failures + ' check(s) failed' : 'all checks passed'));
process.exit(failures ? 1 : 0);
