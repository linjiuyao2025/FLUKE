"""Reviewed English text for the news workbench and article-reading dialog."""

ENGLISH_CATALOG: dict[str, str] = {
    "改用此城市": "Use this city",
    "新闻 JSON 内容": "News JSON content",
    "城市名或“城市, 省/国家”": "City or “city, region/country”",
    "文章阅读": "Article reader",
    "本期推送": "This issue",
    "关闭文章阅读": "Close article reader",
    "AI 整理稿": "AI-edited content",
    "AI 整理": "AI edited",
    "本期視覺": "Issue artwork",
    "与你的关联": "Why this matters to you",
    "可以做什么": "What you can do",
    "条件与边界": "Conditions and limits",
    "同一事件的其他报道": "Other coverage of this event",
    "事件进展": "Event updates",
    "核对原文 ↗": "Verify the original ↗",
    "资料出处": "Source details",
    "原始标题：": "Original title: ",
    "内容包未单独提供": "Not provided separately in this content package",
    "发布方未提供": "Publisher not provided",
    "发布日期未提供": "Publication date not provided",
    "未提供有效的 HTTPS 原文链接": "No valid HTTPS link to the original article was provided",
    "上方正文为 AI 整理稿；原始报道链接用于核对，不展示新闻源稿全文。": (
        "The article text above was prepared with AI. Use the original link to verify it; "
        "the full source article is not reproduced here."
    ),
    "已开启稍后读 ✓": "Saved to read later ✓",
    "开启稍后读 +": "Save for later +",
    "关闭全局稍后读 ✓": "Saved to read later ✓",
    "开启全局稍后读 +": "Save for later +",
    "关闭全局稍后读": "Turn off read later",
    "开启全局稍后读": "Turn on read later",
    "已收进剪报 ✓": "Added to clippings ✓",
    "收进剪报 +": "Add to clippings +",
    "从剪报移出这篇文章": "Remove this article from clippings",
    "将这篇文章收进剪报": "Add this article to clippings",
    "打开原始报道 ↗": "Open original article ↗",
    "告诉本机推荐你的兴趣（再次点击可撤销）": (
        "Share your interests with recommendations on this device (click again to undo)"
    ),
    "本机推荐反馈暂不可用；文章阅读和剪报仍可正常使用。": (
        "On-device recommendation feedback is unavailable; article reading and clippings still work."
    ),
    "这篇有帮助 ✓": "Helpful ✓",
    "这篇有帮助": "Helpful",
    "不感兴趣 ✓": "Not interested ✓",
    "不感兴趣": "Not interested",
    "多看这个主题 ✓": "More on this topic ✓",
    "多看这个主题": "More on this topic",
    "少看这个来源 ✓": "Less from this source ✓",
    "少看这个来源": "Less from this source",
    # Fixed labels and explanations in the Main-context news workbench.
    "我的新闻剪报": "My news clippings",
    "NEWS SCOPE": "NEWS SCOPE",
    "本机刊期编辑工作台": "Local issue editing workspace",
    "打开编辑工作台": "Open editing workspace",
    "收起工作台": "Close workspace",
    "刊期草稿、排序和本地素材管理已收起；展开后继续编辑。": (
        "Drafts, ordering, and local source management are tucked away. Open the workspace to continue editing."
    ),
    "草稿预览": "Draft preview",
    "本机刊期": "Local issue",
    "待导入": "Awaiting import",
    "关注方向": "Topics of interest",
    "偏好仅用于新闻内容准备提示，不会自动屏蔽其他新闻；每篇内容仍需保留来源与日期。": (
        "Preferences guide news preparation only; they do not hide other stories. Keep each story's source and date."
    ),
    "正在编辑草稿": "Editing draft",
    "预览未保存": "Preview not saved",
    "预览未保存 · 保存后才写入本机": "Preview not saved · Save it to store it on this device.",
    "草稿已保存到本机": "Draft saved on this device",
    "尚无草稿": "No draft yet",
    "已保存草稿": "Draft saved",
    "收起推荐反馈": "Collapse recommendation feedback",
    "已设置推荐反馈 · 修改": "Recommendation feedback set · edit",
    "告诉本机推荐系统": "Give feedback to local recommendations",
    "打开或收起本机推荐反馈": "Open or close local recommendation feedback",
    "只影响这台设备上的推荐，不会点赞、发送消息或改变原文": (
        "Affects recommendations on this device only. It will not like, message, or change the original article."
    ),
    "只影响本机推荐；再次点击可撤销，不会点赞或发送消息。": (
        "Affects local recommendations only. Click again to undo. It will not like or message the article."
    ),
    "当前已发布刊期": "Currently published issue",
    "编辑本期 JSON": "Edit this issue's JSON",
    "导入本期 JSON": "Import this issue's JSON",
    "复制生成提示": "Copy generation prompt",
    "导出已发布刊期": "Export published issue",
    "推荐第 %1 位": "Recommended rank: %1",
    "本机保存的报道快照 · %1 / 80": "Saved article snapshots · %1 / 80",
    "还没有收进剪报的报道。": "No saved clippings yet.",
    "来信剪报": "Letter clipping",
    "未命名报道": "Untitled story",
    "阅读全文": "Read article",
    "移出剪报": "Remove from clippings",
    "已从剪报中移出。": "Removed from clippings.",
    "全局稍后读功能已开启。": "Read later is on for all articles.",
    "全局稍后读功能已关闭。": "Read later is off for all articles.",
    "已收进本期剪报。": "Added to this issue's clippings.",
    "已从本期剪报移出。": "Removed from this issue's clippings.",
    "文章反馈已保存到本机。": "Article feedback saved on this device.",
    "已撤销这条文章反馈。": "Article feedback removed.",
    "关注方向已保存。": "Topics and source preferences saved.",
    "关注方向保存失败，请重试。": "Could not save preferences. Try again.",
    "选择本机新闻 JSON 文件": "Choose a local news JSON file",
    "JSON 文件 (*.json)": "JSON files (*.json)",
    "导出已发布的本期刊物": "Export the published issue",
    "本期 JSON 已导出到所选位置。": "Issue JSON exported to the selected location.",
    "粘贴或编辑新闻 JSON": "Paste or edit news JSON",
    "当前草稿已载入文本框。修改后请先预览，再选择保存草稿或发布。": (
        "The current draft is loaded in the text box. Preview your changes before saving or publishing."
    ),
    "粘贴新闻 JSON 后先预览；预览不会直接发布。": (
        "Preview the news JSON before saving. Previewing never publishes it."
    ),
    "粘贴包含 version、date、topic、focus 和 highlights 的 JSON 内容包。": (
        "Paste a JSON package with version, date, topic, focus, and highlights."
    ),
    "打开 JSON 文件": "Open JSON file",
    "校验并预览": "Validate and preview",
    "新闻刊期预览": "News issue preview",
    "日期待定": "Date not set",
    "未命名主题": "Untitled topic",
    "没有可显示的预览内容。": "There is no preview to display.",
    "这是未发布的预览。关闭窗口不会保存；保存草稿或发布都需要你明确点击对应按钮。": (
        "This is an unpublished preview. Closing this window will not save it. Choose Save draft or Publish to continue."
    ),
    "%1 · %2 条": "%1 · %2 items",
    "%1 · %2": "%1 · %2",
    "预览历史刊期": "Preview historical issue",
    "历史刊期不存在": "Historical issue not found",
    "这是只读预览。选择“载入为草稿”后，才会把它放入编辑工作台；当前草稿不会在这里自动替换。": (
        "This is a read-only preview. Select Load as draft to place it in the editing workspace; "
        "the current draft will not be replaced here."
    ),
    "载入为草稿": "Load as draft",
    "返回编辑": "Back to editing",
    "保存草稿": "Save draft",
    "草稿已保存到本机。": "Draft saved on this device.",
    "确认发布本期新闻": "Confirm issue publication",
    "将发布“%1”，并把当前已发布刊期移入历史。": (
        "Publish “%1” and move the current issue to history."
    ),
    "当前没有可发布的草稿。": "There is no draft to publish.",
    "发布会写入本机数据库；你仍需再次点击下方确认。": (
        "Publishing writes to the local database. Select Confirm below to continue."
    ),
    "取消": "Cancel",
    "确认发布": "Confirm publication",
    "本期已发布，原刊期已归档。": "Issue published; the previous issue was archived.",
    "清除文章反馈画像": "Clear article feedback profile",
    "这会清除你对文章的有用、不感兴趣、主题和来源反馈。手动关注主题、来源偏好、剪报和新闻刊期会保留。": (
        "This clears your helpful, not interested, topic, and source feedback. Manual topic and source preferences, clippings, and issues will remain."
    ),
    "清除反馈": "Clear feedback",
    "文章反馈画像已清除；主题偏好和剪报仍保留。": (
        "Article feedback was cleared; topic preferences and clippings remain."
    ),
    "调整新闻版面": "Arrange news layout",
    "勾选控制分组显示；拖动左侧手柄或使用上下按钮调整顺序。保存时保留其他版面字段。": (
        "Select groups to show, then drag the left handle or use the arrows to reorder them. Other layout fields are preserved when you save."
    ),
    "新闻工作台显示": "Show news workbench",
    "拖动以调整%1顺序": "Drag to reorder %1",
    "%1显示": "Show %1",
    "上移%1": "Move %1 up",
    "下移%1": "Move %1 down",
    "完成": "Done",
    "NEWS SCOPE · 本机刊期工作台": "NEWS SCOPE · Local issue workspace",
    "版面设置": "Layout",
    "关注设置": "Preferences",
    "我的剪报 · %1": "My clippings · %1",
    "关闭全局稍后读": "Turn off read later for all articles",
    "开启全局稍后读": "Turn on read later for all articles",
    "关注方向与本期编辑": "Topics of interest and issue editor",
    "主题和候选媒体只用于生成内容准备提示；每篇新闻仍保留来源、日期和核对边界。": (
        "Topics and candidate sources guide preparation only. Every article still keeps its source, date, and verification context."
    ),
    "编辑 / 粘贴 JSON": "Edit / paste JSON",
    "粘贴 JSON": "Paste JSON",
    "复制新闻生成提示": "Copy news-generation prompt",
    "新闻生成提示已复制。": "News-generation prompt copied.",
    "导出本期 JSON": "Export issue JSON",
    "把 .json 文件拖入以预览；把 HTTP(S) 网页链接拖入本地素材箱。链接不会被抓取或发布。": (
        "Drop a .json file to preview it, or drop an HTTP(S) link into the local link inbox. Links are not fetched or published."
    ),
    "当前已发布": "Currently published",
    "草稿与排序": "Draft and order",
    "尚无草稿；导入 JSON 或载入历史刊期开始编辑。": (
        "No draft yet. Import JSON or load an issue from history to start editing."
    ),
    "发布本期": "Publish issue",
    "生成推荐建议": "Generate recommendations",
    "已生成组内推荐顺序和理由；草稿尚未修改。": (
        "Group recommendations and reasons are ready; the draft has not changed."
    ),
    "采用建议排序": "Apply suggested order",
    "推荐顺序已应用到草稿，可继续手动调整。": (
        "Suggested order applied to the draft. You can still adjust it manually."
    ),
    "清除文章反馈": "Clear article feedback",
    "建议只在原有分组内排序；保存或发布前仍可用上下箭头手动调整。清除反馈不会删除关注设置或剪报。": (
        "Recommendations only reorder items within their groups. You can still use the arrows before saving or publishing. Clearing feedback does not remove preferences or clippings."
    ),
    "选择历史刊期并载入草稿…": "Choose an issue from history to load as a draft…",
    "历史刊期已载入为草稿，可继续排序、保存或发布。": (
        "Issue loaded from history as a draft. You can reorder, save, or publish it."
    ),
    "历史刊期已载入为草稿；原草稿已被替换，可继续排序、保存或发布。": (
        "Historical issue loaded as a draft; the previous draft was replaced. "
        "You can continue reordering, saving, or publishing."
    ),
    "载入历史刊期？": "Load historical issue?",
    "当前草稿“%1”将被历史刊期“%2”替换。": (
        "The current draft “%1” will be replaced by the historical issue “%2”."
    ),
    "将载入历史刊期“%1”。": "Load the historical issue “%1”.",
    "当前预览内容尚未保存；如果继续，返回时无法恢复这份预览。": (
        "The current preview is not saved. If you continue, you cannot restore it when you return."
    ),
    "这会替换当前草稿；已发布刊期和历史记录不会被删除。": (
        "This will replace the current draft; published issues and history will not be deleted."
    ),
    "覆盖并载入": "Replace and load",
    "替换当前未保存内容？": "Replace unsaved content?",
    "当前“%1”还没有保存；继续预览会用新的 JSON 替换它。": (
        "“%1” is unsaved. Continuing to preview will replace it with the new JSON."
    ),
    "当前预览还没有保存；继续会替换它。": "This preview is unsaved. Continuing will replace it.",
    "如果想保留当前内容，请先取消并保存草稿。": (
        "Cancel and save the draft first if you want to keep the current content."
    ),
    "替换并预览": "Replace and preview",
    "已发布内容可从上方历史列表载入；当前没有待编辑草稿。": (
        "Load a published issue from the history list above. There is no draft to edit right now."
    ),
    "导入后会先校验并预览，不会直接发布。": (
        "Imported JSON is validated and previewed first; it is never published directly."
    ),
    "建议顺序：%1": "Suggested order: %1",
    "本地链接素材箱 · %1": "Local link inbox · %1",
    "仅保存链接，不抓取页面": "Links are saved only; pages are not fetched",
    "拖入 HTTP(S) 网页链接后，会列在这里供本机管理。": (
        "Dropped HTTP(S) links appear here for local management."
    ),
    "打开素材链接": "Open saved link",
    "打开": "Open",
    "移除": "Remove",
    "链接已从本地素材箱移除。": "Link removed from the local inbox.",
    "每日一刊 · JSON 导入先预览；草稿、发布、历史刊期和版面设置保存在本机。": (
        "Daily edition · JSON imports are previewed first; drafts, published issues, history, and layout are stored locally."
    ),
    "收起更多": "Show less",
    "收起新闻工作台的低频操作": "Hide less-frequently used news workspace actions",
    "打开新闻工作台的低频操作": "Show less-frequently used news workspace actions",
    "每日一刊 · JSON 导入先预览；草稿、发布和历史刊期保存在本机；低频设置在工作台“更多”中。": (
        "Daily edition · JSON imports are previewed first; drafts, published issues, and issue history stay on this device; "
        "less-frequently used settings are under More in the workspace."
    ),
    "模块与版面 +": "Sections and layout +",
    "本期内容": "Current issue",
    "草稿待编辑 / 发布": "Draft ready to edit / publish",
    "已载入已发布刊期": "Published issue loaded",
    "尚未载入本期新闻": "No issue loaded",
    "关注焦点": "Focus areas",
    "行业看点": "Industry highlights",
    "文章内容": "Articles",
    "未命名条目": "Untitled item",
    "尚未发布刊期。": "No issue has been published yet.",
    "尚未发布刊期": "No issue published",
    "导入并发布本期 JSON 后，这里会显示刊期摘要。": (
        "Import and publish this issue's JSON to see its summary here."
    ),
    "日期未填写": "Date not provided",
    "焦点 %1": "%1 focus areas",
    "看点 %1": "%1 highlights",
    "文章 %1": "%1 articles",
    "操作未完成，请检查内容后重试。": "The operation did not complete. Check the content and try again.",
    "操作已完成。": "Operation completed.",
    "校验通过，已进入预览；尚未发布。": "Validation passed. Preview opened; nothing has been published.",
    "版面显示设置已保存。": "Layout visibility saved.",
    "版面顺序已保存。": "Layout order saved.",
    "网页链接已收进本地素材箱；不会抓取或发布页面。": (
        "Link added to the local inbox. The page will not be fetched or published."
    ),
    "请一次拖入一个 JSON 文件或网页链接。": "Drop one JSON file or web link at a time.",
    "请拖入本机 .json 文件，或以 http://、https:// 开头的网页链接。": (
        "Drop a local .json file or a web link starting with http:// or https://."
    ),
    "条目顺序已调整。": "Item order updated.",
    "保存失败。": "Could not save the layout.",
    "保存失败；当前版面设置未更改。": "Save failed; the current layout was not changed.",
    "本期内容": "Current issue",
    "草稿待编辑 / 发布": "Draft ready to edit / publish",
    "已载入已发布刊期": "Published issue loaded",
    "尚未载入本期新闻": "No issue loaded",
    "无法预览新闻内容包：": "Could not preview the news package: ",
    "新闻内容包超过 500 KB，请压缩图片后再导入。": (
        "The news package exceeds 500 KB. Compress images before importing it."
    ),
    "新闻内容包不是有效的 UTF-8 文本。": "The news package is not valid UTF-8 text.",
    "新闻内容包必须是 JSON 文本。": "The news package must be JSON text.",
    "请选择本机 JSON 内容包。": "Choose a local JSON package.",
    "所选内容包文件不存在。": "The selected package file does not exist.",
    "新闻数据仓储尚未就绪。": "The news data store is not ready.",
    "请先预览或载入一份有效的新闻刊期。": "Preview or load a valid news issue first.",
    "新闻链接无效：": "Invalid news link: ",
    "全局阅读设置": "Global reading settings",
    "稍后读会影响后续文章；它不会把当前文章收进本期剪报。": (
        "Read later applies to future articles; it will not add this article to the current issue's clippings."
    ),
    "草稿没有保存成功，请返回编辑。": "The draft could not be saved. Return to editing.",
    "没有可恢复的已保存草稿。": "There is no saved draft to restore.",
    "清理本机数据": "Clear local data",
    "示例清理只移除示例记录，不会删除你添加的内容；全部清空则会另行确认范围。": (
        "Clearing samples removes sample entries only; it will not delete content you added. Clearing everything requires separate confirmation of the scope."
    ),
    "清理示例数据…": "Clear sample data…",
    "有未保存的新闻预览": "Unsaved news preview",
    "当前预览“%1”还没有保存。关闭窗口会丢弃这次预览。": (
        "The current preview “%1” has not been saved. Closing the window will discard it."
    ),
    "当前新闻预览还没有保存；关闭窗口会丢弃这次预览。": (
        "The current news preview has not been saved. Closing the window will discard it."
    ),
    "你可以保存为本机草稿，或放弃这次预览后退出。": (
        "Save it as a local draft, or discard the preview and exit."
    ),
    "恢复上次已保存草稿": "Restore last saved draft",
    "保存并退出": "Save and exit",
    "放弃并退出": "Discard and exit",
}
