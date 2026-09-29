# FLUKE

<p align="center">
  <img src="assets/fluke-logo.png" alt="FLUKE 标志" width="520">
</p>

<p align="center">
  <img src="assets/github-social-preview.jpg" alt="FLUKE 项目宣传图" width="100%">
</p>

FLUKE 是本机优先的 Windows 生活工作台。本仓库正在把桌面核心从 Electron/HTML 迁移到 **Python + PySide6 + Qt Quick**：Python 负责业务、SQLite、本机数据迁移和网络服务；Qt Quick（QML）负责原生桌面界面，不在浏览器中运行。

## 当前版本状态

> **preview.2 更新（2026-09-30）**：当前公开候选为 [FLUKE Native v0.1.2 迁移预览 2](https://github.com/linjiyao2025/FLUKE/releases/tag/native-v0.1.2-preview.2)。候选安装包已完成 PyInstaller/Inno Setup 编译、SHA-256 sidecar 校验和隔离生产布局安装；受控全量回归为 648 项通过、1 项跳过。自动安装/重启/失败恢复闭环、默认 Windows GUI 逐控件验收、真实个人数据与阶段 7 并行观察仍未完成，旧版及旧版数据必须保留。

GitHub `main` 现包含 FLUKE Native 迁移源码。当前公开预览是 [FLUKE Native v0.1.2 迁移预览](https://github.com/linjiyao2025/FLUKE/releases/tag/native-v0.1.2-preview.1)。候选实现包含新的 FLUKE 安装向导、side-by-side 版本目录、根目录 launcher，以及只在可回滚布局中出现的自动安装入口：更新器会先检查官方 Release、下载并校验 SHA-256 sidecar，再用隔离临时 SQLite 做启动健康检查；失败时保留旧版本并支持回退。受控全量回归已在规定 Qt 环境下通过，真实旧版运行、个人数据、云服务和自动更新闭环也仍待验收，所以这只是预览发布，不代表阶段 6/7 完成。旧版 v0.1.1 的 `D:\FLUKE` 安装仍只允许手动下载/安装，不会被新方案覆盖。Native 正逐阶段对照旧版验收，**整体迁移尚未完成，Native 还不是完整的旧版替代品**。历史 [Electron v1.0.3](https://github.com/linjiyao2025/FLUKE/releases/tag/v1.0.3) 和 Native v0.1.0 仍保留，可作回退版本；在迁移验收完成前，请保留旧版及备份。

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
