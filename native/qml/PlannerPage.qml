pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "plannerPage"
    property alias selectedDateText: dateField.text

    property var controller: null
    property var webdavController: null
    property var uiTheme: null
    readonly property var snapshot: controller ? (controller.state || ({})) : ({})
    readonly property var webdavState: webdavController ? (webdavController.state || ({})) : ({})
    readonly property var webdavConflicts: webdavController ? asList(webdavController.conflicts) : []
    readonly property var groups: asList(snapshot.groups)
    readonly property var allTasks: asList(valueOf(snapshot, "allRecords", valueOf(snapshot, "records", [])))
    readonly property var projects: asList(valueOf(snapshot, "projects", []))
    readonly property var tags: asList(valueOf(snapshot, "tags", []))
    readonly property var customBoards: asList(valueOf(snapshot, "customBoards", []))
    readonly property var customBoardOrders: valueOf(snapshot, "customBoardOrders", ({}))
    readonly property var standardBoardOrders: valueOf(snapshot, "boardOrders", ({}))
    readonly property string viewMode: String(valueOf(snapshot, "viewMode", "list"))
    readonly property var selectedCustomBoard: {
        if (!viewMode.startsWith("custom-board:"))
            return null
        var boardId = viewMode.substring("custom-board:".length)
        for (var index = 0; index < customBoards.length; ++index) {
            if (String(valueOf(customBoards[index], "id", "")) === boardId)
                return customBoards[index]
        }
        return null
    }
    readonly property var visibleTasks: flattenGroups()
    readonly property var statusOptions: [
        { value: "todo", label: qsTr("待办") },
        { value: "doing", label: qsTr("进行中") },
        { value: "done", label: qsTr("完成") }
    ]
    readonly property var weekDays: asList(snapshot.weekDays)
    readonly property var timeline: valueOf(snapshot, "timeline", ({}))
    readonly property var timelineBlocks: asList(valueOf(timeline, "blocks", []))
    readonly property var timelineEventBlocks: asList(valueOf(timeline, "eventBlocks", []))
    readonly property var unscheduledTasks: asList(valueOf(timeline, "unscheduled", []))
    readonly property bool hasTimelineContent: unscheduledTasks.length > 0
                                               || timelineBlocks.length > 0
                                               || timelineEventBlocks.length > 0
    readonly property string selectedDay: String(valueOf(snapshot, "selectedDate", todayKey()))
    readonly property var activeTracking: valueOf(snapshot, "activeTracking", ({}))
    readonly property string activeTrackingMode: String(valueOf(activeTracking, "mode", "stopwatch"))
    readonly property bool activeTrackingPaused: Boolean(valueOf(activeTracking, "paused", false))
    readonly property int timelineStartHour: Number(valueOf(timeline, "visibleStartHour", 7))
    readonly property int timelineEndHour: Number(valueOf(timeline, "visibleEndHour", 23))
    readonly property int pixelsPerHour: Number(valueOf(timeline, "pixelsPerHour", 60))
    property string notice: ""
    property bool noticeIsError: false
    property string formNotice: ""
    property string postCreateTaskId: ""
    property string postCreateTaskTitle: ""
    property string postCreateTaskDay: ""
    property int postCreateTaskEstimateMinutes: 30
    property string draftSaveStatus: "草稿自动保存"
    property string draftSaveError: ""
    property bool suppressDraft: false
    property bool advancedOptionsExpanded: false
    property string editingTaskId: ""
    property var pendingEditRecord: null
    property string selectedDeleteId: ""
    property string selectedDeleteTitle: ""
    property int selectedDeleteSubtaskCount: 0
    property string selectedParentId: ""
    property string selectedParentTitle: ""
    property string selectedOrganizationId: ""
    property string selectedOrganizationTitle: ""
    property string selectedCalendarSubscriptionId: ""
    property string selectedCalendarSubscriptionName: ""
    property string selectedCalDAVAccountId: ""
    property string selectedCalDAVAccountName: ""
    property string selectedWebDavClearName: ""
    property string selectedFocusTaskId: ""
    property string selectedFocusTaskTitle: ""
    property int procrastinationTipIndex: 0
    property string customBoardEditorId: ""
    property var customBoardEditorColumns: []
    readonly property var procrastinationTips: [
        qsTr("把任务缩小成一个两分钟内能完成的动作。"),
        qsTr("先准备好要用的文件或工具，只做开始前的一步。"),
        qsTr("给自己两分钟试做时间，之后再决定是否继续。"),
        qsTr("先移开一个干扰；如果已经很累，安排一次真正的休息。")
    ]
    property var timesheetReport: ({})

    readonly property color canvas: uiTheme ? uiTheme.canvas : "#f6f5f0"
    readonly property color sidebar: uiTheme ? uiTheme.sidebar : "#efede7"
    readonly property color surface: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color surfaceSoft: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color accent: uiTheme ? uiTheme.accent : "#456b73"
    readonly property color accentStrong: uiTheme ? uiTheme.accentStrong : "#315761"
    readonly property color accentSoft: uiTheme ? uiTheme.accentSoft : "#e6efee"
    readonly property color brand: uiTheme ? uiTheme.brand : "#9f4137"
    readonly property color brandSoft: uiTheme ? uiTheme.brandSoft : "#f7eae5"
    readonly property color success: uiTheme ? uiTheme.success : "#3d654e"
    readonly property color successSoft: uiTheme ? uiTheme.successSoft : "#eaf2ec"
    readonly property color warning: uiTheme ? uiTheme.warning : "#80531b"
    readonly property color warningSoft: uiTheme ? uiTheme.warningSoft : "#f6efe2"
    readonly property color danger: uiTheme ? uiTheme.danger : "#9d4038"
    readonly property color dangerSoft: uiTheme ? uiTheme.dangerSoft : "#f8eae7"
    readonly property color blue: accent
    readonly property color red: danger
    readonly property color paper: canvas
    readonly property color white: surface
    readonly property string sansFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property string serifFamily: uiTheme ? uiTheme.serifFamily : "Noto Serif SC"
    readonly property string fontFamily: sansFamily

    function asList(value) {
        return UiPageUtils.asList(value, true)
    }

    function valueOf(object, key, fallback) {
        return UiPageUtils.valueOf(object, key, fallback)
    }

    function taskSourceCancelled(record) {
        return Boolean(valueOf(taskData(record).externalTodo, "cancelled", false))
    }

    function flattenGroups() {
        var rows = []
        for (var i = 0; i < groups.length; ++i) {
            var groupRows = asList(valueOf(groups[i], "records", []))
            for (var j = 0; j < groupRows.length; ++j)
                rows.push(groupRows[j])
        }
        return rows
    }

    function taskStatus(record) {
        var data = taskData(record)
        var status = String(valueOf(data, "status", Boolean(data.done) ? "done" : "todo"))
        return status === "todo" || status === "doing" || status === "done"
                ? status : (Boolean(data.done) ? "done" : "todo")
    }

    function customBoardLaneTasks(column) {
        var columnStatus = String(valueOf(column, "status", "todo"))
        var rows = visibleTasks.filter(function(row) {
            return page.taskStatus(row) === columnStatus && page.taskHasTag(row, column.tag)
        })
        var boardId = String(valueOf(selectedCustomBoard, "id", ""))
        var boardOrders = valueOf(customBoardOrders, boardId, ({}))
        var savedOrder = asList(valueOf(boardOrders, String(valueOf(column, "id", "")), []))
        if (!savedOrder.length)
            return rows
        var ranks = Object.create(null)
        for (var orderIndex = 0; orderIndex < savedOrder.length; ++orderIndex)
            ranks[String(savedOrder[orderIndex])] = orderIndex
        return rows.map(function(row, rowIndex) {
            var id = page.taskId(row)
            var hasRank = ranks[id] !== undefined
            return { record: row, fallback: rowIndex, rank: hasRank ? ranks[id] : savedOrder.length + rowIndex }
        }).sort(function(left, right) {
            if (left.rank !== right.rank)
                return left.rank - right.rank
            return left.fallback - right.fallback
        }).map(function(entry) { return entry.record })
    }

    function standardBoardLaneTasks(status) {
        var rows = visibleTasks.filter(function(row) { return page.taskStatus(row) === status })
        var savedOrder = asList(valueOf(standardBoardOrders, status, []))
        if (!savedOrder.length)
            return rows
        var ranks = Object.create(null)
        for (var orderIndex = 0; orderIndex < savedOrder.length; ++orderIndex)
            ranks[String(savedOrder[orderIndex])] = orderIndex
        return rows.map(function(row, rowIndex) {
            var id = page.taskId(row)
            var hasRank = ranks[id] !== undefined
            return { record: row, fallback: rowIndex, rank: hasRank ? ranks[id] : savedOrder.length + rowIndex }
        }).sort(function(left, right) {
            if (left.rank !== right.rank)
                return left.rank - right.rank
            return left.fallback - right.fallback
        }).map(function(entry) { return entry.record })
    }

    function moveTaskOnStandardBoard(recordId, status, beforeTaskId) {
        if (!controller || !controller.moveTaskOnStandardBoard)
            return showResult(null, qsTr("标准看板排序暂不可用。"))
        return showResult(controller.moveTaskOnStandardBoard(
                              String(recordId || ""), String(status || "todo"),
                              String(beforeTaskId || "")), qsTr("看板顺序已更新。"))
    }

    function draggedStandardBoardTaskId(source) {
        if (!source)
            return ""
        var sourceId = String(source["standardBoardTaskId"] || "")
        if (sourceId)
            return sourceId
        if (source.getDataAsString)
            return String(source.getDataAsString("application/x-wanxiang-standard-board-task") || "")
        return ""
    }

    function taskIsImportant(record) {
        return String(valueOf(taskData(record), "priority", "normal")) === "high"
    }

    function taskIsUrgent(record) {
        var data = taskData(record)
        var dueDay = String(valueOf(data, "plannedDate", "") || valueOf(record, "date", ""))
        return !Boolean(data.done) && dueDay !== "" && dueDay <= selectedDay
    }

    function setTaskStatus(record, status) {
        if (!controller || !controller.setTaskStatus)
            return showResult(null, qsTr("任务状态暂不可修改。"))
        var label = status === "todo" ? qsTr("待办") : (status === "doing" ? qsTr("进行中") : qsTr("已完成"))
        return showResult(controller.setTaskStatus(taskId(record), status), qsTr("状态已更新为 %1。").arg(label))
    }

    function resolveCalDAVTaskConflict(record, choice) {
        if (!controller || !controller.resolveCalDAVTaskConflict)
            return showResult(null, qsTr("CalDAV 冲突处理暂不可用。"))
        var message = choice === "remote"
                ? qsTr("已采用服务器上的完成状态。")
                : qsTr("已保留本机完成状态；下次同步时推送到服务器。")
        return showResult(controller.resolveCalDAVTaskConflict(taskId(record), choice), message)
    }

    function setPlannerView(mode) {
        if (!controller || !controller.setViewMode)
            return showResult(null, qsTr("视图暂不可切换。"))
        return showResult(controller.setViewMode(mode), qsTr("视图已切换。"))
    }

    function openCustomBoardEditor(board) {
        if (board) {
            customBoardEditorId = String(valueOf(board, "id", ""))
            customBoardNameField.text = String(valueOf(board, "name", ""))
            customBoardEditorColumns = JSON.parse(JSON.stringify(asList(valueOf(board, "columns", []))))
        } else {
            customBoardEditorId = ""
            customBoardNameField.text = ""
            customBoardEditorColumns = [
                { id: "", title: qsTr("待办"), status: "todo", tag: "" },
                { id: "", title: qsTr("进行中"), status: "doing", tag: "" },
                { id: "", title: qsTr("完成"), status: "done", tag: "" }
            ]
        }
        customBoardDialog.open()
    }

    function updateCustomBoardColumn(index, key, value) {
        var columns = JSON.parse(JSON.stringify(customBoardEditorColumns))
        if (index < 0 || index >= columns.length)
            return
        columns[index][key] = value
        customBoardEditorColumns = columns
    }

    function addCustomBoardColumn() {
        if (customBoardEditorColumns.length >= 8)
            return
        var columns = JSON.parse(JSON.stringify(customBoardEditorColumns))
        columns.push({ id: "", title: qsTr("新列 %1").arg(columns.length + 1), status: "todo", tag: "" })
        customBoardEditorColumns = columns
    }

    function removeCustomBoardColumn(index) {
        if (customBoardEditorColumns.length <= 2)
            return
        var columns = JSON.parse(JSON.stringify(customBoardEditorColumns))
        columns.splice(index, 1)
        customBoardEditorColumns = columns
    }

    function saveCustomBoard() {
        if (!controller || !controller.saveCustomBoard)
            return showResult(null, qsTr("自定义看板服务暂不可用。"))
        var result = controller.saveCustomBoard({
            id: customBoardEditorId,
            name: customBoardNameField.text,
            columns: customBoardEditorColumns
        })
        if (!showResult(result, qsTr("自定义看板已保存。")))
            return false
        customBoardDialog.close()
        var savedId = customBoardEditorId
        if (!savedId && customBoards.length > 0)
            savedId = String(valueOf(customBoards[customBoards.length - 1], "id", ""))
        if (savedId)
            setPlannerView("custom-board:" + savedId)
        else
            Qt.callLater(function() {
                var savedBoards = page.customBoards
                if (savedBoards.length > 0)
                    page.setPlannerView("custom-board:" + String(page.valueOf(savedBoards[savedBoards.length - 1], "id", "")))
            })
        return true
    }

    function deleteCustomBoard() {
        if (!controller || !controller.deleteCustomBoard)
            return showResult(null, qsTr("自定义看板服务暂不可用。"))
        var result = controller.deleteCustomBoard(customBoardEditorId)
        if (!showResult(result, qsTr("自定义看板已删除。")))
            return false
        customBoardDeleteDialog.close()
        customBoardDialog.close()
        return true
    }

    function moveTaskToBoardColumn(recordId, column, boardId, columnId, beforeTaskId) {
        if (!controller || !controller.moveTaskToBoardColumn)
            return showResult(null, qsTr("自定义看板服务暂不可用。"))
        return showResult(controller.moveTaskToBoardColumn(
                              recordId,
                              String(valueOf(column, "status", "todo")),
                              String(valueOf(column, "tag", "")),
                              String(boardId || ""),
                              String(columnId || ""),
                              String(beforeTaskId || "")), qsTr("待办已移入此列并排至末尾。"))
    }

    function draggedCustomBoardTaskId(source) {
        return source ? String(source["boardTaskId"] || "") : ""
    }

    function taskHasTag(record, tag) {
        if (!tag)
            return true
        var wanted = String(tag).toLocaleLowerCase()
        return asList(valueOf(taskData(record), "tags", [])).some(function(item) {
            return String(item).toLocaleLowerCase() === wanted
        })
    }

    function setTaskFilters(project, tag) {
        if (!controller || !controller.setTaskFilters)
            return showResult(null, qsTr("筛选暂不可用。"))
        return showResult(controller.setTaskFilters(project, tag), qsTr("项目和标签筛选已更新。"))
    }

    function editOrganization(record) {
        selectedOrganizationId = taskId(record)
        selectedOrganizationTitle = String(valueOf(taskData(record), "title", qsTr("未命名待办")))
        organizationProjectField.text = String(valueOf(taskData(record), "project", ""))
        organizationTagsField.text = asList(valueOf(taskData(record), "tags", [])).join(", ")
        organizationDialog.open()
        Qt.callLater(function() { organizationProjectField.forceActiveFocus() })
    }

    function confirmOrganization() {
        if (!controller || !controller.setTaskOrganization)
            return
        var result = controller.setTaskOrganization(
                    selectedOrganizationId, organizationProjectField.text.trim(), organizationTagsField.text)
        if (showResult(result, qsTr("项目和标签已保存。"))) {
            organizationDialog.close()
            selectedOrganizationId = ""
            selectedOrganizationTitle = ""
        }
    }

    function todayKey() {
        return String(valueOf(snapshot, "today", localDateKey()))
    }

    function localDateKey() {
        return UiPageUtils.localDateKey()
    }

    function pad2(value) { return value < 10 ? "0" + value : String(value) }

    function taskData(record) { return valueOf(record, "data", ({})) }
    function taskId(record) { return String(valueOf(record, "id", "")) }
    function taskContext(data) {
        var parts = []
        var project = String(valueOf(data, "project", "")).trim()
        var tags = asList(valueOf(data, "tags", []))
                .filter(function(tag) { return typeof tag === "string" && tag.trim() !== "" })
        if (project)
            parts.push(project)
        if (tags.length)
            parts.push(tags.map(function(tag) { return "#" + tag.trim() }).join(" "))
        return parts.join(" · ")
    }

    function advancedOptionsLabels() {
        var labels = []
        if (String(projectField.text || "").trim())
            labels.push(qsTr("项目"))
        if (String(tagsField.text || "").trim())
            labels.push(qsTr("标签"))
        if (Number(estimateBox.currentValue) !== 30)
            labels.push(qsTr("预估"))
        if (String(repeatBox.currentValue || "none") !== "none")
            labels.push(qsTr("重复"))
        if (String(noteField.text || "").trim())
            labels.push(qsTr("备注"))
        if (remindBox.checked)
            labels.push(qsTr("提醒"))
        return labels
    }

    function advancedOptionsSummary() {
        return advancedOptionsLabels().join("、")
    }
    function subtasksOf(recordId) {
        return asList(valueOf(snapshot, "allRecords", valueOf(snapshot, "records", [])))
                .filter(function(record) {
                    return String(valueOf(taskData(record), "parentTaskId", "")) === String(recordId)
                })
    }
    function subtaskProgress(record) {
        var children = subtasksOf(taskId(record))
        if (!children.length)
            return ""
        var done = children.filter(function(child) { return Boolean(taskData(child).done) }).length
        return qsTr("子任务 %1/%2").arg(done).arg(children.length)
    }
    function taskIsTracked(record) { return String(valueOf(activeTracking, "taskId", "")) === taskId(record) }
    function formatMinutes(value) {
        var minutes = Math.max(0, Number(value) || 0)
        if (minutes >= 60) {
            var hours = Math.floor(minutes / 60)
            return minutes % 60
                    ? qsTr("%1 小时 %2 分").arg(hours).arg(minutes % 60)
                    : qsTr("%1 小时").arg(hours)
        }
        return qsTr("%1 分钟").arg(minutes)
    }
    function formatElapsed(value) {
        var seconds = Math.max(0, Number(value) || 0)
        var hours = Math.floor(seconds / 3600)
        var minutes = Math.floor((seconds % 3600) / 60)
        return hours > 0 ? hours + ":" + pad2(minutes) : qsTr("%1 分").arg(minutes)
    }
    function formatClock(value) {
        var seconds = Math.max(0, Number(value) || 0)
        return pad2(Math.floor(seconds / 60)) + ":" + pad2(seconds % 60)
    }
    function formatVariance(value) {
        var seconds = Number(value) || 0
        return (seconds > 0 ? "+" : seconds < 0 ? "−" : "") + formatElapsed(Math.abs(seconds))
    }
    function shiftDate(value, days) {
        var parts = String(value).split("-")
        if (parts.length !== 3)
            return todayKey()
        var shifted = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]) + days, 12)
        return String(shifted.getFullYear()) + "-" + pad2(shifted.getMonth() + 1) + "-" + pad2(shifted.getDate())
    }
    function activeTrackingTitle() {
        var id = String(valueOf(activeTracking, "taskId", ""))
        for (var i = 0; i < allTasks.length; ++i) {
            if (taskId(allTasks[i]) === id)
                return String(valueOf(taskData(allTasks[i]), "title", qsTr("未命名待办")))
        }
        return qsTr("这件待办")
    }
    function activeTrackingSummary() {
        var elapsed = Number(valueOf(activeTracking, "elapsedSeconds", 0))
        var remaining = Number(valueOf(activeTracking, "remainingSeconds", 0))
        if (activeTrackingMode === "stopwatch")
            return qsTr("任务计时 · 已记录 %1").arg(formatElapsed(elapsed))
        if (activeTrackingMode === "flowtime")
            return qsTr("Flowtime · 已专注 %1").arg(formatElapsed(elapsed))
        var label = activeTrackingMode === "pomodoro" ? qsTr("番茄钟") : qsTr("倒计时")
        var time = qsTr(" · 剩余 %1").arg(formatClock(remaining))
        return label + (activeTrackingPaused ? qsTr(" · 已暂停") : "") + time
    }
    function selectDay(day) {
        if (controller && controller.setSelectedDay)
            showResult(controller.setSelectedDay(day), "已切换日计划。")
    }
    function selectDayAndFocus(day) {
        selectDay(day)
        Qt.callLater(function() {
            for (var index = 0; index < weekDaysRepeater.count; ++index) {
                var item = weekDaysRepeater.itemAt(index)
                if (item && String(page.weekDays[index].date) === String(day)) {
                    item.forceActiveFocus()
                    return
                }
            }
        })
    }
    function moveSelectedWeek(delta) {
        var parts = selectedDay.split("-")
        if (parts.length !== 3)
            return
        var day = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]) + delta * 7, 12)
        selectDay(String(day.getFullYear()) + "-" + pad2(day.getMonth() + 1) + "-" + pad2(day.getDate()))
    }
    function timelineTimeAt(y, duration) {
        var minutes = timelineStartHour * 60 + Math.max(0, Number(y) || 0) * 60 / pixelsPerHour
        var first = timelineStartHour * 60
        var last = timelineEndHour * 60 - Math.min(Math.max(5, Number(duration) || 30),
                                                   (timelineEndHour - timelineStartHour) * 60)
        last = Math.max(first, Math.floor(last / 15) * 15)
        minutes = Math.max(first, Math.min(last, Math.round(minutes / 15) * 15))
        return pad2(Math.floor(minutes / 60)) + ":" + pad2(minutes % 60)
    }
    function suggestStartTime(duration) {
        var minutesNeeded = Math.max(15, Number(duration) || 30)
        for (var candidate = 9 * 60; candidate + minutesNeeded <= timelineEndHour * 60; candidate += 15) {
            var available = true
            for (var i = 0; i < timelineBlocks.length; ++i) {
                var block = timelineBlocks[i]
                if (candidate < Number(block.endMinute) && candidate + minutesNeeded > Number(block.startMinute)) {
                    available = false
                    break
                }
            }
            for (var j = 0; available && j < timelineEventBlocks.length; ++j) {
                var eventBlock = timelineEventBlocks[j]
                if (candidate < Number(eventBlock.endMinute) && candidate + minutesNeeded > Number(eventBlock.startMinute)) {
                    available = false
                }
            }
            if (available)
                return pad2(Math.floor(candidate / 60)) + ":" + pad2(candidate % 60)
        }
        return ""
    }
    function selectedClockMinutes() {
        var parts = String(valueOf(snapshot, "localTime", "00:00")).split(":")
        return parts.length === 2 ? Number(parts[0]) * 60 + Number(parts[1]) : 0
    }
    function scheduleTask(recordId, day, start, duration) {
        if (!controller || !controller.scheduleTask)
            return showResult(null, "日程控制器尚未连接。")
        var result = controller.scheduleTask(recordId, day, start, duration)
        return showResult(result, qsTr("已安排到 %1。").arg(start))
    }
    function dropTask(drop) {
        var source = drop ? drop.source : null
        if (!source || !source.dragTaskId)
            return
        var duration = Number(source.dragEstimateMinutes) || 30
        scheduleTask(String(source.dragTaskId), selectedDay, timelineTimeAt(drop.y, duration), duration)
    }
    function toggleTracking(record) {
        if (!controller)
            return
        var wasTracking = taskIsTracked(record)
        if (wasTracking && activeTrackingMode !== "stopwatch") {
            var paused = activeTrackingPaused
                    ? controller.resumeTrackingTask()
                    : controller.pauseTrackingTask()
            showResult(paused, activeTrackingPaused ? qsTr("已继续专注。") : qsTr("专注已暂停。"))
            return
        }
        var result = wasTracking ? controller.stopTrackingTask() : controller.startTrackingTask(taskId(record))
        showResult(result, wasTracking ? qsTr("已结束计时。"): qsTr("已开始记录实际用时。"))
    }
    function openFocusDialog(record) {
        selectedFocusTaskId = taskId(record)
        selectedFocusTaskTitle = String(valueOf(taskData(record), "title", qsTr("未命名待办")))
        focusModeBox.currentIndex = 0
        focusDurationBox.value = Math.max(5, Math.min(480, Number(valueOf(taskData(record), "estimateMinutes", 25)) || 25))
        focusDialog.open()
    }
    function openProcrastinationHelp() {
        procrastinationHelpDialog.open()
    }
    function nextProcrastinationTip() {
        procrastinationTipIndex = (procrastinationTipIndex + 1) % procrastinationTips.length
    }
    function confirmFocusSession() {
        if (!controller || !controller.startFocusTask)
            return showResult(null, qsTr("专注计时暂不可用。"))
        var mode = ["pomodoro", "flowtime", "countdown"][focusModeBox.currentIndex] || "pomodoro"
        var result = controller.startFocusTask(selectedFocusTaskId, mode, focusDurationBox.value)
        var success = mode === "pomodoro" ? qsTr("番茄钟已开始。")
                    : mode === "flowtime" ? qsTr("Flowtime 专注已开始。") : qsTr("倒计时已开始。")
        if (showResult(result, success)) {
            focusDialog.close()
            selectedFocusTaskId = ""
            selectedFocusTaskTitle = ""
        }
    }
    function pauseResumeActiveTracking() {
        if (!controller)
            return
        var result = activeTrackingPaused ? controller.resumeTrackingTask() : controller.pauseTrackingTask()
        showResult(result, activeTrackingPaused ? qsTr("计时已继续。") : qsTr("计时已暂停。"))
    }
    function focusTaskEntry() {
        scroll.contentY = 0
        Qt.callLater(function() { titleField.forceActiveFocus() })
    }
    function stopActiveTracking() {
        if (controller)
            showResult(controller.stopTrackingTask(), qsTr("计时结果已保存。"))
    }
    function openTimesheet() {
        timesheetEndField.text = selectedDay
        timesheetStartField.text = shiftDate(selectedDay, -6)
        timesheetDialog.open()
        loadTimesheet()
    }
    function loadTimesheet() {
        if (!controller || !controller.getTimesheet)
            return showResult(null, qsTr("工时复盘暂不可用。"))
        var result = controller.getTimesheet(timesheetStartField.text.trim(), timesheetEndField.text.trim())
        if (!result || result.ok !== true) {
            notice = String(valueOf(result, "error", qsTr("工时复盘暂不可用。")))
            noticeIsError = true
            return false
        }
        timesheetReport = valueOf(result, "data", ({}))
        notice = ""
        noticeIsError = false
        return true
    }
    function exportTimesheet() {
        timesheetExportDialog.open()
    }
    function importCalendar(fileUrl) {
        if (!controller || !controller.importCalendarIcs)
            return showResult(null, qsTr("日历导入暂不可用。"))
        var result = controller.importCalendarIcs(fileUrl)
        var imported = valueOf(result, "data", ({}))
        var success = qsTr("日历已导入：新增 %1，更新 %2，未变 %3。")
                .arg(Number(valueOf(imported, "added", 0)))
                .arg(Number(valueOf(imported, "updated", 0)))
                .arg(Number(valueOf(imported, "unchanged", 0)))
        var tasks = valueOf(imported, "tasks", ({}))
        if (Number(valueOf(tasks, "total", 0)) > 0)
            success += " " + qsTr("另导入外部待办：新增 %1，更新 %2，未变 %3。")
                    .arg(Number(valueOf(tasks, "added", 0)))
                    .arg(Number(valueOf(tasks, "updated", 0)))
                    .arg(Number(valueOf(tasks, "unchanged", 0)))
        if (Number(valueOf(tasks, "cancelled", 0)) > 0)
            success += " " + qsTr("来源标记已取消：%1 项。")
                    .arg(Number(valueOf(tasks, "cancelled", 0)))
        return showResult(result, success)
    }
    function openCalendarImport() {
        calendarImportDialog.open()
    }
    function openCalendarSubscriptions() {
        calendarSubscriptionNameField.text = ""
        calendarSubscriptionUrlField.text = ""
        calendarSubscriptionsDialog.open()
    }
    function openCalDAVAccounts() {
        caldavAccountNameField.text = ""
        caldavAccountUrlField.text = ""
        caldavAccountUsernameField.text = ""
        caldavAccountPasswordField.text = ""
        caldavAccountsDialog.open()
    }
    function openWebDavPlannerSync() {
        webdavUrlField.text = ""
        webdavUsernameField.text = ""
        webdavPasswordField.text = ""
        webdavPassphraseField.text = ""
        webdavPlannerDialog.open()
    }
    function configureWebDavPlannerSync() {
        if (!webdavController || !webdavController.configure)
            return showResult(null, qsTr("WebDAV 日程同步暂不可用。"))
        var result = webdavController.configure(
                    webdavUrlField.text.trim(), webdavUsernameField.text,
                    webdavPasswordField.text, webdavPassphraseField.text)
        if (!showResult(result, qsTr("同步设置已保存，正在连接 WebDAV。")))
            return false
        webdavPasswordField.text = ""
        webdavPassphraseField.text = ""
        return true
    }
    function syncWebDavPlannerNow() {
        if (!webdavController || !webdavController.syncNow)
            return showResult(null, qsTr("WebDAV 日程同步暂不可用。"))
        return showResult(webdavController.syncNow(), qsTr("已开始同步日程。"))
    }
    function requestClearWebDavPlannerAccount() {
        selectedWebDavClearName = String(valueOf(webdavState, "host", "WebDAV"))
        webdavClearAccountDialog.open()
    }
    function confirmClearWebDavPlannerAccount() {
        if (!webdavController || !webdavController.clearAccount)
            return showResult(null, qsTr("WebDAV 日程同步暂不可用。"))
        var result = webdavController.clearAccount()
        if (showResult(result, qsTr("本机 WebDAV 登录设置已移除；日程和云端文件均保留。")))
            webdavClearAccountDialog.close()
        return result
    }
    function resolveWebDavPlannerConflict(conflict, variantIndex, keepBoth) {
        if (!webdavController || !webdavController.resolveConflict)
            return showResult(null, qsTr("WebDAV 冲突选择暂不可用。"))
        var taskId = String(valueOf(conflict, "id", ""))
        var message = keepBoth
                ? qsTr("已保存冲突选择和并发副本，准备同步。")
                : qsTr("已采用所选日程分支，准备同步。")
        return showResult(webdavController.resolveConflict(taskId, variantIndex, keepBoth), message)
    }
    function webDavConflictTitle(conflict) {
        var variants = asList(valueOf(conflict, "variants", []))
        for (var i = 0; i < variants.length; ++i) {
            if (!Boolean(valueOf(variants[i], "deleted", false))) {
                var record = valueOf(variants[i], "record", ({}))
                return String(valueOf(valueOf(record, "data", ({})), "title", qsTr("未命名任务")))
            }
        }
        return qsTr("已删除的日程")
    }
    function addCalDAVAccount() {
        if (!controller || !controller.addCalDAVAccount)
            return showResult(null, qsTr("CalDAV 账户暂不可用。"))
        var result = controller.addCalDAVAccount(
                    caldavAccountNameField.text.trim(),
                    caldavAccountUrlField.text.trim(),
                    caldavAccountUsernameField.text,
                    caldavAccountPasswordField.text)
        if (!showResult(result, qsTr("账户已保存，正在检查日历集。")))
            return false
        caldavAccountNameField.text = ""
        caldavAccountUrlField.text = ""
        caldavAccountUsernameField.text = ""
        caldavAccountPasswordField.text = ""
        return true
    }
    function checkCalDAVAccount(accountId) {
        if (!controller || !controller.checkCalDAVAccount)
            return showResult(null, qsTr("CalDAV 账户暂不可用。"))
        return showResult(controller.checkCalDAVAccount(accountId), qsTr("正在检查 CalDAV 日历集。"))
    }
    function syncCalDAVCalendar(accountId) {
        if (!controller || !controller.syncCalDAVTasks)
            return showResult(null, qsTr("CalDAV 账户暂不可用。"))
        return showResult(controller.syncCalDAVTasks(accountId), qsTr("正在同步 CalDAV 日历内容。"))
    }
    function caldavAccountHasSyncableContent(account) {
        var calendars = asList(valueOf(account, "calendars", []))
        for (var i = 0; i < calendars.length; ++i) {
            var components = asList(valueOf(calendars[i], "components", []))
            if (components.indexOf("VEVENT") >= 0 || components.indexOf("VTODO") >= 0)
                return true
        }
        return false
    }
    function caldavAccountStatus(account) {
        if (Boolean(valueOf(account, "checking", false)))
            return qsTr("正在检查…")
        if (Boolean(valueOf(account, "syncing", false)))
            return qsTr("正在同步日历内容…")
        var syncError = String(valueOf(account, "lastSyncError", ""))
        if (syncError)
            return syncError
        var error = String(valueOf(account, "lastError", ""))
        if (error)
            return error
        var calendars = asList(valueOf(account, "calendars", []))
        if (!calendars.length)
            return qsTr("尚未成功检查")
        var components = []
        for (var i = 0; i < calendars.length; ++i) {
            var supported = asList(valueOf(calendars[i], "components", []))
            if (supported.indexOf("VEVENT") >= 0 && components.indexOf(qsTr("日历事件")) < 0)
                components.push(qsTr("日历事件"))
            if (supported.indexOf("VTODO") >= 0 && components.indexOf(qsTr("待办任务")) < 0)
                components.push(qsTr("待办任务"))
        }
        var status = qsTr("连接成功，可读取：%1").arg(components.join("、") || qsTr("日历集"))
        var lastSync = String(valueOf(account, "lastSyncSuccessAt", ""))
        if (lastSync)
            status += " · " + qsTr("最近同步：%1").arg(lastSync)
        else if (String(valueOf(account, "lastSyncAt", "")))
            status += " · " + qsTr("尚未成功同步")
        return status
    }
    function requestRemoveCalDAVAccount(accountId, accountName) {
        selectedCalDAVAccountId = String(accountId || "")
        selectedCalDAVAccountName = String(accountName || "CalDAV")
        caldavAccountRemoveDialog.open()
    }
    function removeCalDAVAccount(accountId) {
        if (!controller || !controller.removeCalDAVAccount)
            return null
        return controller.removeCalDAVAccount(accountId)
    }
    function confirmRemoveCalDAVAccount() {
        var result = removeCalDAVAccount(selectedCalDAVAccountId)
        if (showResult(result, qsTr("CalDAV 账户和本机同步内容已移除。")))
            caldavAccountRemoveDialog.close()
        return result
    }
    function addCalendarSubscription() {
        if (!controller || !controller.addCalendarSubscription)
            return showResult(null, qsTr("日历订阅暂不可用。"))
        var result = controller.addCalendarSubscription(
                    calendarSubscriptionNameField.text.trim(),
                    calendarSubscriptionUrlField.text.trim())
        if (!showResult(result, result && result.refreshStarted
                        ? qsTr("订阅已保存，正在首次同步。")
                        : qsTr("订阅已保存；请查看同步状态。")))
            return false
        calendarSubscriptionNameField.text = ""
        calendarSubscriptionUrlField.text = ""
        return true
    }
    function refreshCalendarSubscription(subscriptionId) {
        if (!controller || !controller.refreshCalendarSubscription)
            return showResult(null, qsTr("日历订阅暂不可用。"))
        return showResult(controller.refreshCalendarSubscription(subscriptionId), qsTr("已开始刷新日历订阅。"))
    }
    function refreshAllCalendarSubscriptions() {
        if (!controller || !controller.refreshAllCalendarSubscriptions)
            return showResult(null, qsTr("日历订阅暂不可用。"))
        return showResult(controller.refreshAllCalendarSubscriptions(), qsTr("已开始刷新全部日历订阅。"))
    }
    function confirmRemoveCalendarSubscription() {
        if (!controller || !controller.removeCalendarSubscription)
            return showResult(null, qsTr("日历订阅暂不可用。"))
        var result = controller.removeCalendarSubscription(selectedCalendarSubscriptionId)
        if (showResult(result, qsTr("订阅和它同步的日程已删除；手动导入的日程不受影响。")))
            removeCalendarSubscriptionDialog.close()
        return result
    }
    function openCalendarExport() {
        calendarExportDialog.open()
    }
    function adjustEstimate(record, delta) {
        var data = taskData(record)
        var current = Number(valueOf(data, "estimateMinutes", 30)) || 30
        var next = Math.max(5, Math.min(480, current + delta))
        var start = String(valueOf(data, "plannedStart", "") || valueOf(record, "start", ""))
        var day = String(valueOf(data, "plannedDate", "") || selectedDay)
        if (start)
            return scheduleTask(taskId(record), day, start, next)
        if (controller && controller.setEstimate)
            return showResult(controller.setEstimate(taskId(record), next), "已调整预计用时。")
        return false
    }
    function changeDuration(record, delta) {
        return adjustEstimate(record, delta)
    }
    function isOverdue(record) {
        return !taskData(record).done && String(valueOf(record, "date", "")) < todayKey()
    }

    function dateHeading(value) {
        var parts = String(value).split("-")
        if (parts.length !== 3)
            return value ? qsTr(String(value)) : qsTr("未标日期")
        var parsed = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12)
        if (isNaN(parsed.getTime()))
            return String(value)
        var weekdays = [qsTr("周日"), qsTr("周一"), qsTr("周二"), qsTr("周三"), qsTr("周四"), qsTr("周五"), qsTr("周六")]
        var today = value === todayKey() ? qsTr(" · 今天") : ""
        return qsTr("%1 月 %2 日 · %3%4").arg(Number(parts[1])).arg(Number(parts[2]))
                .arg(weekdays[parsed.getDay()]).arg(today)
    }

    function weekDayLabel(value) {
        var labels = {
            "一": qsTr("周一"),
            "二": qsTr("周二"),
            "三": qsTr("周三"),
            "四": qsTr("周四"),
            "五": qsTr("周五"),
            "六": qsTr("周六"),
            "日": qsTr("周日")
        }
        return labels[String(value)] || String(value)
    }

    function calendarCells(year, month) {
        var first = new Date(year, month, 1, 12)
        var start = new Date(year, month, 1 - first.getDay(), 12)
        var cells = []
        for (var i = 0; i < 42; ++i) {
            var day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i, 12)
            cells.push({
                key: String(day.getFullYear()) + "-" + pad2(day.getMonth() + 1) + "-" + pad2(day.getDate()),
                day: day.getDate(),
                inMonth: day.getMonth() === month,
                today: day.getFullYear() === new Date().getFullYear() && day.getMonth() === new Date().getMonth() && day.getDate() === new Date().getDate()
            })
        }
        return cells
    }

    function showResult(result, successText) {
        if (result && typeof result === "object" && result.ok === false) {
            notice = String(result.error || "操作未完成，请检查后重试。")
            noticeIsError = true
            return false
        }
        if (result === false || result === null || result === undefined) {
            notice = "操作未完成，请检查后重试。"
            noticeIsError = true
            return false
        }
        notice = successText || "已保存。"
        noticeIsError = false
        return true
    }

    function clearPostCreateAction() {
        postCreateTaskId = ""
        postCreateTaskTitle = ""
        postCreateTaskDay = ""
        postCreateTaskEstimateMinutes = 30
    }

    function preparePostCreateAction(title, day, estimateMinutes) {
        // The bridge returns only {ok: true} for writes. Wait for its stateChanged
        // refresh, then identify the just-created unscheduled task from the
        // effective state so the next action remains tied to the real record.
        Qt.callLater(function() {
            var candidates = allTasks.filter(function(record) {
                var data = taskData(record)
                return String(valueOf(data, "title", "")) === String(title)
                        && String(valueOf(record, "date", "")) === String(day)
                        && !String(valueOf(data, "plannedStart", ""))
                        && !Boolean(valueOf(data, "done", false))
            })
            if (!candidates.length)
                return
            candidates.sort(function(left, right) {
                return Number(valueOf(right, "createdAt", 0)) - Number(valueOf(left, "createdAt", 0))
            })
            var record = candidates[0]
            postCreateTaskId = taskId(record)
            postCreateTaskTitle = String(title)
            postCreateTaskDay = String(day)
            postCreateTaskEstimateMinutes = Math.max(5, Number(estimateMinutes) || 30)
        })
    }

    function schedulePostCreateTask() {
        if (!postCreateTaskId)
            return false
        if (postCreateTaskDay !== selectedDay) {
            if (controller && controller.setSelectedDay)
                controller.setSelectedDay(postCreateTaskDay)
            notice = qsTr("已切换到 %1，请在“待安排”里确认时间。").arg(dateHeading(postCreateTaskDay))
            noticeIsError = false
            clearPostCreateAction()
            return true
        }
        var start = suggestStartTime(postCreateTaskEstimateMinutes)
        if (!start) {
            notice = qsTr("今天暂时找不到完整空档，请从“待安排”里拖动或选择时间。")
            noticeIsError = true
            return false
        }
        if (scheduleTask(postCreateTaskId, postCreateTaskDay, start, postCreateTaskEstimateMinutes)) {
            clearPostCreateAction()
            return true
        }
        return false
    }

    function restoreDraft() {
        var draft = valueOf(snapshot, "draft", ({}))
        suppressDraft = true
        titleField.text = String(valueOf(draft, "title", ""))
        dateField.text = String(valueOf(draft, "date", todayKey()))
        timeField.text = String(valueOf(draft, "time", ""))
        listBox.currentIndex = Math.max(0, listBox.model.indexOf(String(valueOf(draft, "list", "生活"))))
        projectField.text = String(valueOf(draft, "project", ""))
        tagsField.text = String(valueOf(draft, "tags", ""))
        var draftPriority = String(valueOf(draft, "priority", "normal"))
        priorityBox.currentIndex = draftPriority === "high" ? 1 : (draftPriority === "low" ? 2 : 0)
        noteField.text = String(valueOf(draft, "note", ""))
        remindBox.checked = Boolean(valueOf(draft, "remind", false))
        estimateBox.currentIndex = Math.max(0, estimateBox.indexOfValue(Number(valueOf(draft, "estimateMinutes", 30))))
        repeatBox.currentIndex = Math.max(0, repeatBox.indexOfValue(String(valueOf(draft, "repeat", "none"))))
        advancedOptionsExpanded = Boolean(
                    projectField.text || tagsField.text || noteField.text || remindBox.checked
                    || draftPriority !== "normal"
                    || Number(valueOf(draft, "estimateMinutes", 30)) !== 30
                    || String(valueOf(draft, "repeat", "none")) !== "none")
        suppressDraft = false
    }

    function editTask(record) {
        if (!record || Boolean(valueOf(record, "sample", false)))
            return showResult(null, qsTr("样例待办不能编辑。"))
        var externalTodo = valueOf(taskData(record), "externalTodo", ({}))
        if (Boolean(valueOf(externalTodo, "cancelled", false)))
            return showResult(null, qsTr("来源已取消的待办不能编辑。"))
        if (!editingTaskId && titleField.text.trim()) {
            pendingEditRecord = record
            editDraftDialog.open()
            return false
        }
        return startTaskEdit(record)
    }

    function startTaskEdit(record) {
        if (!record)
            return false
        var data = taskData(record)
        var day = String(valueOf(data, "plannedDate", "") || valueOf(record, "date", todayKey()))
        suppressDraft = true
        draftTimer.stop()
        if (controller && controller.clearDraft)
            controller.clearDraft()
        editingTaskId = taskId(record)
        titleField.text = String(valueOf(data, "title", ""))
        dateField.text = day
        timeField.text = String(valueOf(data, "plannedStart", "") || valueOf(data, "time", ""))
        listBox.currentIndex = Math.max(0, listBox.model.indexOf(String(valueOf(data, "list", "生活"))))
        projectField.text = String(valueOf(data, "project", ""))
        var rawTags = valueOf(data, "tags", [])
        tagsField.text = typeof rawTags === "string" ? rawTags : page.asList(rawTags).join(", ")
        var priority = String(valueOf(data, "priority", "normal"))
        priorityBox.currentIndex = priority === "high" ? 1 : (priority === "low" ? 2 : 0)
        noteField.text = String(valueOf(data, "note", ""))
        remindBox.checked = Boolean(valueOf(data, "remind", false))
        estimateBox.currentIndex = Math.max(0, estimateBox.indexOfValue(Number(valueOf(data, "estimateMinutes", 30))))
        repeatBox.currentIndex = Math.max(0, repeatBox.indexOfValue(String(valueOf(data, "repeat", "none"))))
        advancedOptionsExpanded = true
        formNotice = ""
        formHeading.text = qsTr("编辑待办")
        submitButton.text = qsTr("保存修改")
        cancelEditButton.visible = true
        suppressDraft = false
        if (controller && controller.setSelectedDay)
            controller.setSelectedDay(day)
        return true
    }

    function cancelTaskEdit() {
        pendingEditRecord = null
        clearForm()
        formNotice = ""
    }

    function queueDraftSave() {
        if (!suppressDraft)
            draftTimer.restart()
    }

    function saveDraftNow() {
        if (!controller || !controller.saveDraft)
            return
        var draft = {
            title: titleField.text,
            date: dateField.text,
            time: timeField.text,
            list: listBox.currentText,
            project: projectField.text,
            tags: tagsField.text,
            priority: priorityBox.currentValue,
            note: noteField.text,
            remind: remindBox.checked,
            estimateMinutes: estimateBox.currentValue,
            repeat: repeatBox.currentValue
        }
        controller.saveDraft(draft)
        var saveError = String(valueOf(controller.state, "notice", "") || "")
        if (saveError) {
            draftSaveStatus = "保存异常"
            draftSaveError = saveError
            formNotice = saveError
            notice = saveError
            noticeIsError = true
        } else {
            draftSaveStatus = "草稿已保存"
            if (draftSaveError && formNotice === draftSaveError)
                formNotice = ""
            if (draftSaveError && notice === draftSaveError) {
                notice = ""
                noticeIsError = false
            }
            draftSaveError = ""
        }
    }

    function clearForm() {
        suppressDraft = true
        draftTimer.stop()
        editingTaskId = ""
        titleField.clear()
        dateField.text = todayKey()
        timeField.clear()
        listBox.currentIndex = 0
        projectField.clear()
        tagsField.clear()
        priorityBox.currentIndex = 0
        noteField.clear()
        remindBox.checked = false
        advancedOptionsExpanded = false
        estimateBox.currentIndex = 1
        repeatBox.currentIndex = 0
        formHeading.text = qsTr("添加待办")
        submitButton.text = qsTr("加入日程")
        cancelEditButton.visible = false
        suppressDraft = false
        if (controller && controller.clearDraft)
            controller.clearDraft()
    }

    function submitTask() {
        clearPostCreateAction()
        formNotice = ""
        if (!controller || (!controller.addTask && !controller.updateTaskWithOrganization)) {
            notice = "日程控制器尚未连接。"
            noticeIsError = true
            formNotice = notice
            return
        }
        if (!titleField.text.trim()) {
            notice = "请填写待办内容。"
            noticeIsError = true
            formNotice = notice
            titleField.forceActiveFocus()
            return
        }
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dateField.text.trim())) {
            notice = "日期请使用 YYYY-MM-DD 格式。"
            noticeIsError = true
            formNotice = notice
            dateField.forceActiveFocus()
            return
        }
        var result
        var wasEditing = Boolean(editingTaskId)
        var createdTitle = titleField.text.trim()
        var createdDay = dateField.text.trim()
        var createdTime = timeField.text.trim()
        var createdEstimateMinutes = Number(estimateBox.currentValue) || 30
        var successText = qsTr("已加入日程。")
        if (editingTaskId) {
            result = controller.updateTaskWithOrganization(
                        editingTaskId, titleField.text.trim(), dateField.text.trim(), timeField.text.trim(),
                        priorityBox.currentValue, listBox.currentText, noteField.text.trim(), remindBox.checked,
                        Number(estimateBox.currentValue), String(repeatBox.currentValue),
                        projectField.text.trim(), tagsField.text)
            successText = qsTr("日程已更新。")
        } else if (controller.addTaskWithOrganization) {
            result = controller.addTaskWithOrganization(
                        titleField.text.trim(), dateField.text.trim(), timeField.text.trim(),
                        priorityBox.currentValue, listBox.currentText, noteField.text.trim(), remindBox.checked,
                        Number(estimateBox.currentValue), String(repeatBox.currentValue),
                        projectField.text.trim(), tagsField.text)
        } else {
            result = controller.addTask(
                        titleField.text.trim(), dateField.text.trim(), timeField.text.trim(),
                        priorityBox.currentValue, listBox.currentText, noteField.text.trim(), remindBox.checked,
                        Number(estimateBox.currentValue), String(repeatBox.currentValue))
        }
        if (showResult(result, successText)) {
            formNotice = ""
            clearForm()
            if (!wasEditing && !createdTime)
                preparePostCreateAction(createdTitle, createdDay, createdEstimateMinutes)
        } else {
            formNotice = notice
            if (notice.indexOf("日期") >= 0)
                dateField.forceActiveFocus()
            else
                titleField.forceActiveFocus()
        }
    }

    function toggleTask(record) {
        if (!controller || !controller.toggleTask)
            return
        var result = controller.toggleTask(taskId(record))
        showResult(result, taskData(record).done ? "已恢复为待办。" : "已完成。")
    }

    function deleteTask(record) {
        selectedDeleteId = taskId(record)
        selectedDeleteTitle = String(valueOf(taskData(record), "title", qsTr("这件待办")))
        selectedDeleteSubtaskCount = subtasksOf(taskId(record)).length
        deleteDialog.open()
    }

    function createSubtask(record) {
        selectedParentId = taskId(record)
        selectedParentTitle = String(valueOf(taskData(record), "title", qsTr("这项任务")))
        subtaskTitleField.clear()
        subtaskDialog.open()
        Qt.callLater(function() { subtaskTitleField.forceActiveFocus() })
    }

    function confirmSubtask() {
        if (!controller || !controller.addSubtask)
            return
        var result = controller.addSubtask(selectedParentId, subtaskTitleField.text.trim())
        if (showResult(result, "子任务已加入。")) {
            subtaskDialog.close()
            selectedParentId = ""
            selectedParentTitle = ""
        }
    }

    function confirmDelete() {
        if (!controller || !controller.deleteTask)
            return
        var result = controller.deleteTask(selectedDeleteId)
        if (showResult(result, "日程已删除。"))
            deleteDialog.close()
    }

    function selectFilter(filterName) {
        if (controller && controller.setFilter)
            showResult(controller.setFilter(filterName), "已切换清单。")
    }

    Timer {
        id: draftTimer
        interval: 280
        repeat: false
        onTriggered: page.saveDraftNow()
    }

    Flickable {
        id: scroll
        objectName: "plannerScroll"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: contentColumn.implicitHeight + 32
        ScrollBar.vertical: ScrollBar { }

        ColumnLayout {
            id: contentColumn
            x: Math.min(32, Math.max(16, scroll.width * 0.045))
            y: 24
            width: Math.max(0, scroll.width - x * 2)
            spacing: 20

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Label { text: qsTr("日程统筹"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 29; font.bold: true }
                    Label {
                        objectName: "plannerCompactMetrics"
                        visible: page.width < 900
                        text: qsTr("今天 %1 项 · 逾期 %2 项 · 未来七天 %3 项")
                              .arg(String(page.valueOf(page.snapshot.metrics, "today", 0)))
                              .arg(String(page.valueOf(page.snapshot.metrics, "overdue", 0)))
                              .arg(String(page.valueOf(page.snapshot.metrics, "week", 0)))
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                    }
                    Label {
                        visible: page.width >= 900
                        text: qsTr("安排今天的节奏，也留意接下来一周")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                    }
                }
                Label {
                    text: qsTr("本机保存")
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    padding: 8
                    background: Rectangle { radius: 12; color: page.accentSoft }
                }
            }

            GridLayout {
                objectName: "plannerMetricCards"
                Layout.fillWidth: true
                visible: page.width >= 900
                columns: width < 560 ? 1 : 3
                columnSpacing: 14
                rowSpacing: 12
                Repeater {
                    model: [
                        { title: qsTr("今天"), value: page.valueOf(page.snapshot.metrics, "today", 0), tone: page.accent },
                        { title: qsTr("已逾期"), value: page.valueOf(page.snapshot.metrics, "overdue", 0), tone: page.danger },
                        { title: qsTr("未来 7 天"), value: page.valueOf(page.snapshot.metrics, "week", 0), tone: page.success }
                    ]
                    delegate: Frame {
                        id: metricCard
                        required property var modelData
                        Layout.fillWidth: true
                        padding: 17
                        background: Rectangle { radius: 18; color: page.white; border.color: page.line }
                        RowLayout {
                            anchors.fill: parent
                            Label { text: metricCard.modelData.title; color: page.muted; font.family: page.fontFamily; font.pixelSize: 13; Layout.fillWidth: true }
                            Label { text: String(metricCard.modelData.value); color: metricCard.modelData.tone; font.family: page.fontFamily; font.pixelSize: 23; font.bold: true }
                        }
                    }
                }
            }

            Frame {
                objectName: "plannerActiveTimer"
                Layout.fillWidth: true
                visible: String(page.valueOf(page.activeTracking, "taskId", "")) !== ""
                padding: 14
                background: Rectangle { radius: 16; color: page.accentSoft; border.color: page.line }
                RowLayout {
                    anchors.fill: parent
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: page.activeTrackingTitle()
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 15
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Label {
                            text: page.activeTrackingSummary()
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                        }
                    }
                    UiButton {
                        objectName: "plannerActiveTimerHelpButton"
                        uiTheme: page.uiTheme
                        text: qsTr("启动提示")
                        Accessible.name: qsTr("我有点拖延，给我一个启动提示")
                        onClicked: page.openProcrastinationHelp()
                    }
                    UiButton {
                        objectName: "plannerActiveTimerPauseButton"
                        uiTheme: page.uiTheme
                        visible: page.activeTrackingMode !== "stopwatch"
                        text: page.activeTrackingPaused ? qsTr("继续") : qsTr("暂停")
                        onClicked: page.pauseResumeActiveTracking()
                    }
                    UiButton {
                        objectName: "plannerActiveTimerStopButton"
                        uiTheme: page.uiTheme
                        text: qsTr("结束并保存")
                        onClicked: page.stopActiveTracking()
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                padding: page.width < 900 ? 14 : 20
                background: Rectangle { radius: 20; color: page.white; border.color: page.line }
                ColumnLayout {
                    anchors.fill: parent
                    spacing: page.width < 900 ? 7 : 10
                    RowLayout {
                        Layout.fillWidth: true
                        Label { id: formHeading; objectName: "plannerFormHeading"; text: qsTr("添加待办"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 18; font.bold: true; Layout.fillWidth: true }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "plannerAdvancedOptionsCompactButton"
                            visible: page.width < 900
                            text: page.advancedOptionsExpanded
                                  ? qsTr("收起")
                                  : page.advancedOptionsLabels().length > 0
                                    ? qsTr("更多（已设置 %1 项）").arg(page.advancedOptionsLabels().length)
                                    : qsTr("更多")
                            Accessible.name: page.advancedOptionsExpanded
                                           ? qsTr("收起更多选项")
                                           : page.advancedOptionsLabels().length > 0
                                             ? qsTr("展开更多选项，已设置：%1").arg(page.advancedOptionsSummary())
                                             : qsTr("展开更多选项")
                            onClicked: page.advancedOptionsExpanded = !page.advancedOptionsExpanded
                        }
                        Label {
                            objectName: "plannerDraftStatus"
                            text: "● " + qsTr(String(page.draftSaveStatus))
                            color: page.draftSaveError ? page.red : page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        UiTextField {
                            id: titleField
                            uiTheme: page.uiTheme
                            objectName: "plannerTitleInput"
                            Layout.fillWidth: true
                            maximumLength: 60
                            placeholderText: qsTr("要做什么？")
                            onTextEdited: page.queueDraftSave()
                        }
                        UiButton {
                            id: submitButton
                            uiTheme: page.uiTheme
                            objectName: "plannerAddButton"
                            text: qsTr("加入日程")
                            highlighted: true
                            Layout.preferredWidth: 116
                            onClicked: page.submitTask()
                        }
                        UiButton {
                            id: cancelEditButton
                            uiTheme: page.uiTheme
                            objectName: "plannerCancelEditButton"
                            visible: page.editingTaskId !== ""
                            text: qsTr("取消编辑")
                            Layout.preferredWidth: 92
                            onClicked: page.cancelTaskEdit()
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 540 ? 1 : page.width < 900 ? 3 : 5
                        columnSpacing: 8
                        rowSpacing: 8
                        ColumnLayout {
                            objectName: "plannerDateField"
                            Layout.fillWidth: true
                            Layout.columnSpan: page.width >= 540 && page.width < 900 ? 2 : 1
                            Text { objectName: "plannerDateLabel"; text: qsTr("日期"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            RowLayout {
                                Layout.fillWidth: true
                                UiTextField {
                                    id: dateField
                                    uiTheme: page.uiTheme
                                    objectName: "plannerDateInput"
                                    accessibleName: qsTr("任务日期")
                                    placeholderText: "YYYY-MM-DD"
                                    onTextEdited: page.queueDraftSave()
                                    Layout.fillWidth: true
                                }
                                UiButton {
                                    uiTheme: page.uiTheme
                                    text: qsTr("选择日期")
                                    onClicked: {
                                        var p = dateField.text.split("-")
                                        calendarDialog.year = p.length === 3 && !isNaN(Number(p[0])) ? Number(p[0]) : new Date().getFullYear()
                                        calendarDialog.month = p.length === 3 && !isNaN(Number(p[1])) ? Number(p[1]) - 1 : new Date().getMonth()
                                        calendarDialog.open()
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            objectName: "plannerTimeField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerTimeLabel"; text: qsTr("时间"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: timeField
                                uiTheme: page.uiTheme
                                objectName: "plannerTimeInput"
                                accessibleName: qsTr("任务时间")
                                Layout.preferredWidth: page.width < 540 ? -1 : 118
                                Layout.fillWidth: true
                                placeholderText: "HH:MM"
                                onTextEdited: page.queueDraftSave()
                            }
                        }
                        ColumnLayout {
                            objectName: "plannerListField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerListLabel"; text: qsTr("任务清单"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: listBox
                                uiTheme: page.uiTheme
                                objectName: "plannerListCombo"
                                accessibleName: qsTr("任务清单")
                                Layout.fillWidth: true
                                model: ["生活", "工作", "家庭", "个人"]
                                contentItem: Text {
                                    leftPadding: listBox.leftPadding
                                    rightPadding: listBox.rightPadding
                                    text: listBox.currentIndex >= 0
                                          ? qsTr(listBox.currentText) : listBox.displayText
                                    color: listBox.enabled ? listBox.inkColor : listBox.mutedColor
                                    font: listBox.font
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                delegate: ItemDelegate {
                                    id: plannerListChoice
                                    required property int index
                                    width: listBox.width
                                    height: 36
                                    highlighted: listBox.highlightedIndex === index
                                    contentItem: Text {
                                        text: qsTr(String(listBox.textAt(plannerListChoice.index)))
                                        color: plannerListChoice.highlighted ? listBox.accentColor : listBox.inkColor
                                        font.family: listBox.font.family
                                        font.pixelSize: 12
                                        verticalAlignment: Text.AlignVCenter
                                        elide: Text.ElideRight
                                        leftPadding: 10
                                        rightPadding: 10
                                    }
                                    background: Rectangle {
                                        radius: listBox.uiTheme ? listBox.uiTheme.radiusSmall : 8
                                        color: plannerListChoice.highlighted ? listBox.accentSoftColor : listBox.surfaceColor
                                    }
                                }
                                onActivated: page.queueDraftSave()
                            }
                        }
                        ColumnLayout {
                            objectName: "plannerPriorityField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerPriorityLabel"; text: qsTr("任务优先级"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: priorityBox
                                uiTheme: page.uiTheme
                                objectName: "plannerPriorityCombo"
                                accessibleName: qsTr("任务优先级")
                                Layout.fillWidth: true
                                model: [
                                    { text: qsTr("普通"), value: "normal" },
                                    { text: qsTr("高优先级"), value: "high" },
                                    { text: qsTr("低优先级"), value: "low" }
                                ]
                                textRole: "text"
                                valueRole: "value"
                                onActivated: page.queueDraftSave()
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: qsTr("时间可留空，未安排的待办可稍后拖入日内时间轴。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Label {
                        objectName: "plannerAdvancedOptionsSummary"
                        visible: page.width < 900 && !page.advancedOptionsExpanded
                                 && page.advancedOptionsLabels().length > 0
                        Layout.fillWidth: true
                        text: qsTr("更多已设置：%1").arg(page.advancedOptionsSummary())
                        color: page.accent
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 540 ? 1 : 2
                        columnSpacing: 8
                        rowSpacing: 8
                        visible: page.advancedOptionsExpanded
                        ColumnLayout {
                            objectName: "plannerProjectField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerProjectLabel"; text: qsTr("项目"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: projectField
                                uiTheme: page.uiTheme
                                objectName: "plannerProjectInput"
                                accessibleName: qsTr("所属项目")
                                Layout.fillWidth: true
                                maximumLength: 60
                                placeholderText: qsTr("可选")
                                onTextEdited: page.queueDraftSave()
                            }
                        }
                        ColumnLayout {
                            objectName: "plannerTagsField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerTagsLabel"; text: qsTr("标签"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: tagsField
                                uiTheme: page.uiTheme
                                objectName: "plannerTagsInput"
                                accessibleName: qsTr("任务标签")
                                Layout.fillWidth: true
                                maximumLength: 360
                                placeholderText: qsTr("用逗号分隔")
                                onTextEdited: page.queueDraftSave()
                            }
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 540 ? 1 : 2
                        columnSpacing: 8
                        rowSpacing: 8
                        visible: page.advancedOptionsExpanded
                        ColumnLayout {
                            objectName: "plannerEstimateField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerEstimateLabel"; text: qsTr("预估时长"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: estimateBox
                                uiTheme: page.uiTheme
                                objectName: "plannerEstimateCombo"
                                accessibleName: qsTr("预估时长")
                                Layout.fillWidth: true
                                model: [
                                    { text: qsTr("估计 15 分钟"), value: 15 },
                                    { text: qsTr("估计 30 分钟"), value: 30 },
                                    { text: qsTr("估计 45 分钟"), value: 45 },
                                    { text: qsTr("估计 1 小时"), value: 60 },
                                    { text: qsTr("估计 1.5 小时"), value: 90 },
                                    { text: qsTr("估计 2 小时"), value: 120 },
                                    { text: qsTr("估计 3 小时"), value: 180 }
                                ]
                                textRole: "text"
                                valueRole: "value"
                                currentIndex: 1
                                onActivated: page.queueDraftSave()
                            }
                        }
                        ColumnLayout {
                            objectName: "plannerRepeatField"
                            Layout.fillWidth: true
                            Text { objectName: "plannerRepeatLabel"; text: qsTr("重复周期"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: repeatBox
                                uiTheme: page.uiTheme
                                objectName: "plannerRepeatCombo"
                                accessibleName: qsTr("重复周期")
                                Layout.fillWidth: true
                                model: [
                                    { text: qsTr("不重复"), value: "none" },
                                    { text: qsTr("每天"), value: "daily" },
                                    { text: qsTr("每个工作日"), value: "weekdays" },
                                    { text: qsTr("每周"), value: "weekly" },
                                    { text: qsTr("每月"), value: "monthly" }
                                ]
                                textRole: "text"
                                valueRole: "value"
                                currentIndex: 0
                                onActivated: page.queueDraftSave()
                            }
                        }
                    }
                    ColumnLayout {
                        objectName: "plannerNoteField"
                        Layout.fillWidth: true
                        visible: page.advancedOptionsExpanded
                        Text { objectName: "plannerNoteLabel"; text: qsTr("备注"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        TextArea {
                            id: noteField
                            objectName: "plannerNoteInput"
                            Accessible.name: qsTr("待办备注")
                            Layout.fillWidth: true
                            Layout.preferredHeight: 66
                            placeholderText: qsTr("地点、准备事项或补充说明")
                            wrapMode: TextEdit.Wrap
                            onTextChanged: {
                                if (length > 100)
                                    remove(100, length)
                                page.queueDraftSave()
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "plannerAdvancedOptionsButton"
                            visible: page.width >= 900
                            text: page.advancedOptionsExpanded
                                  ? qsTr("收起更多选项")
                                  : qsTr("更多选项：项目、标签、预估、重复、备注与提醒")
                            onClicked: page.advancedOptionsExpanded = !page.advancedOptionsExpanded
                        }
                        CheckBox {
                            id: remindBox
                            objectName: "plannerRemindCheck"
                            text: qsTr("工作台打开时提醒我")
                            visible: page.advancedOptionsExpanded
                            onToggled: page.queueDraftSave()
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Label {
                        objectName: "plannerFormNotice"
                        visible: page.formNotice !== ""
                        text: qsTr(String(page.formNotice))
                        color: page.red
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Frame {
                        objectName: "plannerPostCreateAction"
                        visible: page.postCreateTaskId !== ""
                        Layout.fillWidth: true
                        padding: 10
                        background: Rectangle { radius: 12; color: page.successSoft; border.color: page.line }
                        RowLayout {
                            anchors.fill: parent
                            spacing: 8
                            Label {
                                objectName: "plannerPostCreateMessage"
                                Layout.fillWidth: true
                                text: qsTr("已保存到待安排：%1").arg(page.postCreateTaskTitle)
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                            UiButton {
                                objectName: "plannerPostCreateScheduleButton"
                                uiTheme: page.uiTheme
                                highlighted: true
                                text: page.postCreateTaskDay === page.selectedDay
                                      ? qsTr("现在安排") : qsTr("查看这天")
                                onClicked: page.schedulePostCreateTask()
                            }
                            UiButton {
                                objectName: "plannerPostCreateLaterButton"
                                uiTheme: page.uiTheme
                                text: qsTr("稍后安排")
                                onClicked: page.clearPostCreateAction()
                            }
                        }
                    }
                }
            }

            Frame {
                objectName: "plannerDayPlan"
                Layout.fillWidth: true
                padding: 18
                background: Rectangle { radius: 20; color: page.white; border.color: page.line }
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: qsTr("日内计划"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 18; font.bold: true }
                            Label { text: qsTr("%1 · 拖动待办到合适时段").arg(page.dateHeading(page.selectedDay)); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        }
                        Label {
                            text: qsTr("%1 已安排 · %2 计划余量")
                                  .arg(page.formatMinutes(Number(page.valueOf(page.timeline, "plannedMinutes", 0))))
                                  .arg(page.formatMinutes(Number(page.valueOf(page.timeline, "freeMinutes", 480))))
                            color: page.accent
                            font.family: page.fontFamily
                            font.pixelSize: 12
                        }
                        Label {
                            visible: Number(page.valueOf(page.timeline, "conflictCount", 0)) > 0
                            text: qsTr("有 %1 项时间冲突").arg(String(page.valueOf(page.timeline, "conflictCount", 0)))
                            color: page.red
                            font.family: page.fontFamily
                            font.pixelSize: 12
                        }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 980 ? 1 : 2
                        columnSpacing: 14
                        rowSpacing: 12
                        Frame {
                            objectName: "plannerUnscheduledPanel"
                            visible: page.unscheduledTasks.length > 0
                            Layout.row: page.width < 980 ? 1 : 0
                            Layout.column: 0
                            Layout.fillWidth: true
                            Layout.preferredWidth: 270
                            padding: 14
                            background: Rectangle { radius: 14; color: page.surfaceSoft; border.color: page.line }
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: qsTr("待安排"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 15; font.bold: true; Layout.fillWidth: true }
                                    Label { text: qsTr("%1 项").arg(String(page.unscheduledTasks.length)); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                                }
                                Label {
                                    visible: page.unscheduledTasks.length === 0
                                    Layout.fillWidth: true
                                    text: qsTr("待办都已放进计划，给日程留点空白也很好。")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                Repeater {
                                    model: page.unscheduledTasks
                                    delegate: Frame {
                                        id: backlogCard
                                        objectName: "plannerBacklogCard_" + page.taskId(modelData)
                                        required property var modelData
                                        required property int index
                                        property string dragTaskId: page.taskId(modelData)
                                        property int dragEstimateMinutes: Number(page.valueOf(page.taskData(modelData), "estimateMinutes", 30)) || 30
                                        property string suggestedStartTime: page.suggestStartTime(dragEstimateMinutes)
                                        Layout.fillWidth: true
                                        padding: 9
                                        Drag.keys: ["wanxiang-planner-task"]
                                        Drag.mimeData: ({ "application/x-wanxiang-planner-task": dragTaskId })
                                        Drag.supportedActions: Qt.MoveAction
                                        Drag.hotSpot.x: width / 2
                                        Drag.hotSpot.y: height / 2
                                        background: Rectangle { radius: 10; color: page.white; border.color: page.line }
                                        ColumnLayout {
                                            anchors.fill: parent
                                            spacing: 5
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Label {
                                                text: String(page.valueOf(page.taskData(backlogCard.modelData), "title", qsTr("未命名待办")))
                                                    color: page.ink
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 13
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                Label {
                                                    text: page.formatMinutes(backlogCard.dragEstimateMinutes)
                                                    color: page.accent
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                }
                                                ToolButton { text: "−"; Accessible.name: qsTr("减少预计用时"); onClicked: page.adjustEstimate(backlogCard.modelData, -15) }
                                                ToolButton { text: "+"; Accessible.name: qsTr("增加预计用时"); onClicked: page.adjustEstimate(backlogCard.modelData, 15) }
                                            }
                                            Label {
                                                text: String(page.valueOf(page.taskData(backlogCard.modelData), "list", qsTr("生活")))
                                                      + " · " + page.dateHeading(String(page.valueOf(backlogCard.modelData, "date", page.selectedDay)))
                                                      + (page.taskContext(page.taskData(backlogCard.modelData)) ? " · " + page.taskContext(page.taskData(backlogCard.modelData)) : "")
                                                      + (page.isOverdue(backlogCard.modelData) ? " · " + qsTr("已逾期") : "")
                                                color: page.isOverdue(backlogCard.modelData) ? page.red : page.muted
                                                font.family: page.fontFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Button {
                                                    text: qsTr("专注")
                                                    enabled: !page.taskData(backlogCard.modelData).done
                                                             && !page.taskSourceCancelled(backlogCard.modelData)
                                                             && (String(page.valueOf(page.activeTracking, "taskId", "")) === ""
                                                                 || page.taskIsTracked(backlogCard.modelData))
                                                    onClicked: page.openFocusDialog(backlogCard.modelData)
                                                }
                                                Button {
                                                    text: page.taskIsTracked(backlogCard.modelData) ? qsTr("结束计时") : qsTr("开始计时")
                                                    enabled: !page.taskSourceCancelled(backlogCard.modelData)
                                                    onClicked: page.toggleTracking(backlogCard.modelData)
                                                }
                                                Button {
                                                    text: backlogCard.suggestedStartTime
                                                          ? qsTr("排入 %1").arg(backlogCard.suggestedStartTime) : qsTr("没有完整空档")
                                                    highlighted: true
                                                    enabled: backlogCard.suggestedStartTime.length > 0
                                                             && !page.taskSourceCancelled(backlogCard.modelData)
                                                    onClicked: page.scheduleTask(backlogCard.dragTaskId, page.selectedDay,
                                                                                backlogCard.suggestedStartTime,
                                                                                backlogCard.dragEstimateMinutes)
                                                }
                                                Item { Layout.fillWidth: true }
                                            }
                                        }
                                        DragHandler {
                                            enabled: !page.taskSourceCancelled(backlogCard.modelData)
                                            target: null
                                            dragThreshold: 10
                                            onActiveChanged: {
                                                if (active)
                                                    backlogCard.Drag.startDrag(Qt.MoveAction)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Frame {
                            id: timeboxFrame
                            objectName: "plannerTimebox"
                            visible: page.hasTimelineContent
                            Layout.row: 0
                            Layout.column: page.width < 980 || page.unscheduledTasks.length === 0 ? 0 : 1
                            Layout.columnSpan: page.width >= 980 && page.unscheduledTasks.length === 0 ? 2 : 1
                            Layout.fillWidth: true
                            padding: 10
                            background: Rectangle { radius: 14; color: page.surfaceSoft; border.color: page.line }
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        objectName: "plannerTimelineRangeLabel"
                                        text: qsTr("%1:00 – %2:00")
                                              .arg(page.pad2(page.timelineStartHour))
                                              .arg(page.pad2(page.timelineEndHour))
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 14
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    Label { objectName: "plannerActualTimeHint"; text: qsTr("开始计时后记录实际用时"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                                }
                                Item {
                                    id: timelineCanvas
                                    objectName: "plannerTimelineCanvas"
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 480
                                    implicitHeight: Math.max(1, page.timelineEndHour - page.timelineStartHour) * page.pixelsPerHour
                                    clip: true
                                    Repeater {
                                        model: Math.max(1, page.timelineEndHour - page.timelineStartHour)
                                        delegate: Item {
                                            required property int index
                                            x: 0
                                            y: index * page.pixelsPerHour
                                            width: timelineCanvas.width
                                            height: page.pixelsPerHour
                                            Label {
                                                x: 0
                                                y: -8
                                                width: 42
                                                text: page.pad2(page.timelineStartHour + parent.index) + ":00"
                                                color: page.muted
                                                font.family: page.fontFamily
                                                font.pixelSize: 12
                                            }
                                            Rectangle {
                                                x: 45
                                                y: 0
                                                width: Math.max(0, timelineCanvas.width - 45)
                                                height: 1
                                                color: page.line
                                            }
                                            Rectangle {
                                                x: 45
                                                y: page.pixelsPerHour / 2
                                                width: Math.max(0, timelineCanvas.width - 45)
                                                height: 1
                                                color: page.line
                                                opacity: 0.55
                                            }
                                        }
                                    }
                                    DropArea {
                                        id: timelineDropArea
                                        objectName: "plannerTimelineDropArea"
                                        anchors.fill: parent
                                        z: 1
                                        keys: ["wanxiang-planner-task"]
                                        onDropped: function(drop) {
                                            page.dropTask(drop)
                                            drop.acceptProposedAction()
                                        }
                                        Rectangle {
                                            anchors.fill: parent
                                            visible: timelineDropArea.containsDrag
                                            color: page.accentSoft
                                            opacity: 0.38
                                            border.color: page.accent
                                            border.width: 2
                                        }
                                    }
                                    Repeater {
                                        model: page.timelineEventBlocks
                                        delegate: Frame {
                                            id: calendarTimelineBlock
                                            objectName: "plannerCalendarTimeline_" + String(modelData.id || index)
                                            required property var modelData
                                            required property int index
                                            x: 50 + Number(page.valueOf(calendarTimelineBlock.modelData, "lane", 0))
                                               * Math.max(0, timelineCanvas.width - 56)
                                               / Number(page.valueOf(calendarTimelineBlock.modelData, "lanes", 1))
                                            y: (Number(calendarTimelineBlock.modelData.startMinute) - page.timelineStartHour * 60)
                                               * page.pixelsPerHour / 60
                                            width: Math.max(60, (timelineCanvas.width - 56)
                                                   / Number(page.valueOf(calendarTimelineBlock.modelData, "lanes", 1)) - 5)
                                            height: Math.max(22, (Number(calendarTimelineBlock.modelData.endMinute)
                                                    - Number(calendarTimelineBlock.modelData.startMinute))
                                                    * page.pixelsPerHour / 60)
                                            z: 1.5
                                            padding: 3
                                            background: Rectangle {
                                                radius: 7
                                                color: page.surfaceSoft
                                                border.color: page.muted
                                                border.width: 1
                                            }
                                            ColumnLayout {
                                                anchors.fill: parent
                                                spacing: 0
                                                Label {
                                                    text: String(calendarTimelineBlock.modelData.title || qsTr("外部日历事件"))
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Label {
                                                    objectName: "plannerCalendarTimelineTime_" + String(calendarTimelineBlock.modelData.id || calendarTimelineBlock.index)
                                                    visible: calendarTimelineBlock.height >= 34
                                                    text: String(calendarTimelineBlock.modelData.displayTime || "")
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 11
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                            }
                                        }
                                    }
                                    Repeater {
                                        model: page.timelineBlocks.filter(function(block) { return Boolean(block.withinVisibleRange) })
                                        delegate: Frame {
                                            id: scheduledBlock
                                            objectName: "plannerTimelineBlock_" + page.taskId(modelData)
                                            required property var modelData
                                            required property int index
                                            property string dragTaskId: page.taskId(modelData)
                                            property int dragEstimateMinutes: Number(page.valueOf(scheduledBlock.modelData, "estimateMinutes", 30)) || 30
                                            x: 50 + Number(page.valueOf(scheduledBlock.modelData, "lane", 0))
                                               * Math.max(0, timelineCanvas.width - 56) / Number(page.valueOf(scheduledBlock.modelData, "lanes", 1))
                                            y: (Number(scheduledBlock.modelData.startMinute) - page.timelineStartHour * 60) * page.pixelsPerHour / 60
                                            width: Math.max(60, (timelineCanvas.width - 56) / Number(page.valueOf(scheduledBlock.modelData, "lanes", 1)) - 5)
                                            height: Math.max(31, Number(page.valueOf(scheduledBlock.modelData, "estimateMinutes", 30)) * page.pixelsPerHour / 60)
                                            z: 2
                                            padding: 4
                                            Drag.keys: ["wanxiang-planner-task"]
                                            Drag.mimeData: ({ "application/x-wanxiang-planner-task": dragTaskId })
                                            Drag.supportedActions: Qt.MoveAction
                                            Drag.hotSpot.x: width / 2
                                            Drag.hotSpot.y: Math.min(height / 2, 20)
                                            background: Rectangle {
                                                radius: 8
                                                color: page.taskData(scheduledBlock.modelData).done ? page.surfaceSoft
                                                       : (Boolean(scheduledBlock.modelData.conflict) ? page.warningSoft : page.accentSoft)
                                                border.color: Boolean(scheduledBlock.modelData.conflict) ? page.red : page.accent
                                                border.width: Boolean(scheduledBlock.modelData.conflict) ? 2 : 1
                                            }
                                            ColumnLayout {
                                                anchors.fill: parent
                                                spacing: 1
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Label {
                                                        text: String(page.valueOf(page.taskData(scheduledBlock.modelData), "title", qsTr("未命名待办")))
                                                        color: page.taskData(scheduledBlock.modelData).done ? page.muted : page.ink
                                                        font.family: page.fontFamily
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                        elide: Text.ElideRight
                                                        Layout.fillWidth: true
                                                    }
                                                    Label {
                                                        text: String(scheduledBlock.modelData.start)
                                                        color: page.accentStrong
                                                        font.family: page.fontFamily
                                                        font.pixelSize: 12
                                                    }
                                                }
                                                Label {
                                                    visible: scheduledBlock.height > 48
                                                    text: qsTr("%1 · 实际 %2").arg(page.formatMinutes(scheduledBlock.dragEstimateMinutes))
                                                          .arg(page.formatElapsed(Number(page.valueOf(page.taskData(scheduledBlock.modelData), "trackedSeconds", 0))))
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                RowLayout {
                                                    visible: scheduledBlock.height > 64 && !page.taskData(scheduledBlock.modelData).done
                                                    Layout.fillWidth: true
                                                    spacing: 1
                                                    ToolButton { text: "−"; Accessible.name: qsTr("缩短计划时长"); onClicked: page.changeDuration(scheduledBlock.modelData, -15) }
                                                    ToolButton { text: "+"; Accessible.name: qsTr("延长计划时长"); onClicked: page.changeDuration(scheduledBlock.modelData, 15) }
                                                    ToolButton {
                                                        text: page.taskIsTracked(scheduledBlock.modelData) ? qsTr("结束") : qsTr("计时")
                                                        onClicked: page.toggleTracking(scheduledBlock.modelData)
                                                    }
                                                    ToolButton {
                                                        text: "×"
                                                        Accessible.name: qsTr("移回待安排清单")
                                                        onClicked: {
                                                            var result = page.controller.unscheduleTask(page.taskId(scheduledBlock.modelData))
                                                            page.showResult(result, "已移回待安排清单。")
                                                        }
                                                    }
                                                }
                                            }
                                            DragHandler {
                                                target: null
                                                dragThreshold: 10
                                                enabled: !page.taskData(scheduledBlock.modelData).done
                                                onActiveChanged: {
                                                    if (active)
                                                        scheduledBlock.Drag.startDrag(Qt.MoveAction)
                                                }
                                            }
                                        }
                                    }
                                    Rectangle {
                                        visible: page.selectedDay === page.todayKey()
                                                 && page.selectedClockMinutes() >= page.timelineStartHour * 60
                                                 && page.selectedClockMinutes() < page.timelineEndHour * 60
                                        x: 45
                                        y: (page.selectedClockMinutes() - page.timelineStartHour * 60) * page.pixelsPerHour / 60
                                        width: Math.max(0, timelineCanvas.width - 45)
                                        height: 2
                                        color: page.red
                                        z: 3
                                    }
                                }
                                Label {
                                    visible: page.timelineBlocks.some(function(block) { return !Boolean(block.withinVisibleRange) })
                                    Layout.fillWidth: true
                                    text: qsTr("时间轴以外还有 %1 项，仍可在下方清单管理。")
                                          .arg(String(page.timelineBlocks.filter(function(block) { return !Boolean(block.withinVisibleRange) }).length))
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                        Frame {
                            objectName: "plannerTimelineEmptyState"
                            visible: !page.hasTimelineContent
                            Layout.row: 0
                            Layout.column: 0
                            Layout.columnSpan: page.width >= 980 ? 2 : 1
                            Layout.fillWidth: true
                            padding: 18
                            background: Rectangle { radius: 14; color: page.surface; border.color: page.line }
                            RowLayout {
                                anchors.fill: parent
                                spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 5
                                    Label {
                                        text: qsTr("今天还没有安排")
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 16
                                        font.bold: true
                                    }
                                    Label {
                                        text: qsTr("添加一项待办后，就可以把它拖到日内计划安排时间。")
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                                UiButton {
                                    uiTheme: page.uiTheme
                                    objectName: "plannerEmptyStateAddButton"
                                    text: qsTr("添加第一项待办")
                                    highlighted: true
                                    onClicked: page.focusTaskEntry()
                                }
                            }
                        }
                    }
                }
            }

            Frame {
                objectName: "plannerExternalCalendar"
                visible: page.asList(page.valueOf(page.snapshot, "calendarEvents", [])).length > 0
                Layout.fillWidth: true
                padding: 16
                background: Rectangle { radius: 18; color: page.surface; border.color: page.line }
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label {
                        text: qsTr("外部日历 · %1").arg(page.asList(page.valueOf(page.snapshot, "calendarEvents", [])).length)
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Repeater {
                        model: page.asList(page.valueOf(page.snapshot, "calendarEvents", []))
                        delegate: RowLayout {
                            id: calendarEventRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Label {
                                text: String(calendarEventRow.modelData.displayTime || (calendarEventRow.modelData.allDay ? qsTr("全天") : ""))
                                color: page.accentStrong
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                Layout.preferredWidth: 100
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label {
                                    text: String(calendarEventRow.modelData.title || qsTr("未命名待办"))
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 13
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                                Label {
                                    visible: String(calendarEventRow.modelData.location || "") !== "" || String(calendarEventRow.modelData.sourceCalendar || "") !== ""
                                    text: [String(calendarEventRow.modelData.location || ""), String(calendarEventRow.modelData.sourceCalendar || "")].filter(function(item) { return item !== "" }).join(" · ")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }

            Frame {
                objectName: "plannerWeekOverview"
                Layout.fillWidth: true
                padding: 18
                background: Rectangle { radius: 20; color: page.white; border.color: page.line }
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("接下来七天"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true }
                        Label { text: qsTr("先看负荷，再决定节奏"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        ToolButton { text: "‹"; Accessible.name: qsTr("上周"); onClicked: page.moveSelectedWeek(-1) }
                        ToolButton { text: qsTr("今天"); onClicked: page.selectDay(page.todayKey()) }
                        ToolButton { text: "›"; Accessible.name: qsTr("下周"); onClicked: page.moveSelectedWeek(1) }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: width < 500 ? 4 : 7
                        columnSpacing: 6
                        rowSpacing: 6
                        Repeater {
                            id: weekDaysRepeater
                            model: page.weekDays
                            delegate: Frame {
                                id: weekDayFrame
                                required property var modelData
                                objectName: "plannerWeekday_" + String(modelData.date)
                                Layout.fillWidth: true
                                padding: 8
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: qsTr("%1，%2").arg(page.dateHeading(String(modelData.date))).arg(
                                                     Number(modelData.plannedCount) > 0
                                                     ? page.formatMinutes(Number(modelData.plannedMinutes))
                                                     : (Number(modelData.count) > 0
                                                        ? qsTr("%1 项待安排").arg(String(modelData.count)) : qsTr("留白")))
                                Keys.onReturnPressed: page.selectDayAndFocus(String(weekDayFrame.modelData.date))
                                Keys.onSpacePressed: page.selectDayAndFocus(String(weekDayFrame.modelData.date))
                                background: Rectangle {
                                    radius: 10
                                    color: String(weekDayFrame.modelData.date) === page.selectedDay ? page.accentSoft : page.surfaceSoft
                                    border.color: String(weekDayFrame.modelData.date) === page.selectedDay ? page.accent : page.line
                                    border.width: weekDayFrame.activeFocus ? 2 : 1
                                }
                                TapHandler {
                                    onTapped: {
                                        weekDayFrame.forceActiveFocus()
                                        page.selectDayAndFocus(String(weekDayFrame.modelData.date))
                                    }
                                }
                                ColumnLayout {
                                    anchors.fill: parent
                                    spacing: 3
                                    Label { text: page.weekDayLabel(weekDayFrame.modelData.weekday); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.alignment: Qt.AlignHCenter }
                                    Label { text: String(weekDayFrame.modelData.day); color: page.ink; font.family: page.fontFamily; font.pixelSize: 17; font.bold: true; Layout.alignment: Qt.AlignHCenter }
                                    Label {
                                        text: Number(weekDayFrame.modelData.plannedCount) > 0
                                              ? page.formatMinutes(Number(weekDayFrame.modelData.plannedMinutes))
                                              : (Number(weekDayFrame.modelData.count) > 0 ? qsTr("%1 项待排").arg(String(weekDayFrame.modelData.count)) : qsTr("留白"))
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        Layout.alignment: Qt.AlignHCenter
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                padding: 18
                background: Rectangle { radius: 20; color: page.white; border.color: page.line }
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("我的提醒事项"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerFilter_all"; text: qsTr("全部"); highlighted: String(page.valueOf(page.snapshot, "filter", "all")) === "all"; onClicked: page.selectFilter("all") }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerFilter_today"; text: qsTr("今天"); highlighted: String(page.valueOf(page.snapshot, "filter", "all")) === "today"; onClicked: page.selectFilter("today") }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerFilter_scheduled"; text: qsTr("计划内"); highlighted: String(page.valueOf(page.snapshot, "filter", "all")) === "scheduled"; onClicked: page.selectFilter("scheduled") }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerFilter_done"; text: qsTr("已完成"); highlighted: String(page.valueOf(page.snapshot, "filter", "all")) === "done"; onClicked: page.selectFilter("done") }
                    }
                    Flow {
                        objectName: "plannerViewControlsFlow"
                        Layout.fillWidth: true
                        spacing: 5
                        Label { text: qsTr("视图"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerView_list"; text: qsTr("清单"); highlighted: page.viewMode === "list"; onClicked: page.setPlannerView("list") }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerView_kanban"; text: qsTr("看板"); highlighted: page.viewMode === "kanban"; onClicked: page.setPlannerView("kanban") }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerView_matrix"; text: qsTr("四象限"); highlighted: page.viewMode === "matrix"; onClicked: page.setPlannerView("matrix") }
                    }
                    Flow {
                        objectName: "plannerCalendarActionsFlow"
                        Layout.fillWidth: true
                        spacing: 5
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerTimesheetButton"; text: qsTr("工时复盘"); onClicked: page.openTimesheet() }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerCalendarImportButton"; text: qsTr("导入日历"); onClicked: page.openCalendarImport() }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "plannerCalendarSourcesButton"
                            text: qsTr("日历来源")
                            Accessible.name: qsTr("打开日历来源菜单")
                            onClicked: calendarSourcesMenu.open()
                            Menu {
                                id: calendarSourcesMenu
                                objectName: "plannerCalendarSourcesMenu"
                                MenuItem {
                                    objectName: "plannerCalendarSubscriptionsMenuItem"
                                    text: qsTr("日历订阅")
                                    onTriggered: page.openCalendarSubscriptions()
                                }
                                MenuItem {
                                    objectName: "plannerCalDAVAccountsMenuItem"
                                    text: qsTr("CalDAV 账户")
                                    onTriggered: page.openCalDAVAccounts()
                                }
                                MenuItem {
                                    objectName: "plannerWebDavPlannerSyncMenuItem"
                                    text: qsTr("跨设备日程同步")
                                    onTriggered: page.openWebDavPlannerSync()
                                }
                            }
                        }
                        UiButton { uiTheme: page.uiTheme; objectName: "plannerCalendarExportButton"; text: qsTr("导出 ICS"); onClicked: page.openCalendarExport() }
                    }
                    Flow {
                        objectName: "plannerCustomBoardPicker"
                        Layout.fillWidth: true
                        spacing: 5
                        Repeater {
                            model: page.customBoards
                            delegate: Button {
                                required property var modelData
                                objectName: "plannerCustomBoardButton_" + String(modelData.id)
                                text: String(modelData.name)
                                highlighted: page.viewMode === "custom-board:" + String(modelData.id)
                                onClicked: page.setPlannerView("custom-board:" + String(modelData.id))
                            }
                        }
                        UiButton {
                            objectName: "plannerCustomBoardManageButton"
                            uiTheme: page.uiTheme
                            text: page.selectedCustomBoard ? qsTr("编辑当前看板") : qsTr("新建自定义看板")
                            onClicked: page.openCustomBoardEditor(page.selectedCustomBoard)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("项目"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        UiComboBox {
                            objectName: "plannerProjectFilter"
                            uiTheme: page.uiTheme
                            accessibleName: qsTr("按项目筛选")
                            Layout.preferredWidth: 190
                            model: [qsTr("全部项目")].concat(page.projects)
                            currentIndex: {
                                var selected = String(page.valueOf(page.snapshot, "projectFilter", ""))
                                return selected ? Math.max(0, page.projects.indexOf(selected) + 1) : 0
                            }
                            onActivated: page.setTaskFilters(
                                             currentIndex > 0 ? page.projects[currentIndex - 1] : "",
                                             String(page.valueOf(page.snapshot, "tagFilter", "")))
                        }
                        Label { text: qsTr("标签"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        UiComboBox {
                            objectName: "plannerTagFilter"
                            uiTheme: page.uiTheme
                            accessibleName: qsTr("按标签筛选")
                            Layout.preferredWidth: 170
                            model: [qsTr("全部标签")].concat(page.tags)
                            currentIndex: {
                                var selected = String(page.valueOf(page.snapshot, "tagFilter", ""))
                                return selected ? Math.max(0, page.tags.indexOf(selected) + 1) : 0
                            }
                            onActivated: page.setTaskFilters(
                                             String(page.valueOf(page.snapshot, "projectFilter", "")),
                                             currentIndex > 0 ? page.tags[currentIndex - 1] : "")
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Label {
                        visible: page.viewMode === "matrix"
                        Layout.fillWidth: true
                        text: qsTr("四象限规则：高优先级视为重要；日期为今天或已逾期的未完成事项视为紧急。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    GridLayout {
                        objectName: "plannerKanbanBoard"
                        visible: page.viewMode === "kanban"
                        Layout.fillWidth: true
                        columns: page.width < 800 ? 1 : 3
                        columnSpacing: 10
                        rowSpacing: 10
                        Repeater {
                            model: page.statusOptions
                            delegate: Frame {
                                id: kanbanLane
                                required property var modelData
                                objectName: "plannerStandardBoardLane_" + modelData.value
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                padding: 9
                                background: Rectangle { radius: 14; color: page.surfaceSoft; border.color: page.line }
                                ColumnLayout {
                                    anchors.fill: parent
                                    spacing: 7
                                    Label {
                                        text: kanbanLane.modelData.label + "  ·  "
                                              + String(page.standardBoardLaneTasks(kanbanLane.modelData.value).length)
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.bold: true
                                        font.pixelSize: 14
                                    }
                                    Label {
                                        objectName: "plannerStandardBoardReorderHint"
                                        text: qsTr("拖动任务可更改状态和列内顺序")
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Repeater {
                                        model: page.standardBoardLaneTasks(kanbanLane.modelData.value)
                                        delegate: Frame {
                                            id: kanbanCard
                                            required property var modelData
                                            required property int index
                                            objectName: "plannerStandardBoardTask_" + page.taskId(modelData)
                                            property string standardBoardTaskId: page.taskId(modelData)
                                            Layout.fillWidth: true
                                            padding: 10
                                            implicitHeight: standardBoardCardContent.implicitHeight + topPadding + bottomPadding
                                            Drag.keys: ["wanxiang-standard-board-task"]
                                            Drag.mimeData: ({ "application/x-wanxiang-standard-board-task": standardBoardTaskId })
                                            Drag.supportedActions: Qt.MoveAction
                                            Drag.hotSpot.x: width / 2
                                            Drag.hotSpot.y: height / 2
                                            background: Rectangle { radius: 10; color: page.surface; border.color: page.line }
                                            ColumnLayout {
                                                id: standardBoardCardContent
                                                anchors.fill: parent
                                                spacing: 5
                                                Label {
                                                    text: String(page.valueOf(page.taskData(kanbanCard.modelData), "title", qsTr("未命名待办")))
                                                    color: page.ink
                                                    font.family: page.fontFamily
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                Label {
                                                    visible: page.taskContext(page.taskData(kanbanCard.modelData)) !== ""
                                                    text: page.taskContext(page.taskData(kanbanCard.modelData))
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 11
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 2
                                                    Repeater {
                                                        model: page.statusOptions
                                                        delegate: UiButton {
                                                            required property var modelData
                                                            uiTheme: page.uiTheme
                                                            objectName: "plannerKanbanStatus_" + page.taskId(kanbanCard.modelData) + "_" + modelData.value
                                                            text: modelData.label
                                                            flat: true
                                                            highlighted: page.taskStatus(kanbanCard.modelData) === modelData.value
                                                            enabled: (!page.taskIsTracked(kanbanCard.modelData) || modelData.value === "doing")
                                                                     && !page.taskSourceCancelled(kanbanCard.modelData)
                                                            onClicked: page.setTaskStatus(kanbanCard.modelData, modelData.value)
                                                            font.pixelSize: 12
                                                            Layout.fillWidth: true
                                                        }
                                                    }
                                                }
                                                Button {
                                                    text: qsTr("专注")
                                                    enabled: !page.taskData(kanbanCard.modelData).done
                                                             && !page.taskSourceCancelled(kanbanCard.modelData)
                                                             && (String(page.valueOf(page.activeTracking, "taskId", "")) === ""
                                                                 || page.taskIsTracked(kanbanCard.modelData))
                                                    onClicked: page.openFocusDialog(kanbanCard.modelData)
                                                }
                                            }
                                            DragHandler {
                                                target: null
                                                dragThreshold: 10
                                                onActiveChanged: {
                                                    if (active)
                                                        kanbanCard.Drag.startDrag(Qt.MoveAction)
                                                }
                                            }
                                            DropArea {
                                                id: standardBoardCardDropArea
                                                objectName: "plannerStandardBoardDrop_" + page.taskId(kanbanCard.modelData)
                                                anchors.fill: parent
                                                z: 3
                                                keys: ["wanxiang-standard-board-task"]
                                                onDropped: function(drop) {
                                                    const taskId = page.draggedStandardBoardTaskId(drop.source)
                                                    if (!taskId)
                                                        return
                                                    const laneTasks = page.standardBoardLaneTasks(kanbanLane.modelData.value)
                                                    var beforeTaskId = ""
                                                    if (drop.y < height / 2) {
                                                        beforeTaskId = page.taskId(kanbanCard.modelData)
                                                    } else if (kanbanCard.index + 1 < laneTasks.length) {
                                                        beforeTaskId = page.taskId(laneTasks[kanbanCard.index + 1])
                                                    }
                                                    page.moveTaskOnStandardBoard(
                                                                taskId,
                                                                kanbanLane.modelData.value,
                                                                beforeTaskId)
                                                    drop.acceptProposedAction()
                                                }
                                                Rectangle {
                                                    anchors.fill: parent
                                                    visible: standardBoardCardDropArea.containsDrag
                                                    radius: 10
                                                    color: page.accentSoft
                                                    opacity: 0.28
                                                    border.color: page.accent
                                                    border.width: 2
                                                }
                                            }
                                        }
                                    }
                                    DropArea {
                                        objectName: "plannerStandardBoardTailDrop_" + kanbanLane.modelData.value
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        implicitHeight: 50
                                        keys: ["wanxiang-standard-board-task"]
                                        onDropped: function(drop) {
                                            const taskId = page.draggedStandardBoardTaskId(drop.source)
                                            if (taskId) {
                                                page.moveTaskOnStandardBoard(
                                                            taskId,
                                                            kanbanLane.modelData.value,
                                                            "")
                                                drop.acceptProposedAction()
                                            }
                                        }
                                        Rectangle {
                                            anchors.fill: parent
                                            visible: parent.containsDrag
                                            color: page.accentSoft
                                            opacity: 0.35
                                            border.color: page.accent
                                            border.width: 2
                                            radius: 10
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Frame {
                        objectName: "plannerCustomBoard"
                        visible: page.selectedCustomBoard !== null
                        Layout.fillWidth: true
                        padding: 12
                        background: Rectangle { radius: 16; color: page.surface; border.color: page.line }
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 10
                            Label {
                                text: page.selectedCustomBoard ? String(page.selectedCustomBoard.name) : ""
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 17
                                font.bold: true
                            }
                            GridLayout {
                                objectName: "plannerCustomBoardColumns"
                                Layout.fillWidth: true
                                columns: page.selectedCustomBoard
                                         ? Math.max(1, Math.min(4, page.selectedCustomBoard.columns.length)) : 1
                                columnSpacing: 10
                                rowSpacing: 10
                                Repeater {
                                    model: page.selectedCustomBoard
                                           ? page.selectedCustomBoard.columns : []
                                    delegate: Frame {
                                        id: customBoardLane
                                        required property var modelData
                                        objectName: "plannerCustomBoardLane_" + String(modelData.id)
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignTop
                                        padding: 9
                                        background: Rectangle { radius: 14; color: page.surfaceSoft; border.color: page.line }
                                        ColumnLayout {
                                            anchors.fill: parent
                                            spacing: 7
                                            Label {
                                                text: String(customBoardLane.modelData.title) + " · "
                                                      + String(page.visibleTasks.filter(function(row) {
                                                          return page.taskStatus(row) === customBoardLane.modelData.status
                                                                  && page.taskHasTag(row, customBoardLane.modelData.tag)
                                                      }).length)
                                                color: page.ink
                                                font.family: page.fontFamily
                                                font.bold: true
                                                font.pixelSize: 14
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                            Label {
                                                visible: String(customBoardLane.modelData.tag || "") !== ""
                                                text: qsTr("包含标签：%1").arg(String(customBoardLane.modelData.tag || ""))
                                                color: page.muted
                                                font.family: page.fontFamily
                                                font.pixelSize: 11
                                                Layout.fillWidth: true
                                            }
                                            Label {
                                                objectName: "plannerBoardReorderHint"
                                                text: qsTr("拖到列尾可排至末尾；拖到卡片上方或下方可插入排序")
                                                color: page.muted
                                                font.family: page.fontFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                            Repeater {
                                                model: page.customBoardLaneTasks(customBoardLane.modelData)
                                                delegate: Frame {
                                                    id: customBoardCard
                                                    required property var modelData
                                                    required property int index
                                                    objectName: "plannerCustomBoardTask_" + page.taskId(modelData)
                                                    property string boardTaskId: page.taskId(modelData)
                                                    Layout.fillWidth: true
                                                    padding: 10
                                                    Drag.keys: ["wanxiang-custom-board-task"]
                                                    Drag.mimeData: ({ "application/x-wanxiang-custom-board-task": boardTaskId })
                                                    Drag.supportedActions: Qt.MoveAction
                                                    Drag.hotSpot.x: width / 2
                                                    Drag.hotSpot.y: height / 2
                                                    background: Rectangle { radius: 10; color: page.surface; border.color: page.line }
                                                    ColumnLayout {
                                                        anchors.fill: parent
                                                        spacing: 5
                                                        Label {
                                                            text: String(page.valueOf(page.taskData(customBoardCard.modelData), "title", qsTr("未命名待办")))
                                                            color: page.ink
                                                            font.family: page.fontFamily
                                                            font.bold: true
                                                            wrapMode: Text.Wrap
                                                            Layout.fillWidth: true
                                                        }
                                                        Label {
                                                            visible: page.taskContext(page.taskData(customBoardCard.modelData)) !== ""
                                                            text: page.taskContext(page.taskData(customBoardCard.modelData))
                                                            color: page.muted
                                                            font.family: page.fontFamily
                                                            font.pixelSize: 11
                                                            wrapMode: Text.Wrap
                                                            Layout.fillWidth: true
                                                        }
                                                        Button {
                                                            text: qsTr("专注")
                                                            enabled: !page.taskData(customBoardCard.modelData).done
                                                                     && (String(page.valueOf(page.activeTracking, "taskId", "")) === ""
                                                                         || page.taskIsTracked(customBoardCard.modelData))
                                                            onClicked: page.openFocusDialog(customBoardCard.modelData)
                                                        }
                                                    }
                                                    DragHandler {
                                                        target: null
                                                        dragThreshold: 10
                                                        onActiveChanged: {
                                                            if (active)
                                                                customBoardCard.Drag.startDrag(Qt.MoveAction)
                                                        }
                                                    }
                                                    DropArea {
                                                        id: customBoardCardDropArea
                                                        objectName: "plannerCustomBoardDrop_" + page.taskId(customBoardCard.modelData)
                                                        anchors.fill: parent
                                                        z: 3
                                                        keys: ["wanxiang-custom-board-task"]
                                                        onDropped: function(drop) {
                                                            const taskId = page.draggedCustomBoardTaskId(drop.source)
                                                            if (!taskId)
                                                                return
                                                            const laneTasks = page.customBoardLaneTasks(customBoardLane.modelData)
                                                            var beforeTaskId = ""
                                                            if (drop.y < height / 2) {
                                                                beforeTaskId = page.taskId(customBoardCard.modelData)
                                                            } else if (customBoardCard.index + 1 < laneTasks.length) {
                                                                beforeTaskId = page.taskId(laneTasks[customBoardCard.index + 1])
                                                            }
                                                            page.moveTaskToBoardColumn(taskId,
                                                                                        customBoardLane.modelData,
                                                                                        page.selectedCustomBoard.id,
                                                                                        customBoardLane.modelData.id,
                                                                                        beforeTaskId)
                                                            drop.acceptProposedAction()
                                                        }
                                                        Rectangle {
                                                            anchors.fill: parent
                                                            visible: customBoardCardDropArea.containsDrag
                                                            radius: 10
                                                            color: page.accentSoft
                                                            opacity: 0.28
                                                            border.color: page.accent
                                                            border.width: 2
                                                        }
                                                    }
                                                }
                                            }
                                            DropArea {
                                                objectName: "plannerCustomBoardTailDrop_" + String(customBoardLane.modelData.id)
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                implicitHeight: 50
                                                keys: ["wanxiang-custom-board-task"]
                                                onDropped: function(drop) {
                                                    const taskId = page.draggedCustomBoardTaskId(drop.source)
                                                    if (taskId) {
                                                        page.moveTaskToBoardColumn(taskId,
                                                                                    customBoardLane.modelData,
                                                                                    page.selectedCustomBoard.id,
                                                                                    customBoardLane.modelData.id,
                                                                                    "")
                                                        drop.acceptProposedAction()
                                                    }
                                                }
                                                Rectangle {
                                                    anchors.fill: parent
                                                    visible: parent.containsDrag
                                                    color: page.accentSoft
                                                    opacity: 0.35
                                                    border.color: page.accent
                                                    border.width: 2
                                                    radius: 10
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    GridLayout {
                        objectName: "plannerMatrixBoard"
                        visible: page.viewMode === "matrix"
                        Layout.fillWidth: true
                        columns: page.width < 760 ? 1 : 2
                        columnSpacing: 10
                        rowSpacing: 10
                        Repeater {
                            model: [
                                { title: qsTr("重要且紧急"), important: true, urgent: true },
                                { title: qsTr("重要不紧急"), important: true, urgent: false },
                                { title: qsTr("紧急不重要"), important: false, urgent: true },
                                { title: qsTr("其他事项"), important: false, urgent: false }
                            ]
                            delegate: Frame {
                                id: matrixCell
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                padding: 10
                                background: Rectangle { radius: 14; color: page.surfaceSoft; border.color: page.line }
                                ColumnLayout {
                                    anchors.fill: parent
                                    spacing: 7
                                    Label { text: matrixCell.modelData.title; color: page.ink; font.family: page.fontFamily; font.bold: true; font.pixelSize: 14 }
                                    Repeater {
                                        model: page.visibleTasks.filter(function(row) {
                                            return page.taskIsImportant(row) === matrixCell.modelData.important
                                                    && page.taskIsUrgent(row) === matrixCell.modelData.urgent
                                        })
                                        delegate: Frame {
                                            id: matrixCard
                                            required property var modelData
                                            Layout.fillWidth: true
                                            padding: 9
                                            background: Rectangle { radius: 9; color: page.surface; border.color: page.line }
                                            ColumnLayout {
                                                anchors.fill: parent
                                                spacing: 5
                                                Label {
                                                    text: String(page.valueOf(page.taskData(matrixCard.modelData), "title", qsTr("未命名待办")))
                                                    color: page.ink
                                                    font.family: page.fontFamily
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                Label {
                                                    text: page.taskContext(page.taskData(matrixCard.modelData))
                                                    visible: text !== ""
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 11
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 2
                                                    Repeater {
                                                        model: page.statusOptions
                                                        delegate: UiButton {
                                                            required property var modelData
                                                            uiTheme: page.uiTheme
                                                            objectName: "plannerMatrixStatus_" + page.taskId(matrixCard.modelData) + "_" + modelData.value
                                                            text: modelData.label
                                                            flat: true
                                                            highlighted: page.taskStatus(matrixCard.modelData) === modelData.value
                                                            enabled: (!page.taskIsTracked(matrixCard.modelData) || modelData.value === "doing")
                                                                     && !page.taskSourceCancelled(matrixCard.modelData)
                                                            onClicked: page.setTaskStatus(matrixCard.modelData, modelData.value)
                                                            font.pixelSize: 12
                                                            Layout.fillWidth: true
                                                        }
                                                    }
                                                }
                                                Button {
                                                    text: qsTr("专注")
                                                    enabled: !page.taskData(matrixCard.modelData).done
                                                             && !page.taskSourceCancelled(matrixCard.modelData)
                                                             && (String(page.valueOf(page.activeTracking, "taskId", "")) === ""
                                                                 || page.taskIsTracked(matrixCard.modelData))
                                                    onClicked: page.openFocusDialog(matrixCard.modelData)
                                                }
                                            }
                                        }
                                    }
                                    Item { Layout.fillHeight: true; implicitHeight: 1 }
                                }
                            }
                        }
                    }
                    Label {
                        visible: page.viewMode === "list" && page.groups.length === 0
                        Layout.fillWidth: true
                        text: qsTr("这个智能清单里暂时没有事项。")
                        color: page.muted
                        font.family: page.fontFamily
                        horizontalAlignment: Text.AlignHCenter
                        padding: 22
                    }
                    Repeater {
                        visible: page.viewMode === "list"
                        model: page.groups
                        delegate: Frame {
                            id: groupFrame
                            required property var modelData
                            required property int index
                            property bool expanded: groupFrame.index < 3
                            Layout.fillWidth: true
                            padding: 0
                            background: Rectangle { radius: 11; color: page.surfaceSoft; border.color: page.line }
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                ToolButton {
                                    Layout.fillWidth: true
                                    text: (groupFrame.expanded ? "⌄  " : "›  ") + qsTr("%1    %2 件待完成")
                                          .arg(page.dateHeading(groupFrame.modelData.date))
                                          .arg(String(groupFrame.modelData.pending))
                                    font.family: page.fontFamily
                                    font.bold: true
                                    onClicked: groupFrame.expanded = !groupFrame.expanded
                                }
                                ColumnLayout {
                                    visible: groupFrame.expanded
                                    Layout.fillWidth: true
                                    Layout.leftMargin: 10
                                    Layout.rightMargin: 10
                                    Layout.bottomMargin: 10
                                    spacing: 4
                                    Repeater {
                                        model: page.asList(groupFrame.modelData.records)
                                        delegate: RowLayout {
                                            id: plannerTaskRow
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 8
                                            CheckBox {
                                                objectName: "plannerToggle_" + page.taskId(plannerTaskRow.modelData)
                                                checked: Boolean(page.taskData(plannerTaskRow.modelData).done)
                                                enabled: !Boolean(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "cancelled", false))
                                                onToggled: page.toggleTask(plannerTaskRow.modelData)
                                                Layout.leftMargin: String(page.valueOf(page.taskData(plannerTaskRow.modelData), "parentTaskId", "")) ? 16 : 0
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    Label {
                                                        text: String(page.valueOf(page.taskData(plannerTaskRow.modelData), "title", qsTr("未命名待办")))
                                                        color: page.taskData(plannerTaskRow.modelData).done ? page.muted : page.ink
                                                        font.family: page.fontFamily
                                                        font.pixelSize: 14
                                                        font.strikeout: Boolean(page.taskData(plannerTaskRow.modelData).done)
                                                        wrapMode: Text.Wrap
                                                        Layout.fillWidth: true
                                                    }
                                                    Label {
                                                        visible: page.taskData(plannerTaskRow.modelData).priority === "high"
                                                        text: qsTr("高优先级")
                                                        color: page.red
                                                        font.family: page.fontFamily
                                                        font.pixelSize: 12
                                                    }
                                                }
                                                Label {
                                                    text: String(page.valueOf(page.taskData(plannerTaskRow.modelData), "list", qsTr("生活")))
                                                          + qsTr("  ·  估计 %1").arg(page.formatMinutes(Number(page.valueOf(page.taskData(plannerTaskRow.modelData), "estimateMinutes", 30))) )
                                                          + qsTr("  ·  实际 %1").arg(page.formatElapsed(Number(page.valueOf(page.taskData(plannerTaskRow.modelData), "trackedSeconds", 0))) )
                                                          + (page.taskContext(page.taskData(plannerTaskRow.modelData)) ? "  ·  " + page.taskContext(page.taskData(plannerTaskRow.modelData)) : "")
                                                          + (page.subtaskProgress(plannerTaskRow.modelData) ? "  ·  " + page.subtaskProgress(plannerTaskRow.modelData) : "")
                                                          + (page.taskData(plannerTaskRow.modelData).repeat && page.taskData(plannerTaskRow.modelData).repeat !== "none" ? qsTr("  ·  重复") : "")
                                                          + (String(page.valueOf(page.taskData(plannerTaskRow.modelData), "note", "")) !== "" ? "  ·  " + String(page.valueOf(page.taskData(plannerTaskRow.modelData), "note", "")) : "")
                                                          + (page.taskData(plannerTaskRow.modelData).remind ? qsTr("  ·  到时提醒") : "")
                                                          + (page.taskData(plannerTaskRow.modelData).externalTodo
                                                             ? (page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "provider", "") === "caldav"
                                                                ? qsTr("  ·  来自 CalDAV · %1").arg(String(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "sourceName", "")))
                                                                : qsTr("  ·  从 iCalendar 导入的任务 · %1").arg(String(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "sourceName", "")))
                                                               ) : "")
                                                          + (page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "cancelled", false) ? qsTr("  ·  来源已取消，不能完成或计时") : "")
                                                          + (page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "sourceMissing", false) ? qsTr("  ·  来源已删除，本机记录仍保留") : "")
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                RowLayout {
                                                    objectName: "plannerCalDAVConflict_" + page.taskId(plannerTaskRow.modelData)
                                                    visible: Boolean(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "syncConflict", false))
                                                    Layout.fillWidth: true
                                                    Label {
                                                        text: qsTr("本机与服务器的完成状态不同，请选择保留哪一侧。")
                                                        color: page.warning
                                                        font.family: page.fontFamily
                                                        font.pixelSize: 12
                                                        wrapMode: Text.Wrap
                                                        Layout.fillWidth: true
                                                    }
                                                    Button {
                                                        objectName: "plannerCalDAVConflictRemote_" + page.taskId(plannerTaskRow.modelData)
                                                        text: qsTr("采用服务器")
                                                        onClicked: page.resolveCalDAVTaskConflict(plannerTaskRow.modelData, "remote")
                                                    }
                                                    Button {
                                                        objectName: "plannerCalDAVConflictLocal_" + page.taskId(plannerTaskRow.modelData)
                                                        text: qsTr("保留本机")
                                                        onClicked: page.resolveCalDAVTaskConflict(plannerTaskRow.modelData, "local")
                                                    }
                                                }
                                            }
                                            Label {
                                                text: page.isOverdue(plannerTaskRow.modelData) ? qsTr("已逾期") : String(page.valueOf(page.taskData(plannerTaskRow.modelData), "plannedStart", "") || page.valueOf(page.taskData(plannerTaskRow.modelData), "time", "") || qsTr("全天"))
                                                color: page.isOverdue(plannerTaskRow.modelData) ? page.red : page.muted
                                                font.family: page.fontFamily
                                                font.pixelSize: 12
                                            }
                                            ToolButton {
                                                objectName: "plannerTrackButton_" + page.taskId(plannerTaskRow.modelData)
                                                text: page.taskIsTracked(plannerTaskRow.modelData)
                                                      ? (page.activeTrackingMode !== "stopwatch"
                                                         ? (page.activeTrackingPaused ? qsTr("继续专注") : qsTr("暂停专注"))
                                                         : qsTr("结束计时"))
                                                      : qsTr("计时")
                                                enabled: (!page.taskData(plannerTaskRow.modelData).done || page.taskIsTracked(plannerTaskRow.modelData))
                                                         && !Boolean(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "cancelled", false))
                                                onClicked: page.toggleTracking(plannerTaskRow.modelData)
                                            }
                                            ToolButton {
                                                objectName: "plannerFocusButton_" + page.taskId(plannerTaskRow.modelData)
                                                text: qsTr("专注")
                                                enabled: !page.taskData(plannerTaskRow.modelData).done
                                                         && !Boolean(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "cancelled", false))
                                                         && (String(page.valueOf(page.activeTracking, "taskId", "")) === ""
                                                             || page.taskIsTracked(plannerTaskRow.modelData))
                                                onClicked: page.openFocusDialog(plannerTaskRow.modelData)
                                            }
                                            ToolButton {
                                                objectName: "plannerSubtaskButton_" + page.taskId(plannerTaskRow.modelData)
                                                visible: !String(page.valueOf(page.taskData(plannerTaskRow.modelData), "parentTaskId", ""))
                                                         && !page.taskData(plannerTaskRow.modelData).done
                                                text: qsTr("子任务 +")
                                                Accessible.name: qsTr("为此任务添加子任务")
                                                onClicked: page.createSubtask(plannerTaskRow.modelData)
                                            }
                                            ToolButton {
                                                objectName: "plannerEditButton_" + page.taskId(plannerTaskRow.modelData)
                                                text: qsTr("编辑")
                                                enabled: !Boolean(page.valueOf(plannerTaskRow.modelData, "sample", false))
                                                         && !Boolean(page.valueOf(page.taskData(plannerTaskRow.modelData).externalTodo, "cancelled", false))
                                                onClicked: page.editTask(plannerTaskRow.modelData)
                                            }
                                            ToolButton {
                                                objectName: "plannerOrganizationButton_" + page.taskId(plannerTaskRow.modelData)
                                                visible: !String(page.valueOf(page.taskData(plannerTaskRow.modelData), "parentTaskId", ""))
                                                text: qsTr("项目/标签")
                                                Accessible.name: qsTr("编辑项目和标签")
                                                onClicked: page.editOrganization(plannerTaskRow.modelData)
                                            }
                                            ToolButton {
                                                objectName: "plannerDeleteButton_" + page.taskId(plannerTaskRow.modelData)
                                                text: qsTr("删除")
                                                onClicked: page.deleteTask(plannerTaskRow.modelData)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Label {
                visible: page.notice !== "" || String(page.valueOf(page.snapshot, "notice", "")) !== ""
                Layout.fillWidth: true
                text: qsTr(String(page.valueOf(page.snapshot, "notice", "")) || String(page.notice))
                color: Boolean(page.valueOf(page.snapshot, "noticeIsError", false)) || page.noticeIsError
                       ? page.red : page.success
                font.family: page.fontFamily
                font.pixelSize: 12
                wrapMode: Text.Wrap
                padding: 5
            }
        }
    }

    Dialog {
        id: editDraftDialog
        objectName: "plannerEditDraftDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, page.width - 24)
        title: qsTr("编辑这项待办？")
        contentItem: Label {
            text: qsTr("当前有未提交的待办草稿。继续编辑会清除这份草稿。")
            color: page.ink
            wrapMode: Text.Wrap
        }
        footer: RowLayout {
            Button {
                text: qsTr("继续保留草稿")
                onClicked: {
                    editDraftDialog.reject()
                    page.pendingEditRecord = null
                }
            }
            Button {
                objectName: "plannerEditDraftConfirmButton"
                text: qsTr("放弃草稿并编辑")
                highlighted: true
                onClicked: {
                    editDraftDialog.close()
                    page.startTaskEdit(page.pendingEditRecord)
                    page.pendingEditRecord = null
                }
            }
        }
    }

    Dialog {
        id: calendarDialog
        objectName: "plannerCalendarDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(350, page.width - 24)
        title: qsTr("选择日期")
        property int year: new Date().getFullYear()
        property int month: new Date().getMonth()

        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Button { text: "‹"; Accessible.name: qsTr("上个月"); onClicked: {
                    if (calendarDialog.month === 0) { calendarDialog.month = 11; calendarDialog.year -= 1 }
                    else calendarDialog.month -= 1
                } }
                Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("%1 年 %2 月").arg(calendarDialog.year).arg(calendarDialog.month + 1)
                    font.bold: true
                }
                Button { text: "›"; Accessible.name: qsTr("下个月"); onClicked: {
                    if (calendarDialog.month === 11) { calendarDialog.month = 0; calendarDialog.year += 1 }
                    else calendarDialog.month += 1
                } }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 7
                Repeater {
                    model: ["日", "一", "二", "三", "四", "五", "六"]
                        delegate: Label { id: weekdayLabel; required property string modelData; text: qsTr(String(weekdayLabel.modelData)); color: page.muted; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                }
                Repeater {
                    model: page.calendarCells(calendarDialog.year, calendarDialog.month)
                    delegate: Button {
                        id: calendarDayButton
                        required property var modelData
                        Layout.fillWidth: true
                        text: String(calendarDayButton.modelData.day)
                        opacity: calendarDayButton.modelData.inMonth ? 1 : 0.45
                        highlighted: calendarDayButton.modelData.key === page.selectedDateText
                        onClicked: {
                            page.selectedDateText = calendarDayButton.modelData.key
                            page.queueDraftSave()
                            calendarDialog.close()
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: subtaskDialog
        objectName: "plannerSubtaskDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, page.width - 24)
        title: qsTr("添加子任务")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: qsTr("添加到：%1").arg(page.selectedParentTitle)
                color: page.muted
                wrapMode: Text.Wrap
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { objectName: "plannerSubtaskTitleLabel"; text: qsTr("子任务内容"); color: page.muted }
                UiTextField {
                    id: subtaskTitleField
                    objectName: "plannerSubtaskTitleInput"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    Accessible.name: qsTr("子任务内容")
                    maximumLength: 60
                    placeholderText: qsTr("例如：检查安装包")
                    onAccepted: page.confirmSubtask()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("取消"); onClicked: subtaskDialog.close() }
                Button {
                    objectName: "plannerSubtaskConfirmButton"
                    text: qsTr("加入")
                    highlighted: true
                    enabled: subtaskTitleField.text.trim().length > 0
                    onClicked: page.confirmSubtask()
                }
            }
        }
    }

    FileDialog {
        id: calendarImportDialog
        objectName: "plannerCalendarImportDialog"
        title: qsTr("导入 iCalendar 文件")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("iCalendar 文件 (*.ics)")]
        onAccepted: page.importCalendar(selectedFile)
    }

    Dialog {
        id: calendarSubscriptionsDialog
        objectName: "plannerCalendarSubscriptionsDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(760, page.width - 24)
        height: Math.min(Math.min(720, page.height - 24), calendarSubscriptionsContent.implicitHeight + 64)
        title: qsTr("日历订阅")
        background: Rectangle {
            color: page.surface
            border.color: page.line
            radius: 16
        }
        header: Rectangle {
            implicitHeight: calendarSubscriptionsTitle.implicitHeight + 24
            color: page.surface
            Label {
                id: calendarSubscriptionsTitle
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                verticalAlignment: Text.AlignVCenter
                text: calendarSubscriptionsDialog.title
                color: page.ink
                font.family: page.fontFamily
                font.pixelSize: 18
                font.bold: true
            }
        }
        contentItem: ColumnLayout {
            id: calendarSubscriptionsContent
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: qsTr("添加只读 iCalendar 订阅。建议使用 HTTPS；链接会在本机加密保存，不会显示在列表中。")
                color: page.muted
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.preferredWidth: 190
                    Label { objectName: "plannerCalendarSubscriptionNameLabel"; text: qsTr("订阅名称"); color: page.muted }
                    UiTextField {
                        id: calendarSubscriptionNameField
                        objectName: "plannerCalendarSubscriptionNameInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("订阅名称")
                        placeholderText: qsTr("可选")
                        maximumLength: 80
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerCalendarSubscriptionUrlLabel"; text: qsTr("订阅地址"); color: page.muted }
                    UiTextField {
                        id: calendarSubscriptionUrlField
                        objectName: "plannerCalendarSubscriptionUrlInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("订阅地址")
                        placeholderText: qsTr("HTTPS / webcal 日历订阅地址")
                        maximumLength: 2048
                        onAccepted: page.addCalendarSubscription()
                    }
                }
                Button {
                    objectName: "plannerCalendarSubscriptionAddButton"
                    text: qsTr("添加并同步")
                    highlighted: true
                    enabled: calendarSubscriptionUrlField.text.trim().length > 0
                    onClicked: page.addCalendarSubscription()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: qsTr("刷新失败时会保留上次成功同步的事件。删除订阅会删除其缓存事件。")
                    color: page.muted
                    wrapMode: Text.WordWrap
                }
                Button {
                    objectName: "plannerCalendarSubscriptionRefreshAllButton"
                    text: qsTr("全部刷新")
                    enabled: page.asList(page.valueOf(page.snapshot, "calendarSubscriptions", [])).length > 0
                    onClicked: page.refreshAllCalendarSubscriptions()
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: page.line }
            Flickable {
                objectName: "plannerCalendarSubscriptionList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(88, Math.min(260, subscriptionListColumn.implicitHeight))
                clip: true
                contentWidth: width
                contentHeight: subscriptionListColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ColumnLayout {
                    id: subscriptionListColumn
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: page.asList(page.valueOf(page.snapshot, "calendarSubscriptions", []))
                        delegate: Frame {
                            id: subscriptionRow
                            required property var modelData
                            Layout.fillWidth: true
                            padding: 10
                            background: Rectangle { radius: 10; color: page.surfaceSoft; border.color: page.line }
                            RowLayout {
                                anchors.fill: parent
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(page.valueOf(subscriptionRow.modelData, "name", "日历订阅"))
                                              + " · " + String(page.valueOf(subscriptionRow.modelData, "host", ""))
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: Boolean(page.valueOf(subscriptionRow.modelData, "refreshing", false))
                                              ? qsTr("正在同步…")
                                              : String(page.valueOf(subscriptionRow.modelData, "lastError", "")
                                                       || (String(page.valueOf(subscriptionRow.modelData, "lastSuccessAt", ""))
                                                           ? qsTr("最近成功：%1").arg(String(page.valueOf(subscriptionRow.modelData, "lastSuccessAt", "")))
                                                           : qsTr("尚未成功同步")))
                                        color: String(page.valueOf(subscriptionRow.modelData, "lastError", "")) ? page.red : page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                    Label {
                                        text: qsTr("缓存事件：%1").arg(Number(page.valueOf(subscriptionRow.modelData, "eventCount", 0)))
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 11
                                    }
                                }
                                Button {
                                    objectName: "plannerCalendarSubscriptionRefresh_" + String(page.valueOf(subscriptionRow.modelData, "id", ""))
                                    text: qsTr("刷新")
                                    enabled: !Boolean(page.valueOf(subscriptionRow.modelData, "refreshing", false))
                                    onClicked: page.refreshCalendarSubscription(String(page.valueOf(subscriptionRow.modelData, "id", "")))
                                }
                                Button {
                                    objectName: "plannerCalendarSubscriptionRemove_" + String(page.valueOf(subscriptionRow.modelData, "id", ""))
                                    text: qsTr("删除")
                                    onClicked: {
                                        page.selectedCalendarSubscriptionId = String(page.valueOf(subscriptionRow.modelData, "id", ""))
                                        page.selectedCalendarSubscriptionName = String(page.valueOf(subscriptionRow.modelData, "name", "日历订阅"))
                                        removeCalendarSubscriptionDialog.open()
                                    }
                                }
                            }
                        }
                    }
                    Label {
                        visible: page.asList(page.valueOf(page.snapshot, "calendarSubscriptions", [])).length === 0
                        Layout.fillWidth: true
                        text: qsTr("添加订阅后，可在此查看最近同步状态和缓存事件数。")
                        color: page.muted
                        horizontalAlignment: Text.AlignHCenter
                        padding: 24
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("关闭"); onClicked: calendarSubscriptionsDialog.close() }
            }
        }
    }

    Dialog {
        id: caldavAccountsDialog
        objectName: "plannerCalDAVAccountsDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(760, page.width - 24)
        height: Math.min(Math.min(720, page.height - 24), caldavAccountsContent.implicitHeight + 64)
        title: qsTr("CalDAV 账户")
        background: Rectangle {
            color: page.surface
            border.color: page.line
            radius: 16
        }
        header: Rectangle {
            implicitHeight: caldavDialogTitle.implicitHeight + 24
            color: page.surface
            Label {
                id: caldavDialogTitle
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                verticalAlignment: Text.AlignVCenter
                text: caldavAccountsDialog.title
                color: page.ink
                font.family: page.fontFamily
                font.pixelSize: 18
                font.bold: true
            }
        }
        contentItem: ColumnLayout {
            id: caldavAccountsContent
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: qsTr("填写具体的 CalDAV 日历集地址。已保存账户会在应用启动时及此后每小时自动同步，也可手动立即同步支持的 VEVENT 日程和 VTODO 待办；VEVENT 只读，重复待办暂不支持。只有服务器提供强 ETag 时才会回写 VTODO 完成状态。账号密码在本机加密保存，含登录信息的地址必须使用 HTTPS。")
                color: page.muted
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.preferredWidth: 160
                    Label { objectName: "plannerCalDAVNameLabel"; text: qsTr("账户名称"); color: page.muted }
                    UiTextField {
                        id: caldavAccountNameField
                        objectName: "plannerCalDAVNameInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("账户名称")
                        placeholderText: qsTr("可选")
                        maximumLength: 80
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerCalDAVUrlLabel"; text: qsTr("CalDAV 日历集地址"); color: page.muted }
                    UiTextField {
                        id: caldavAccountUrlField
                        objectName: "plannerCalDAVUrlInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("CalDAV 日历集地址")
                        placeholderText: qsTr("HTTPS CalDAV 日历集地址")
                        maximumLength: 2048
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerCalDAVUsernameLabel"; text: qsTr("账号"); color: page.muted }
                    UiTextField {
                        id: caldavAccountUsernameField
                        objectName: "plannerCalDAVUsernameInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("账号")
                        placeholderText: qsTr("公开日历可留空")
                        maximumLength: 256
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerCalDAVPasswordLabel"; text: qsTr("密码 / 应用专用密码"); color: page.muted }
                    UiTextField {
                        id: caldavAccountPasswordField
                        objectName: "plannerCalDAVPasswordInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("密码 / 应用专用密码")
                        placeholderText: qsTr("密码或应用专用密码")
                        maximumLength: 1024
                        echoMode: TextInput.Password
                    }
                }
                Item { Layout.fillWidth: true; Layout.preferredWidth: 0 }
                Button {
                    objectName: "plannerCalDAVAddButton"
                    text: qsTr("保存并检测")
                    highlighted: true
                    enabled: caldavAccountUrlField.text.trim().length > 0
                    onClicked: page.addCalDAVAccount()
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: page.line }
            Flickable {
                objectName: "plannerCalDAVAccountList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(88, Math.min(260, caldavAccountColumn.implicitHeight))
                clip: true
                contentWidth: width
                contentHeight: caldavAccountColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ColumnLayout {
                    id: caldavAccountColumn
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: page.asList(page.valueOf(page.snapshot, "caldavAccounts", []))
                        delegate: Frame {
                            id: caldavAccountRow
                            required property var modelData
                            Layout.fillWidth: true
                            padding: 10
                            background: Rectangle { radius: 10; color: page.surfaceSoft; border.color: page.line }
                            RowLayout {
                                anchors.fill: parent
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Label {
                                        Layout.fillWidth: true
                                        text: String(page.valueOf(caldavAccountRow.modelData, "name", "CalDAV"))
                                              + " · " + String(page.valueOf(caldavAccountRow.modelData, "host", ""))
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        objectName: "plannerCalDAVAccountStatus_" + String(page.valueOf(caldavAccountRow.modelData, "id", ""))
                                        Layout.fillWidth: true
                                        text: page.caldavAccountStatus(caldavAccountRow.modelData)
                                        color: (String(page.valueOf(caldavAccountRow.modelData, "lastError", ""))
                                               || String(page.valueOf(caldavAccountRow.modelData, "lastSyncError", "")))
                                               ? page.red : page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                }
                                Button {
                                    objectName: "plannerCalDAVSync_" + String(page.valueOf(caldavAccountRow.modelData, "id", ""))
                                    text: qsTr("同步日历内容")
                                    enabled: !Boolean(page.valueOf(caldavAccountRow.modelData, "checking", false))
                                             && !Boolean(page.valueOf(caldavAccountRow.modelData, "syncing", false))
                                             && page.caldavAccountHasSyncableContent(caldavAccountRow.modelData)
                                    onClicked: page.syncCalDAVCalendar(String(page.valueOf(caldavAccountRow.modelData, "id", "")))
                                }
                                Button {
                                    objectName: "plannerCalDAVCheck_" + String(page.valueOf(caldavAccountRow.modelData, "id", ""))
                                    text: qsTr("重新检测")
                                    enabled: !Boolean(page.valueOf(caldavAccountRow.modelData, "checking", false))
                                    onClicked: page.checkCalDAVAccount(String(page.valueOf(caldavAccountRow.modelData, "id", "")))
                                }
                                Button {
                                    objectName: "plannerCalDAVRemove_" + String(page.valueOf(caldavAccountRow.modelData, "id", ""))
                                    text: qsTr("移除")
                                    onClicked: page.requestRemoveCalDAVAccount(
                                                   String(page.valueOf(caldavAccountRow.modelData, "id", "")),
                                                   String(page.valueOf(caldavAccountRow.modelData, "name", "CalDAV"))
                                                           + " · "
                                                           + String(page.valueOf(caldavAccountRow.modelData, "host", "")))
                                }
                            }
                        }
                    }
                    Label {
                        visible: page.asList(page.valueOf(page.snapshot, "caldavAccounts", [])).length === 0
                        Layout.fillWidth: true
                        text: qsTr("添加账户后，可在此查看连接状态并同步支持的 VEVENT 日程和 VTODO 待办。")
                        color: page.muted
                        horizontalAlignment: Text.AlignHCenter
                        padding: 24
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("关闭"); onClicked: caldavAccountsDialog.close() }
            }
        }
    }

    Dialog {
        id: caldavAccountRemoveDialog
        objectName: "plannerCalDAVAccountRemoveDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, page.width - 24)
        title: qsTr("移除 CalDAV 账户")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                objectName: "plannerCalDAVAccountRemoveMessage"
                Layout.fillWidth: true
                text: qsTr("移除“%1”会删除本机保存的登录信息和它同步的日历事件；已导入的远程待办会保留为本机记录，但不再同步。继续吗？")
                      .arg(page.selectedCalDAVAccountName)
                color: page.ink
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    objectName: "plannerCalDAVAccountRemoveCancelButton"
                    text: qsTr("取消")
                    onClicked: caldavAccountRemoveDialog.close()
                }
                Button {
                    objectName: "plannerCalDAVAccountRemoveConfirmButton"
                    text: qsTr("移除账户和同步内容")
                    onClicked: page.confirmRemoveCalDAVAccount()
                }
            }
        }
    }

    Dialog {
        id: webdavPlannerDialog
        objectName: "plannerWebDavSyncDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(780, page.width - 24)
        height: Math.min(Math.min(760, page.height - 24), webdavPlannerContent.implicitHeight + 64)
        title: qsTr("跨设备日程同步")
        background: Rectangle { color: page.surface; border.color: page.line; radius: 16 }
        contentItem: ColumnLayout {
            id: webdavPlannerContent
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: qsTr("只同步本机计划任务，不包含其他生活记录。请输入 .wxbackup 完整备份地址；程序会在同一目录使用独立的加密日程文件。所有设备使用相同的日程同步密码。")
                color: page.muted
                wrapMode: Text.WordWrap
            }
            ColumnLayout {
                Layout.fillWidth: true
                Label { objectName: "plannerWebDavUrlLabel"; text: qsTr("WebDAV 完整备份文件地址"); color: page.muted }
                UiTextField {
                    id: webdavUrlField
                    objectName: "plannerWebDavUrlInput"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    Accessible.name: qsTr("WebDAV 完整备份文件地址")
                    placeholderText: "https://example.com/dav/backup.wxbackup"
                    maximumLength: 4096
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerWebDavUsernameLabel"; text: qsTr("WebDAV 用户名"); color: page.muted }
                    UiTextField {
                        id: webdavUsernameField
                        objectName: "plannerWebDavUsernameInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("WebDAV 用户名")
                        maximumLength: 512
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { objectName: "plannerWebDavPasswordLabel"; text: qsTr("WebDAV 密码"); color: page.muted }
                    UiTextField {
                        id: webdavPasswordField
                        objectName: "plannerWebDavPasswordInput"
                        uiTheme: page.uiTheme
                        Layout.fillWidth: true
                        Accessible.name: qsTr("WebDAV 密码")
                        maximumLength: 1024
                        echoMode: TextInput.Password
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Label { objectName: "plannerWebDavPassphraseLabel"; text: qsTr("日程同步密码（至少 12 个字符）"); color: page.muted }
                UiTextField {
                    id: webdavPassphraseField
                    objectName: "plannerWebDavPassphraseInput"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    Accessible.name: qsTr("日程同步密码")
                    maximumLength: 256
                    echoMode: TextInput.Password
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Label {
                    objectName: "plannerWebDavSyncStatus"
                    Layout.fillWidth: true
                    text: String(page.valueOf(page.webdavState, "message", "尚未设置 WebDAV 日程同步。"))
                    color: Boolean(page.valueOf(page.webdavState, "error", false)) ? page.red : page.muted
                    wrapMode: Text.WordWrap
                }
                Button {
                    objectName: "plannerWebDavSyncNowButton"
                    text: Boolean(page.valueOf(page.webdavState, "busy", false)) ? qsTr("同步中…") : qsTr("立即同步 / 重试")
                    enabled: Boolean(page.valueOf(page.webdavState, "configured", false))
                             && !Boolean(page.valueOf(page.webdavState, "busy", false))
                    onClicked: page.syncWebDavPlannerNow()
                }
            }
            Label {
                objectName: "plannerWebDavAccountSummary"
                Layout.fillWidth: true
                visible: Boolean(page.valueOf(page.webdavState, "configured", false))
                text: qsTr("目标：%1 / %2 · 最近同步：%3")
                      .arg(String(page.valueOf(page.webdavState, "host", "")))
                      .arg(String(page.valueOf(page.webdavState, "fileName", "")))
                      .arg(String(page.valueOf(page.webdavState, "lastSyncAt", "") || qsTr("尚未成功")))
                color: page.muted
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Button {
                    objectName: "plannerWebDavConfigureButton"
                    text: Boolean(page.valueOf(page.webdavState, "configured", false))
                          ? qsTr("保存新设置并同步") : qsTr("保存设置并同步")
                    highlighted: true
                    enabled: webdavUrlField.text.trim().length > 0
                    onClicked: page.configureWebDavPlannerSync()
                }
                Button {
                    objectName: "plannerWebDavClearButton"
                    text: qsTr("清除本机账户")
                    visible: Boolean(page.valueOf(page.webdavState, "configured", false))
                    onClicked: page.requestClearWebDavPlannerAccount()
                }
                Item { Layout.fillWidth: true }
                Button { text: qsTr("关闭"); onClicked: webdavPlannerDialog.close() }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: page.line }
            Label {
                Layout.fillWidth: true
                text: qsTr("并发冲突：%1").arg(page.webdavConflicts.length)
                color: page.ink
                font.bold: true
            }
            ListView {
                id: webdavConflictList
                objectName: "plannerWebDavConflictList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(76, Math.min(300, contentHeight))
                clip: true
                model: page.webdavConflicts
                boundsBehavior: Flickable.StopAtBounds
                spacing: 8
                delegate: Frame {
                    id: webdavConflictRow
                    required property var modelData
                    width: ListView.view.width
                    padding: 10
                    background: Rectangle { radius: 10; color: page.surfaceSoft; border.color: page.line }
                    ColumnLayout {
                        anchors.fill: parent
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("日程：%1 · %2")
                                  .arg(page.webDavConflictTitle(webdavConflictRow.modelData))
                                  .arg(String(page.valueOf(webdavConflictRow.modelData, "id", "")))
                            color: page.ink
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Repeater {
                            model: page.asList(page.valueOf(webdavConflictRow.modelData, "variants", []))
                            delegate: Frame {
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                padding: 8
                                background: Rectangle { radius: 8; color: page.surface; border.color: page.line }
                                RowLayout {
                                    anchors.fill: parent
                                    Label {
                                        Layout.fillWidth: true
                                        text: Boolean(page.valueOf(modelData, "deleted", false))
                                              ? qsTr("此设备删除了这项日程")
                                              : String(page.valueOf(page.valueOf(page.valueOf(modelData, "record", ({})), "data", ({})), "title", qsTr("未命名任务")))
                                        color: page.ink
                                        wrapMode: Text.WordWrap
                                    }
                                    Button {
                                        objectName: "plannerWebDavResolve_" + String(page.valueOf(webdavConflictRow.modelData, "id", "")) + "_" + index
                                        text: qsTr("采用此版本")
                                        onClicked: page.resolveWebDavPlannerConflict(webdavConflictRow.modelData, index, false)
                                    }
                                    Button {
                                        objectName: "plannerWebDavKeepBoth_" + String(page.valueOf(webdavConflictRow.modelData, "id", "")) + "_" + index
                                        text: qsTr("采用并保留其他分支")
                                        onClicked: page.resolveWebDavPlannerConflict(webdavConflictRow.modelData, index, true)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Label {
                visible: page.webdavConflicts.length === 0
                Layout.fillWidth: true
                text: qsTr("当前没有待处理的并发冲突。")
                color: page.muted
                horizontalAlignment: Text.AlignHCenter
                padding: 12
            }
        }
    }

    Dialog {
        id: webdavClearAccountDialog
        objectName: "plannerWebDavClearAccountDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, page.width - 24)
        title: qsTr("清除本机 WebDAV 账户")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: qsTr("清除 %1 的本机登录信息会停止后续同步。日程、冲突记录和服务器文件都会保留。继续吗？")
                      .arg(page.selectedWebDavClearName)
                color: page.ink
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("取消"); onClicked: webdavClearAccountDialog.close() }
                Button {
                    objectName: "plannerWebDavClearConfirmButton"
                    text: qsTr("清除本机账户")
                    onClicked: page.confirmClearWebDavPlannerAccount()
                }
            }
        }
    }

    Dialog {
        id: removeCalendarSubscriptionDialog
        objectName: "plannerCalendarSubscriptionRemoveDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, page.width - 24)
        title: qsTr("删除日历订阅")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: qsTr("删除“%1”及其同步的缓存日程？手动导入的日程不会删除。")
                      .arg(page.selectedCalendarSubscriptionName)
                color: page.ink
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("取消"); onClicked: removeCalendarSubscriptionDialog.close() }
                Button {
                    objectName: "plannerCalendarSubscriptionRemoveConfirmButton"
                    text: qsTr("删除订阅和缓存")
                    onClicked: page.confirmRemoveCalendarSubscription()
                }
            }
        }
    }

    FileDialog {
        id: calendarExportDialog
        objectName: "plannerCalendarExportDialog"
        title: qsTr("导出日程到 ICS")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("iCalendar 文件 (*.ics)")]
        defaultSuffix: "ics"
        onAccepted: page.showResult(
                        page.controller.exportCalendarIcs(selectedFile, page.selectedDay, page.shiftDate(page.selectedDay, 6)),
                        qsTr("ICS 日程已导出。"))
    }

    FileDialog {
        id: timesheetExportDialog
        objectName: "plannerTimesheetExportDialog"
        title: qsTr("导出工时 CSV")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("CSV 文件 (*.csv)")]
        defaultSuffix: "csv"
        onAccepted: page.showResult(
                        page.controller.exportTimesheetCsv(selectedFile, timesheetStartField.text.trim(), timesheetEndField.text.trim()),
                        qsTr("工时 CSV 已导出。"))
    }

    Dialog {
        id: timesheetDialog
        objectName: "plannerTimesheetDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(620, page.width - 24)
        height: Math.min(700, page.height - 24)
        title: qsTr("工时复盘")
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("从"); color: page.muted }
                UiTextField {
                    id: timesheetStartField
                    objectName: "plannerTimesheetStartDate"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    placeholderText: "YYYY-MM-DD"
                }
                Label { text: qsTr("到"); color: page.muted }
                UiTextField {
                    id: timesheetEndField
                    objectName: "plannerTimesheetEndDate"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    placeholderText: "YYYY-MM-DD"
                }
                UiButton { uiTheme: page.uiTheme; text: qsTr("更新统计"); onClicked: page.loadTimesheet() }
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("实际 %1 · 估算 %2 · 差额 %3")
                      .arg(page.formatElapsed(Number(page.valueOf(page.timesheetReport.totals, "actualSeconds", 0))))
                      .arg(page.formatElapsed(Number(page.valueOf(page.timesheetReport.totals, "estimatedSeconds", 0))))
                      .arg(page.formatVariance(Number(page.valueOf(page.timesheetReport.totals, "actualSeconds", 0))
                                               - Number(page.valueOf(page.timesheetReport.totals, "estimatedSeconds", 0))))
                color: page.accentStrong
                font.family: page.fontFamily
                font.pixelSize: 14
                font.bold: true
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("专注 %1 次 · 活跃 %2 天 · 日均 %3 · 估算准确度 %4%")
                      .arg(Number(page.valueOf(page.timesheetReport.totals, "sessionCount", 0)))
                      .arg(Number(page.valueOf(page.timesheetReport.totals, "activeDays", 0)))
                      .arg(page.formatElapsed(Number(page.valueOf(page.timesheetReport.totals, "averageFocusSecondsPerActiveDay", 0))))
                      .arg(Number(page.valueOf(page.timesheetReport.totals, "estimateAccuracyPercent", 0)))
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 12
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ColumnLayout {
                    width: parent.width
                    spacing: 6
                    Label { text: qsTr("每日工时"); color: page.ink; font.bold: true }
                    Repeater {
                        model: page.asList(page.valueOf(page.timesheetReport, "days", []))
                        delegate: RowLayout {
                            id: timesheetDayRow
                            required property var modelData
                            Layout.fillWidth: true
                            Label { text: String(timesheetDayRow.modelData.date); color: page.ink; Layout.fillWidth: true }
                            Label { text: qsTr("实际 %1").arg(page.formatElapsed(Number(timesheetDayRow.modelData.actualSeconds))); color: page.accent }
                            Label { text: qsTr("估算 %1").arg(page.formatElapsed(Number(timesheetDayRow.modelData.estimatedSeconds))); color: page.muted }
                        }
                    }
                    Label { text: qsTr("任务估算与实际"); color: page.ink; font.bold: true; Layout.topMargin: 8 }
                    Repeater {
                        model: page.asList(page.valueOf(page.timesheetReport, "tasks", []))
                        delegate: ColumnLayout {
                            id: timesheetTaskRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                text: String(timesheetTaskRow.modelData.title)
                                      + (String(timesheetTaskRow.modelData.project || "") ? " · " + String(timesheetTaskRow.modelData.project) : "")
                                color: page.ink
                                font.bold: true
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Label {
                                text: qsTr("实际 %1 · 估算 %2 · 差额 %3")
                                      .arg(page.formatElapsed(Number(timesheetTaskRow.modelData.actualSeconds)))
                                      .arg(page.formatElapsed(Number(timesheetTaskRow.modelData.estimatedSeconds)))
                                      .arg(page.formatVariance(Number(timesheetTaskRow.modelData.actualSeconds) - Number(timesheetTaskRow.modelData.estimatedSeconds)))
                                color: page.muted
                                font.pixelSize: 12
                                Layout.fillWidth: true
                            }
                            Label {
                                text: qsTr("专注 %1 次").arg(Number(timesheetTaskRow.modelData.sessionCount))
                                color: page.muted
                                font.pixelSize: 11
                            }
                        }
                    }
                    Label { text: qsTr("项目汇总"); color: page.ink; font.bold: true; Layout.topMargin: 8 }
                    Repeater {
                        model: page.asList(page.valueOf(page.timesheetReport, "projects", []))
                        delegate: RowLayout {
                            id: timesheetProjectRow
                            required property var modelData
                            Layout.fillWidth: true
                            Label { text: String(timesheetProjectRow.modelData.name); color: page.ink; Layout.fillWidth: true }
                            Label { text: page.formatElapsed(Number(timesheetProjectRow.modelData.actualSeconds)); color: page.accent }
                        }
                    }
                    Label { text: qsTr("标签汇总"); color: page.ink; font.bold: true; Layout.topMargin: 8 }
                    Repeater {
                        model: page.asList(page.valueOf(page.timesheetReport, "tags", []))
                        delegate: RowLayout {
                            id: timesheetTagRow
                            required property var modelData
                            Layout.fillWidth: true
                            Label { text: String(timesheetTagRow.modelData.name); color: page.ink; Layout.fillWidth: true }
                            Label { text: page.formatElapsed(Number(timesheetTagRow.modelData.actualSeconds)); color: page.accent }
                        }
                    }
                }
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            UiButton { uiTheme: page.uiTheme; text: qsTr("导出 CSV"); onClicked: page.exportTimesheet() }
            UiButton { uiTheme: page.uiTheme; text: qsTr("关闭"); onClicked: timesheetDialog.close() }
        }
    }

    Dialog {
        id: focusDialog
        objectName: "plannerFocusDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, page.width - 24)
        title: qsTr("开始任务专注")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: qsTr("任务：%1").arg(page.selectedFocusTaskTitle)
                color: page.muted
                wrapMode: Text.Wrap
            }
            UiButton {
                objectName: "plannerFocusHelpButton"
                uiTheme: page.uiTheme
                text: qsTr("需要一个启动提示？")
                Accessible.name: qsTr("我有点拖延，给我一个启动提示")
                onClicked: page.openProcrastinationHelp()
            }
            UiComboBox {
                id: focusModeBox
                objectName: "plannerFocusModeCombo"
                uiTheme: page.uiTheme
                accessibleName: qsTr("计时方式")
                Layout.fillWidth: true
                model: [qsTr("番茄钟 · 25 分钟"), qsTr("Flowtime · 自由计时"), qsTr("倒计时 · 自定义时长")]
            }
            RowLayout {
                Layout.fillWidth: true
                visible: focusModeBox.currentIndex === 2
                Label { text: qsTr("时长（分钟）"); color: page.ink }
                SpinBox {
                    id: focusDurationBox
                    objectName: "plannerFocusDuration"
                    Accessible.name: qsTr("时长（分钟）")
                    from: 5
                    to: 480
                    stepSize: 5
                    editable: true
                }
                Item { Layout.fillWidth: true }
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("计时会保存到该任务；退出工作台时会自动暂停。番茄钟结束后会提醒你休息 5 分钟。")
                color: page.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            UiButton { uiTheme: page.uiTheme; text: qsTr("取消"); onClicked: focusDialog.close() }
            UiButton {
                objectName: "plannerFocusStartButton"
                uiTheme: page.uiTheme
                text: qsTr("开始专注")
                highlighted: true
                onClicked: page.confirmFocusSession()
            }
        }
    }

    Dialog {
        id: procrastinationHelpDialog
        objectName: "plannerProcrastinationHelpDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, page.width - 24)
        title: qsTr("先迈出一小步")
        contentItem: ColumnLayout {
            spacing: 14
            Label {
                objectName: "plannerProcrastinationTip"
                Layout.fillWidth: true
                text: page.procrastinationTips[page.procrastinationTipIndex]
                color: page.ink
                font.pixelSize: 16
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("不用一次完成整件事。选一个够小的下一步，然后再决定接下来怎么做。")
                color: page.muted
                wrapMode: Text.Wrap
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            UiButton {
                objectName: "plannerNextProcrastinationTipButton"
                uiTheme: page.uiTheme
                text: qsTr("换一个方法")
                onClicked: page.nextProcrastinationTip()
            }
            UiButton {
                objectName: "plannerCloseProcrastinationHelpButton"
                uiTheme: page.uiTheme
                text: qsTr("回到任务")
                highlighted: true
                onClicked: procrastinationHelpDialog.close()
            }
        }
    }

    Dialog {
        id: customBoardDialog
        objectName: "plannerCustomBoardDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(760, page.width - 24)
        height: Math.min(620, page.height - 24)
        title: page.customBoardEditorId ? qsTr("编辑自定义看板") : qsTr("新建自定义看板")
        contentItem: ColumnLayout {
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: qsTr("按任务状态和可选标签组成列。把待办拖到其他列即可更新状态并添加列标签。")
                color: page.muted
                wrapMode: Text.Wrap
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { objectName: "plannerCustomBoardNameLabel"; text: qsTr("看板名称"); color: page.muted }
                UiTextField {
                    id: customBoardNameField
                    objectName: "plannerCustomBoardNameInput"
                    uiTheme: page.uiTheme
                    Layout.fillWidth: true
                    Accessible.name: qsTr("看板名称")
                    maximumLength: 40
                    placeholderText: qsTr("例如：发布流程")
                }
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ColumnLayout {
                    width: Math.max(0, customBoardDialog.width - 60)
                    spacing: 8
                    Repeater {
                        model: page.customBoardEditorColumns
                        delegate: Frame {
                            id: customBoardEditorRow
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            padding: 8
                            background: Rectangle { radius: 10; color: page.surfaceSoft; border.color: page.line }
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: qsTr("列名称"); color: page.muted }
                                    UiTextField {
                                        objectName: "plannerBoardColumnTitle_" + customBoardEditorRow.index
                                        uiTheme: page.uiTheme
                                        Layout.fillWidth: true
                                        maximumLength: 32
                                        text: String(customBoardEditorRow.modelData.title || "")
                                        placeholderText: qsTr("列名称")
                                        onTextEdited: page.updateCustomBoardColumn(customBoardEditorRow.index, "title", text)
                                    }
                                    ToolButton {
                                        text: "×"
                                        Accessible.name: qsTr("删除此列")
                                        enabled: page.customBoardEditorColumns.length > 2
                                        onClicked: page.removeCustomBoardColumn(customBoardEditorRow.index)
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: qsTr("列规则"); color: page.muted }
                                    UiComboBox {
                                        objectName: "plannerBoardColumnStatus_" + customBoardEditorRow.index
                                        uiTheme: page.uiTheme
                                        accessibleName: qsTr("看板列状态")
                                        Layout.fillWidth: true
                                        model: [qsTr("待办"), qsTr("进行中"), qsTr("完成")]
                                        currentIndex: Math.max(0, ["todo", "doing", "done"].indexOf(String(customBoardEditorRow.modelData.status)))
                                        onActivated: page.updateCustomBoardColumn(
                                                         customBoardEditorRow.index, "status",
                                                         ["todo", "doing", "done"][currentIndex])
                                    }
                                    UiComboBox {
                                        objectName: "plannerBoardColumnTag_" + customBoardEditorRow.index
                                        uiTheme: page.uiTheme
                                        accessibleName: qsTr("看板列标签")
                                        Layout.fillWidth: true
                                        model: [qsTr("不限标签")].concat(page.tags)
                                        currentIndex: {
                                            var selectedTag = String(customBoardEditorRow.modelData.tag || "")
                                            return selectedTag ? Math.max(0, page.tags.indexOf(selectedTag) + 1) : 0
                                        }
                                        onActivated: page.updateCustomBoardColumn(
                                                         customBoardEditorRow.index, "tag",
                                                         currentIndex > 0 ? page.tags[currentIndex - 1] : "")
                                    }
                                }
                            }
                        }
                    }
                    UiButton {
                        objectName: "plannerAddBoardColumnButton"
                        uiTheme: page.uiTheme
                        text: qsTr("添加一列")
                        enabled: page.customBoardEditorColumns.length < 8
                        onClicked: page.addCustomBoardColumn()
                    }
                }
            }
        }
        footer: RowLayout {
            UiButton {
                objectName: "plannerDeleteBoardButton"
                visible: page.customBoardEditorId !== ""
                uiTheme: page.uiTheme
                text: qsTr("删除看板")
                onClicked: customBoardDeleteDialog.open()
            }
            Item { Layout.fillWidth: true }
            UiButton { uiTheme: page.uiTheme; text: qsTr("取消"); onClicked: customBoardDialog.close() }
            UiButton {
                objectName: "plannerSaveBoardButton"
                uiTheme: page.uiTheme
                text: qsTr("保存看板")
                highlighted: true
                onClicked: page.saveCustomBoard()
            }
        }
    }

    Dialog {
        id: customBoardDeleteDialog
        objectName: "plannerCustomBoardDeleteDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(380, page.width - 24)
        title: qsTr("删除这个看板？")
        contentItem: Label {
            text: qsTr("只会删除看板配置，不会删除任何待办。")
            color: page.ink
            wrapMode: Text.Wrap
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            UiButton { uiTheme: page.uiTheme; text: qsTr("取消"); onClicked: customBoardDeleteDialog.close() }
            UiButton {
                objectName: "plannerConfirmDeleteBoardButton"
                uiTheme: page.uiTheme
                text: qsTr("删除看板")
                highlighted: true
                onClicked: page.deleteCustomBoard()
            }
        }
    }

    Dialog {
        id: organizationDialog
        objectName: "plannerOrganizationDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, page.width - 24)
        title: qsTr("编辑项目和标签")

        contentItem: ColumnLayout {
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: qsTr("任务：%1").arg(page.selectedOrganizationTitle)
                color: page.muted
                font.family: page.fontFamily
                wrapMode: Text.WordWrap
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { objectName: "plannerOrganizationProjectLabel"; text: qsTr("项目"); color: page.muted }
                UiTextField {
                    id: organizationProjectField
                    uiTheme: page.uiTheme
                    objectName: "plannerOrganizationProjectInput"
                    Layout.fillWidth: true
                    Accessible.name: qsTr("所属项目")
                    maximumLength: 60
                    placeholderText: qsTr("可选")
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { objectName: "plannerOrganizationTagsLabel"; text: qsTr("标签"); color: page.muted }
                UiTextField {
                    id: organizationTagsField
                    uiTheme: page.uiTheme
                    objectName: "plannerOrganizationTagsInput"
                    Layout.fillWidth: true
                    Accessible.name: qsTr("任务标签")
                    maximumLength: 400
                    placeholderText: qsTr("用逗号分隔；最多 12 个")
                }
            }
        }

        footer: RowLayout {
            Item { Layout.fillWidth: true }
            UiButton { uiTheme: page.uiTheme; text: qsTr("取消"); onClicked: organizationDialog.close() }
            UiButton {
                objectName: "plannerOrganizationSaveButton"
                uiTheme: page.uiTheme
                text: qsTr("保存")
                highlighted: true
                onClicked: page.confirmOrganization()
            }
        }
    }

    Dialog {
        id: deleteDialog
        objectName: "plannerDeleteDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(400, page.width - 24)
        title: qsTr("删除这件待办？")
        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: page.selectedDeleteSubtaskCount > 0
                      ? qsTr("确定删除“%1”及其 %2 个子任务吗？删除后无法撤回。")
                        .arg(page.selectedDeleteTitle).arg(page.selectedDeleteSubtaskCount)
                      : qsTr("确定删除“%1”吗？删除后无法撤回。")
                        .arg(page.selectedDeleteTitle)
                color: page.ink
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: qsTr("取消"); onClicked: deleteDialog.close() }
                Button { objectName: "plannerDeleteConfirmButton"; text: qsTr("删除"); highlighted: true; onClicked: page.confirmDelete() }
            }
        }
    }

    Component.onCompleted: {
        restoreDraft()
    }
}
