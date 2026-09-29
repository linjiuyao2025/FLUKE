# FLUKE

<p align="center">
  <img src="assets/fluke-logo.png" alt="FLUKE 标志" width="520">
</p>

<p align="center">
  <img src="assets/github-social-preview.jpg" alt="FLUKE 项目宣传图" width="100%">
</p>

FLUKE 是本机优先的 Windows 生活工作台。本仓库正在把桌面核心从 Electron/HTML 迁移到 **Python + PySide6 + Qt Quick**：Python 负责业务、SQLite、本机数据迁移和网络服务；Qt Quick（QML）负责原生桌面界面，不在浏览器中运行。

## 当前版本状态

GitHub `main` 现包含 FLUKE Native 迁移源码。它仍在逐阶段对照旧版验收，**不是已完成的旧版替代品**；当前公开稳定安装包仍是 [v1.0.3](https://github.com/linjiuyao2025/FLUKE/releases/tag/v1.0.3) 旧版 Electron。旧版源码和数据路径保留为回退参考。当前尚未发布 FLUKE Native 安装包，也没有 Native 整应用自动更新器；请不要把本机测试安装包当作正式发行版。

当前迁移状态和验证边界见 [FLUKE Native 说明](native/README.md)。真实个人数据、迁移包、SQLite 数据库、凭据和本机测试产物不属于公开仓库。

## 运行原生版源码

需要 Python 3.10 或更新版本。Windows PowerShell：

```powershell
cd native
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python main.py
```

原生版的 Windows 安装包构建说明见 [native/README.md](native/README.md)。安装包构建会准备外部转换引擎；其依赖授权审查和公开发行验收尚未完成，因此本仓库目前只发布迁移源码，不提供新的安装包下载。

## 旧版 Electron 回退

当前公开稳定版的 Electron 源码仍保留在仓库根目录，可按原流程运行：

```powershell
npm ci
npm start
```

本机数据不会随源码上传。只有在原生版完成数据、功能、安装、更新和回退验收后，才会决定停止提供旧版。
