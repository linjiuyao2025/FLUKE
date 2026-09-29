# FLUKE 原生桌面版

原生版使用 **Python + PySide6 + Qt Quick**：Python 负责业务逻辑、SQLite、本机数据迁移和网络服务；QML 负责原生桌面界面。界面不使用 HTML，也不在浏览器或 Electron 中运行。

## 状态

原生版源码和功能仍按旧版基线分阶段核对，尚未达到替代旧版的验收门槛。当前公开稳定安装包仍为 Electron v1.0.3；旧版源码和数据路径继续保留。此目录不包含个人迁移包、用户数据库、个人记录或本机 QA 产物。

当前可见的主要缺口包括：旧版功能的逐控件基线尚未完成；原生安装版的完整功能回归尚未完成；旧版密码加密手动备份的读取/导出尚未迁移；SmartPage 云端数据库能力是否在旧桌面运行时启用仍待核实；Spotify 目前保存链接并外部打开，未保留页内播放器；尚无 Native 整应用更新与失败恢复流程。旧版自有 WebDAV 日程同步现已接入界面和本地模拟服务测试，真实 WebDAV 账户/Windows 安装环境尚未验收。七张首页卡的顺序、分区和显隐设置现已驱动主窗口布局并通过 SQLite/QML 合成流程检查。外部拖放、定位、通知和缩放还需在正式 Windows 安装版现场验收。

## 源码运行

需要 Python 3.10 或更新版本。在 `native` 目录运行：

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python main.py
```

默认数据库位于 `%APPDATA%\FLUKE\fluke.sqlite3`。不指定数据库时首次启动可能从旧原生版目录复制 SQLite 数据库；卸载不会删除用户数据。开发和测试应使用独立数据库路径。

窗口默认尺寸为 1480×960，最小尺寸为 760×620。隔离开发预览示例：

```powershell
.\.venv\Scripts\python main.py --size 760x620 --database .\preview.sqlite3 --capture .\preview.png
```

## Windows 安装包构建

构建依赖 PyInstaller 和 Inno Setup 6.7 或更新版本：

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[build]"
.\build-installer.ps1
```

此流程会下载并组装 OFD、音视频、OCR 与电子书转换引擎。**目前不能据此公开分发安装包**：Tesseract 随包 Windows 依赖 DLL 的许可、固定版本和对应源码材料仍需审计；最新工作树也尚未重建并完成安装版验收。已准备的本地引擎、安装包、发布清单和 QA 产物均被 Git 忽略，不属于源码提交。

## 已接入的功能范围

- **今日速览与新闻：** 天气和城市设置、刊期 JSON 粘贴/编辑/文件拖入、新闻链接拖入素材箱、预览、草稿、发布、历史、分组顺序和版面设置；推荐排序与反馈在本机运行。
- **生活记录：** 习惯、记账、健身、日程与日计划、待买、书影音和时光档案；记录以 SQLite 仓储或本机覆盖层保存，并保留旧迁移快照原文。
- **日历与提醒：** iCalendar 导入/导出、在线日历订阅、CalDAV 读取和任务完成状态回写、应用运行时提醒及可选托盘通知；旧版 WebDAV 日程同步的账户设置、状态、重试与冲突处理已接入，当前只用 localhost 合成服务验证。
- **外观与数据：** 品牌、头像、主题、七张首页卡排序/分区/显隐设置、SQLite 完整备份恢复、旧版明文备份读取，以及 schema 1/2 本地迁移包导入。旧版密码加密备份格式和加密导出仍未支持。
- **本地转换工具：** 图片、表格、文档、PDF、EPUB、OFD、OCR 和音视频转换；部分办公格式依赖本机 Office/WPS，专业转换引擎由构建流程准备。格式支持和限制以转换器页面与实现为准。

上述范围表示源码中已有实现或合成流程覆盖，不代表所有旧版行为均已对齐，也不代表正式安装包完成验收。

## 验证

运行原生版回归：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

根目录旧版 Electron 服务测试：

```powershell
node --test desktop/*.test.cjs
```

合成数据和测试数据库用于自动化验证，不应被视为真实账户、真实 WebDAV、Windows 通知中心、系统级拖放或正式安装流程的验收证据。

## 源码布局

- `main.py`：桌面入口与 QML 桥接。
- `qml/`：Qt Quick 页面和对话框。
- `wanxiang/`：SQLite 仓储、迁移、生活模块、新闻、网络服务和转换器。
- `tests/`：仓储、规则、QML 集成与合成流程测试。
- `scripts/`、`installer/`：引擎准备、打包和安装向导资源。
