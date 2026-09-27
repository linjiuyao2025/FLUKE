# 万象来信更新方式

## GitHub Releases

从 [GitHub 发布页](https://github.com/linjiuyao2025/wanxiang-life-workspace/releases) 安装 1.0.3 或更新版本。软件会在启动后和每隔 6 小时检查新版本；下载完成后选择立即重启安装，或退出软件时安装。按 Alt 打开菜单，可选择“帮助 → 检查更新”或“打开 GitHub 发布页”。

发布新版本时，先更新 `package.json` 版本并推送源码，再在 Windows 上运行 `npm.cmd run dist:win`。把 `release` 内对应版本的 Setup.exe、`.exe.blockmap` 和 `latest.yml` 一起上传到同一个公开 GitHub Release，标签格式为 `v版本号`。`latest.yml` 是应用检查更新所需的元数据，不要单独修改。

## 本机 AI 开发更新

安装 1.0.2 或更新版本后，在项目目录修改 `life-workspace.html`，运行：

```powershell
npm.cmd run update:local
```

关闭并重开已安装的软件，页面改动即生效。脚本将页面放入当前 Windows 用户的 `%APPDATA%\Wanxiang Life Workspace\content`，软件核对版本和文件摘要后才读取。字体等静态资源仍来自安装包，用户记录继续保存在原来的软件数据目录。

如果页面更新有问题，可运行 `npm.cmd run update:rollback`，然后重开软件；它会恢复上一次同步的页面，或回到安装包内置页面。安装新版本后，如仍需使用本地页面，请重新运行 `update:local`，以免旧页面覆盖新版。

`desktop/main.cjs`、Electron 版本、依赖和安装器设置的更改需要重新生成安装包。本机内容同步只影响这台电脑；其他电脑通过 GitHub Release 更新。
