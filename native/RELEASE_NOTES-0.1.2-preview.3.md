# FLUKE Native v0.1.2 — 迁移预览 3

这是 FLUKE Native v0.1.2-preview.3 的公开预览发布。它不会覆盖 `native-v0.1.2-preview.1` 或 `native-v0.1.2-preview.2`，也不会删除 Electron v1.0.3、旧版数据、本机备份或旧版回退路径。

## 本版内容

- 保留 preview.2 的 PyInstaller、Inno Setup 6.7.3、side-by-side 版本目录、根 launcher、安装向导资源和外部 SQLite 数据边界。
- 应用内更新器在 GitHub API 返回公共限流 `403/429` 时，回退到官方 `releases.atom`、`expanded_assets/<tag>` 页面和官方安装包 `HEAD Content-Length`；仍只接受精确的 FLUKE 官方资产路径。
- API 与页面回退都继续执行 sidecar 文件名、SHA-256、安装包大小、Windows PE 和失败清理校验。
- 只有 side-by-side 版本目录具有自动安装入口；旧式平面安装仍保持下载/校验模式。

## 发布资产与证据

- GitHub tag：`native-v0.1.2-preview.3`
- 安装包：`FLUKE-0.1.2-Setup.exe`
- 本地候选包路径：`native/release/FLUKE-0.1.2-Setup.exe`
- 候选包大小：`962,040,550` bytes
- 候选包 SHA-256：`00ee1b1fdc8f9315bc9af4515ed83d6b6dd1cd70a7f5b7851be4b1ea75521012`
- `scripts/verify-release-artifacts.ps1` 已通过，并确认 3 个引擎更新包清单。
- PyInstaller 和 Inno Setup 编译成功；安装向导继续读取 `fluke-wizard.png` 与 `fluke-small.png`。
- 正式候选包在全新隔离根目录安装成功；安装日志记录 `Installation process succeeded`，`versions\0.1.2\.install-complete.json`、根 launcher 和 `active.json` 均存在；安装后 payload 与 `dist\FLUKE.exe` SHA-256 一致，健康检查退出码为 0，独立 SQLite `PRAGMA integrity_check` 为 `ok`。
- 更新器、launcher 和启动错误聚焦测试共 `22` 项通过；包含 API 限流回退、失败首次启动回退、SQLite 保留、下载中断/取消、磁盘空间不足、SHA-256/PE 校验和不完整版本保护。
- 真实 GitHub API 返回 `403 rate limit exceeded` 时，官方 Atom/expanded-assets fallback 成功读取 preview.3，得到精确安装包大小并选出可用 Release。
- 使用官方 preview.3 Release URL 通过现有 updater helper 完成完整公开安装包下载；隔离目录中收到 `962,040,550` bytes，SHA-256 与 sidecar 均为 `00ee1b1fdc8f9315bc9af4515ed83d6b6dd1cd70a7f5b7851be4b1ea75521012`，没有遗留 `.part` 文件。
- 在同一隔离生产根目录构造失败的 `0.1.3` launcher 候选后，实际根 launcher 激活失败仍保留可启动的 `0.1.1` 活动版本；外部健康 SQLite 的完整性仍为 `ok`。
- 隔离 QA 直接调用现有应用内更新桥接，以已校验的 preview.3 安装包完成 `0.1.1 -> 0.1.2` 自动安装切换；`active.json` 切换成功，外部 SQLite 仍为 `integrity_check=ok`，QA 进程已停止。
- 以刚才完整下载的公开包再次执行桥接安装，`0.1.1 -> 0.1.2` 切换成功；另一次 QA 演练用 `taskkill /T /F` 终止安装器进程树，等待稳定后 `active.json` 仍保持 `0.1.1`，没有未经健康检查的切换。
- 阶段 7 的补充性隔离观察让 `0.1.1` 与 `0.1.2` 使用独立 SQLite 和独立 `LOCALAPPDATA` 并行健康启动 3 轮；6 次退出码均为 `0`，两份数据库完整性均为 `ok`。这不是长期观察，也不替代真实个人数据验收。

## 阶段边界

本版仍不是阶段 7 的最终通过版本。阶段 6 的公开资产下载、sidecar/SHA-256/PE 校验、side-by-side 自动安装、首次启动健康检查、强制终止保留旧版和外置 SQLite 保留，已经在独立 QA 根目录完成；但尚未完成默认 Windows GUI 逐控件人工验收、真实个人数据切换和长期新旧版并行观察。因此旧版、旧数据和旧回退路径必须保留；自动安装不得扩大到旧式平面布局。

`.sha256` 只证明下载内容与 sidecar 一致；安装包没有 Authenticode 签名，不能单独证明发布者身份。
