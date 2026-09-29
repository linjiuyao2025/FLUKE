# FLUKE Native v0.1.2 — 迁移预览 2

这是 FLUKE Native v0.1.2-preview.2 的公开预览发布。它不会覆盖既有 `native-v0.1.1-preview.1` 或 `native-v0.1.2-preview.1`，也不会删除 Electron v1.0.3、旧版数据、本机备份或旧版回退路径。

## 本版内容

- Native 源码继续使用 PyInstaller、Inno Setup 6.7.3、FLUKE 安装向导资源和独立 Native AppId。
- 正式安装布局为 side-by-side：程序写入 `D:\FLUKE-Native\versions\<version>`，根目录 launcher 保留为恢复入口；用户 SQLite 数据在版本目录之外。
- 新版本只有在完成标记存在且临时 SQLite 启动健康检查成功后才会写入 `active.json`；旧版本保留并记录为 `previousVersion`。
- 应用内更新器继续检查官方 GitHub Release，下载并校验安装包与 `.sha256` sidecar 的文件名、大小、Windows PE、SHA-256；旧式平面安装仍只显示下载/校验，不显示自动安装。
- 本版修复了 Native QML 的键盘侧栏激活和历史摘要参数调用，并保留失败启动、安装中断、用户取消、磁盘空间不足和 SQLite 数据保护的回滚边界。

## 发布资产与证据

- GitHub tag：`native-v0.1.2-preview.2`
- 安装包：`FLUKE-0.1.2-Setup.exe`
- 本地候选包路径：`native/release/FLUKE-0.1.2-Setup.exe`
- 候选包大小：`962,034,879` bytes
- 候选包 SHA-256：`ec4425be909ff59150a02b2503fea6b04169560898f497c208ff7c36579bc902`
- sidecar 已由 `scripts/verify-release-artifacts.ps1` 重新校验，并确认 3 个引擎包清单。
- PyInstaller 和 Inno Setup 编译成功；隔离生产包安装日志以 `Installation process succeeded` 结束；`versions\0.1.2\.install-complete.json`、根 launcher 和 `active.json` 均存在。
- 隔离生产安装版的 `FLUKE.exe` 与当前 `dist\FLUKE\FLUKE.exe` SHA-256 一致；安装版健康检查生成独立 SQLite，完整性检查为 `ok`。
- 安装向导编译日志确认读取 `installer/fluke-wizard.png` 与 `installer/fluke-small.png`；QA 使用独立 AppId、程序目录和用户数据目录，未使用生产 `D:\FLUKE`。
- 当前工作区受控全量回归：`648` 项通过、`1` 项跳过，退出码 0；环境为 `QT_QPA_PLATFORM=offscreen`、软件 Qt Quick、Basic controls 和 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`。跳过项是 FFmpeg 构建不含视频测试 codec。

## 更新器和恢复验证

已通过源码聚焦测试和隔离演练覆盖：SHA-256 不匹配、sidecar 文件名不匹配、无效 PE、下载中断、用户取消、磁盘空间不足、缓存包重校验、失败激活回滚、首次启动失败回滚、不完整版本不被选择、重启后选择活动版本，以及更新/回滚后外部 SQLite 仍可读。公开 preview.1 资产也已独立下载并与 sidecar 的大小和 SHA-256 对齐；应用内 bridge 的缓存包重新校验路径已实际执行。

本机再做一次未认证 GitHub API 实时检查时遇到 `HTTP 403 rate limit exceeded`。这说明在线检查还需要在受限网络/公共 API 限流条件下做独立稳定性验收；不能把 GitHub CLI 读取 Release 或已上传资产的元数据，写成应用内 bridge 的实时检查已通过。

这仍不等于阶段 6/7 全部通过：本轮没有把公开资产执行成无人值守的自动安装/重启/失败恢复闭环，也没有完成默认 Windows GUI 的逐控件人工验收、真实个人数据切换、真实云服务/Spotify/通知/定位/拖放验收或长期并行观察。因此自动安装按钮仍只在可验证的 side-by-side 布局中可用，旧版仍应保留。

## 回退与安全边界

- 现有 `D:\FLUKE` 旧式 Native v0.1.1 安装不会被本预览自动覆盖。
- 保留 Electron v1.0.3、Native v0.1.0/v0.1.1、旧版数据和备份；不要删除旧目录或直接把个人数据库放进版本目录。
- `.sha256` 只证明下载内容与 sidecar 一致；安装包没有 Authenticode 签名，不能单独证明发布者身份。
