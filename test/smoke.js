#!/usr/bin/env node
'use strict';

/**
 * Smoke test for the installer and the packaged skill.
 *
 * Zero dependencies - runs anywhere Node >= 18 runs. Exercises the installer
 * against a throwaway directory so it never touches the real skills folder.
 *
 * Run with:  npm test
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

function test(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (err) {
    failures += 1;
    console.log('FAIL ' + name);
    console.log('     ' + (err && err.message ? err.message : String(err)));
  }
}

function runInstaller(args) {
  return spawnSync(process.execPath, [INSTALLER, ...args], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
  });
}

// mkdtempSync creates the directory it returns, so install into a child path
// that does not exist yet - otherwise the "fresh install" tests would start
// from an already-populated target.
const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'svg-to-png-wb-smoke-'));
const dest = path.join(sandbox, 'svg-to-png-wb');

// ---------------------------------------------------------------- packaging
test('payload files are present in the package', () => {
  for (const rel of PAYLOAD) {
    assert.ok(fs.existsSync(path.join(PKG_ROOT, rel)), 'missing ' + rel);
  }
});

test('package.json declares the bin entry and required metadata', () => {
  const pkg = require(path.join(PKG_ROOT, 'package.json'));
  assert.strictEqual(pkg.bin['svg-to-png-wb'], 'bin/install.js');
  assert.ok(pkg.license, 'license must be set');
  assert.ok(pkg.repository && pkg.repository.url, 'repository.url is required for npm trusted publishing');
  assert.ok(/github\.com\/Helloqiyuan\/svg-to-png-wb/.test(pkg.repository.url),
    'repository.url must match the GitHub repo');
});

test('SKILL.md has valid frontmatter with the expected name', () => {
  const text = fs.readFileSync(path.join(PKG_ROOT, 'SKILL.md'), 'utf8');
  assert.ok(text.startsWith('---'), 'SKILL.md must start with YAML frontmatter');
  assert.ok(/^name:\s*svg-to-png-wb\s*$/m.test(text), 'frontmatter name must be svg-to-png-wb');
  assert.ok(/^description:\s*\S/m.test(text), 'frontmatter needs a description');
  assert.ok(/^agent_created:\s*true\s*$/m.test(text), 'frontmatter needs agent_created: true');
});

// ---------------------------------------------------------------- CLI basics
test('--version prints the package version', () => {
  const pkg = require(path.join(PKG_ROOT, 'package.json'));
  const out = runInstaller(['--version']);
  assert.strictEqual(out.status, 0);
  assert.strictEqual(out.stdout.trim(), pkg.version);
});

test('--help exits 0 and mentions the install target', () => {
  const out = runInstaller(['--help']);
  assert.strictEqual(out.status, 0);
  assert.ok(out.stdout.includes('svg-to-png-wb'), 'help should mention the skill name');
});

test('an unknown flag exits 1', () => {
  assert.strictEqual(runInstaller(['--definitely-not-a-flag']).status, 1);
});

// ---------------------------------------------------------------- install
test('--dry-run writes nothing and exits 0', () => {
  const out = runInstaller(['--dry-run', '--dest', dest]);
  assert.strictEqual(out.status, 0);
  assert.ok(!fs.existsSync(dest), 'dry-run must not create the target');
});

test('install copies the whole payload', () => {
  const out = runInstaller(['--dest', dest]);
  assert.strictEqual(out.status, 0, out.stderr);
  for (const rel of PAYLOAD) {
    assert.ok(fs.existsSync(path.join(dest, rel)), 'not installed: ' + rel);
  }
});

test('installed payload is byte-identical to the package', () => {
  for (const rel of PAYLOAD) {
    const from = fs.readFileSync(path.join(PKG_ROOT, rel));
    const to = fs.readFileSync(path.join(dest, rel));
    assert.ok(from.equals(to), 'content differs: ' + rel);
  }
});

test('re-installing without --force exits 1', () => {
  assert.strictEqual(runInstaller(['--dest', dest]).status, 1);
});

test('--dry-run still exits 0 when the target already exists', () => {
  const out = runInstaller(['--dry-run', '--dest', dest]);
  assert.strictEqual(out.status, 0);
  assert.ok(/--force/.test(out.stdout), 'preview should warn that --force is needed');
});

test('--force overwrites an existing install', () => {
  assert.strictEqual(runInstaller(['--dest', dest, '--force']).status, 0);
});

test('--project targets ./.agent-skills under the cwd', () => {
  const out = runInstaller(['--project', '--dry-run']);
  assert.strictEqual(out.status, 0);
  const expected = path.join('.agent-skills', 'svg-to-png-wb');
  assert.ok(out.stdout.includes(expected), 'expected ' + expected + ' in:\n' + out.stdout);
});

test('the default target is a neutral path', () => {
  const out = runInstaller(['--dry-run']);
  assert.strictEqual(out.status, 0);
  const expected = path.join(os.homedir(), '.agent-skills', 'svg-to-png-wb');
  assert.ok(out.stdout.includes(expected), 'expected ' + expected + ' in:\n' + out.stdout);
});

test('AGENT_SKILLS_DIR overrides the default root', () => {
  const root = path.join(sandbox, 'custom-root');
  const out = spawnSync(process.execPath, [INSTALLER, '--dry-run'], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
    env: { ...process.env, AGENT_SKILLS_DIR: root },
  });
  assert.strictEqual(out.status, 0, out.stderr);
  assert.ok(out.stdout.includes(path.join(root, 'svg-to-png-wb')),
    'expected the env root in:\n' + out.stdout);
});

test('an explicit --dest wins over AGENT_SKILLS_DIR', () => {
  const out = spawnSync(process.execPath, [INSTALLER, '--dry-run', '--dest', dest], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
    env: { ...process.env, AGENT_SKILLS_DIR: path.join(sandbox, 'ignored-root') },
  });
  assert.strictEqual(out.status, 0, out.stderr);
  assert.ok(out.stdout.includes(dest), 'expected --dest to win in:\n' + out.stdout);
});

test('no agent-client product name appears anywhere in the package', () => {
  // This skill deliberately stays client-agnostic: it must not hardcode any
  // particular client's directory name or brand it as being "for" one client.
  // The term is assembled rather than spelled out, because a file that asserts
  // the term is absent cannot itself contain it.
  const forbidden = ['work', 'buddy'].join('');
  const offenders = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === '.git' || entry.name === 'node_modules') continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (fs.readFileSync(full, 'utf8').toLowerCase().includes(forbidden)) {
        offenders.push(path.relative(PKG_ROOT, full));
      }
    }
  };
  walk(PKG_ROOT);
  assert.deepStrictEqual(offenders, [], 'the term leaked into: ' + offenders.join(', '));
});

// ---------------------------------------------------------------- uninstall
test('uninstall refuses a directory that is not this skill', () => {
  const other = fs.mkdtempSync(path.join(os.tmpdir(), 'svg-to-png-wb-notours-'));
  try {
    const out = runInstaller(['--uninstall', '--dest', other]);
    assert.strictEqual(out.status, 1);
    assert.ok(fs.existsSync(other), 'guard must not delete an unrelated directory');
  } finally {
    fs.rmSync(other, { recursive: true, force: true });
  }
});

test('uninstall removes the installed skill', () => {
  assert.strictEqual(runInstaller(['--uninstall', '--dest', dest]).status, 0);
  assert.ok(!fs.existsSync(dest), 'target should be gone');
});

test('uninstalling twice exits 1', () => {
  assert.strictEqual(runInstaller(['--uninstall', '--dest', dest]).status, 1);
});

// ---------------------------------------------------------------- the python side
function findPython() {
  for (const exe of ['python3', 'python']) {
    const probe = spawnSync(exe, ['-c', 'pass'], { encoding: 'utf8' });
    if (!probe.error && probe.status === 0) return exe;
  }
  return null;
}

const PYTHON = findPython();

test('scripts/svg2png.py parses as valid Python', () => {
  if (!PYTHON) {
    console.log('     (skipped: no python on PATH)');
    return;
  }
  const target = path.join(PKG_ROOT, 'scripts', 'svg2png.py');
  // ast.parse only checks syntax - it never writes __pycache__, so this test
  // cannot leave bytecode behind for a later `npm publish` to sweep up.
  const program = 'import ast,sys;ast.parse(open(sys.argv[1],encoding="utf-8").read())';
  const out = spawnSync(PYTHON, ['-c', program, target], { encoding: 'utf8' });
  assert.strictEqual(out.status, 0, 'syntax error: ' + (out.stderr || ''));
});

test('svg2png.py regression suite passes', () => {
  if (!PYTHON) {
    console.log('     (skipped: no python on PATH)');
    return;
  }
  // Skips itself, rather than failing, when no Chromium-family browser exists.
  const out = spawnSync(PYTHON, [path.join(PKG_ROOT, 'test', 'regression.py')], {
    encoding: 'utf8',
    cwd: PKG_ROOT,
  });
  assert.strictEqual(out.status, 0,
    'regression suite failed:\n' + (out.stdout || '') + (out.stderr || ''));
});

// ---------------------------------------------------------------- summary
fs.rmSync(sandbox, { recursive: true, force: true });

if (failures > 0) {
  console.log('\n' + failures + ' test(s) failed');
  process.exit(1);
}
console.log('\nall tests passed');
