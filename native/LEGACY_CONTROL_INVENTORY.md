# FLUKE 旧版控件静态清单（Stage 0）

审计日期：2026-09-29<br>
旧版源码：仓库当前 main 分支根目录的 life-workspace.html；不表示全部控件都存在于 Electron v1.0.3 发布标签<br>
来源 SHA-256：CADAD4662DFA835A6DC49E20FDDAED67830B46AC2BB79982CD5D1DEDB27141ED

## 范围与证据口径

- 候选清单记录 247 个静态 HTML 交互元素；源文件 SHA-256 与本次计算结果完全匹配，按要求复用该清单并保留其行号、元素类型、ID/name、标签或提示、容器线索、源码事件/属性。
- 版本边界见 [旧版功能基线](LEGACY_FUNCTION_BASELINE.md#版本范围)：当前 main 的静态 HTML 可能包含 v1.0.3 发布标签之后增加的操作；需按具体版本核对，不能将本表直接解释为 v1.0.3 控件表。
- 下表每一行的证据状态均为“静态源码（L0）；旧版运行：待验证”。这不是旧版安装包的按钮验收，也不证明控件可见、可点击、事件成功或数据已保存。
- 当前源码中有 18 个 localStorage 显式方法调用点：getItem 8、setItem 8、removeItem 2、clear 0。调用点数不等于存储键数；固定迁移包键数另见 LEGACY_STORAGE_MAP.md（schema 1 九键、schema 2 十键）。
- 本表没有从用户数据库、浏览器存储、运行时表单、账号、凭据或个人记录取值。标签/提示均来自经哈希核对的静态源码候选。

## 运行时动态控件

**247 项不含动态实例。** 新闻卡片、文章/剪报操作、历史选择、洞察入口、任务行与看板、日历订阅行、冲突选项和数据列表会由 JavaScript 按数据生成；按控件族整理的源码锚点、委托事件和状态目标见[动态控件清单](LEGACY_DYNAMIC_CONTROLS.md)。该清单也是静态源码（L0）；实际数量、可见性和旧版运行行为仍待验证，不能以 247 项静态数量代替。

## 静态 HTML 控件明细（247 项）

| # | 源码行 | 元素 | ID / name | 标签或提示 | 所属容器线索 | 源码事件/属性 | 验收状态 |
|---:|---:|---|---|---|---|---|---|
| 1 | 803 | `button` | `brandSettingsBtn` | 万 万象来信 把远方与日常，折进今天 自定义 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 2 | 805 | `button` | `` | 每日流程 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 3 | 807 | `button` | `` | 记账理财 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 4 | 808 | `button` | `` | 习惯健康 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 5 | 809 | `button` | `` | 减脂健身 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 6 | 810 | `button` | `` | 日程统筹 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 7 | 811 | `button` | `` | 待买清单 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 8 | 812 | `button` | `` | 书影音 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 9 | 814 | `button` | `` | 时光档案 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 10 | 825 | `button` | `exportBackupBtn` | 导出完整备份 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 11 | 826 | `button` | `exportEncryptedBackupBtn` | 导出加密备份 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 12 | 827 | `button` | `webdavBackupSetupBtn` | 设置 WebDAV 备份 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 13 | 828 | `button` | `webdavBackupPushBtn` | 上传加密快照 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 14 | 829 | `button` | `webdavBackupFetchBtn` | 恢复云端快照 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 15 | 830 | `button` | `exportLegacyMigrationBtn` | 导出原生版迁移包 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 16 | 831 | `button` | `importBackupBtn` | 导入备份 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 17 | 832 | `button` | `clearAllBtn` | 清空全部数据 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 18 | 835 | `button` | `clearSamplesBtn` | 清理示例 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 19 | 836 | `input` | `backupFileInput` |  |  | `type=file`  | 静态源码（L0）；旧版运行：待验证 |
| 20 | 843 | `input` | `password` |  |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 21 | 844 | `input` | `confirmPassword` |  |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 22 | 845 | `button` | `backupPasswordCancel` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 23 | 845 | `button` | `backupPasswordSubmit` | 继续 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 24 | 852 | `input` | `url` | https://cloud.example/remote.php/dav/files/name/wanxiang.wxbackup |  | `type=url`  | 静态源码（L0）；旧版运行：待验证 |
| 25 | 853 | `input` | `username` |  |  | `type=text`  | 静态源码（L0）；旧版运行：待验证 |
| 26 | 854 | `input` | `password` |  |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 27 | 855 | `input` | `plannerSyncPassphrase` |  |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 28 | 856 | `input` | `plannerSyncPassphraseConfirm` |  |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 29 | 857 | `button` | `webdavBackupRemoveBtn` | 移除本机设置 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 30 | 857 | `button` | `webdavBackupCancelBtn` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 31 | 857 | `button` | `webdavBackupSaveBtn` | 连接并保存 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 32 | 865 | `button` | `webdavPlannerConflictsCancel` | 稍后处理 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 33 | 865 | `button` | `` | 保存选择并同步 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 34 | 876 | `a` | `` | 01 今日速览 天气 · 行业 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 35 | 877 | `a` | `` | 02 昨日复盘 记录 · 想法 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 36 | 878 | `a` | `` | 03 今日工作 待办 · 邮件 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 37 | 879 | `a` | `` | 04 开始专注 任务 · 音频 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 38 | 881 | `button` | `flowPrevious` | ← 上一页 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 39 | 881 | `button` | `flowNext` | 下一页 → |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 40 | 889 | `input` | `flowCityInput` | 输入城市，例如上海 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 41 | 889 | `button` | `flowCitySubmit` | 查询城市 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 42 | 889 | `button` | `flowLocateBtn` | 重新定位 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 43 | 896 | `input` | `topic` | news |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 44 | 896 | `input` | `topic` | domestic |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 45 | 896 | `input` | `topic` | international |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 46 | 896 | `input` | `topic` | finance |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 47 | 896 | `input` | `topic` | technology |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 48 | 896 | `input` | `topic` | ai |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 49 | 896 | `input` | `topic` | games |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 50 | 896 | `input` | `topic` | culture |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 51 | 896 | `input` | `topic` | health |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 52 | 896 | `input` | `topic` | life |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 53 | 896 | `input` | `topic` | other |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 54 | 896 | `input` | `issueTopicDetails` | 如：AI Agent、独立游戏 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 55 | 897 | `input` | `presetSource` | 财新网 |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 56 | 897 | `input` | `presetSource` | 澎湃明查 |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 57 | 897 | `input` | `presetSource` | 端传媒 |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 58 | 897 | `input` | `presetSource` | 新华社 |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 59 | 897 | `input` | `presetSource` | Reuters |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 60 | 897 | `input` | `presetSource` | Associated Press |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 61 | 897 | `input` | `presetSource` | ProPublica |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 62 | 897 | `input` | `presetSource` | Rest of World |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 63 | 897 | `input` | `presetSource` | Ars Technica |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 64 | 897 | `input` | `presetSource` | The Guardian |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 65 | 897 | `input` | `presetSource` | Floodlight |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 66 | 897 | `input` | `presetSource` | Nature |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 67 | 897 | `input` | `presetSource` | Science |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 68 | 897 | `input` | `presetSource` | IEEE Spectrum |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 69 | 897 | `input` | `presetSource` | Game Developer |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 70 | 897 | `input` | `issuePreferredSources` | 输入其他媒体，用顿号分隔 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 71 | 898 | `button` | `` | 保存关注方向 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 72 | 903 | `button` | `paperLibraryBtn` | 模块与版面 + |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 73 | 906 | `button` | `copyIssuePromptBtn` | 复制生成提示 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 74 | 906 | `button` | `exportIssueBtn` | 导出本期 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 75 | 906 | `button` | `importIssueBtn` | 导入 JSON 文件 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 76 | 906 | `input` | `issueFileInput` |  |  | `type=file`  | 静态源码（L0）；旧版运行：待验证 |
| 77 | 908 | `textarea` | `issuePackageInput` | {"version":1,"date":"2026-09-26","topic":"AI 与数字工具","focus":[...],"highlights":[...]} |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 78 | 909 | `button` | `previewIssueBtn` | 校验并预览 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 79 | 909 | `button` | `publishIssueBtn` | 发布本期 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 80 | 909 | `select` | `issueHistorySelect` | 选择并载入历史期 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 81 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 82 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 83 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 84 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 85 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 86 | 915 | `input` | `` |  |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 87 | 927 | `textarea` | `flowIntentionInput` | 例如：继续跟进昨天没完成的事项，或提醒我关注某个主题 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 88 | 927 | `button` | `flowIntentionSave` | 保存，明天复盘时回看 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 89 | 929 | `button` | `` | 进入档案 → |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 90 | 929 | `input` | `issueQuestionInput` | 例如：怎么把零散笔记变成可检索的知识？ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 91 | 929 | `button` | `` | 收进问题簿 ＋ |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 92 | 933 | `button` | `` | 打开完整日程 → |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 93 | 935 | `button` | `` | ＋ 添加一项待办 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 94 | 936 | `a` | `` | 打开 Gmail ↗ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 95 | 936 | `a` | `` | 打开 Outlook ↗ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 96 | 938 | `button` | `` | 管理 → |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 97 | 938 | `button` | `` | 记一笔 支出或收入 ＋ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 98 | 938 | `button` | `` | 记体重 关注趋势 ＋ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 99 | 938 | `button` | `` | 待买物品 采购清单 ＋ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 100 | 944 | `input` | `flowFocusTask` | 从今日待办选择，或写下具体下一步 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 101 | 944 | `select` | `flowTimerMode` | 番茄钟 · 25 分钟 Flowtime · 正向计时 自定义倒计时 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 102 | 944 | `input` | `flowTimerMinutes` | 25 |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 103 | 944 | `button` | `flowTimerStart` | 开始专注 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 104 | 944 | `button` | `flowTimerReset` | 重置 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 105 | 945 | `input` | `flowAudioInput` | 粘贴 Spotify 播放列表或播客链接 |  | `type=url`  | 静态源码（L0）；旧版运行：待验证 |
| 106 | 945 | `button` | `` | 打开播放器 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 107 | 945 | `button` | `flowAudioClear` | 移除 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 108 | 955 | `button` | `` | 导出 Excel |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 109 | 959 | `input` | `flow` | expense |  | `type=radio`  | 静态源码（L0）；旧版运行：待验证 |
| 110 | 959 | `input` | `flow` | income |  | `type=radio`  | 静态源码（L0）；旧版运行：待验证 |
| 111 | 960 | `input` | `amount` | 0.00 |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 112 | 961 | `select` | `moneyCategory` |  |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 113 | 961 | `input` | `date` |  |  | `type=date`  | 静态源码（L0）；旧版运行：待验证 |
| 114 | 962 | `input` | `note` | 这笔钱花在了哪里 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 115 | 963 | `button` | `` | 记下这笔 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 116 | 970 | `input` | `budgetInput` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 117 | 972 | `button` | `` | 记一笔支出 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 118 | 973 | `select` | `moneyFilter` | 全部分类 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 119 | 983 | `button` | `` | 新增习惯 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 120 | 992 | `button` | `` | 目标设置 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 121 | 992 | `button` | `` | 导出 Excel |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 122 | 996 | `input` | `weight` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 123 | 997 | `input` | `duration` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 124 | 997 | `input` | `date` |  |  | `type=date`  | 静态源码（L0）；旧版运行：待验证 |
| 125 | 998 | `input` | `note` | 可以留空 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 126 | 999 | `button` | `` | 保存今日数据 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 127 | 1007 | `button` | `` | 新增计划 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 128 | 1017 | `input` | `editingId` |  |  | `type=hidden`  | 静态源码（L0）；旧版运行：待验证 |
| 129 | 1018 | `input` | `title` | 写下一件具体的事 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 130 | 1019 | `input` | `date` |  |  | `type=date`  | 静态源码（L0）；旧版运行：待验证 |
| 131 | 1019 | `input` | `time` |  |  | `type=time`  | 静态源码（L0）；旧版运行：待验证 |
| 132 | 1019 | `input` | `estimateMin` | 30 |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 133 | 1019 | `select` | `plannerRepeatInput` | 不重复 每天 每个工作日 每周 每月 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 134 | 1020 | `select` | `list` | 生活 工作 家庭 个人 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 135 | 1020 | `select` | `priority` | 普通 高优先级 低优先级 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 136 | 1021 | `input` | `project` | 可选，例如：毕业设计 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 137 | 1021 | `input` | `tags` | 用逗号分隔，最多 12 个 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 138 | 1022 | `input` | `note` | 地点、准备事项或补充说明 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 139 | 1023 | `input` | `remind` | 1 |  | `type=checkbox`  | 静态源码（L0）；旧版运行：待验证 |
| 140 | 1024 | `button` | `` | 加入日程 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 141 | 1024 | `button` | `plannerCancelEdit` | 取消编辑 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 142 | 1026 | `input` | `plannerCustomBoardName` | 例如：内容发布流程 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 143 | 1026 | `button` | `plannerAddBoardColumn` | 添加一列 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 144 | 1026 | `button` | `plannerDeleteBoardButton` | 删除看板 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 145 | 1026 | `button` | `plannerCancelBoardButton` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 146 | 1026 | `button` | `plannerSaveBoardButton` | 保存看板 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 147 | 1027 | `input` | `title` |  |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 148 | 1027 | `button` | `plannerSubtaskCancel` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 149 | 1027 | `button` | `plannerSubtaskSubmit` | 添加 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 150 | 1030 | `button` | `` | ‹ |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 151 | 1030 | `button` | `` | 今天 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 152 | 1030 | `button` | `` | › |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 153 | 1030 | `button` | `plannerCalendarImport` | 导入日历 .ics |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 154 | 1030 | `button` | `plannerCalendarExport` | 导出本周任务 .ics |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 155 | 1030 | `input` | `plannerCalendarFile` |  |  | `type=file`  | 静态源码（L0）；旧版运行：待验证 |
| 156 | 1030 | `input` | `plannerCalendarSubscriptionName` | 日历名称（可选） |  | `type=text`  | 静态源码（L0）；旧版运行：待验证 |
| 157 | 1030 | `input` | `plannerCalendarSubscriptionUrl` | 日历订阅链接 |  | `type=text`  | 静态源码（L0）；旧版运行：待验证 |
| 158 | 1030 | `button` | `` | 添加在线日历 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 159 | 1030 | `input` | `name` | CalDAV 日历名称（可选） |  | `type=text`  | 静态源码（L0）；旧版运行：待验证 |
| 160 | 1030 | `input` | `url` | CalDAV 日历集地址 |  | `type=url`  | 静态源码（L0）；旧版运行：待验证 |
| 161 | 1030 | `input` | `username` | CalDAV 账号 |  | `type=text`  | 静态源码（L0）；旧版运行：待验证 |
| 162 | 1030 | `input` | `password` | CalDAV 密码 |  | `type=password`  | 静态源码（L0）；旧版运行：待验证 |
| 163 | 1030 | `button` | `` | 连接 CalDAV 日历 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 164 | 1030 | `button` | `plannerCalendarRefreshAll` | 刷新全部在线日历 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 165 | 1031 | `button` | `` | 时间轴 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 166 | 1031 | `button` | `` | 看板 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 167 | 1031 | `button` | `` | 四象限 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 168 | 1031 | `button` | `` | 全部 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 169 | 1031 | `button` | `` | 今天 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 170 | 1031 | `button` | `` | 计划内 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 171 | 1031 | `button` | `` | 已完成 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 172 | 1031 | `select` | `plannerProjectFilter` | 全部项目 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 173 | 1031 | `select` | `plannerTagFilter` | 全部标签 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 174 | 1031 | `button` | `` | 重试同步 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 175 | 1031 | `button` | `` | 立即同步 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 176 | 1031 | `button` | `` | 查看冲突 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 177 | 1035 | `button` | `focusWorklogExport` | 导出全部专注会话 CSV |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 178 | 1041 | `input` | `name` | 例如：洗衣液、燕麦奶 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 179 | 1042 | `input` | `quantity` | 2 盒 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 180 | 1042 | `select` | `category` | 食品 日用品 家居 数码 药品 其他 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 181 | 1043 | `input` | `price` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 182 | 1043 | `select` | `priority` | 有空买 急需 等等再买 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 183 | 1044 | `input` | `note` | 品牌、规格或购买渠道 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 184 | 1045 | `button` | `` | 加入待买清单 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 185 | 1049 | `button` | `` | 待买 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 186 | 1049 | `button` | `` | 全部 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 187 | 1049 | `button` | `` | 已买 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 188 | 1058 | `input` | `name` | 电影、剧、书或番的名字 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 189 | 1059 | `select` | `type` | 电影 剧 书 番 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 190 | 1059 | `select` | `status` | 想看 在看 看完 弃了 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 191 | 1060 | `select` | `rating` | 暂不评分 ★ ★★ ★★★ ★★★★ ★★★★★ |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 192 | 1060 | `input` | `date` |  |  | `type=date`  | 静态源码（L0）；旧版运行：待验证 |
| 193 | 1061 | `input` | `review` | 这一部为什么值得记住 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 194 | 1062 | `input` | `mediaCoverInput` |  |  | `type=file`  | 静态源码（L0）；旧版运行：待验证 |
| 195 | 1063 | `button` | `` | 加入我的书影音 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 196 | 1068 | `button` | `` | 封面墙 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 197 | 1068 | `button` | `` | 列表 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 198 | 1068 | `select` | `mediaStatusFilter` | 全部状态 想看 在看 看完 弃了 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 199 | 1068 | `select` | `mediaRatingFilter` | 全部评分 5 星 4 星以上 3 星以上 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 200 | 1074 | `button` | `` | 全部 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 201 | 1074 | `button` | `` | 财务 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 202 | 1074 | `button` | `` | 健康 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 203 | 1074 | `button` | `` | 日程 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 204 | 1074 | `button` | `` | 待买 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 205 | 1085 | `button` | `` | 头版 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 206 | 1085 | `button` | `` | 记账 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 207 | 1085 | `button` | `` | 习惯 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 208 | 1085 | `button` | `` | 减脂 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 209 | 1085 | `button` | `` | 日程 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 210 | 1085 | `button` | `` | 待买 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 211 | 1085 | `button` | `` | 书影音 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 212 | 1085 | `button` | `` | 档案 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 213 | 1088 | `button` | `` | × |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 214 | 1090 | `input` | `name` | 例如：早睡、拉伸、背单词 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 215 | 1091 | `select` | `habitTypeSelect` | 完成 / 未完成 计数累加 填写数值 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 216 | 1091 | `select` | `tone` | 鼠尾草绿 暮色紫 陶土橙 燕麦色 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 217 | 1092 | `input` | `target` | 1 |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 218 | 1092 | `input` | `unit` | 次 / 分钟 / 页 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 219 | 1094 | `button` | `` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 220 | 1094 | `button` | `` | 添加习惯 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 221 | 1101 | `button` | `` | × |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 222 | 1103 | `select` | `group` | 运动 饮食 恢复 其他 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 223 | 1103 | `input` | `title` | 例如：慢跑 2 次 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 224 | 1104 | `input` | `note` | 频次、时长或具体做法 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 225 | 1106 | `button` | `` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 226 | 1106 | `button` | `` | 添加计划 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 227 | 1113 | `button` | `` | × |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 228 | 1115 | `input` | `height` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 229 | 1115 | `input` | `target` |  |  | `type=number`  | 静态源码（L0）；旧版运行：待验证 |
| 230 | 1116 | `button` | `` | 取消 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 231 | 1116 | `button` | `` | 保存目标 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 232 | 1123 | `button` | `` | × |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 233 | 1126 | `input` | `name` | 万象来信 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 234 | 1127 | `input` | `avatarMode` | letter |  | `type=radio`  | 静态源码（L0）；旧版运行：待验证 |
| 235 | 1127 | `input` | `avatarMode` | image |  | `type=radio`  | 静态源码（L0）；旧版运行：待验证 |
| 236 | 1127 | `input` | `brandAvatarFile` |  |  | `type=file`  | 静态源码（L0）；旧版运行：待验证 |
| 237 | 1127 | `input` | `brandCropZoom` | 缩放头像图片 |  | `type=range`  | 静态源码（L0）；旧版运行：待验证 |
| 238 | 1127 | `input` | `avatarImage` |  |  | `type=hidden`  | 静态源码（L0）；旧版运行：待验证 |
| 239 | 1128 | `input` | `tagline` | 把远方与日常，折进今天 |  | ``  | 静态源码（L0）；旧版运行：待验证 |
| 240 | 1129 | `input` | `theme` | plum |  | `type=hidden`  | 静态源码（L0）；旧版运行：待验证 |
| 241 | 1129 | `button` | `` | 暮色紫 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 242 | 1129 | `button` | `` | 森林绿 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 243 | 1129 | `button` | `` | 陶土棕 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 244 | 1129 | `button` | `` | 深海蓝 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 245 | 1130 | `button` | `` | 恢复默认 |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
| 246 | 1130 | `button` | `` | 保存外观 |  | `type=submit`  | 静态源码（L0）；旧版运行：待验证 |
| 247 | 1138 | `button` | `articleDialogClose` | × |  | `type=button`  | 静态源码（L0）；旧版运行：待验证 |
