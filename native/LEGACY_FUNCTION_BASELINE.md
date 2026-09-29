# FLUKE 旧版功能基线（Stage 0）

审计日期：2026-09-29<br>
旧版源码入口：仓库根目录的 life-workspace.html<br>
适用目的：为 FLUKE Native 的逐功能迁移和回归提供可追踪清单；本文件是源码基线，不是旧版或新版运行验收报告。

## 基线身份与证据规则

| 项目 | 当前结论 | 证据 |
|---|---|---|
| 旧版发布标称 | Native README 将 Electron v1.0.3 标为公开稳定版 | native/README.md:5-9 |
| 源码与 v1.0.3 安装包是否同源 | **待核**。当前没有建立发布标签、源码提交、安装包散列和运行文件之间的对应关系；旧版迁移导出写入 sourceVersion=unknown | life-workspace.html:2988-3003；native/README.md:7-9 |
| 本清单的旧版证据 | L0：只从旧版 HTML/脚本静态列出可见界面和操作；没有在本轮打开或操作旧版 v1.0.3 安装程序 | 下表每项旧版来源锚点 |
| Native 对照证据 | N1：Native QML/Python 对应源码存在；只表示可以找到实现位置，不表示与旧版逐操作一致或运行通过 | 各行 Native 对照列；native/README.md:43-49 |
| 自动化与安装证据 | 本轮运行 Native 全量 unittest：620 项通过、1 项跳过；这是源码/QML 合成回归（N2），不等于逐控件的 Native 安装版验收（N3）或旧版运行验收（L3） | `native/.venv\Scripts\python.exe -m unittest discover -s tests -v`；安装版逐功能和旧版现场证据仍待补 |

每项状态都按“旧版运行：待验证”处理。旧版源码锚点用于安排后续现场检查；确认旧版安装版本、执行每个流程并留截图/记录后，才可更新为运行验收。Native 源码和合成数据结果不能替代旧版运行证据。

## 八个主导航页

| 页面 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 每日流程 | life-workspace.html:805,869-951。四步导览；首页模块、快捷记账/体重/待买、新闻与天气、问题簿、昨日记录、今日待办和专注入口 | DailyFlowPage.qml；daily.py、issues.py、preferences.py、reading.py 有对应源码。旧版 L0；Native N1 | 旧版运行交互、字段保存/重启、所有快捷入口和布局行为；新闻导入各路径及天气失败提示 |
| 记账理财 | life-workspace.html:807,953-977。收入/支出、金额、类别、日期、备注；月预算、月份/类别筛选、趋势统计、表格导出和记录删除 | FinancePage.qml、finance.py 有对应源码。旧版 L0；Native N1 | 分类、预算、筛选统计、删除、导出与旧版逐项一致性；重启后的记录和设置 |
| 习惯健康 | life-workspace.html:808,979-989。每日打卡、计数/数值目标、连续天数、热图；新增/删除自定义习惯和管理设置 | HabitPage.qml、habits.py 有对应源码。旧版 L0；Native N1 | 三类习惯输入、日期边界、连续天数/热图、隐藏/删除行为和重启持久化 |
| 减脂健身 | life-workspace.html:809,990-1012。体重及身体记录、运动/时长、饮食/热量、睡眠和备注；目标档案、进度趋势、每周运动/饮食计划、表格导出 | FitnessPage.qml、fitness.py 有对应源码。旧版 L0；Native N1 | 记录字段、目标计算、档案及周计划弹层、导出和跨日展示；Native 安装版行为 |
| 日程统筹 | life-workspace.html:810,1013-1037。添加/编辑/删除任务；日期时间、预计时长、重复、项目/标签、优先级、备注、提醒、完成状态；周视图、时间线/看板/矩阵、自定义看板、子任务、计时与工作记录、ICS 导入导出、远程日历来源与冲突处理 | PlannerPage.qml、planner.py、calendar/提醒相关源码有对应实现。旧版 L0；Native N1；native/README.md:45 记载远程 WebDAV 目前只用 localhost 合成服务验证 | 所有视图及任务字段；ICS 往返；订阅/CalDAV/WebDAV 真实账户、重复/冲突、系统提醒和通知；安装版与离线恢复 |
| 待买清单 | life-workspace.html:811,1038-1054。新增物品、数量、类别、价格、优先级、备注；按状态过滤、标记已买、删除和汇总 | ShoppingPage.qml、shopping.py 有对应源码。旧版 L0；Native N1 | 新增/编辑状态、分类、金额汇总、过滤、已买日期和删除确认 |
| 书影音 | life-workspace.html:812,1055-1073。记录名称、类型、状态、评分、日期、短评和封面；墙面/列表、状态与评分过滤、年度统计、删除 | MediaPage.qml、media.py 有对应源码。旧版 L0；Native N1 | 封面选择与持久化、筛选/统计、删除和数据关联；真实安装版体验 |
| 时光档案 | life-workspace.html:814,1074-1080。按全部/记账/健康/日程/待买筛选历史记录；按日期或月份折叠查看并呈现月度洞察 | ArchivePage.qml、archive.py 有对应源码。旧版 L0；Native N1 | 所有记录类型的归档关系、日期分组、筛选以及统计边界 |

移动端导航在 life-workspace.html:1085 使用相同八个 data-nav 目标；这只是旧版 HTML 结构证据，系统缩放、窗口窄屏布局和实际点击行为仍待运行检查。

## 每日流程的四个步骤

| 步骤 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 01 今日速览 | life-workspace.html:875-918。天气城市设置/定位；关注主题；新闻链接拖入素材箱、刊期 JSON 文件拖入或粘贴/编辑；预览、保存草稿、发布、历史、模块排序/显隐；打开文章、保存剪报/知识 | DailyFlowPage.qml、ArticleDialog.qml；daily.py、issues.py、news_import.py、home_layout.py、reading.py。旧版 L0；Native N1。README:43 称新闻流程已接入源码 | 链接拖入和 JSON 文件拖入必须分别现场验证；预览、校验错误、保存/发布/历史、城市/定位失败和重启持久化 |
| 02 昨日复盘 | life-workspace.html:923-929。查看近期/更早记录和周摘要；添加、查看、移除问题簿条目；跳转时光档案 | DailyFlowPage.qml、ArchivePage.qml；daily.py、archive.py。旧版 L0；Native N1 | 笔记日期归属、问题簿字符串/对象格式、删除/归档与历史跳转 |
| 03 今日工作 | life-workspace.html:932-940。查看今日任务、习惯；完成状态；打开完整日程/习惯管理；快捷记账、记体重、加入待买项；页面同时出现待办/邮件语义区域 | DailyFlowPage.qml 与 PlannerPage.qml、HabitPage.qml、FinancePage.qml、FitnessPage.qml、ShoppingPage.qml。旧版 L0；Native N1 | 快捷操作是否进入正确表单并保存；邮件/连接器区域实际可用性与旧版条件状态 |
| 04 开始专注 | life-workspace.html:941-951；播放器相关实现 life-workspace.html:3423-3506。选择当前任务，开始/暂停/继续/重置或结束计时，选择专注模式；Spotify 链接和页内播放器 | DailyFlowPage.qml、daily.py。旧版 L0；Native N1，但有已知差异：native/README.md:9 记载 Native 保存 Spotify 链接并外部打开，不保留旧版页内播放器 | 旧版计时状态、累计与工作日志；音频播放/控制。需记录播放器差异的产品验收决定，当前不能标为功能等价 |

## 设置、弹层、反馈和全局数据操作

| 范围 | 旧版来源锚点与可见操作 | Native 对照状态 / 证据等级 | 待验证项 |
|---|---|---|---|
| 品牌与外观 | life-workspace.html:803,1121-1135。品牌名称/副标题、文字或图片头像、主题配色、裁切预览 | BrandAppearanceDialog.qml、PreferencesDialog.qml、preferences.py 有源码。旧版 L0；Native N1；README:46 概述品牌/头像/主题 | 图片权限/裁切、主题在各页覆盖、保存后重启、键盘/缩放表现 |
| 语言和通用提示 | life-workspace.html:1709-1717,1134。中英文切换；确认框、toast、状态/错误信息 | PreferencesDialog.qml 与各页面状态处理有源码。旧版 L0；Native N1 | 所有界面的完整翻译、错误提示、确认流程和可访问操作 |
| 习惯设置面板 | life-workspace.html:1086-1098。习惯名称、类型、目标、单位、颜色及管理/删除 | HabitPage.qml / Native 习惯编辑 UI 有源码。旧版 L0；Native N1 | 表单字段、校验、已有历史数据删除后处理 |
| 每周计划面板 | life-workspace.html:1099-1110。新增/调整运动或饮食计划及完成状态 | FitnessPage.qml 有源码。旧版 L0；Native N1 | 增删改、完成标记、保存和计划排序 |
| 健身档案面板 | life-workspace.html:1111-1120。个人起点、目标和档案设置 | FitnessPage.qml 有源码。旧版 L0；Native N1 | 字段范围、估算规则、已有记录变化后的进度结果 |
| 文章阅读弹层 | life-workspace.html:1137-1139,2178。新闻正文、摘要、出处/原文链接、保存入口、关闭 | ArticleDialog.qml、reading.py 有源码。旧版 L0；Native N1 | 链接安全、正文/图片显示、键盘关闭、保存与重启 |
| 加密备份密码弹层 | life-workspace.html:839-847,2884-2893。导出时设置并确认密码；恢复时输入密码；密码不留存 | Main.qml 与 backup.py 有源码；全量 Native 合成回归通过。旧版 L0；Native N1+N2 | 正式安装版导出/恢复、错误密码和损坏包恢复；不要据源码或合成测试宣称已验收 |
| WebDAV 备份和同步冲突弹层 | life-workspace.html:848-868,2973-2977,3309-3313。配置地址/账号/密码、上传/恢复加密快照、移除本机凭据；查看/解决日程同步冲突 | Native 有 WebDAV 账户/冲突源码；README:45 仅记载 localhost 合成服务测试。旧版 L0；Native N1 | 旧版真实 WebDAV 账号、服务器端文件、恢复/移除/冲突语义和 Native 真实账户行为 |
| 自定义看板与子任务弹层 | life-workspace.html:1026-1027,2461-2463。建改删看板列、状态/标签绑定；为任务新增子任务 | PlannerPage.qml、planner.py 有源码。旧版 L0；Native N1 | 看板限制、拖动/排序、任务保留关系、子任务完成与删除 |
| 全局数据菜单与危险操作 | life-workspace.html:822-836。导出完整明文备份、导出加密备份、配置/上传/恢复 WebDAV 快照、导出原生迁移包、导入 JSON/.wxbackup、清除全部数据、仅清除样例数据；导入文件输入接受 application/json/.json/.wxbackup | Main.qml、backup.py、migration.py 有源码；README:46 记载相关 Native 流程。旧版 L0；Native N1 | 每种文件格式/备份内容、重复导入、失败回滚、危险操作确认，以及真实迁移包数量和内容对账 |
| 外部服务与云账户边界 | life-workspace.html:约 1200-1370 的条件式 SmartPage 数据库调用、planner 远端同步逻辑；Native README:9 明确 provider 注入和云账号范围/历史未验证 | Native 不能从本地迁移源码推断云账户内容。旧版 L0；Native 对照状态待核 | SmartPage provider 实际注入、云端表/记录种类、账号与本地缓存边界、冲突/历史同步。须独立登录与服务端证据；不得以 localStorage 导出替代 |

## 最快补齐基线的追踪缺口

1. 锁定 Electron v1.0.3 的发布包、源码提交和可运行安装环境之间的对应关系；保存版本信息、哈希和验收环境记录。
2. 依据上表逐项操作旧版并补截图/录屏或结果记录，特别覆盖新闻的两种拖入、备份/恢复、清除、WebDAV、计时与跨日状态。
3. 为 Native 每行添加对应的页面/流程/持久化/错误恢复验收记录；区分源码审阅、合成回归、Native 安装版和旧版现场证据。
4. 将 SmartPage、WebDAV 服务器、日历订阅、天气和 Spotify 外部服务列为单独数据范围，不从本地迁移包推断云端账户完成迁移。
