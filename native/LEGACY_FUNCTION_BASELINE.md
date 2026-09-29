# FLUKE 旧版功能基线（Stage 0）

审计日期：2026-09-29<br>
旧版源码入口：仓库根目录的 life-workspace.html<br>
适用目的：为 FLUKE Native 的逐功能迁移和回归提供可追踪清单；本文件是仓库当前 main 分支旧版源码基线，不是旧版或新版运行验收报告。

## 基线身份与证据规则

| 项目 | 当前结论 | 证据 |
|---|---|---|
| 旧版发布标称 | Native README 将 Electron v1.0.3 标为公开稳定版 | native/README.md:5-9 |
| 源码与 v1.0.3 安装包是否同源 | **待核**。当前没有建立发布标签、源码提交、安装包散列和运行文件之间的对应关系；旧版迁移导出写入 sourceVersion=unknown | life-workspace.html:2988-3003；native/README.md:7-9 |
| 本清单的旧版证据 | L0：只从旧版 HTML/脚本静态列出可见界面和操作；没有在本轮打开或操作旧版 v1.0.3 安装程序 | 下表每项旧版来源锚点 |
| Native 对照证据 | N1：Native QML/Python 对应源码存在；只表示可以找到实现位置，不表示与旧版逐操作一致或运行通过 | 各行 Native 对照列；native/README.md:43-49 |
| 自动化与安装证据 | v0.1.1 发布候选源码的历史结果是 624 项通过、1 项跳过；当前 main 在明确记录的 Qt 受控环境下为 647 项通过、1 项跳过；这些都是源码/QML 合成回归（N2），不等于逐控件的 Native 安装版验收（N3）或旧版运行验收（L3） | `native/.venv\Scripts\python.exe -m unittest discover -s tests -v`；当前结果见 `qa-artifacts/stage5/native-unittest-main-offscreen-2026-09-30-after-health-report-fix.log`，安装版逐功能和旧版现场证据仍待补 |

## 本轮逐功能状态标签

下表把“有 Native 去向”和“已经验收”分开记录。除特别注明外，旧版功能均为 L0 静态源码证据；Native 源码/合成检查不升级为旧版现场、真实数据或安装版证据。

| 功能范围 | Native 去向 | 只有源码实现 / 已有合成证据 | v0.1.1 安装包 | 旧版运行 | 真实数据 | 云端或外部范围 |
|---|---|---|---|---|---|---|
| 每日流程、问题簿、新闻导入/编辑/阅读 | `DailyFlowPage.qml`、`daily.py`、`issues.py`、`news_import.py`、`ArticleDialog.qml`、`reading.py` | 源码 + N2 QML/模块合成检查；127 项阶段 1/3/4 针对性测试覆盖拖入解析、发布、历史和重启路径；N3 仅有当前 main 启动/渲染证据 | 当前 main QA 包已启动；真实链接/JSON 拖入和逐功能安装版操作仍未验收 | 待验证 | 待验证 | 天气、新闻原文、Spotify 和可能的连接器不属于本地迁移包 |
| 记账、习惯、健身、待买、书影音、时光档案 | 对应 `*Page.qml`、`finance.py`、`habits.py`、`fitness.py`、`shopping.py`、`media.py`、`archive.py` | 源码 + N2 模块/完整回归合成测试；存储、边界、首页关联和重启路径有自动化证据；未把合成数据升级为安装版逐字段验收 | 当前 main QA 包有首页渲染；每个模块的安装版人工字段、导出和真实数据仍未验收 | 待验证 | 待验证 | 远程 ID、服务端表和外部封面/服务不由 localStorage 快照证明 |
| 日程、看板、子任务、专注与工作记录 | `PlannerPage.qml`、`planner.py`、日历/提醒/同步模块；`DailyFlowPage.qml` 负责专注入口 | 源码 + N2 本地/合成服务检查；任务、专注、备份关联和恢复路径纳入回归；真实提醒、ICS/CalDAV/WebDAV 与安装版待验 | 当前 main QA 包仅证明启动/健康检查；真实提醒、拖动和云服务操作未验收 | 待验证 | 待验证 | 远程日历、WebDAV 服务器和账号历史必须独立核对 |
| 品牌、主题、语言、设置、备份/恢复/清理、迁移 | `PreferencesDialog.qml`、`BrandAppearanceDialog.qml`、`Main.qml`、`backup.py`、`migration.py` | 源码 + N2；迁移、主题、备份恢复和设置数据关联有合成回归；旧版密码备份和正式发布包现场验收仍缺失 | 当前 main QA 包已做启动/健康检查，历史 QA 包有主题/缩放截图；当前安装版逐控件操作仍未验收 | 待验证 | 真实迁移包仅做只读校验/预览，未应用 | 云端备份/同步服务不属于本地迁移包 |

## 证据边界

- `native/LEGACY_CONTROL_INVENTORY.md` 记录 247 项静态控件，`native/LEGACY_DYNAMIC_CONTROLS.md` 记录动态控件族；它们与本表合并阅读，不能把控件数量当作运行通过数量。
- 仓库没有找到名为 `build.files` 的文件；本轮读取到的旧版运行相关源码在 `life-workspace.html` 与 `desktop/`，发布/安装输入另见 `package.json`、`build/installer.nsh` 和 `native/installer/FLUKE.iss`。因此不能声称已经核对了不存在的 `build.files`。
- 本机找到一份 Downloads 下的迁移 JSON，但来源和对应旧版 profile 未建立关系；只读结果与当前活动 Native 快照为新快照而非相同快照，未执行导入。

## 版本范围

下表以仓库当前 main 分支的 `life-workspace.html` 为静态核对对象，不能整体视为 Electron v1.0.3 发布包的功能清单。可重复的动态控件族另见[动态控件清单](LEGACY_DYNAMIC_CONTROLS.md)，与[247 项静态控件表](LEGACY_CONTROL_INVENTORY.md)合并阅读。GitHub `v1.0.3` 标签指向源码提交 `2025032e1140eb01e0900cd2254354a422ef472d`；该标签源码中未发现 WebDAV 备份界面、加密备份密码弹层、Native 专用迁移导出、`.wxbackup` 导入、ICS/在线日历界面或专注会话 CSV 导出。这些项目是仓库当前 main 的后续源码，逐项列出是为了避免迁移时遗漏后续版本行为，不代表它们属于 v1.0.3 稳定版。v1.0.3 标签源码枚举的九个 localStorage 键与存储映射中的 schema 1 相符；当前 main 的迁移格式另有 schema 2 设备标识键。发布标签与日常使用的安装包/profile 仍未建立对应关系。

每项状态都按“旧版运行：待验证”处理。旧版源码锚点用于安排后续现场检查；确认具体旧版安装版本、执行每个流程并留截图/记录后，才可更新为运行验收。Native 源码和合成数据结果不能替代旧版运行证据。

## 八个主导航页

| 页面 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 每日流程 | life-workspace.html:805,869-951。四步导览；首页模块、快捷记账/体重/待买、新闻与天气、问题簿、昨日记录、今日待办和专注入口 | DailyFlowPage.qml；daily.py、issues.py、preferences.py、reading.py 有对应源码。旧版 L0；Native N1+N2；当前 main QA 有启动/渲染证据 | 旧版运行交互、字段保存/重启、所有快捷入口和布局行为；新闻导入各路径及天气失败提示的安装版现场操作 |
| 记账理财 | life-workspace.html:807,953-977。收入/支出、金额、类别、日期、备注；月预算、月份/类别筛选、趋势统计、表格导出和记录删除 | FinancePage.qml、finance.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 分类、预算、筛选统计、删除、导出与旧版逐项一致性；安装版重启后的记录和设置 |
| 习惯健康 | life-workspace.html:808,979-989。每日打卡、计数/数值目标、连续天数、热图；新增/删除自定义习惯和管理设置 | HabitPage.qml、habits.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 三类习惯输入、日期边界、连续天数/热图、隐藏/删除行为和安装版重启持久化 |
| 减脂健身 | life-workspace.html:809,990-1012。体重及身体记录、运动/时长、饮食/热量、睡眠和备注；目标档案、进度趋势、每周运动/饮食计划、表格导出 | FitnessPage.qml、fitness.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 记录字段、目标计算、档案及周计划弹层、导出和跨日展示；Native 安装版行为 |
| 日程统筹 | life-workspace.html:810,1013-1037。添加/编辑/删除任务；日期时间、预计时长、重复、项目/标签、优先级、备注、提醒、完成状态；周视图、时间线/看板/矩阵、自定义看板、子任务、计时与工作记录；仓库当前 main 另有 ICS、在线日历来源/冲突和专注会话 CSV 导出（v1.0.3 标签未发现这些界面） | PlannerPage.qml、planner.py、calendar/提醒相关源码有对应实现。旧版 L0；Native N1+N2；远程 WebDAV 目前只用 localhost 合成服务验证 | 所有视图及任务字段；工作记录 CSV；ICS 往返；订阅/CalDAV/WebDAV 真实账户、重复/冲突、系统提醒和通知；安装版与离线恢复 |
| 待买清单 | life-workspace.html:811,1038-1054。新增物品、数量、类别、价格、优先级、备注；按状态过滤、标记已买、删除和汇总 | ShoppingPage.qml、shopping.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 新增/编辑状态、分类、金额汇总、过滤、已买日期和删除确认 |
| 书影音 | life-workspace.html:812,1055-1073。记录名称、类型、状态、评分、日期、短评和封面；墙面/列表、状态与评分过滤、年度统计、删除 | MediaPage.qml、media.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 封面选择与持久化、筛选/统计、删除和数据关联；真实安装版体验 |
| 时光档案 | life-workspace.html:814,1074-1080。按全部/记账/健康/日程/待买筛选历史记录；按日期或月份折叠查看并呈现月度洞察 | ArchivePage.qml、archive.py 有对应源码。旧版 L0；Native N1+N2 合成回归 | 所有记录类型的归档关系、日期分组、筛选以及统计边界的安装版逐项验收 |

移动端导航在 life-workspace.html:1085 使用相同八个 data-nav 目标；这只是旧版 HTML 结构证据，系统缩放、窗口窄屏布局和实际点击行为仍待运行检查。

## 每日流程的四个步骤

| 步骤 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 01 今日速览 | life-workspace.html:875-918。天气城市设置/定位；关注主题；新闻链接拖入素材箱、刊期 JSON 文件拖入或粘贴/编辑；仓库当前 main 另有复制生成提示和导出本期 JSON；预览、保存草稿、发布、历史、模块排序/显隐；打开文章、保存剪报/知识 | DailyFlowPage.qml、ArticleDialog.qml；daily.py、issues.py、news_import.py、home_layout.py、reading.py。旧版 L0；Native N1+N2；127 项针对性测试覆盖导入、预览、发布、历史和重启 | 链接拖入和 JSON 文件拖入必须分别在 QA 安装版现场验证；提示复制和 JSON 导出；预览、校验错误、保存/发布/历史、城市/定位失败和重启持久化的安装版操作 |
| 02 昨日复盘 | life-workspace.html:923-929。查看近期/更早记录和周摘要；仓库当前 main 另有“给明天的自己留一句跟进线索”及保存操作；添加、查看、移除问题簿条目；跳转时光档案 | DailyFlowPage.qml、ArchivePage.qml；daily.py、archive.py。旧版 L0；Native N1+N2 合成回归 | 次日线索保存、跨日回看；笔记日期归属、问题簿字符串/对象格式、删除/归档与历史跳转的安装版现场行为 |
| 03 今日工作 | life-workspace.html:932-940。查看今日任务、习惯；完成状态；打开完整日程/习惯管理；快捷记账、记体重、加入待买项；页面同时出现待办/邮件语义区域 | DailyFlowPage.qml 与 PlannerPage.qml、HabitPage.qml、FinancePage.qml、FitnessPage.qml、ShoppingPage.qml。旧版 L0；Native N1+N2 合成回归 | 快捷操作是否进入正确表单并保存；邮件/连接器区域实际可用性与旧版条件状态；安装版逐项点击未验收 |
| 04 开始专注 | life-workspace.html:941-951；播放器相关实现 life-workspace.html:3423-3506。选择当前任务，开始/暂停/继续/重置或结束计时，选择专注模式；Spotify 链接和页内播放器 | Native 当前 main：DailyFlowPage.qml、daily.py 已接入 Spotify 官方嵌入播放器并保留外部打开入口；focused QML/integration 检查覆盖支持类型、embed URL 与视图加载（N2）；当前 main 已打包进 `FLUKE QA 0.1.2` 并完成启动/健康检查，但未完成真实播放器操作。已发布 v0.1.1 安装包仍仅保存链接并外部打开，不含页内播放器。实际音频播放尚未在桌面运行环境验证，源码测试不代表播放验收 | 旧版计时状态、累计与工作日志；Spotify 实际播放、登录/账户状态、地区可用性和网络限制；正式 Windows 安装版的 WebEngine 播放行为 |

## 设置、弹层、反馈和全局数据操作

| 范围 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 品牌与外观 | life-workspace.html:803,1121-1135。品牌名称/副标题、文字或图片头像、主题配色、裁切预览 | BrandAppearanceDialog.qml、PreferencesDialog.qml、preferences.py 有源码。旧版 L0；Native N1+N2；主题预览/保存/重开有自动化证据，历史 QA 有主题截图 | 图片权限/裁切、主题在各页覆盖、当前 main 安装版保存后重启、键盘/缩放表现 |
| 语言和通用提示 | life-workspace.html:1709-1717,1134。中英文切换；确认框、toast、状态/错误信息 | PreferencesDialog.qml 与各页面状态处理有源码。旧版 L0；Native N1+N2；本地化 QML/状态检查通过 | 所有界面的完整翻译、安装版错误提示、确认流程和可访问操作 |
| 习惯设置面板 | life-workspace.html:1086-1098。习惯名称、类型、目标、单位、颜色及管理/删除 | HabitPage.qml / Native 习惯编辑 UI 有源码。旧版 L0；Native N1+N2 合成回归 | 表单字段、校验、已有历史数据删除后处理的安装版行为 |
| 每周计划面板 | life-workspace.html:1099-1110。新增/调整运动或饮食计划及完成状态 | FitnessPage.qml 有源码。旧版 L0；Native N1+N2 合成回归 | 增删改、完成标记、保存和计划排序的安装版行为 |
| 健身档案面板 | life-workspace.html:1111-1120。个人起点、目标和档案设置 | FitnessPage.qml 有源码。旧版 L0；Native N1+N2 合成回归 | 字段范围、估算规则、已有记录变化后的进度结果 |
| 文章阅读弹层 | life-workspace.html:1137-1139,2178。新闻正文、摘要、出处/原文链接、保存入口、关闭 | ArticleDialog.qml、reading.py 有源码。旧版 L0；Native N1+N2；新闻工作流合成回归覆盖链接处理和保存路径 | 链接安全、正文/图片显示、当前安装版键盘关闭、保存与重启 |
| 加密备份密码弹层（仓库当前 main 后续源码） | life-workspace.html:839-847,2884-2893。导出时设置并确认密码；恢复时输入密码；密码不留存；v1.0.3 标签未发现对应控件 | Main.qml 与 backup.py 有源码；Native N1+N2，全量合成回归通过 | 正式安装版导出/恢复、错误密码和损坏包恢复；不要据源码或合成测试宣称已验收 |
| WebDAV 备份和同步冲突弹层（备份界面为仓库当前 main 后续源码） | life-workspace.html:848-868,2973-2977,3309-3313。配置地址/账号/密码、上传/恢复加密快照、移除本机凭据；查看/解决日程同步冲突；v1.0.3 标签未发现 WebDAV 备份控件，冲突界面的标签内存在性待逐项核对 | Native 有 WebDAV 账户/冲突源码；README:9 仅记载 localhost 合成服务测试。旧版 main L0；Native N1+N2（localhost 合成） | 旧版真实 WebDAV 账号、服务器端文件、恢复/移除/冲突语义和 Native 真实账户行为 |
| 自定义看板与子任务弹层 | life-workspace.html:1026-1027,2461-2463。建改删看板列、状态/标签绑定；为任务新增子任务 | PlannerPage.qml、planner.py 有源码。旧版 L0；Native N1+N2 合成回归 | 看板限制、拖动/排序、任务保留关系、子任务完成与删除 |
| 全局数据菜单与危险操作 | life-workspace.html:822-836。明文备份与清理操作；仓库当前 main 另有加密备份、WebDAV 快照、Native 专用迁移包及 `.wxbackup` 导入，v1.0.3 标签未发现这些新增控件 | Main.qml、backup.py、migration.py 有源码；README:46 记载相关 Native 流程。旧版 main L0；Native N1+N2 合成回归 | 按具体版本核对每种文件格式/备份内容、重复导入、失败回滚、危险操作确认，以及真实迁移包数量和内容对账 |
| 外部服务与云账户边界 | life-workspace.html:约 1200-1370 的条件式 SmartPage 数据库调用、planner 远端同步逻辑；Native README:9 明确 provider 注入和云账号范围/历史未验证 | Native 不能从本地迁移源码推断云账户内容。旧版 L0；Native 对照状态待核 | SmartPage provider 实际注入、云端表/记录种类、账号与本地缓存边界、冲突/历史同步。须独立登录与服务端证据；不得以 localStorage 导出替代 |

## 最快补齐基线的追踪缺口

1. 锁定 Electron v1.0.3 的发布包、源码提交和可运行安装环境之间的对应关系；保存版本信息、哈希和验收环境记录。
2. 依据上表逐项操作旧版并补截图/录屏或结果记录，特别覆盖新闻的两种拖入、备份/恢复、清除、WebDAV、计时与跨日状态。
3. 为 Native 每行添加对应的页面/流程/持久化/错误恢复验收记录；区分源码审阅、合成回归、Native 安装版和旧版现场证据。
4. 将 SmartPage、WebDAV 服务器、日历订阅、天气和 Spotify 外部服务列为单独数据范围，不从本地迁移包推断云端账户完成迁移。

## 2026-09-30 阶段 1/3/4/5 证据补充

本节记录本轮对当前 main 的证据等级。N1 表示源码对应关系已存在，N2 表示源码/合成自动化检查通过，N3 表示隔离 QA 安装版已有实际启动、渲染或操作证据。N2 不升级为 N3；合成数据不代表用户真实数据，离线 mock 不代表外部服务已经可用。

| 阶段/功能 | 当前证据等级 | 已确认内容 | 仍未确认内容 |
|---|---|---|---|
| 阶段 1：启动、退出、主窗口、主题、窗口尺寸和系统缩放 | N1 + N2 + N3 | 源码入口和健康检查存在；阶段 1 针对性测试通过；旧 QA 包有首次/第二次启动、退出、1024x700 窄窗口、150% 缩放和主题切换截图；当前 main QA 安装版四个持久化主题读取截图均成功且像素哈希不同，并完成当前 main `1024x700` 逻辑尺寸截图 | 当前 main 安装版逐项人工键盘焦点/Tab 顺序、外观弹层真实点击切换、所有窄屏断点和不同 Windows 显示器组合仍需现场记录 |
| 阶段 1：键盘、无障碍和离线/异常状态 | N1 + N2；部分 N3 | QML/窗口/主题与异常状态自动化检查通过；最新 QA 安装版有离线隔离启动/渲染和健康检查证据；损坏 SQLite 的 `--health-check` 在安装版返回退出码 1、写出可理解错误且不覆盖原文件；错误输出兼容无 stderr 句柄的 GUI 打包环境 | 尚无当前 main 安装版逐控件 Tab 录屏或可访问树现场记录；离线新闻、天气、Spotify 网络失败的每个 UI 文案仍未逐项人工验收 |
| 阶段 3：新闻链接拖入 | N1 + N2 | `DailyFlowPage.qml`、`daily.py` 和新闻导入流程存在；针对链接拖入、错误处理、预览/保存/发布/历史的自动化检查通过 | QA 安装版真实鼠标拖入链接尚未验收 |
| 阶段 3：JSON 文件拖入 | N1 + N2 | 文件拖入与 JSON 刊期解析、错误提示和保存/重启流程的自动化检查通过 | QA 安装版真实文件拖入尚未验收 |
| 阶段 3：天气、保存后重启和排版操作 | N1 + N2；重启有合成证据 | 城市设置、查询失败、预览、草稿、发布、历史、排版和隔离数据库重启读取均有针对性或全量 unittest 证据 | 真实天气服务、安装版重启后的人工操作和真实用户数据尚未验收 |
| 阶段 3：Spotify 播放器 | N1 + N2 | 当前源码含载入中、载入成功、加载失败状态和官方 embed URL 校验；保留“在 Spotify 打开”外部回退；相关 QML/integration 检查通过 | 当前 QA/正式安装版未完成真实登录、音频播放、地区/网络限制和 WebEngine 实际播放验收；已发布旧 v0.1.1 包不包含本轮源码播放器 |
| 阶段 3：应用更新器 | N1 + N2 | 14/14 updater unittest 通过；离线 probe 的 8 个本地校验点通过，包含大小、PE、SHA-256、`.part` 清理和错误包不保留；GitHub Release 真实读取受未认证 API 403 限流影响 | 真实 GitHub Release 端到端读取、下载和安装重启仍未验证；当前源码环境默认不执行自动安装 |
| 阶段 4：生活记录、计划、媒体、提醒、首页和设置 | N1 + N2 | 当前 Native 对应页面、Python 存储和数据关联纳入完整 unittest；本轮 fail-fast 全量重跑通过 644 项、跳过 1 项 | QA 安装版只做了合成数据导入和首页渲染；每个页面的人工逐字段等价、真实提醒/通知和真实用户数据仍未完成 |
| 阶段 4：备份、恢复、WebDAV、云端边界 | N1 + N2；N3 未完成 | 备份/恢复、迁移、冲突和 WebDAV localhost 合成路径保留并通过源码/合成检查；本地数据与远端数据仍分层 | 真实 WebDAV 账号、远端文件、日历/云端冲突、真实恢复回滚和系统通知仍未验证；不得以合成服务结果代替云端验收 |
| 阶段 5：自动化回归 | N2（受控 Qt 环境稳定；默认 GUI 后端仍未证明） | 默认环境首次完整运行：639 项，144 failures，1 skipped；随后未改源码的 fail-fast 完整重跑：644 项通过，1 项跳过；2026-09-30 默认环境再次不带 fail-fast 的全量重跑在 `test_news_preview_offers_publish_and_cancel_returns_to_preview` 处进程中止；健康报告修复后，固定 `QT_QPA_PLATFORM=offscreen`、`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 的当前 main 普通全量运行：647 项通过，1 项跳过，343.359s。跳过项是 FFmpeg 构建不含视频测试 codec | 受控环境已经有当前源码普通全量绿色结果；默认 Windows GUI/图形后端仍需单独稳定性记录，不能把受控 offscreen 回归写成安装版或默认图形后端验收 |
| 阶段 5：隔离 QA 安装版 | N3（限定范围） | 用最新源码和稳定的 5,939 文件 dist 重新编译 `FLUKE-QA-0.1.2-Setup.exe`；安装退出码 0，安装目录 5,941 文件，QML/FFmpeg/Tesseract/Calibre 关键文件均存在；安装版隔离启动生成 1024x700 截图，健康检查数据库创建成功；损坏 SQLite 检查返回 1、错误可读且原文件保持不变。QA AppId 为 `FLUKE-Desktop-Native-QA` | 未完成安装版 Tab/拖放、真实 Spotify、真实天气/云服务、干净用户/VM 与正式发布包验收；当前截图/健康检查不等于逐项人工操作验收 |

### 本轮可复现证据位置

- 阶段 5 首次完整结果：`qa-artifacts/stage5/native-unittest-main-2026-09-29.log`。
- 阶段 5 完整重跑结果：`qa-artifacts/stage5/native-unittest-failfast-2026-09-29.log`。
- 阶段 5 2026-09-30 非 fail-fast 重跑：`qa-artifacts/stage5/native-unittest-main-rerun-2026-09-30.log`；在新闻预览 QML 用例处中止，无测试汇总。
- 阶段 5 2026-09-30 受控 Qt 环境普通全量结果：`qa-artifacts/stage5/native-unittest-main-offscreen-2026-09-30.log`；`644` 项通过、`1` 项跳过，退出码 0。
- 阶段 5 当前 main（健康报告兼容 GUI 打包环境后）普通全量结果：`qa-artifacts/stage5/native-unittest-main-offscreen-2026-09-30-after-health-report-fix.log`；`647` 项通过、`1` 项跳过，退出码 0，`343.359s`。
- 阶段 1 启动异常最新针对性结果：`qa-artifacts/stage5/startup-error-health-report-focused-2026-09-30.log`；`19` 项通过，包含损坏数据库不覆盖原文件检查。
- 阶段 1/3/4 针对性结果：`qa-artifacts/stage5/focused-stage1-3-4-2026-09-30.log`；`127` 项通过，退出码 0。
- 阶段 1 启动异常针对性结果：`qa-artifacts/stage5/startup-error-stage1-focused-2026-09-30.log`；`19` 项通过，包含损坏数据库不覆盖原文件检查。
- 更新器与 side-by-side launcher 针对性结果：`qa-artifacts/stage5/updater-launcher-focused-2026-09-30.log`；`19` 项通过，退出码 0。
- 源码隔离健康检查：`qa-artifacts/stage5/source-health-2026-09-30.log`，使用独立 `source-health.sqlite3`，退出码 0。
- 安装版 QA 证据：`qa-artifacts/qa-ds20260929/evidence/`；包括首次/二次启动、窄窗口、150% 缩放、合成数据、主题和离线截图及日志。
- QA 安装包：`qa-artifacts/qa-ds20260929/installer-output/FLUKE-QA-ds20260929-0.1.1-Setup.exe`；SHA-256 为 `0A727F737FB4747DF9631A7CE34DCDA295F9EE44FAF99E3DA794102A512AF868`。
- QA 安装目录：`qa-artifacts/qa-ds20260929/program/`；QA 数据库：`qa-artifacts/qa-ds20260929/db/fluke.sqlite3`；QA profile：`qa-artifacts/qa-ds20260929/profile/`。本轮没有安装到 `D:\FLUKE`，没有使用日常数据库。
- 当前 main QA 构建日志：`qa-artifacts/qa-ds20260930-current/qa-installer-build.log`；安装包：`qa-artifacts/qa-ds20260930-current/installer-output/FLUKE-QA-0.1.2-Setup.exe`；SHA-256 为 `9E2C1CA929060648FDE960AD71417C8F87724480540460F4E2BCB042E910DE4C`。
- 当前 main QA 安装目录：`qa-artifacts/qa-ds20260930-current/program/`；启动截图：`qa-artifacts/qa-ds20260930-current/current-main-capture.png`；启动输出：`qa-artifacts/qa-ds20260930-current/launch.stdout.log`、`launch.stderr.log`；健康检查数据库：`qa-artifacts/qa-ds20260930-current/db/health-check.sqlite3`。本轮仍只写入 `native/qa-artifacts`，没有安装到 `D:\FLUKE`，没有使用日常数据库。
- 当前 main QA 主题读取证据：`qa-artifacts/qa-ds20260930-current/theme-capture-results.txt` 与 `theme-{plum,forest,clay,navy}-capture.png`；四个隔离数据库分别保存主题后，安装版均退出码 0，截图哈希不同。这证明安装版能读取并渲染持久化主题，不等于人工打开外观弹层点击切换。
- 当前 main QA 紧凑窗口证据：`qa-artifacts/qa-ds20260930-current/current-main-1024x700.png`；请求逻辑尺寸 `1024x700`，安装版截图退出码 0，实际截图为 `1536x1050`，保留滚动区域且未发现启动级布局溢出。
- 最新源码 QA 构建日志：`qa-artifacts/qa-ds20260930-current-after-health-report-fix/qa-installer-build.log`；编译包含 `5,939` 个文件。
- 最新源码 QA 安装包：`qa-artifacts/qa-ds20260930-current-after-health-report-fix/installer-output/FLUKE-QA-0.1.2-Setup.exe`；SHA-256 为 `D71D9869AE5AFFCFABBA4C623CCE5AD547E42F573BD8B79882368662690C12FF`。
- 最新源码 QA 安装目录：`qa-artifacts/qa-ds20260930-current-after-health-report-fix/installed/program/`；QA 数据目录：`qa-artifacts/qa-ds20260930-current-after-health-report-fix/installed/db/`，隔离 profile：`qa-artifacts/qa-ds20260930-current-after-health-report-fix/installed/profile/`；有效安装版截图为 `installed/direct-capture.png`，健康检查数据库为 `installed/db/direct-health.sqlite3`，损坏数据库为 `installed/db/direct-corrupt.sqlite3`。
- 桌面控制器现场限制：启动的 QA 窗口实际存在且标题为 `FLUKE`，但桌面控制连接器仍返回 `apps=[]`；因此本轮没有生成键盘/Tab/鼠标拖放的伪造 N3 结论，相关日志和截图证据边界保持不变。

### 发布门槛判断

当前可以继续作为隔离 QA 包和源码回归候选，不宜宣称已经完成正式发布验收。最短阻塞清单是：

1. 将 Qt 测试环境固定项纳入可重复的回归入口，并决定是否还要补一轮默认 Windows GUI 后端的稳定性测试；当前受控 offscreen 普通全量已通过，但不能替代安装版图形验收。
2. 在隔离安装版补做键盘焦点/Tab、链接拖入、JSON 文件拖入和 Spotify 失败回退的现场证据。
3. 在不接触日常数据库的前提下补做真实天气、WebDAV/日历服务、提醒通知和干净用户/VM 验收。
4. 用包含当前 Spotify 播放器和更新器改动的源码重新生成正式发布候选包，再单独做发布包验收；当前 main 的隔离 QA 包已完成启动/健康检查，但不能把 QA 包等同于正式发布包，也不能把历史 v0.1.1 包当作当前 main 的证明。
