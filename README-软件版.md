# FLUKE Windows 桌面版

本页说明 FLUKE Windows 桌面版的下载与维护。稳定版仍为 Electron v1.0.3；Python + PySide6 + Qt Quick Native v0.1.0 Preview 1 已作为预览安装包单独发布。Native 仍在逐阶段对照旧版验收，尚不等同于完整替代版。旧版 Electron 的显示名称、应用标识、安装包文件名和本机数据目录会继续保留历史标识，以兼容现有安装、更新和记录。

## Native 预览版

从 [FLUKE Native v0.1.0 Preview 1 发布页](https://github.com/linjiuyao2025/FLUKE/releases/tag/native-v0.1.0-preview.1) 下载 Windows 安装包。安装器使用新的 FLUKE 品牌画面，并与旧版 Electron 使用不同的安装标识。Native 预览版尚无整应用内更新功能；新版本需从 GitHub 发布页手动下载。迁移验收完成前，请保留旧版、旧数据和可用备份。

旧版页面、字体和资源会随应用一起打包。日常记录继续保存在本机；天气查询和 Spotify 播放需要联网。

## 运行

安装 Node.js 后，在项目目录运行：

```powershell
npm install
npm start
```

## 生成安装包

```powershell
npm run dist:win
```

旧版 Electron 安装程序会输出到 `release\万象来信-当前版本-Setup.exe`（沿用历史构建文件名）。如需免安装版本，可运行 `npm run dist:portable`。

安装 1.0.3 或更新版本后，软件会在启动后和运行期间检查 [GitHub Releases](https://github.com/linjiuyao2025/FLUKE/releases)。下载完成时会询问是否立即重启安装；也可以按 Alt 打开菜单，在“帮助 → 检查更新”中手动检查。

## 导入本期新闻

展开报纸中的“本期内容”，把 `.json` 新闻内容包拖到虚线区域。应用会先校验并预览，确认后再发布；也可继续用“导入 JSON 文件”按钮。单个内容包最大 500KB。

天气查询可输入常用中文城市名（例如厦门）；无法识别的城市可试试英文或拼音。

## 从浏览器版迁移数据

1. 在原浏览器版打开“备份与数据”，选择“导出完整备份”。
2. 安装并打开桌面版，在同一位置选择“导入备份”。
3. 选择刚导出的 JSON 文件并确认恢复。

旧版 Electron 数据保存在 `%APPDATA%\Wanxiang Life Workspace`。该目录名是历史兼容标识；卸载应用不会自动删除这份本机数据，更换电脑前仍建议导出完整备份。
