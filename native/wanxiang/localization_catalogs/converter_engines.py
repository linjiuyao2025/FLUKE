"""Reviewed English strings for the converter-engine management dialog."""

ENGLISH_CATALOG: dict[str, str] = {
    "转换引擎": "Conversion engines",
    "FLUKE 把转换引擎作为独立组件管理。随安装包提供的版本可离线使用；更新会下载安装到当前 Windows 用户的 FLUKE 数据目录。安装失败时旧版保持启用，成功更新后也可在这里恢复到上一版本。": (
        "FLUKE manages conversion engines as separate components. Bundled versions work offline. Updates are installed in the current Windows user's FLUKE data folder. If an installation fails, the previous version stays active. After a successful update, you can restore the previous version here."
    ),
    "正在处理…": "Working…",
    "检查更新": "Check for updates",
    "更新通道：%1": "Update channel: %1",
    "更新通道：FLUKE GitHub Releases": "Update channel: FLUKE GitHub Releases",
    "当前：%1（%2）": "Current: %1 (%2)",
    "当前：未安装": "Current: Not installed",
    "未安装": "Not installed",
    "可用版本：%1 · 更新包约 %2 MiB": "Available version: %1 · update is about %2 MiB",
    "安装": "Install",
    "暂无安装包": "No package available",
    "更新": "Update",
    "恢复旧版": "Roll back",
    "回滚引擎版本": "Roll back engine version",
    "回滚到 %1": "Roll back to %1",
    "许可说明": "License information",
    "关闭": "Close",
    "未知类型": "Unknown type",
    "正在为“%1”检查转换组件": "Checking conversion components for “%1”",
    "输入类型：%1。安装或更新后，关闭此窗口并重新添加文件，系统会重新检测可用格式。": (
        "Input type: %1. After installing or updating, close this window and add the file again so the app can detect available formats."
    ),
}
