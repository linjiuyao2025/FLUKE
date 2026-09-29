"""Incremental UI localization for the native Qt Quick application.

User-authored values and migrated legacy data are deliberately outside the
translation catalog. QML strings join the catalog by wrapping their source
text in ``qsTr``; untranslated source text remains visible until a surface is
reviewed and translated.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from PySide6.QtCore import QObject, Property, QCoreApplication, QTranslator, Signal, Slot

from .database import get_app_setting, set_app_setting
from .localization_catalogs.archive import (
    DISAMBIGUATED_ENGLISH_CATALOG as ARCHIVE_DISAMBIGUATED_ENGLISH_CATALOG,
    ENGLISH_CATALOG as ARCHIVE_ENGLISH_CATALOG,
)
from .localization_catalogs.converter import ENGLISH_CATALOG as CONVERTER_ENGLISH_CATALOG
from .localization_catalogs.converter_engines import (
    ENGLISH_CATALOG as CONVERTER_ENGINES_ENGLISH_CATALOG,
)
from .localization_catalogs.daily_flow import ENGLISH_CATALOG as DAILY_FLOW_ENGLISH_CATALOG
from .localization_catalogs.finance import ENGLISH_CATALOG as FINANCE_ENGLISH_CATALOG
from .localization_catalogs.fitness import ENGLISH_CATALOG as FITNESS_ENGLISH_CATALOG
from .localization_catalogs.habits import ENGLISH_CATALOG as HABITS_ENGLISH_CATALOG
from .localization_catalogs.media import ENGLISH_CATALOG as MEDIA_ENGLISH_CATALOG
from .localization_catalogs.news import ENGLISH_CATALOG as NEWS_ENGLISH_CATALOG
from .localization_catalogs.planner import ENGLISH_CATALOG as PLANNER_ENGLISH_CATALOG
from .localization_catalogs.preferences import ENGLISH_CATALOG as PREFERENCES_ENGLISH_CATALOG
from .localization_catalogs.shopping import (
    DISAMBIGUATED_ENGLISH_CATALOG as SHOPPING_DISAMBIGUATED_ENGLISH_CATALOG,
    ENGLISH_CATALOG as SHOPPING_ENGLISH_CATALOG,
)


LANGUAGE_SETTING_KEY = "uiLanguage"
DEFAULT_LANGUAGE = "zh_CN"
SUPPORTED_LANGUAGES = ("zh_CN", "en_US")

# Keep this catalog limited to strings currently marked with qsTr in QML.
# Coverage is intentionally incremental; a missing entry falls back to Chinese.
_CORE_ENGLISH_CATALOG: dict[str, str] = {
    "简体中文": "Chinese (Simplified)",
    "English": "English",
    "界面语言": "Interface language",
    "英文界面正在逐步完善；尚未翻译的页面会继续显示中文。": (
        "English support is being added module by module; untranslated pages remain in Chinese."
    ),
    "工作台外观": "Workspace appearance",
    "可向下滚动查看更多": "Scroll down for more options",
    "为 FLUKE 工作台设置名称、头像和主题色": (
        "Set the workspace name, avatar, and accent color."
    ),
    "页面名称": "Workspace name",
    "头像": "Avatar",
    "名称首字": "Initial",
    "上传图片": "Use an image",
    "选择图片": "Choose image",
    "图片无法读取，请换一张图片。": "The image could not be read. Choose another image.",
    "拖动图片调整位置，也可用方向按钮微调；滑块调整缩放。头像会裁成方形。": (
        "Drag to position the image, use the arrow buttons for fine adjustments, "
        "and use the slider to zoom. The avatar is cropped to a square."
    ),
    "位置微调": "Fine position adjustment",
    "头像向左微调": "Nudge avatar left",
    "头像向上微调": "Nudge avatar up",
    "头像向下微调": "Nudge avatar down",
    "头像向右微调": "Nudge avatar right",
    "副标题": "Tagline",
    "主题色": "Accent color",
    "暮色紫": "Dusk plum",
    "森林绿": "Forest green",
    "陶土棕": "Terracotta",
    "深海蓝": "Deep ocean blue",
    "恢复默认": "Restore defaults",
    "恢复默认（待保存）": "Restore defaults (save to apply)",
    "界面语言会立即保存；取消只放弃其他外观修改。": "Language changes are saved immediately; Cancel only discards other appearance changes.",
    "取消": "Cancel",
    "保存外观": "Save appearance",
    "页面名称最多 12 个字符。": "The workspace name must be 12 characters or fewer.",
    "副标题最多 20 个字符。": "The tagline must be 20 characters or fewer.",
    "请选择一个主题色。": "Choose an accent color.",
    "外观保存服务尚未连接。": "The appearance service is not connected.",
    "头像读取服务尚未连接。": "The avatar service is not connected.",
    "先选择并裁剪一张头像图片。": "Choose and crop an avatar image first.",
    "头像图片转换失败。": "The avatar image could not be converted.",
    "保存外观失败，请重试。": "Could not save appearance. Try again.",
    "恢复默认外观失败。": "Could not restore the defaults.",
    "界面语言保存失败；已保留当前语言。": "Could not save the language. The current language is unchanged.",
    "选择头像图片": "Choose avatar image",
    "图片文件 (*.png *.jpg *.jpeg *.webp *.gif)": "Image files (*.png *.jpg *.jpeg *.webp *.gif)",
    "所有文件 (*)": "All files (*)",
    "个人板块": "Personal",
    "数据": "Data",
    "工具": "Tools",
    "每日流程": "Daily flow",
    "记账理财": "Finance",
    "习惯健康": "Habits & health",
    "习惯打卡": "Habit check-in",
    "打开习惯健康": "Open habits & health",
    "首页显示前 5 项；还有 %1 项，请打开“习惯健康”查看全部。": (
        "The home page shows the first 5. Open Habits & Health to view %1 more."
    ),
    "输入数值": "Enter value",
    "已完成 · 重置": "Completed · reset",
    "记录 +1": "Record +1",
    "快速打卡": "Quick check-in",
    "清零": "Clear to zero",
    "一键完成": "Complete in one tap",
    "减脂健身": "Fitness",
    "日程统筹": "Planner",
    "待买清单": "Shopping list",
    "书影音": "Books & media",
    "时光档案": "Life archive",
    "格式转换": "Format converter",
    "今日速览": "Today at a glance",
    "今日速览布局": "Today overview layout",
    "布局设置": "Layout settings",
    "选择要显示的旧版卡片，并编辑顺序与版面槽位。隐藏问题簿不会隐藏昨日回顾。": (
        "Choose which legacy cards to show, then edit their order and layout slots. Hiding the question desk does not hide yesterday's review."
    ),
    "显示卡片": "Show card",
    "顺序": "Order",
    "旧版版面槽位": "Legacy layout slot",
    "显示新闻头条": "Show lead story",
    "显示新闻快讯": "Show news briefs",
    "显示我的一周": "Show my week",
    "显示近期记录": "Show recent records",
    "显示习惯打卡": "Show habit check-ins",
    "显示问题簿": "Show question desk",
    "显示随手记快捷入口": "Show quick-entry shortcuts",
    "旧版自定义版面": "Legacy custom slot",
    "我的一周": "My week",
    "本周": "This week",
    "%1 条记录": "%1 records",
    "%1 天留下记录 · 习惯打卡 %2 次": "%1 active days · %2 habit check-ins",
    "还没有记录，想起什么就记下来。": "No records yet. Add something when you think of it.",
    "上周与更早": "Last week and earlier",
    "第一条记录，会从这里开始": "Your first record will appear here.",
    "打开时光档案": "Open life archive",
    "给今天留个注脚": "Leave a note for today",
    "随手记": "Quick entries",
    "记一笔": "Add an expense or income",
    "记体重": "Record weight",
    "待买物品": "Add a shopping item",
    "首页布局服务尚未连接。": "The home layout service is not connected.",
    "首页布局保存失败，布局数据无法读取。": "Could not save the home layout because its data could not be read.",
    "首页布局保存失败：%1": "Could not save the home layout: %1",
    "保存服务未确认成功。": "The save service did not confirm success.",
    "首页布局已保存。": "Home layout saved.",
    "先看世界，再照顾好今天。": "See the world, then take care of today.",
    "把天气、行业动向、昨日复盘与今日工作，收进同一封每日来信。": (
        "Bring weather, industry updates, yesterday's reflection, and today's work into one daily letter."
    ),
    "先了解天气与值得关注的变化": "Start with the weather and noteworthy changes",
    "天气查询失败，请检查城市名称或网络后重试。": (
        "Weather lookup failed. Check the city name or network and try again."
    ),
    "没有找到该城市，请检查名称或尝试输入拼音。": (
        "City not found. Check the name or try entering its pinyin."
    ),
    "城市名称无效，请重新输入。": "City name is invalid. Enter it again.",
    "查询失败": "Lookup failed",
    "当前天气": "Current weather",
    "待查询": "Not checked",
    "待设置": "Not set",
    "正在定位": "Locating",
    "正在查询": "Searching",
    "详情": "Details",
    "收起": "Hide",
    "当前位置": "Current location",
    "待设置城市": "No city set",
    "正在获取系统位置…": "Getting system location…",
    "正在获取天气…": "Getting weather…",
    "输入城市后查询天气": "Enter a city to check the weather",
    "输入城市，或使用当前位置查看本地天气。": "Enter a city or use your current location to see local weather.",
    "把远方与日常，折进今天": "Fold faraway places and everyday life into today",
    "单个自定义来源最多 60 字，请缩短或拆分后再保存。": (
        "Each custom source can be up to 60 characters. Shorten it or split it before saving."
    ),
    "次": "times",
    "体感 %1": "Feels like %1",
    "今日 %1 / %2": "Today %1 / %2",
    "湿度 %1 · 风 %2 · 降水 %3": "Humidity %1 · Wind %2 · Precipitation %3",
    "输入城市名称": "Enter a city name",
    "查询中…": "Searching…",
    "查询天气": "Get weather",
    "定位中…": "Locating…",
    "重新定位": "Locate again",
    "使用当前位置": "Use current location",
    "系统位置设置": "Location settings",
    "仅保存约 0.1° 精度的位置；也可手动输入城市。": (
        "Only location data rounded to about 0.1° is saved. You can also enter a city."
    ),
    # Exact, fixed status and error text emitted by WeatherBridge and the
    # Windows location provider. Messages containing city names or exception
    # details intentionally have no entry and remain unchanged.
    "天气已更新。": "Weather updated.",
    "请输入城市名称并查询天气。": "Enter a city to check the weather.",
    "请输入城市名称。": "Enter a city name.",
    "城市名称最多 32 个字符。": "City names can contain up to 32 characters.",
    "请输入有效的城市名称。": "Enter a valid city name.",
    "无法保存城市设置，请检查本机存储后重试。": (
        "Could not save the city setting. Check local storage and try again."
    ),
    "正在查询城市天气……": "Looking up city weather…",
    "定位未完成，可重新定位或手动输入城市。": (
        "Location was not obtained. Try again or enter a city manually."
    ),
    "正在请求 Windows 系统位置……": "Requesting Windows location…",
    "正在查询当前位置天气……": "Looking up weather for the current location…",
    "城市查询服务暂不可用，请检查网络后重试。": (
        "The city search service is unavailable. Check the network and try again."
    ),
    "天气服务暂不可用，请检查网络后重试。": (
        "The weather service is unavailable. Check the network and try again."
    ),
    "城市查询服务返回的内容无法读取，请稍后重试。": (
        "The city search service returned unreadable data. Try again later."
    ),
    "城市查询结果缺失，请重新查询。": "City search results are missing. Search again.",
    "Windows 定位服务没有返回有效结果，可手动输入城市。": (
        "Windows location returned no valid result. Enter a city manually."
    ),
    "获取系统位置超时，可重试或手动输入城市。": (
        "The location request timed out. Try again or enter a city manually."
    ),
    "Windows 定位请求未能完成，请手动输入城市。": (
        "The Windows location request did not complete. Enter a city manually."
    ),
    "Windows 未允许此应用访问位置；可在系统位置设置中开启，或手动输入城市。": (
        "Windows did not allow this app to access your location. Enable access in system settings or enter a city manually."
    ),
    "Windows 暂未提供位置授权，请手动输入城市。": (
        "Windows has not granted location access. Enter a city manually."
    ),
    "已允许访问，正在获取当前位置……": "Access granted. Getting the current location…",
    "Windows 定位服务暂不可用，可稍后重试或手动输入城市。": (
        "Windows location is unavailable. Try again later or enter a city manually."
    ),
    "城市查询结果缺少 results 字段，请稍后重试。": (
        "City search results are missing the results field. Try again later."
    ),
    "城市查询结果格式无效，请稍后重试。": (
        "City search results have an invalid format. Try again later."
    ),
    "没有找到匹配的城市，请检查城市名称或尝试输入拼音。": (
        "No matching city was found. Check the name or try entering its pinyin."
    ),
    "城市查询结果缺少有效地点，请稍后重试。": (
        "City search results contain no valid place. Try again later."
    ),
    "城市查询返回的内容不是有效 JSON，请稍后重试。": (
        "City search returned invalid JSON. Try again later."
    ),
    "天气服务返回的内容不是有效 JSON，请稍后重试。": (
        "The weather service returned invalid JSON. Try again later."
    ),
    "城市查询返回的数据格式无效，请稍后重试。": (
        "City search returned data in an invalid format. Try again later."
    ),
    "天气服务返回的数据格式无效，请稍后重试。": (
        "The weather service returned data in an invalid format. Try again later."
    ),
    "城市纬度无效，请重新查询城市。": "The city latitude is invalid. Search again.",
    "城市经度无效，请重新查询城市。": "The city longitude is invalid. Search again.",
    "城市纬度超出有效范围，请重新查询城市。": (
        "The city latitude is out of range. Search again."
    ),
    "城市经度超出有效范围，请重新查询城市。": (
        "The city longitude is out of range. Search again."
    ),
    "天气数据缺少 current 对象，请稍后重试。": (
        "Weather data is missing the current object. Try again later."
    ),
    "天气数据缺少 daily 对象，请稍后重试。": (
        "Weather data is missing the daily object. Try again later."
    ),
    "城市查询结果缺少有效的 name 字段，请重新查询城市。": (
        "City search results are missing a valid name field. Search again."
    ),
    "天气数据缺少 current.temperature_2m，请稍后重试。": (
        "Weather data is missing current.temperature_2m. Try again later."
    ),
    "天气数据缺少 current.apparent_temperature，请稍后重试。": (
        "Weather data is missing current.apparent_temperature. Try again later."
    ),
    "天气数据缺少 current.weather_code，请稍后重试。": (
        "Weather data is missing current.weather_code. Try again later."
    ),
    "天气数据缺少 daily.temperature_2m_max，请稍后重试。": (
        "Weather data is missing daily.temperature_2m_max. Try again later."
    ),
    "天气数据缺少 daily.temperature_2m_min，请稍后重试。": (
        "Weather data is missing daily.temperature_2m_min. Try again later."
    ),
    "天气数据中的 current.temperature_2m 无效，请稍后重试。": (
        "Weather data contains an invalid current.temperature_2m. Try again later."
    ),
    "天气数据中的 current.apparent_temperature 无效，请稍后重试。": (
        "Weather data contains an invalid current.apparent_temperature. Try again later."
    ),
    "天气数据中的 current.weather_code 无效，请稍后重试。": (
        "Weather data contains an invalid current.weather_code. Try again later."
    ),
    "天气数据中的 current.relative_humidity_2m 无效，请稍后重试。": (
        "Weather data contains an invalid current.relative_humidity_2m. Try again later."
    ),
    "天气数据中的 current.wind_speed_10m 无效，请稍后重试。": (
        "Weather data contains an invalid current.wind_speed_10m. Try again later."
    ),
    "天气数据中的 daily.precipitation_probability_max 无效，请稍后重试。": (
        "Weather data contains an invalid daily precipitation probability. Try again later."
    ),
    "天气数据中的 daily.temperature_2m_max 无效，请稍后重试。": (
        "Weather data contains an invalid daily.temperature_2m_max. Try again later."
    ),
    "天气数据中的 daily.temperature_2m_min 无效，请稍后重试。": (
        "Weather data contains an invalid daily.temperature_2m_min. Try again later."
    ),
    "天气数据缺少 daily.temperature_2m_max，请稍后重试。": (
        "Weather data is missing daily.temperature_2m_max. Try again later."
    ),
    "天气数据缺少 daily.temperature_2m_min，请稍后重试。": (
        "Weather data is missing daily.temperature_2m_min. Try again later."
    ),
    "天气数据中的 daily.temperature_2m_max 不完整，请稍后重试。": (
        "Weather data contains an incomplete daily.temperature_2m_max. Try again later."
    ),
    "天气数据中的 daily.temperature_2m_min 不完整，请稍后重试。": (
        "Weather data contains an incomplete daily.temperature_2m_min. Try again later."
    ),
    "天气数据中的 current.relative_humidity_2m 超出有效范围。": (
        "Weather data contains an out-of-range current.relative_humidity_2m."
    ),
    "天气代码无效，请稍后重试。": "The weather code is invalid. Try again later.",
    "天气数据中的 current.is_day 无效，请稍后重试。": (
        "The current.is_day value in the weather data is invalid. Try again later."
    ),
    "天气数据中的 daily.precipitation_probability_max 不完整，请稍后重试。": (
        "The daily precipitation probability in the weather data is incomplete. Try again later."
    ),
    "天气数据中的 daily.precipitation_probability_max 超出有效范围。": (
        "The daily precipitation probability is out of range."
    ),
    "昨日复盘": "Yesterday's review",
    "今日工作": "Today's work",
    "开始专注": "Focus session",
    "天气 · 行业": "Weather · News",
    "记录 · 想法": "Journal · Ideas",
    "待办 · 邮件": "Tasks · Email",
    "任务 · 音频": "Tasks · Audio",
    "简报 · 偏好": "Briefing · Preferences",
    "外观": "Appearance",
    "备份与数据": "Backup & data",
    "清理示例": "Clear samples",
    "关闭": "Close",
    "确定": "OK",
    "取消": "Cancel",
    "选择旧版迁移包": "Choose legacy migration package",
    "旧版数据迁移包 (*.json)": "Legacy data migration package (*.json)",
    "JSON 文件 (*.json)": "JSON files (*.json)",
    "导出本机完整备份": "Export full local backup",
    "新版完整备份 (*.wxbak)": "FLUKE full backup (*.wxbak)",
    "Native 密码保护备份 (*.wxbak2)": "Native password-protected backup (*.wxbak2)",
    "旧版密码保护备份 (*.wxbackup)": "Legacy password-protected backup (*.wxbackup)",
    "选择本机完整备份": "Choose local full backup",
    "旧版完整备份 JSON (*.json)": "Legacy full backup JSON (*.json)",
    "导出密码保护 Native 备份": "Export password-protected Native backup",
    "Native 密码保护备份请使用 .wxbak2 扩展名。": "Native password-protected backups must use the .wxbak2 extension.",
    "可导出普通或密码保护的 Native 完整备份，也可恢复旧版 JSON 与 .wxbackup 加密备份。密码保护的 Native 文件使用独立 .wxbak2 格式，旧版软件无法读取。备份可能含个人数据，请妥善保管。": (
        "Export a regular or password-protected Native backup, or restore legacy JSON and .wxbackup encrypted backups. "
        "Password-protected Native files use the separate .wxbak2 format and cannot be read by the legacy app. "
        "Backups may contain personal data; store them carefully."
    ),
    "导出密码保护备份…": "Export password-protected backup…",
    "Native 密码保护备份采用独立 .wxbak2 格式；旧版软件不能读取。密码只在本次导出时使用，不会保存。": (
        "Native password-protected backups use the separate .wxbak2 format and cannot be read by the legacy app. "
        "The password is used for this export only and is not saved."
    ),
    "设置备份密码": "Set backup password",
    "输入备份密码": "Enter backup password",
    "再次输入备份密码": "Enter the backup password again",
    "导出加密备份": "Export encrypted backup",
    "两次输入的备份密码不一致。": "The backup passwords do not match.",
    "请输入备份密码。": "Enter a backup password.",
    "密码保护 Native 备份已保存。请妥善保管密码；旧版无法读取此格式。": (
        "Password-protected Native backup saved. Keep the password safe; the legacy app cannot read this format."
    ),
    "密码保护备份导出失败。": "Failed to export the password-protected backup.",
    "备份失败：%1": "Backup failed: %1",
    "Native 密码保护完整备份": "Native password-protected full backup",
    "旧版密码保护完整备份": "Legacy password-protected full backup",
    " · 完整本机数据库约 %1 KB": " · Full local database about %1 KB",
    " · 旧记录 %1 · 习惯 %2 · 书影音 %3 · 文件约 %4 KB": (
        " · Legacy records %1 · Habits %2 · Media %3 · File about %4 KB"
    ),
    "加密备份无法预览：%1": "Cannot preview encrypted backup: %1",
    "请检查密码或文件完整性。": "Check the password or file integrity.",
    "密码只在本次恢复预览期间暂存在内存中；取消预览或完成恢复后会清除。": (
        "The password stays in memory during this restore preview only and is cleared when you cancel or finish."
    ),
    "备份密码": "Backup password",
    "解密并预览": "Decrypt and preview",
    "可导出新版本机数据库备份，也可恢复旧版“日常集”完整备份 JSON。备份可能含个人数据，请妥善保管。旧版迁移包请使用单独的导入入口。": (
        "Export a full backup of the new local database or restore a legacy Daily Atlas backup JSON. "
        "Backups may contain personal data; store them carefully. Use the separate import option "
        "for a legacy data migration package."
    ),
    "恢复本机完整备份": "Restore local full backup",
    "导入旧版迁移包": "Import legacy migration package",
    "清空全部本机数据…": "Clear all local data…",
    "清理示例数据": "Clear sample data",
    "清空全部本机数据": "Clear all local data",
    "将清除 %1 条示例记录、%2 个示例书影音条目，以及 %3 个样本习惯的打卡历史。你添加的内容、习惯定义和周计划会保留。": (
        "This will clear %1 sample records, %2 sample books and media items, and the check-in "
        "history for %3 sample habits. Your own content, habit definitions, and weekly plan will remain."
    ),
    "将清空 %1 条本机记录、%2 个本机书影音条目和所有习惯打卡历史，并将周计划恢复默认值；删除每日一刊活动内容、历史和草稿。": (
        "This will clear %1 local records, %2 local books and media items, and all habit check-in "
        "history; reset the weekly plan; and delete Daily Issue activity, history, and drafts."
    ),
    "只修改本机 SQLite；不影响云端账户数据、旧版数据或迁移原件。": (
        "Only the local SQLite database is changed. Cloud account data, legacy data, and the original migration package are unaffected."
    ),
    "保留版面、问题簿、关注主题与媒体偏好、剪报、已存知识、品牌主题及其他独立本机设置。": (
        "Layout, question log, followed topics and media preferences, clippings, saved knowledge, "
        "brand theme, and other independent local settings will be kept."
    ),
    "确认清理示例": "Clear sample data",
    "确认清空本机数据": "Clear local data",
    "本机数据清理": "Local data cleanup",
    "核对完整备份": "Review full backup",
    "导出时间：%1": "Exported: %1",
    "旧版完整备份": "Legacy full backup",
    "数据表 %1": "%1 tables",
    " · 记录 %1 · 习惯 %2 · 书影音 %3 · 本机数据约 %4 KB": (
        " · %1 records · %2 habits · %3 books & media · about %4 KB locally"
    ),
    "旧版备份将替换生活记录和刊期内容；本机独立设置及新闻问题簿会保留，依附旧记录的新版模块覆盖会清除。": (
        "The legacy backup will replace life records and issue content. Independent local settings "
        "and the news question log will remain; newer module overlays linked to legacy records will be cleared."
    ),
    "恢复会完整替换当前本机数据库。": "Restore will replace the entire current local database.",
    "确认后应用会自动关闭并重新打开；执行前会再次核验文件，取消不会更改数据库。": (
        "After confirmation, the app will close and reopen automatically. The file will be checked again before restore; canceling leaves the database unchanged."
    ),
    "确认恢复并重启": "Restore and restart",
    "恢复失败；当前数据库未替换：%1": "Restore failed; the current database was not replaced: %1",
    "备份与恢复": "Backup & restore",
    "导入旧版数据": "Import legacy data",
    "请核对数量后再导入。该操作只写入新版独立数据库，不改动旧版数据。": (
        "Review the counts before importing. This writes only to the new, separate database and does not change legacy data."
    ),
    "存储键 %1/%2 · 记录 %3 · 习惯 %4 · 书影音 %5": (
        "Storage keys %1/%2 · %3 records · %4 habits · %5 books & media"
    ),
    "新闻刊期 %1 · 问题簿 %2 · 关注主题 %3 · 剪报 %4": (
        "News issues %1 · question log %2 · followed topics %3 · clippings %4"
    ),
    "检测到同一旧版来源的新快照。确认后保留历史快照和本机模块修改，并切换当前数据。": (
        "A new snapshot from the same legacy source was found. Confirming preserves snapshot history and local module changes, then makes this snapshot current."
    ),
    "这份快照已保存在历史记录中，但不是当前快照。为避免意外回退，不能再次切换它。请从旧版导出当前数据。": (
        "This snapshot is already in history but is not current. It cannot be selected again to avoid rolling back accidentally. Export the current data from the legacy app."
    ),
    "存储键变化：新增 %1 · 修改 %2 · 移除 %3 · 未变 %4": (
        "Storage keys: %1 added · %2 changed · %3 removed · %4 unchanged"
    ),
    "记录变化：新增 %1 · 修改 %2 · 移除 %3": (
        "Records: %1 added · %2 changed · %3 removed"
    ),
    "习惯变化：新增 %1 · 修改 %2 · 移除 %3": (
        "Habits: %1 added · %2 changed · %3 removed"
    ),
    "书影音变化：新增 %1 · 修改 %2 · 移除 %3": (
        "Books & media: %1 added · %2 changed · %3 removed"
    ),
    "SHA-256：%1…": "SHA-256: %1…",
    "确认导入": "Import",
    "确认切换到新快照": "Switch to new snapshot",
    "重新打开软件": "Reopen the app",
    "这份迁移包已导入过，没有重复写入。": "This package was already imported. No duplicate data was written.",
    "导入成功；旧版数据保持不变。": "Import complete. Legacy data remains unchanged.",
    "导入成功。请重新打开软件以载入所有模块的数据。": (
        "Import complete. Reopen the app to load the data in all modules."
    ),
    "新快照已设为当前数据，历史快照和本机模块修改均已保留。请重新打开软件以载入更新后的数据。": (
        "The new snapshot is now active. Snapshot history and local module changes have been preserved. Reopen the app to load the updated data."
    ),
    "这份迁移快照已存在于历史记录中，未重新激活。请预览当前活动快照后再选择新导出包。": (
        "This snapshot is already in history and was not reactivated. Preview the active snapshot and select a newly exported package."
    ),
    "当前迁移快照已变化，请重新预览后再确认。": (
        "The active snapshot changed. Preview the package again before confirming."
    ),
    "导入失败：%1": "Import failed: %1",
    "数据迁移": "Data migration",
    "本地优先": "Local-first",
    "个人记录保存在这台设备。": "Your personal records stay on this device.",
    "已读入旧版数据": "Legacy data loaded",
    "一个键": "one key",
    "%1 个键": "%1 keys",
    "一条记录": "one record",
    "%1 条记录": "%1 records",
    "一项习惯": "one habit",
    "%1 项习惯": "%1 habits",
    "迁移数据暂不可读": "Migration data is temporarily unavailable",
    "尚未导入旧版数据": "No legacy data imported",
    "1 件": "1 item",
    "%1 件": "%1 items",
    "今日": "Today",
    "记账": "Finance",
    "习惯": "Habits",
    "健身": "Fitness",
    "日程": "Planner",
    "一笔收支": "A transaction",
    "身体记录": "Health entry",
    "一项日程": "Planner task",
    "生活记录": "Life record",
    "昨日回顾": "Yesterday's review",
    "待买": "Shopping",
    "档案": "Archive",
    "转换": "Convert",
}


def _merge_catalogs(*catalogs: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for catalog in catalogs:
        for source, translation in catalog.items():
            existing = merged.get(source)
            if existing is not None and existing != translation:
                raise ValueError(f"Conflicting English translation for {source!r}")
            merged[source] = translation
    return merged


ENGLISH_CATALOG = _merge_catalogs(_CORE_ENGLISH_CATALOG, NEWS_ENGLISH_CATALOG)

# QML supplies its component name as the translation context. Keep each page's
# reviewed vocabulary local so a short Chinese label can have a natural, precise
# translation in its own UI (for example, the "to buy" filter vs. the page name).
QML_CONTEXT_CATALOGS: dict[str, dict[str, str]] = {
    "ArchivePage": ARCHIVE_ENGLISH_CATALOG,
    "ArticleDialog": NEWS_ENGLISH_CATALOG,
    "Main": _merge_catalogs(NEWS_ENGLISH_CATALOG, PLANNER_ENGLISH_CATALOG),
    "ConverterPage": CONVERTER_ENGLISH_CATALOG,
    "ConverterEnginesDialog": CONVERTER_ENGINES_ENGLISH_CATALOG,
    "DailyFlowPage": DAILY_FLOW_ENGLISH_CATALOG,
    "FinancePage": FINANCE_ENGLISH_CATALOG,
    "FitnessPage": FITNESS_ENGLISH_CATALOG,
    "HabitPage": HABITS_ENGLISH_CATALOG,
    "MediaPage": MEDIA_ENGLISH_CATALOG,
    "PlannerPage": PLANNER_ENGLISH_CATALOG,
    "PreferencesDialog": PREFERENCES_ENGLISH_CATALOG,
    "ShoppingPage": SHOPPING_ENGLISH_CATALOG,
}
QML_DISAMBIGUATED_CATALOGS: dict[tuple[str, str, str], str] = {
    ("ArchivePage", source, disambiguation): translation
    for (source, disambiguation), translation in ARCHIVE_DISAMBIGUATED_ENGLISH_CATALOG.items()
}
QML_DISAMBIGUATED_CATALOGS.update(
    {
        ("ShoppingPage", source, disambiguation): translation
        for (source, disambiguation), translation in SHOPPING_DISAMBIGUATED_ENGLISH_CATALOG.items()
    }
)


def normalize_language(value: Any) -> str:
    """Return a supported language, defaulting safely to Simplified Chinese."""
    if isinstance(value, str) and value in SUPPORTED_LANGUAGES:
        return value
    return DEFAULT_LANGUAGE


class LocalizationRepository:
    """Persist only the native UI-language preference in app_settings."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()

    def language(self) -> str:
        stored = get_app_setting(self.database_path, LANGUAGE_SETTING_KEY)
        return normalize_language(stored)

    def set_language(self, language: str) -> str:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported UI language")
        try:
            set_app_setting(self.database_path, LANGUAGE_SETTING_KEY, language)
        except (OSError, TypeError, ValueError, RuntimeError, sqlite3.Error) as exc:
            raise RuntimeError("Could not save the UI language") from exc
        return language


class DictionaryTranslator(QTranslator):
    """Small runtime translator backed by reviewed source-to-English entries."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._language = DEFAULT_LANGUAGE

    def set_language(self, language: str) -> None:
        self._language = normalize_language(language)

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        if self._language == "en_US":
            # QML treats an empty result from a custom translator as an empty
            # display string. Return the source explicitly for reviewed-but-
            # untranslated coverage so the UI remains readable.
            specialized = QML_DISAMBIGUATED_CATALOGS.get(
                (context, source_text, disambiguation or "")
            )
            if specialized is not None:
                return specialized
            contextual = QML_CONTEXT_CATALOGS.get(context)
            if contextual is not None and source_text in contextual:
                return contextual[source_text]
            return ENGLISH_CATALOG.get(source_text, source_text)
        return source_text


class LocalizationBridge(QObject):
    """QML adapter for language selection and live translation refresh."""

    languageChanged = Signal()
    errorChanged = Signal()

    def __init__(
        self,
        repository: LocalizationRepository,
        engine: Any,
        application: QCoreApplication | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self._engine = engine
        self._application = application or QCoreApplication.instance()
        self._translator = DictionaryTranslator(self)
        self._language = repository.language()
        self._error = ""
        self._translator.set_language(self._language)
        if self._application is not None:
            self._application.installTranslator(self._translator)

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        return self._error

    @Slot(str, result="QVariant")
    def setLanguage(self, language: str) -> dict[str, Any]:
        if language not in SUPPORTED_LANGUAGES:
            self._error = "请选择受支持的界面语言。"
            self.errorChanged.emit()
            return {"ok": False, "error": self._error, "language": self._language}
        if language == self._language:
            self._error = ""
            self.errorChanged.emit()
            return {"ok": True, "error": "", "language": self._language}
        try:
            self.repository.set_language(language)
        except RuntimeError:
            self._error = "界面语言保存失败；已保留当前语言。"
            self.errorChanged.emit()
            return {"ok": False, "error": self._error, "language": self._language}

        self._language = language
        self._translator.set_language(language)
        self._error = ""
        self.errorChanged.emit()
        if self._engine is not None:
            self._engine.retranslate()
        # Emit after QML retranslation because model-backed selectors may be
        # rebuilt as bindings refresh; listeners then restore their selection.
        self.languageChanged.emit()
        return {"ok": True, "error": "", "language": self._language}

    @Slot()
    def close(self) -> None:
        if self._application is not None:
            self._application.removeTranslator(self._translator)
            self._application = None
