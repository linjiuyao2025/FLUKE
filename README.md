# FLUKE

<p align="center">
  <img src="assets/fluke-logo.png" alt="FLUKE 标志" width="520">
</p>

<p align="center">
  <img src="assets/github-social-preview.jpg" alt="FLUKE 项目宣传图" width="100%">
</p>

FLUKE 是本机优先的 Windows 生活工作台。本仓库正在把桌面核心从 Electron/HTML 迁移到 **Python + PySide6 + Qt Quick**：Python 负责业务、SQLite、本机数据迁移和网络服务；Qt Quick（QML）负责原生桌面界面，不在浏览器中运行。

## 当前版本状态

GitHub `main` 现包含 FLUKE Native 迁移源码。当前 Latest 是 [FLUKE Native v0.1.1 迁移预览](https://github.com/linjiuyao2025/FLUKE/releases/tag/native-v0.1.1-preview.1)，提供新版 Windows 安装包、FLUKE 品牌安装向导画面及 FFmpeg、Tesseract、Calibre 引擎更新包。应用会把旧版内置默认名称迁移为 FLUKE，同时保留用户明确保存的自定义名称和导入原文。Native 正逐阶段对照旧版验收，**整体迁移尚未完成，Native 还不是完整的旧版替代品**。历史 [Electron v1.0.3](https://github.com/linjiuyao2025/FLUKE/releases/tag/v1.0.3) 和 Native v0.1.0 仍保留，可作回退版本。Native 使用独立的安装标识和数据目录，不会覆盖旧版安装或数据；在迁移验收完成前，请保留旧版及备份。Native 暂无整应用自动更新器；获取新版本需从发布页手动下载。

当前迁移状态和验证边界见 [FLUKE Native 说明](native/README.md)。真实个人数据、迁移包、SQLite 数据库、凭据和本机测试产物不属于公开仓库。

## 运行原生版源码

需要 Python 3.10 或更新版本。Windows PowerShell：

```powershell
cd native
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python main.py
```

原生版 Windows 安装包构建说明和预览版已知限制见 [native/README.md](native/README.md)。最新安装包使用独立的 FLUKE Native 安装标识，不会升级旧版 Electron；迁移验收完成前，请保留旧版及其本机数据和备份。

## 旧版 Electron 回退

Electron v1.0.3 的源码和 GitHub 发布包仍保留在仓库中，可作为回退版本；源码可按原流程运行：

```powershell
npm ci
npm start
```

本机数据不会随源码上传。只有在原生版完成数据、功能、安装、更新和回退验收后，才会决定停止提供旧版。
