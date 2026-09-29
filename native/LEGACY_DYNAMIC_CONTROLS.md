# FLUKE 旧版动态控件清单（Stage 0）

审计日期：2026-09-29<br>
源码范围：仓库当前 main 分支的 `life-workspace.html`，SHA-256 `CADAD4662DFA835A6DC49E20FDDAED67830B46AC2BB79982CD5D1DEDB27141ED`<br>
版本边界：这是当前 main 源码的静态行为清单，不等于 Electron v1.0.3 安装包或运行时验收。已知版本差异见 [旧版功能基线](LEGACY_FUNCTION_BASELINE.md#版本范围)。

## 证据口径

- 动态控件的实例数随记录、新闻刊期、外部日历或同步冲突变化，因此按“控件族 / 事件委托”登记，不把一次静态扫描得到的实例数冒充固定控件总数。
- 下表的行为、事件选择器和数据目标来自源码（L0）。当前会话的电脑窗口清单没有可操作的原生旧版窗口；尚未锁定日常使用的 Electron v1.0.3 安装目录与 profile，也没有运行这些控件。因此全部旧版运行行为均为**待验证**。
- Native 对应模块仅表示可以追索到源码，不表示逐项功能等价或正式安装版已通过。真实用户文本、远程日历条目和账号数据不属于本清单。

## 动态控件族

| # | 动态内容 / 页面 | 按数据生成的可操作控件 | 事件处理与源码锚点 | 关联本地状态 / 影响 | 验收状态 |
|---:|---|---|---|---|---|
| 1 | 今日刊期焦点、快讯、延伸文章卡 | 阅读正文（`data-open-issue-article`，含可键盘聚焦的卡片）；打开原文链接；收进/移出剪报（`data-issue-save-id`、日期）；版面整理模式下，动态模块可在版位间拖动/排序（`data-paper-module`、`data-paper-slot`） | `renderIssueNewsCard`、`renderIssuePackage`、`issueSourceLink`、`issueSaveButton`：life-workspace.html:2084-2094,2135-2145；打开与键盘委托：:2171-2183,2233；版面拖放：:2252-2262 | 刊期来自 `ISSUE_CONTENT_KEY`；剪报写入 `ISSUE_CLIPPINGS_KEY`；模块布局写入 `wanxiang-paper-layout-v2`。外链只打开来源，不代表正文归档 | 静态源码 L0；卡片点击、键盘、图片、外链、剪报保存/重启和版面排序待验证 |
| 2 | 新闻导入预览、历史刊期 | 焦点/快讯各自上移和下移（`data-issue-move`、组、序号、方向）；历史选择器按归档动态添加选项并载入；发布后重建历史与当前刊期 | `renderIssuePackagePreview`、`updateIssueHistorySelect`、`initIssuePublisher`：:2148-2155,2183 | 刊期及历史写入 `ISSUE_CONTENT_KEY`；排序调整待发布内容；需覆盖非法/空历史行 | 静态源码 L0；顺序、历史载入、发布后重启待验证 |
| 3 | 新闻剪报列表 | 打开剪报文章（`data-open-issue-clipping`）；查看原文；删除剪报（`data-remove-issue-clipping`） | `renderIssueClippings`：:2107-2112；事件委托与 `toggleIssueClipping`：:2120-2128,2233-2249 | `ISSUE_CLIPPINGS_KEY`；条目数和排序取决于本机剪报 | 静态源码 L0；增删、重复项、顺序和重启待验证 |
| 4 | 问题簿列表 | 按列表索引删除问题（`data-delete-issue-question`） | `renderIssueDesk`、`bindIssueDesk`：:2184-2215 | `ISSUE_QUESTIONS_KEY`；需要核对字符串行和扩展对象行 | 静态源码 L0；删除、边界索引、重启待验证 |
| 5 | 首页洞察卡 | 空身体数据卡提供“记一次身体数据”（`data-quick=fitness`）；待买摘要可跳转清单（`data-nav=home`）；空待读卡可跳转书影音（`data-nav=media`）；其他洞察目前由数字/条形摘要组成 | `renderFitnessInsights`、`renderShoppingInsights`、`renderMediaInsights` 等：:2266-2302；点击委托：:3195-3197 | 快捷项只导航/打开对应表单；摘要读取本机记录，不单独新增记录 | 静态源码 L0；可见条件、跳转和空状态待验证 |
| 6 | 首页待办、习惯快捷卡、记录时间线 | 今日待办行可切换完成（`data-action=toggle-task`）；首页习惯 pill 可快速打卡（`habit-quick`）；近期记录和周活动是动态只读展示 | `taskRow`、`renderDashboard`：:1988-1997,2317-2320；总操作委托：:3195-3208 | 主状态记录与习惯条目；重启后应一致 | 静态源码 L0；快捷打卡、完成状态和跨页同步待验证 |
| 7 | 财务记录行及分类选项 | 动态分类筛选 `<option>`；每条记录的删除按钮（`data-action=delete`） | `recordRow`、`renderMoney`、分类更新：:2000-2001,2334-2346,2867；操作委托：:3197 | 主状态中的财务记录；筛选为设置项 | 静态源码 L0；收入/支出类别、删除确认、筛选和持久化待验证 |
| 8 | 每日习惯卡和每周计划 | 习惯有完成切换、计数加减、数值输入及删除；周计划有完成切换/删除；设置列表中的自定义习惯和计划各有动态删除按钮 | `renderHabits`、健身周计划与管理列表：:2350-2355,2383,2832-2835；操作委托/变更处理：:3197-3208 | 主状态中的 `habits.entries`、`weeklyPlan`；要区分内置、样例和用户自建项目 | 静态源码 L0；计数/数值边界、删除后历史及重启待验证 |
| 9 | 日程任务行、分组和拖动排序 | 任务行可完成、编辑、删除；符合条件的任务可新增子任务；任务可拖动；日期分组用 `<details>/<summary>` 展开 | `taskRow`、`renderPlanner`：:1988-1997,2801-2809；排序事件：:3215 起 | 主状态 planner 记录、重复任务/子任务关联、队列及排序设置 | 静态源码 L0；编辑、重复实例、撤销/同步状态和重启待验证 |
| 10 | 日程看板、自定义看板与象限卡 | 任务卡可编辑；按状态更改；上移/下移或拖放排序/跨列；自定义看板选择、创建、编辑；动态列名/状态/标签字段和删除列按钮；看板删除不删除任务 | `plannerRenderBoardCard`、`renderPlannerBoard`、`plannerRenderMatrix`、看板编辑器：:2455-2463；事件：:3141-3150,3177-3179 | `plannerCustomBoards`、看板顺序、任务 `done/status` 和四象限字段；保存后需保持任务与看板关联 | 静态源码 L0；键鼠、拖放、重排持久化、列数限制和删除语义待验证 |
| 11 | 周历、时间轴和空档建议 | 周 strip 生成七个日期按钮；时间轴按半小时生成 48 个放置按钮；已有任务生成可拖动事件按钮；点击空档可设定时间/排入任务，空档建议在有待排任务时可点击 | `renderPlannerTimeline`、`renderPlanner`：:2745-2784,2801-2805；选择/拖放事件：:3213-3226 | planner 日期、时间、预计时长及任务记录 | 静态源码 L0；48 个位置映射、跨日/拖动、空档安排与保存待验证 |
| 12 | 远程日历来源列表 | 每个订阅源按状态生成刷新/同步和移除按钮（`data-calendar-source-refresh`、`data-calendar-source-caldav-refresh`、`data-calendar-source-remove`）；远端事件本身生成为只读时间轴卡/全天 chip | `renderPlannerCalendarSources`：:2510-2524；订阅增删/刷新：:2528-2717；列表委托：:3216-3221；日历事件时间轴：:2773-2777 | 本机日历来源、事件/待办记录与同步状态；服务器数据单独核对，不能当成本地迁移记录 | 静态源码 L0；文件导入、在线刷新、移除、冲突和离线保留待验证；v1.0.3 标签范围按基线单独核对 |
| 13 | 日程同步冲突弹窗 | 每条冲突生成版本单选项和“同时保留另一版本”复选框；提交选中的版本并可生成双份记录 | `renderPlannerSyncConflicts`、`showPlannerSyncConflicts`：:2903-2913；提交：:3315-3316 | `webdavPlannerConflicts` 与设备标识；确认后还会排队发起同步 | 静态源码 L0；真实冲突构造、选择、重启和远端回写待验证 |
| 14 | 待买清单、书影音卡片、档案分组 | 待买条目可标记已买/删除；书影音条目可删除；档案按日期动态生成折叠组；评分分布和其他统计为只读图表 | `renderHome`、`renderMedia`、`renderArchive`：:2811-2830；操作委托：:3197 | 主状态 shopping/media/records；删除与购买状态应反映到时光档案和洞察 | 静态源码 L0；筛选、统计、关联和重启待验证 |
| 15 | 自定义下拉控件 | 初始化时从原生 `<select>` 选项动态生成 button/listbox；支持选择、上下键、Enter、Escape、关闭时焦点返回，并同步原 select 值 | `renderCustomSelectOptions`、创建与事件：:3061-3129 | 将选择值写回原生表单；业务持久化由对应表单/设置处理 | 静态源码 L0；键盘/屏幕阅读器、缩放、焦点、原生下拉回退待验证 |
| 16 | 动态但只读的摘要/选项与外部嵌入 | 周活动、昨日记录、专注任务选项、计时/工时表、归档洞察、外部事件 chip 等根据数据重建；Spotify 播放器由运行时插入 iframe，播放器本身的控制属于嵌入内容，不由旧页面事件代理处理 | `renderDashboard`、`renderPlannerWorklog`、`renderFlowFocusTaskOptions`、`renderDailyFlow`、`renderFlowAudio`：:2317-2320,2795-2799,3422-3440 | 读取主状态、筛选结果或外部服务缓存，不应因被误计为控件而遗漏呈现/空态验收；Spotify URL 与登录/地区播放状态需独立核对 | 静态源码 L0；值、日期、空状态、播放器加载、遮挡和缩放待验证 |

## 后续运行验收记录模板

取得具体旧版安装版本及其 profile 的对应证据后，每个控件族至少记录：版本/源码或包哈希、入口页面、前置数据、鼠标与键盘动作、结果/错误反馈、关联数据变化、关闭重开后的结果、截图或短录屏。先用合成数据；不得在确认范围前操作或覆盖真实用户记录。运行证据补齐前，以上 L0 状态不升级为“已验收”。
