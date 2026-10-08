# svg-to-png-wb

[![npm version](https://img.shields.io/npm/v/svg-to-png-wb.svg)](https://www.npmjs.com/package/svg-to-png-wb)
[![license](https://img.shields.io/npm/l/svg-to-png-wb.svg)](LICENSE)
[![publish](https://github.com/Helloqiyuan/svg-to-png-wb/actions/workflows/publish.yml/badge.svg)](https://github.com/Helloqiyuan/svg-to-png-wb/actions/workflows/publish.yml)

把 SVG 矢量图渲染成 PNG 位图的 WorkBuddy Skill。

用系统已装的 Chromium 系浏览器（Chrome / Edge / Chromium / Brave / Vivaldi / Opera）**无头模式**渲染，**零第三方依赖**——纯 Python 标准库，不需要 `pip install` 或 `npm install` 任何东西。

## 依赖

- Python 3
- 系统已安装下列浏览器之一：Chrome / Edge / Chromium / Brave / Vivaldi / Opera

## 安装

### 方式一：用 npx 安装（推荐）

零配置，直接从 npm 拉取并安装到 WorkBuddy 的 skills 目录：

```bash
# 装到用户级目录（~/.workbuddy-ai/skills/），所有项目都能用
npx svg-to-png-wb

# 装到当前项目（./.workbuddy-ai/skills/）
npx svg-to-png-wb --project

# 覆盖已安装的旧版本
npx svg-to-png-wb --force

# 先看看会做什么，不写任何文件
npx svg-to-png-wb --dry-run

# 卸载
npx svg-to-png-wb --uninstall
```

没发布到 npm 时也可以直接从源码仓库装：

```bash
npx github:Helloqiyuan/svg-to-png-wb
```

| 选项 | 说明 |
|---|---|
| `-p, --project` | 装到当前项目的 `.workbuddy-ai/skills/` 下（默认是用户级目录） |
| `--dest <path>` | 指定确切的安装目录 |
| `-f, --force` | 目标已存在时覆盖 |
| `--dry-run` | 只打印将要执行的操作 |
| `--uninstall` | 卸载（只会删除确认为本 skill 的目录） |
| `-h, --help` / `-v, --version` | 帮助 / 版本号 |

安装器只依赖 Node 内置模块，Node.js >= 18 即可，不需要 `npm install` 任何东西。

### 方式二：手动放置

把整个目录放到：

- 用户级：`~/.workbuddy-ai/skills/svg-to-png-wb/`
- 项目级：`<项目根>/.workbuddy-ai/skills/svg-to-png-wb/`

也可以完全不当 Skill，直接当独立脚本用（见下方快速开始）。


## 快速开始

```bash
# 单文件，1 倍
python scripts/svg2png.py icon.svg

# 2 倍图 + 透明背景
python scripts/svg2png.py icon.svg -s 2 -b transparent

# 指定输出路径
python scripts/svg2png.py icon.svg -o build/icon.png -s 3

# 批量：把 svg/ 下所有 SVG 转成 png/，2 倍
python scripts/svg2png.py --input-dir ./svg --outdir ./png -s 2 --recursive

# 看看检测到哪些浏览器
python scripts/svg2png.py --list-browsers

# 只打印将要执行的命令（排障用）
python scripts/svg2png.py icon.svg --dry-run
```

输出尺寸 = SVG 逻辑尺寸 × `--scale`。PNG 没有"矢量 DPI"，所谓 300dpi 本质就是按目标像素放大。

## 为什么用无头浏览器而不是渲染库

无头 Chromium 是唯一**既不需要额外安装、又能认全 SVG 特性**的方案。实测对比（同一张测试图，6 类特性）：

| 特性 | headless Chrome | resvg-js |
|---|---|---|
| `<style>` 类选择器 | 正确 | 正确 |
| `feGaussianBlur` 滤镜 | 正确 | 正确 |
| `clipPath` + `mask` | 正确 | 正确 |
| 系统字体族 | 正确 | 正确 |
| `foreignObject` 内嵌 HTML | 正确 | **整块丢失** |
| CSS 变量 `var()` | 正确 | **回退成黑色** |

resvg 的失分是**静默的**（不报错、不警告），批处理时容易产出"看起来成功了"的错图。

## 脚本会做的校验

每次转换后都会用纯标准库的 PNG 解码器读回像素，判断图像是否**全透明或全白**（`blank`）。判定是**逐像素**做的，所以大画布上只有一个小元素也不会被漏判。批处理时务必留意输出里的 `WARNING`；要程序化判断就用 `--json`，检查每个 result 的 `ok` 与 `warning` 字段。

批量模式会在 stderr 打印 `[3/30] xxx.svg` 形式的进度，stdout 保持干净（便于管道处理）。

## 发布新版本

发布走 GitHub Actions + **trusted publishing (OIDC)**，不使用任何长期令牌——npm 计划在 2027 年 1 月收回 bypass-2FA 令牌的直接发布权限，OIDC 是唯一长期可用的路径。

```bash
# 1) 改版本号并提交
npm version patch   # 或 minor / major

# 2) 触发发布：打 tag 推上去，或在 GitHub Actions 页面手动 Run workflow
git push && git push --tags
```

工作流见 [`.github/workflows/publish.yml`](.github/workflows/publish.yml)。它会先跑 `npm ci` 和 `npm test`，tag 推送时还会校验 tag 与 `package.json` 版本是否一致，然后才 `npm publish`。

首次使用需要在 npmjs.com 上配置 trusted publisher（包的 Settings → Trusted Publisher）：

| 字段 | 值 |
|---|---|
| Select your publisher | GitHub Actions |
| Organization or user | `Helloqiyuan` |
| Repository | `svg-to-png-wb` |
| Workflow filename | `publish.yml`（**只填文件名，区分大小写**） |
| Allowed actions | `npm publish` |

两点注意：配置**保存后 2 天内**必须完成首次成功发布，否则会失效；`package.json` 的 `repository.url` 必须与仓库精确匹配，否则认证失败。

## 测试

```bash
npm test                        # 安装器 + 回归测试（后者在无浏览器时自动跳过）
python test/regression.py       # 只跑 svg2png.py 的回归测试
```

- `test/smoke.js` —— 打包完整性、SKILL.md frontmatter、CLI 退出码、安装/覆盖/卸载、卸载安全护栏
- `test/regression.py` —— 覆盖 v1.0.1 修掉的每一个静默失败：缺失输入文件不再拖垮整批、`--recursive` 保留目录结构、`--flat` 冲突上报、数值参数校验、批量进度、`blank` 判定不被采样漏判。装了 Pillow 时还会用它做一次交叉校验

两者都不需要额外依赖，也不写入仓库（Python 语法校验用 `ast.parse` 而非 `py_compile`，避免 `__pycache__` 混进 npm 包）。

## 文档

- [`SKILL.md`](SKILL.md) — 完整参数表、必须知道的坑、常见问题排查
- [`references/renderer-comparison.md`](references/renderer-comparison.md) — 渲染方案取舍依据与实测数据

## 许可证

[MIT](LICENSE) © 2026 Helloqiyuan
