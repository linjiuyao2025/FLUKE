"""Reviewed English strings for daily-news focus preferences."""

ENGLISH_CATALOG: dict[str, str] = {
    "关注主题与候选媒体": "Topics and candidate sources",
    "选择你希望纳入每日内容准备的方向。": (
        "Choose the topics to include when preparing your daily briefing."
    ),
    "不选主题或媒体也可以保存；这些偏好只用于提示内容准备，不会自动屏蔽其他新闻。": (
        "You can save without selecting any topics or sources. These preferences guide briefing "
        "preparation only and do not automatically hide other news."
    ),
    "关注主题": "Topics of interest",
    "%1 项": "%1 items",
    "可多选；具体选题可以在下方补充。": "Select more than one, then add specific topics below if you like.",
    "以下主题来自旧版设置，当前没有对应的选项；移除只会取消关注，不会删除新闻或历史内容。": (
        "These topics came from older settings and have no matching option now; removing one only stops following it and does not delete news or history."
    ),
    "旧版主题：%1  × 移除": "Legacy topic: %1  × Remove",
    "补充具体选题": "Add specific topics",
    "例如：AI Agent、独立游戏": "For example: AI agents, indie games",
    "最多 240 字；这里只补充关注方向，不代表已自动筛选或核实新闻。": (
        "Up to 240 characters. Add areas of interest here; this does not mean news has been "
        "automatically filtered or verified."
    ),
    "候选媒体": "Candidate sources",
    "%1 家预设": "%1 preset sources",
    "媒体只作为候选范围，不代表质量保证；每篇仍需核对原文、日期、证据和关联度。": (
        "Sources are candidates only and are not a quality guarantee. Check each article's "
        "original text, date, evidence, and relevance."
    ),
    "补充其他来源": "Add other sources",
    "输入其他媒体，用顿号、逗号或分号分隔": (
        "Enter other sources, separated by enumeration commas, commas, or semicolons"
    ),
    "最多 240 字；多个来源可用顿号、逗号或分号分隔，每个来源最多 60 字。": (
        "Up to 240 characters. Separate sources with enumeration commas, commas, or semicolons; "
        "each source can contain up to 60 characters."
    ),
    "单个自定义来源最多 60 字，请缩短或拆分后再保存。": (
        "Each custom source can contain up to 60 characters. Shorten or split it before saving."
    ),
    "仅点击保存才会提交；取消或按 Esc 会丢弃本次修改。": (
        "Changes are submitted only when you select Save. Cancel or press Esc to discard them."
    ),
    "取消": "Cancel",
    "保存关注方向": "Save preferences",
    # The following topic labels come from the QML defaults or Python topic
    # options. The associated stable topic keys are not translated.
    "新闻与时事": "News & current affairs",
    "国内": "Domestic",
    "国际": "International",
    "财经商业": "Finance & business",
    "科技数码": "Technology & digital",
    "人工智能": "Artificial intelligence",
    "游戏": "Games",
    "文化影视": "Culture & film",
    "健康": "Health",
    "生活方式": "Lifestyle",
    "其他": "Other",
    # Exact fixed errors supplied by the Python preferences repository or
    # bridge. Exception details appended to these messages are not rewritten.
    "关注方向暂时无法载入。": "Preferences could not be loaded right now.",
    "关注方向暂不可保存。": "Preferences cannot be saved right now.",
    "关注方向保存失败。": "Saving preferences failed.",
    "导入数据后无法更新关注方向。": "Preferences could not be updated after importing data.",
    "本机关注偏好必须是对象。": "Local preferences must be an object.",
    "无法初始化关注偏好状态。": "The preferences state could not be initialized.",
    "关注主题必须是字符串数组。": "Topics of interest must be a list of strings.",
    "候选媒体偏好必须是对象。": "Candidate source preferences must be an object.",
    "细分选题必须是文本。": "Specific topics must be text.",
    "自定义来源必须是文本。": "Custom sources must be text.",
    "预设媒体必须是字符串数组。": "Preset sources must be a list of strings.",
    # FLUKE application updates are shown in the preferences dialog.
    "FLUKE 应用更新": "FLUKE app updates",
    "当前版本：%1。检查 GitHub Releases 中 v0.1.2 及以上的 Windows 安装包。": (
        "Current version: %1. Check GitHub Releases for Windows installers v0.1.2 and later."
    ),
    "可用版本：%1 · %2": "Available version: %1 · %2",
    "正在检查…": "Checking…",
    "检查应用更新": "Check for app updates",
    "正在下载…": "Downloading…",
    "下载并校验": "Download and verify",
    "打开安装包位置": "Open installer folder",
    "安全安装并重启": "Install safely and restart",
    "取消下载": "Cancel download",
    "正在安装…": "Installing…",
    "新版会安装到独立版本目录；启动健康检查成功后才切换，失败时自动保留旧版并可回退。": (
        "The new version is installed in a separate version directory; it switches only after a "
        "successful startup health check, and failures keep the old version available for rollback."
    ),
    "当前安装不是可回滚的 side-by-side 布局，只能下载并校验官方安装包；自动安装已关闭。": (
        "This installation is not a rollback-safe side-by-side layout; only download and verification "
        "are available, and automatic installation is disabled."
    ),
}
