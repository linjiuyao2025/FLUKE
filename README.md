# FLUKE · 万象来信

万象来信是一个本机优先的 Windows 生活工作台，由原有的 `life-workspace.html` 页面封装为 Electron 桌面软件。日常记录保存在本机，天气查询和 Spotify 播放需要联网。

## 下载与更新

前往 [GitHub Releases](https://github.com/linjiuyao2025/FLUKE/releases) 下载最新的 Windows x64 安装包。1.0.3 及后续版本会检查 GitHub 更新，下载完成后提示重启安装；按 Alt 可打开菜单，手动选择“帮助 → 检查更新”。新安装默认放在 `%LOCALAPPDATA%\Programs\万象来信`，选择其他父目录时会自动创建应用文件夹。旧版本升级时保留原安装路径。

本机 AI 修改页面后，也可运行 `npm.cmd run update:local`，关闭并重开软件即可应用页面改动；详见 [更新说明](UPDATES.md)。

## 从源码运行

需要 Node.js。克隆仓库后运行：

```powershell
npm ci
npm start
```

在 Windows 上构建安装包：

```powershell
npm run dist:win
```

生成的安装包、blockmap 和 `latest.yml` 位于 `release/`。公开发布流程见 [更新说明](UPDATES.md)。

## 数据

软件数据保存在 `%APPDATA%\Wanxiang Life Workspace`，不随源码或安装包上传。若此前使用浏览器版，请在浏览器版“备份与数据”导出完整备份，再在桌面版导入。

仓库只包含软件源码与打包所需资源。项目工作目录中的个人笔记、试跑内容包、历史备份和构建产物不在仓库内。
