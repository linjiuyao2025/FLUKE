# FLUKE 旧版本地存储映射（Stage 0）

审计日期：2026-09-29<br>
范围：旧版迁移导出明确枚举的浏览器 localStorage 键。本文不包含用户迁移包原文、浏览器配置文件内容或个人记录；真实数据预览的最小摘要仅保存在本机私有证据记录。

## 结论与边界

- Electron v1.0.3 标签源码可核对九个 localStorage 键，对应 schema 1。仓库当前 main 的迁移格式在这九个键上增加设备同步标识，形成 schema 2 十键；权威清单为 native/wanxiang/migration.py:13-30，当前 main 导出列表和读取位置为 life-workspace.html:2976-3003。
- 当前 main 的导出器读取 localStorage 原始字符串或 null，不改动旧值，并将包元信息的 sourceVersion 标为 unknown。v1.0.3 标签、实际日常使用的安装包/profile 与当前 main 源码之间的对应关系仍待核。
- Native 的迁移模型先将每个键的原始值写入 SQLite legacy_storage.raw_value；可解析 JSON 同时保存在 json_documents.document_json。records、habits、media_items 等是供本机模块查询的投影，不替代原始快照。
- 下表的 SQLite “目标”表示源码可追索到的设计/消费位置。最新本机候选包已通过 Native 校验器并与当前默认 SQLite 只读对照为同一快照；候选包记录的来源版本是 1.0.2，尚不能证明与旧版 v1.0.3 当前数据同步。不得把源码映射或快照相等误作 v1.0.3 运行验收。
- 导出器只覆盖本地 localStorage 快照。它不能证明云端 SmartPage 表、WebDAV 服务器快照、远程日历订阅或任何服务端账号记录已导入。即使本地对象里有远程 ID、同步队列或缓存，也只能说明本地保存过这些字段。

## 十个 localStorage 键逐项映射

| 版本 / 键 | 旧版字段语义与来源锚点 | Native 原文保留和投影目标（源码意图） | 证据等级 / 待验证 |
|---|---|---|---|
| schema 1：richangji-state-v1 | 主 JSON 对象：records（财务、日程、待买、健身等活动记录）、habits、mediaItems、drafts、calendarSources、settings。旧版初始状态与规范化位置 life-workspace.html:1719-1727,1765-1807,1862-1908；动态加入设备同步队列见 :1930-1940 | 原字符串留 legacy_storage；解析对象留 json_documents。通用索引投影 records/habits/media_items；模块目标分别见 finance.py、fitness.py、planner.py、shopping.py、habits.py、media.py、daily.py 及 app_settings。database.py:56-115,754-814；daily.py:29-30,238-280,439-445 | L0 旧版源码 + N1 Native 源码。旧版真实字段分布、各 Native 模块覆盖字段和所有 settings 的逐字段映射未核；主状态中的远端 ID 不代表云端数据迁移 |
| schema 1：richangji-samples-cleared | 单独本地样例清理标记，旧版值为字符串 1/缺失；与主状态 settings.samplesCleared 共同影响样例初始化。life-workspace.html:1354-1360,1912-1925 | 原字符串留 legacy_storage；Native data_cleanup.py 使用同名应用设置，并由 backup.py:596-597 重建本地备份标记 | L0 + N1。迁移导入独立键是否统一写入 Native 设置、与主状态标志不一致时如何处理，待核 |
| schema 1：wanxiang-paper-layout-v2 | 每日流程首页卡片顺序/槽位/显隐的 JSON 布局；由 PAPER_LAYOUT_KEY 定位 life-workspace.html:2007 及旧版布局读写逻辑 | 原字符串和 JSON 文档留存；home_layout.py:27-28,197-225,291-368 投影至 app_settings.dailyOverviewLayout | L0 + N1。旧版布局中的过时卡片 ID、Native 七张卡设置对照见 Native README:9,46；真实用户布局导入和视觉对应待核 |
| schema 1：wanxiang-daily-issues-v1 | 今日新闻刊期 JSON，包含 active 与 archive；旧版键与版本 life-workspace.html:2034，迁移枚举 :2976-3003 | 原值和解析文档保留；issues.py:18-23,278-319 读取为 dailyIssueStore，并使用 dailyIssueDraft、newsLinkInbox、newsIssueLayout 等 Native 应用设置 | L0 + N1。发布历史数量上限、草稿/布局/素材箱与键内历史的关系，真实旧包导入及重启恢复待核 |
| schema 1：wanxiang-issue-questions-v1 | 每日流程问题簿，可为旧字符串行或对象行；life-workspace.html:2031，新增/删除 UI 在 :929 附近 | 原 JSON 文档留存；daily.py:29-30,238-272,355-363 将字符串/对象列表映射到 daily_flow_state，源码注明保留未来字段 | L0 + N1。旧版实际格式分布、对象扩展字段和排序/删除历史待核 |
| schema 1：wanxiang-issue-topics-v1 | 新闻关注主题列表，life-workspace.html:2031 及每日速览主题设置区 | 原文和解析文档留存；preferences.py 规范化至 issue_preferences_state 的新闻偏好投影 | L0 + N1。最新本机候选的原始键值与 Native 活动快照相同；具体主题内容不写入本文件。旧版 v1.0.3 同步状态仍待核 |
| schema 1：wanxiang-issue-preferences-v1 | 新闻偏好对象，含 subtopics、sources、presetSources 等字段；旧版键声明 life-workspace.html:2031 | 原文和 JSON 文档留存；preferences.py:22-24,93-135,196-207 投影到 issue_preferences_state.state_json；归一化可能合并/限制集合，未知预设来源可能改存到 sources | L0 + N1。必须用逐字段差异预览识别归一化差异，不可只比较对象数 |
| schema 1：wanxiang-issue-clippings-v1 | 已保存新闻剪报/文章快照数组；旧版键声明 life-workspace.html:2031 | 原始数组和 JSON 文档留存；reading.py:19-22,135-165,219-227,285-312 投影到 reading_module_state.clippings_json；运行读取最多采用前 80 条有效项 | L0 + N1。原始完整数组仍在导入快照，但当前阅读投影会跳过无效行并限制 80 条；真实剪报数量、先后顺序和文章字段待核 |
| schema 1：wanxiang-saved-knowledge | 本地“已存入稍后读”布尔开关，旧版实际存 1/0 字符串，并非文章集合。life-workspace.html:2029,2263 | 原始标记留 legacy_storage；reading.py:19-20,104-117,219-227,291-312 映射为 reading_module_state.saved_knowledge | L0 + N1。确认旧版语义是总开关而非每篇文章收藏；真实运行行为及其与剪报数组关系待核 |
| schema 2：wanxiang-planner-sync-device-v1 | 本地日程同步设备标识；旧版键和校验/生成逻辑 life-workspace.html:1930-1932 | 迁移包中作为原始值保留；Native WebDAV 同步源码使用 app_settings.webdavPlannerSyncDeviceId（webdav_planner.py:34-35,233-239），不是同名导入字段的已证实等价物 | L0 + N1。迁移代码中未发现把旧 ID 直接采用为 Native WebDAV 设备 ID 的依据；旧同步对端识别、是否应映射均待核 |

### 主状态的字段覆盖提醒

旧主状态对象的高层字段可以从 life-workspace.html:1765-1807 和 :1862-1908 追索，但旧版会持续扩充 settings。静态枚举只给出主 JSON 键，不构成完整的嵌套字段目录。Native 同时保留原始主对象，以应对投影未覆盖的字段；逐字段映射表仍需补齐，尤其是预算/筛选、首页和看板布局、提醒/计时、品牌/健身档案、日历来源、同步队列和远端标记。源码能读取这些属性，不等于每个字段都已在真实导入后由新模块消费。

## SQLite 保留、数量和校验位置

| 目标或证据 | 源码位置 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 导入批次与来源 | native/wanxiang/database.py:34-53 | schema 保存来源身份、schema 版本、导出/导入时间和 SHA-256；批次对来源身份和校验和设置唯一约束 | 没有证明某一真实旧用户批次存在 |
| 原始键值快照 | native/wanxiang/database.py:56-69,1061-1068 | 每个键的原字符串或 null 写入 legacy_storage；可解析 JSON 另存 json_documents | 不证明业务模块无损消费全部未知字段 |
| 类型化实体投影 | native/wanxiang/database.py:72-115,754-814 | 记录、习惯、媒体条目有查询列及完整 JSON 载荷；一般设置有 app_settings | 不等于八个 Native 页面逐项等价 |
| 包校验和 | life-workspace.html:2995-3000；native/wanxiang/migration.py:13-30,87-100,214-258 | 旧版按固定键顺序序列化 [key, 原字符串/null] 并计算 SHA-256；Native 按对应 schema 键顺序重新计算并拒绝不一致 | 本机最新候选已由 `read_package_file` 通过 schema/键清单/SHA-256 校验；该候选标记 sourceVersion=1.0.2，而当前导出源码标记 unknown；不证明 v1.0.3 当前 profile 同源 |
| 导入快照完整性复核 | native/wanxiang/database.py:489-650,754-814 | 加载时重算快照校验和，并核对 JSON 文档/实体投影是否匹配数据库批次 | 最新候选只读预览命中现有活动快照，校验和、原始键和实体投影一致；精确个人数量只保存在本机私有报告 |
| 预览和差异 | native/wanxiang/database.py:898-978 | 写入前可呈现每键差异、实体新增/变更/未变、当前及候选 checksum 和重复批次识别 | 本机最新候选预览为 `same_snapshot`，十个键均未变化、受统计实体均未变化；不证明快照与当前旧版 v1.0.3 profile 同步 |
| 事务、重复导入和回滚 | native/wanxiang/database.py:991-1096 | BEGIN IMMEDIATE 包围批次、原文、文档和实体投影写入；可按来源身份+checksum 识别重复批次，异常时回滚 | 源码/合成测试设计不等于真实数据实测成功 |
| 迁移包数量摘要 | native/wanxiang/migration.py:192-213 | 源码统计 keys_total/keys_present、记录/习惯/媒体、新闻发布/归档、问题、主题及剪报等可识别数量 | 不统计所有嵌套 settings 字段、布局槽、全局稍后读开关、样例标记或设备 ID；也不是用户真实数量报告 |

本轮已在本机只读解析候选包并对照活动 SQLite；不把原文、具体个人字段或完整校验和写入仓库。只读预览证明现存 Native 数据库与最新合法候选一致；候选来源版本为 1.0.2。本轮在标准 Windows 卸载登记位置找到两个 v1.0.3 条目，均指向 Electron QA 安装目录；没有据此锁定日常使用的稳定安装目录及其 profile，也不能排除未登记的便携副本，因此“与当前旧版实际使用 profile 同步”仍为待验证。v0.1.1 发布候选源码/QML 合成回归为 624 项通过、1 项跳过，不替代旧版运行或正式安装版的逐功能验收。

## 本地与云端数据的明确分界

旧版迁移导出在 life-workspace.html:2976-3003 对本机浏览器 localStorage 中枚举的十个键逐项取值。导出说明也明确提及本机记录和新闻偏好，且不改变旧版数据。迁移包只覆盖这些本地字符串。

以下内容不能因为出现在旧版代码、缓存对象或 Native README 中而认定已迁移：SmartPage 云表及其账号历史、外部注入的 provider 数据、WebDAV 服务器上的备份或同步快照、远程日历内容、天气服务数据、Spotify 服务端或播放状态。Native README:9 明确说明旧版发布包静态审计未发现 SmartPage provider 创建/注入，云账号数据范围和历史同步结果未验证；README:45 说明 Native WebDAV 目前仅经过 localhost 合成服务测试。

因此 Stage 0 的云端范围结论是：**待核，不能推断已迁移**。后续必须分别登记数据来源、服务端账户/表、时间范围、读取方式和独立的现场证据；不得把 localStorage 的本地快照数量当作云端账户数据数量。
