# 万象来信 Windows 桌面版

原有的生活工作台页面已接入 Windows 桌面窗口，字体和页面文件会随应用一起打包。日常记录继续保存在本机；天气查询和 Spotify 播放需要联网。

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

安装程序会输出到 `release\万象来信-当前版本-Setup.exe`。如需免安装版本，可运行 `npm run dist:portable`。

安装 1.0.3 或更新版本后，软件会在启动后和运行期间检查 [GitHub Releases](https://github.com/linjiuyao2025/wanxiang-life-workspace/releases)。下载完成时会询问是否立即重启安装；也可以按 Alt 打开菜单，在“帮助 → 检查更新”中手动检查。

## 导入本期新闻

展开报纸中的“本期内容”，把 `.json` 新闻内容包拖到虚线区域。应用会先校验并预览，确认后再发布；也可继续用“导入 JSON 文件”按钮。单个内容包最大 500KB。

天气查询可输入常用中文城市名（例如厦门）；无法识别的城市可试试英文或拼音。

## 从浏览器版迁移数据

1. 在原浏览器版打开“备份与数据”，选择“导出完整备份”。
2. 安装并打开桌面版，在同一位置选择“导入备份”。
3. 选择刚导出的 JSON 文件并确认恢复。

桌面版数据保存在 `%APPDATA%\Wanxiang Life Workspace`。卸载应用不会自动删除这份本机数据；更换电脑前仍建议导出完整备份。
