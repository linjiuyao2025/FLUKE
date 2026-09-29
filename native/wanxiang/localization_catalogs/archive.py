"""Reviewed English strings for the life archive page."""

ENGLISH_CATALOG: dict[str, str] = {
    "财务": "Finance",
    "健康": "Health",
    "日程": "Planner",
    "待买": "Shopping",
    "记录": "Record",
    "一笔收支": "Financial transaction",
    "身体记录": "Health record",
    "一项日程": "Planner item",
    "待买物品": "Shopping item",
    "生活记录": "Life record",
    "其他": "Other",
    "收入": "Income",
    "支出": "Expense",
    "%1 分钟运动": "%1-minute workout",
    "体重记录": "Weight record",
    "生活": "Life",
    "全天": "All day",
    "已完成": "Completed",
    "待完成": "To do",
    "数量未填": "Quantity not set",
    "未分类": "Uncategorized",
    "已买": "Purchased",
    "未标日期": "Undated",
    "今天": "Today",
    "昨天": "Yesterday",
    "周日": "Sun",
    "周一": "Mon",
    "周二": "Tue",
    "周三": "Wed",
    "周四": "Thu",
    "周五": "Fri",
    "周六": "Sat",
    "%1 月 %2 日 · %3": "%1/%2 · %3",
    "%1 年 %2 月": "%1/%2",
    "本月": "This month",
    "筛选暂时无法保存。": "Could not save the filter right now.",
    "时光档案": "Life archive",
    "只读汇总 · 共 %1 条": "Read-only summary · %1 records",
    "当前统计为本月全部记录；下面可按类别筛选并按日期回看各模块内容。": (
        "The current summary covers all records this month. "
        "Filter the list below by category and review entries by date."
    ),
    "当前为“%1”，上方统计和下方列表使用同一筛选范围。可切换“全部”查看所有记录。": (
        "The current filter is \"%1\"; the summary and list use the same scope. "
        "Switch to All to view every record."
    ),
    "本月记录": "This month's records",
    "最常记录": "Most frequent type",
    "最近七天": "Last 7 days",
    "%1 条": "%1 records",
    "%1 个日期": "%1 days",
    "按记录日期统计": "Grouped by record date",
    "最近七天的生活切片": "Last 7 days of activity",
    "%1 · 最近七天 %2 条": "%1 · %2 records in the last 7 days",
    "全部": "All",
    "全部记录": "All records",
    "筛选": "Filter",
    "筛选范围记录": "Records in range",
    "%1 条记录": "%1 records",
    "还没有可回看的记录": "Nothing to review yet",
    "当前分类没有记录": "No records in this category",
    "时光档案会汇总其他模块的记录。先去记账、记录运动、安排日程或添加待买事项。": (
        "The archive gathers records from other sections. Start by adding a transaction, "
        "workout, planner item, or shopping item."
    ),
    "这个分类暂时为空，可以切换筛选，或查看全部记录。": (
        "There are no records in this category yet. Change the filter or view all records."
    ),
    "去记账": "Add a transaction",
    "记录运动": "Log a workout",
    "添加日程": "Add a planner item",
    "打开待买清单": "Open shopping list",
    "查看全部记录": "View all records",
    "这个范围还没有记录。": "There are no records in this range yet.",
    # Exact Python archive error strings can also be translated when they are
    # shown in the page notice. Errors with appended exception details remain
    # readable in their original form.
    "时光档案暂时无法载入。": "The life archive could not be loaded right now.",
    "时光档案暂时无法计算。": "The life archive could not be calculated right now.",
    "时光档案暂不可用。": "The life archive is not available right now.",
    "档案筛选没有保存。": "The archive filter was not saved.",
    "旧版主状态原文必须是 JSON 字符串。": "The original legacy main-state value must be a JSON string.",
    "旧版主状态原文不是有效 JSON。": "The original legacy main-state value is not valid JSON.",
    "旧版主状态必须是对象。": "The legacy main state must be an object.",
    "旧版 settings 必须是对象。": "The legacy settings value must be an object.",
    "本机档案设置结构无效。": "The local archive settings have an invalid structure.",
    "本机档案筛选设置无效。": "The local archive filter setting is invalid.",
    "本机档案筛选数据无法解析。": "The local archive filter data could not be parsed.",
    "无法初始化本机档案设置。": "The local archive settings could not be initialized.",
    "档案输入必须是 records 对象数组。": "Archive input must be an array of record objects.",
    "档案 records 中的每项都必须是对象。": "Each item in archive records must be an object.",
    "档案筛选必须是 all、money、fitness、planner 或 home。": (
        "The archive filter must be all, money, fitness, planner, or home."
    ),
}

DISAMBIGUATED_ENGLISH_CATALOG: dict[tuple[str, str], str] = {
    ("待买", "purchase status"): "To buy",
}
