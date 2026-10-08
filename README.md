# svg-to-png-wb

把 SVG 矢量图渲染成 PNG 位图的 WorkBuddy Skill。

用系统已装的 Chromium 系浏览器（Chrome / Edge / Chromium / Brave / Vivaldi / Opera）**无头模式**渲染，**零第三方依赖**——纯 Python 标准库，不需要 `pip install` 或 `npm install` 任何东西。

## 依赖

- Python 3
- 系统已安装下列浏览器之一：Chrome / Edge / Chromium / Brave / Vivaldi / Opera

## 安装

作为 WorkBuddy Skill 使用，把整个目录放到：

- 用户级：`~/.workbuddy-ai/skills/svg-to-png-wb/`
- 项目级：`<项目根>/.workbuddy-ai/skills/svg-to-png-wb/`

也可以直接当独立脚本用，不需要装成 Skill。

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

每次转换后都会用纯标准库的 PNG 解码器读回像素，判断图像是否**全透明或全白**（`blank`）。批处理时务必留意输出里的 `WARNING`；要程序化判断就用 `--json`，检查每个 result 的 `ok` 与 `warning` 字段。

## 文档

- [`SKILL.md`](SKILL.md) — 完整参数表、必须知道的坑、常见问题排查
- [`references/renderer-comparison.md`](references/renderer-comparison.md) — 渲染方案取舍依据与实测数据
