#!/usr/bin/env node
'use strict';

/**
 * svg-to-png-wb 安装器
 *
 * 把本仓库里的 skill 文件（SKILL.md / scripts / references）复制到
 * WorkBuddy 的 skills 目录，使其成为可被自动加载的 skill。
 *
 * 零依赖，只用 Node 内置模块。
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SKILL_NAME = 'svg-to-png-wb';
const PKG_ROOT = path.resolve(__dirname, '..');
/** 真正需要装到 skills 目录里的内容（不含 package.json / bin / README） */
const PAYLOAD = ['SKILL.md', 'scripts', 'references'];

const pkg = require(path.join(PKG_ROOT, 'package.json'));

// ---------------------------------------------------------------- 工具函数

function fail(msg) {
  process.stderr.write(`\n✗ ${msg}\n\n`);
  process.exit(1);
}

function exists(p) {
  try {
    fs.statSync(p);
    return true;
  } catch {
    return false;
  }
}

function countFiles(dir) {
  let n = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    n += entry.isDirectory() ? countFiles(path.join(dir, entry.name)) : 1;
  }
  return n;
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function dirSize(dir) {
  let total = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    total += entry.isDirectory() ? dirSize(p) : fs.statSync(p).size;
  }
  return total;
}

function printHelp() {
  const target = defaultDest();
  process.stdout.write(`
svg-to-png-wb v${pkg.version}
${pkg.description}

用法
  npx github:Helloqiyuan/svg-to-png-wb [选项]

选项
  -p, --project        装到当前项目的 .workbuddy-ai/skills/ 下（默认装到用户级目录）
      --dest <path>    指定确切的安装目录（覆盖 --project 与默认值）
  -f, --force          目标已存在时覆盖
      --dry-run        只打印将要执行的操作，不写任何文件
      --uninstall      卸载已安装的 skill
  -h, --help           显示本帮助
  -v, --version        显示版本号

安装位置
  用户级（默认）  ${target}
  项目级          <当前目录>/.workbuddy-ai/skills/${SKILL_NAME}

示例
  # 装到用户级目录，所有项目都能用
  npx github:Helloqiyuan/svg-to-png-wb

  # 装到当前项目
  npx github:Helloqiyuan/svg-to-png-wb --project

  # 覆盖已安装的旧版本
  npx github:Helloqiyuan/svg-to-png-wb --force

  # 先看看会做什么
  npx github:Helloqiyuan/svg-to-png-wb --dry-run

  # 卸载
  npx github:Helloqiyuan/svg-to-png-wb --uninstall

前置条件
  - Node.js >= 18
  - 系统已安装 Chrome / Edge / Chromium / Brave / Vivaldi / Opera 之一
`);
}

// ---------------------------------------------------------------- 参数解析

function parseArgs(argv) {
  const opts = {
    project: false,
    dest: null,
    force: false,
    dryRun: false,
    uninstall: false,
    help: false,
    version: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    switch (arg) {
      case '-h':
      case '--help':
        opts.help = true;
        break;
      case '-v':
      case '--version':
        opts.version = true;
        break;
      case '-p':
      case '--project':
        opts.project = true;
        break;
      case '-f':
      case '--force':
        opts.force = true;
        break;
      case '--dry-run':
        opts.dryRun = true;
        break;
      case '--uninstall':
        opts.uninstall = true;
        break;
      case '--dest': {
        const value = argv[i + 1];
        if (!value || value.startsWith('-')) fail('--dest 后面需要一个路径参数');
        opts.dest = path.resolve(value);
        i += 1;
        break;
      }
      default:
        fail(`未知参数：${arg}\n用 --help 查看用法`);
    }
  }

  return opts;
}

function defaultDest() {
  return path.join(os.homedir(), '.workbuddy-ai', 'skills', SKILL_NAME);
}

function resolveDest(opts) {
  if (opts.dest) return opts.dest;
  if (opts.project) {
    return path.join(process.cwd(), '.workbuddy-ai', 'skills', SKILL_NAME);
  }
  return defaultDest();
}

// ---------------------------------------------------------------- 安装 / 卸载

function verifyPayload() {
  const missing = PAYLOAD.filter((item) => !exists(path.join(PKG_ROOT, item)));
  if (missing.length > 0) {
    fail(
      `安装包不完整，缺少：${missing.join(', ')}\n` +
        `包根目录：${PKG_ROOT}\n` +
        '如果你是用 npx 从 GitHub 拉取的，请确认仓库里这些文件已被提交。'
    );
  }
}

function doInstall(opts, dest) {
  verifyPayload();

  const alreadyThere = exists(dest);

  if (alreadyThere && !opts.force) {
    fail(
      `目标已存在：${dest}\n` +
        '如果确认要覆盖，请加 --force：\n' +
        `  npx github:Helloqiyuan/svg-to-png-wb --force`
    );
  }

  if (opts.dryRun) {
    process.stdout.write('\n[dry-run] 不会写入任何文件\n\n');
    process.stdout.write(`  源目录  ${PKG_ROOT}\n`);
    process.stdout.write(`  目标    ${dest}\n`);
    process.stdout.write(`  ${alreadyThere ? '将覆盖已存在的目录' : '将新建目录'}\n\n`);
    for (const item of PAYLOAD) {
      const src = path.join(PKG_ROOT, item);
      const isDir = fs.statSync(src).isDirectory();
      process.stdout.write(`  复制  ${item}${isDir ? '/' : ''}\n`);
    }
    process.stdout.write('\n');
    return;
  }

  fs.mkdirSync(dest, { recursive: true });

  for (const item of PAYLOAD) {
    const from = path.join(PKG_ROOT, item);
    const to = path.join(dest, item);
    fs.cpSync(from, to, { recursive: true, force: true });
  }

  const fileCount = countFiles(dest);
  const size = humanSize(dirSize(dest));
  const scriptPath = path.join(dest, 'scripts', 'svg2png.py');

  process.stdout.write(`\n✓ svg-to-png-wb v${pkg.version} 已安装\n\n`);
  process.stdout.write(`  位置    ${dest}\n`);
  process.stdout.write(`  文件    ${fileCount} 个，共 ${size}${alreadyThere ? '（已覆盖原目录）' : ''}\n\n`);
  process.stdout.write('怎么用\n');
  process.stdout.write('  在 WorkBuddy 里直接说「把 xxx.svg 转成 PNG」，skill 会被自动加载。\n');
  process.stdout.write('  也可以直接调脚本：\n');
  process.stdout.write(`    python "${scriptPath}" icon.svg -s 2 -b transparent\n\n`);
  process.stdout.write('  查看检测到的浏览器：\n');
  process.stdout.write(`    python "${scriptPath}" --list-browsers\n\n`);
}

function doUninstall(opts, dest) {
  if (!exists(dest)) {
    fail(`没有找到已安装的 skill：${dest}`);
  }

  // 安全护栏：只删确认是本 skill 的目录
  const skillMd = path.join(dest, 'SKILL.md');
  if (!exists(skillMd)) {
    fail(
      `目录里没有 SKILL.md，看起来不是 ${SKILL_NAME} 的安装目录，已中止：\n  ${dest}\n` +
        '如需删除请手动处理。'
    );
  }
  const head = fs.readFileSync(skillMd, 'utf8').slice(0, 500);
  if (!head.includes(`name: ${SKILL_NAME}`)) {
    fail(
      `SKILL.md 里的 name 不是 ${SKILL_NAME}，已中止删除：\n  ${dest}\n` +
        '如需删除请手动处理。'
    );
  }

  if (opts.dryRun) {
    process.stdout.write(`\n[dry-run] 将删除目录：${dest}\n\n`);
    return;
  }

  fs.rmSync(dest, { recursive: true, force: true });
  process.stdout.write(`\n✓ 已卸载，目录已删除：${dest}\n\n`);
}

// ---------------------------------------------------------------- 入口

function main() {
  const opts = parseArgs(process.argv.slice(2));

  if (opts.help) {
    printHelp();
    return;
  }
  if (opts.version) {
    process.stdout.write(`${pkg.version}\n`);
    return;
  }

  const dest = resolveDest(opts);

  if (opts.uninstall) {
    doUninstall(opts, dest);
  } else {
    doInstall(opts, dest);
  }
}

main();
