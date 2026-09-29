# FLUKE Native v0.1.2 — 迁移预览 1

这是 FLUKE Native v0.1.2-preview.1 的预览发布说明；源码 tag 和 GitHub Release 已创建。它不会覆盖既有 `native-v0.1.1-preview.1`，也不会删除 Electron v1.0.3、旧版数据或本机备份。

## 本版计划内容

- 继续保留当前 main 的 FLUKE 品牌、迁移摘要、Spotify 嵌入和本机数据路径改动。
- 安装包改为 side-by-side：程序 payload 写入 `D:\FLUKE-Native\versions\<version>`，根目录 launcher 负责选择活动版本。
- 新版本先使用临时 SQLite 做完整 Qt Quick 启动健康检查，成功后才写入 `active.json`；失败启动、安装中断、磁盘空间不足或用户取消时不切换旧版本。
- 应用内更新器检查官方 GitHub Release，下载 Setup 与 `.sha256` sidecar，验证文件名、SHA-256、Windows PE 和文件大小；只有可回滚布局才显示自动安装。
- 保留 Electron v1.0.3、Native v0.1.0/v0.1.1、旧版数据和旧版回退路径。

## 本次发布证据

- Inno Setup 6.7.3 编译退出码为 0；安装包使用新的 FLUKE 安装向导资源和 side-by-side `[安装目录]\versions\0.1.2` 布局。
- 隔离安装日志显示 `Installation process succeeded`；安装后的 root launcher 成功生成 `active.json`，并启动 `versions\0.1.2\FLUKE.exe`（窗口标题为 `FLUKE`）。
- 启动器回滚、安装器路径、更新器下载和迁移 schema 1/2 的聚焦回归共 41 项通过。
- 发布资产同时提供 `FLUKE-0.1.2-Setup.exe` 和同名 `.sha256` sidecar；sidecar 只校验该安装包，不代表 Authenticode 签名。
- 候选安装包为本地 `native/release/FLUKE-0.1.2-Setup.exe`，大小为 960,984,717 bytes，SHA-256 为 `71e2ce63b4474d19762ef61db8e4e27fdd82e7101e2a0b7b8caaa0fc4a2a6a93`；安装包作为 Release 附件上传；QA 数据不会上传到 GitHub。

## 已知限制与发布前门槛

- 旧 Native v0.1.1 的旧式 `D:\FLUKE` 安装不启用自动安装，需要手动安装本版到新的 side-by-side 目录。
- Native 还不是 Electron v1.0.3 的完整替代品；正式安装版、真实旧版运行、云账号、WebDAV、通知、定位、拖放和实际 Spotify 播放仍须分别验收。
- 这仍是预览版：完整旧版功能对照、真实个人数据导入、SmartPage/WebDAV/远程日历、通知/定位/拖放、实际 Spotify 播放和全量 Qt PDF 回归仍未完成。
- 应用内更新的下载和强校验已有聚焦测试；真实发布资产上的下载、安装中断、重启和自动回滚仍需后续独立验收。
- 当前全量 Native 回归为 647 项：628 项通过、18 项失败、1 项跳过；失败集中在 QtQuick.Pdf/pdfquickplugin 的同进程运行时加载，因此这次仍是预览发布，不能替代正式安装版全功能回归；真实发布资产上的自动安装闭环仍需独立验收。
- 在迁移验收完成前，不应停止使用旧版或删除旧版数据和备份。
