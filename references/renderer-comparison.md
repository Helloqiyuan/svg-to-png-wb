# SVG 渲染器能力边界实测

数据来源：同一张测试图 `svg2png-test.svg`（680×360，6 个 tile 各测一类特性），
分别交给 headless Chrome 与 resvg-js 渲染成 1360×720 的 PNG。

## 结果

| 测试特性 | headless Chrome | resvg-js |
|---|---|---|
| 1. `<style>` 类选择器 | 正确 | 正确 |
| 2. `feGaussianBlur` 滤镜 | 正确 | 正确 |
| 3. `clipPath` + `mask` | 正确 | 正确 |
| 4. 文本 + 系统字体族 | 正确 | 正确（需 `font:{loadSystemFonts:true}`） |
| 5. `foreignObject` 内嵌 HTML | 正确 | 整块空白 |
| 6. CSS 变量 `var()` | 正确 | 回退为黑色初始值 |

## 关键结论

- resvg 比普遍预期强：滤镜、遮罩、系统字体都扛住了，**不是"只能渲染简单图形"**。
- resvg 的失分方式是**静默失败**——不报错、不警告。第 5 项直接留白，第 6 项退化成黑色。
  批量出图时这最危险：拿到的是一堆"看起来生成成功了"的错图。
- 字体一项两边都过，但那是因为本机装了 Georgia。换到没有该字体的 Docker/CI 环境，
  resvg 会静默回退。**导出前把 text 转成 path 可规避这一整类问题**。

## 输出对比

| | headless Chrome | resvg-js |
|---|---|---|
| 尺寸 | 1360×720 | 1360×720 |
| colorType | 2（RGB） | 6（RGBA） |
| 体积 | 81 KB | 99 KB |
| 耗时 | 秒级启动 | 十几毫秒 |
| 依赖 | 系统已装浏览器 | `npm i @resvg/resvg-js`（预编译二进制） |

## 无头 Chrome 的额外陷阱

**无 `width`/`height`、只有 `viewBox` 的 SVG，作为独立文档渲染时，窗口小于约 176px
会输出全透明图。** `--virtual-time-budget=1000` 也无法修复。

实测扫描（`viewBox="0 0 120 120"` 的 SVG，`--force-device-scale-factor=1`）：

| 窗口边长 | 结果 |
|---|---|
| 100 / 120 / 150 | 全透明（空白） |
| 180 / 200 / 240 / 300 | 正常 |

对照组：

| 场景 | 结果 |
|---|---|
| 显式 `width="120" height="120"` 的 SVG，窗口 120×120 | 正常 |
| 普通 HTML 红方块，窗口 120×120 | 正常 |
| viewBox-only SVG，窗口 400×400 | 正常 |

结论：问题出在**无内在尺寸的 SVG 文档 + 小窗口**这个组合，而非窗口尺寸本身。
规避方式是渲染前把 viewBox 尺寸回填成显式像素宽高——`scripts/svg2png.py` 已内置该处理。

## 其他可选方案

| 方案 | 保真度 | 适用 | 短板 |
|---|---|---|---|
| Playwright / Puppeteer | ★★★★★ | 复杂 SVG、动效截帧 | 要装浏览器运行时，冷启动慢 |
| resvg-js / resvg CLI | ★★★★☆ | 服务端批量、CI、Serverless（有 wasm 版） | 见上表失分项 |
| sharp（libvips + librsvg） | ★★★☆☆ | 已有 sharp 图片流水线 | librsvg 内核，CSS/滤镜支持更弱 |
| Inkscape CLI | ★★★★☆ | 桌面一次性转换 | 启动慢，不适合高并发 |
| cairosvg（Python） | ★★☆☆☆ | 纯 Python 项目的简单 SVG | CSS、滤镜、mask 支持差 |
| ImageMagick | ★★☆☆☆ | 简单图形 | 内置解析器弱，需配 rsvg delegate |
| 云服务（CloudConvert 等） | ★★★★☆ | 不想维护环境 | 网络依赖 + 费用 |
