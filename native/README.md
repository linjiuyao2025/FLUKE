# FLUKE 原生桌面版

原生版使用 **Python + PySide6 + Qt Quick**：Python 负责业务逻辑、SQLite、本机数据迁移和网络服务；QML 负责原生桌面界面。界面不使用 HTML，也不在浏览器或 Electron 中运行。

## 状态（preview.2；下方旧段落保留 preview.1 历史说明）

> **preview.3 更新**：更新器新增官方 Atom/expanded-assets 页面回退，已在 GitHub API `403` 限流环境下读取并选出 preview.2；preview.3 已完成重新打包，正在进行隔离安装和发布验证。阶段 6/7 仍未宣称通过。

> **preview.2 更新（2026-09-30）**：当前公开候选为 [Native v0.1.2 迁移预览 2](https://github.com/linjiyao2025/FLUKE/releases/tag/native-v0.1.2-preview.2)。候选安装包已完成 PyInstaller/Inno Setup 编译、SHA-256 sidecar 校验和隔离生产布局安装；受控全量回归为 648 项通过、1 项跳过。公开资产的应用内完整下载转安装、重启和失败恢复闭环、默认 Windows GUI 逐控件验收、真实个人数据与阶段 7 并行观察仍未完成，旧版及旧版数据必须保留。

原生版源码和功能仍按旧版基线分阶段核对，尚未达到完整替代旧版的验收门槛。GitHub 当前公开预览是 [Native v0.1.2 迁移预览](https://github.com/linjiyao2025/FLUKE/releases/tag/native-v0.1.2-preview.1)，安装包已通过 ISCC 编译、隔离安装和启动验证。Native v0.1.2 使用 FLUKE 品牌安装向导、side-by-side 版本目录和根目录 launcher：新版写入 `D:\FLUKE-Native\versions\<version>`，完成标记后由 launcher 用临时 SQLite 做 Qt Quick 健康检查，健康检查成功才切换 `active.json`；失败、安装中断或空间不足时保留旧版本。当前工作区最新受控全量 Native 自动化回归为 650 项：650 项通过、1 项跳过；由 `native/run-native-unittest.ps1` 固定 QT_QPA_PLATFORM=offscreen、软件 Qt Quick、Basic Controls 和 WebEngine GPU fallback，耗时 349.552 秒。该结果证明源码/QML 受控回归通过，但不替代正式安装版逐功能验收。应用更新器的下载、sidecar 文件名、PE、SHA-256、下载中断/取消和 side-by-side launcher 回退已有聚焦测试；真实发布资产上的自动安装、重启和完整回滚仍待独立验收。其他缺口包括：真实旧版运行、个人数据、SmartPage/WebDAV/远程日历、通知、定位、拖放和实际 Spotify 播放仍未完成验收。旧 Native v0.1.1 的 `D:\FLUKE` 安装仍保持手动升级，不会被自动更新覆盖。品牌默认值迁移只修改本机显示投影，保留用户明确保存的自定义名称和旧数据原文。Electron v1.0.3 与 Native v0.1.0 的源码、发布包和数据路径继续保留作回退。用户数据库、个人迁移包、个人记录和本机 QA 产物不会纳入 Git 跟踪或发布。

目前已建立 [旧版功能对照基线](LEGACY_FUNCTION_BASELINE.md)、[旧版存储键映射](LEGACY_STORAGE_MAP.md)、[247 项静态控件清单](LEGACY_CONTROL_INVENTORY.md) 和 [动态控件族清单](LEGACY_DYNAMIC_CONTROLS.md)。基线以仓库当前 main 为对象，并单独标识 v1.0.3 标签未发现的后续控件；旧版运行时及动态控件验收仍待完成。当前工作区最新受控全量 Native 自动化回归为 650 项：650 项通过、1 项跳过；由 `native/run-native-unittest.ps1` 固定 Qt 受控环境，耗时 349.552 秒。该结果证明源码/QML 受控回归通过，但不替代正式安装版逐功能验收。应用更新器的下载、sidecar 文件名、PE、SHA-256、下载中断/取消和 side-by-side launcher 回退已有聚焦测试；这也不能替代独立 Windows 安装版与真实发布资产验收。其他缺口包括：旧版 v1.0.3 发布包静态审计没有发现 SmartPage provider 创建/注入代码，页面中的六类云表操作仍是条件式；外部注入、云账号数据范围和历史同步结果没有验证；已发布的 Native v0.1.1 安装包仍保存 Spotify 链接并外部打开，不含页内播放器；仓库当前 main 源码已接入 Spotify 官方嵌入播放器并保留外部打开入口，当前 main 已进入隔离 QA 包但尚未进入正式发布包；focused QML/integration 检查覆盖链接类型、embed URL 与视图加载，但实际播放、登录/账户状态、地区可用性及网络行为尚未在运行环境验证。旧版 `.wxbackup` 密码保护备份读取和 Native `.wxbak2` 密码保护导出/恢复现已接入并有合成流程测试，尚待正式 Windows 安装版验收。旧版自有 WebDAV 日程同步已接入界面和本地模拟服务测试，真实 WebDAV 账户/Windows 安装环境尚未验收。七张首页卡的顺序、分区和显隐设置现已驱动主窗口布局并通过 SQLite/QML 合成流程检查。外部拖放、定位、通知和缩放还需在正式 Windows 安装版现场验收。

候选引擎包中的 Tesseract 使用禁用了 JBIG codec 的 libtiff，因此依赖 JBIG 解压的 TIFF 图像无法读取；这是特定 TIFF 压缩格式限制，不表示一般 OCR 功能不可用。Native 的整应用更新仅在 side-by-side 安装布局中允许自动安装；v0.1.1 旧布局仍手动升级。整体迁移和阶段 7 并行观察仍未完成。

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

FLUKE 自定义安装向导画面使用 [`fluke-wizard.png`](installer/fluke-wizard.png) 和 [`fluke-small.png`](installer/fluke-small.png)，Inno Setup 会将两者嵌入 Windows 安装包。

此流程会下载并组装 OFD、音视频、OCR 与电子书转换引擎。Native 预览安装包仅用于迁移验收；完整功能回归、干净 Windows 用户环境验收及整应用更新和失败恢复流程仍待完成。已准备的本地引擎、安装包、发布清单和 QA 产物均被 Git 忽略，不属于源码提交。

## 已接入的功能范围

- **今日速览与新闻：** 天气和城市设置、刊期 JSON 粘贴/编辑/文件拖入、新闻链接拖入素材箱、预览、草稿、发布、历史、分组顺序和版面设置；推荐排序与反馈在本机运行。
- **生活记录：** 习惯、记账、健身、日程与日计划、待买、书影音和时光档案；记录以 SQLite 仓储或本机覆盖层保存，并保留旧迁移快照原文。
- **日历与提醒：** iCalendar 导入/导出、在线日历订阅、CalDAV 读取和任务完成状态回写、应用运行时提醒及可选托盘通知；旧版 WebDAV 日程同步的账户设置、状态、重试与冲突处理已接入，当前只用 localhost 合成服务验证。
- **外观与数据：** 品牌、头像、主题、七张首页卡排序/分区/显隐设置、SQLite 完整备份恢复、旧版明文备份读取、旧版 `.wxbackup` 密码保护备份恢复、Native `.wxbak2` 密码保护备份导出/恢复，以及 schema 1/2 本地迁移包导入。Native 加密包使用独立 v2 封套，旧版软件无法读取；密码不写入设置或备份外的文件。
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
