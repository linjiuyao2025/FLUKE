pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "habitPage"

    property var controller: null
    property var uiTheme: null
    readonly property var snapshot: controller ? (controller.state || ({})) : ({})
    readonly property var habits: asList(snapshot.habits)
    readonly property var todayHabits: habits.filter(function(habit) {
        return page.habitActiveOnDate(habit, String(valueOf(snapshot, "today", dateKey(0))))
    })
    readonly property var metrics: snapshot.metrics || ({})
    readonly property bool hasAnyRecordedHistory: hasLoggedEntryBefore()
    readonly property bool hasRecentRecordedHistory: hasLoggedEntryWithinDays(30)
    property string notice: ""
    property string noticeKind: "info"
    property string selectedDeleteId: ""
    property string selectedDeleteName: ""
    property string selectedEditId: ""
    property var selectedWeekdays: []

    readonly property color canvas: uiTheme ? uiTheme.canvas : "#f6f5f0"
    readonly property color sidebar: uiTheme ? uiTheme.sidebar : "#efede7"
    readonly property color surface: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color surfaceSoft: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color controlBorder: uiTheme ? uiTheme.controlBorder : "#807d76"
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
    readonly property string sansFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property string serifFamily: uiTheme ? uiTheme.serifFamily : "Noto Serif SC"
    readonly property string yesterdayReviewEmptyText: qsTr("昨天的记录会汇总在这里，帮你看到持续的小进步。")
    readonly property color blue: accent
    readonly property color red: danger
    readonly property color paper: canvas
    readonly property color white: surface
    readonly property string fontFamily: sansFamily

    function asList(value) {
        return UiPageUtils.asList(value, true)
    }

    function valueOf(object, key, fallback) {
        return UiPageUtils.valueOf(object, key, fallback)
    }

    function habitId(habit) {
        return String(valueOf(habit, "id", valueOf(habit, "key", "")))
    }

    function habitType(habit) {
        var type = String(valueOf(habit, "type", "check"))
        return type === "counter" || type === "number" ? type : "check"
    }

    function habitTarget(habit) {
        var target = Number(valueOf(habit, "target", 1))
        return isFinite(target) && target > 0 ? target : 1
    }

    function dateKey(offset) {
        var d = new Date()
        d.setHours(12, 0, 0, 0)
        d.setDate(d.getDate() - offset)
        return String(d.getFullYear()) + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
    }

    function hasLoggedEntryBefore() {
        for (var habitIndex = 0; habitIndex < page.habits.length; ++habitIndex) {
            var entries = page.valueOf(page.habits[habitIndex], "entries", ({}))
            if (entries && Object.keys(entries).length > 0)
                return true
        }
        return false
    }

    function hasLoggedEntryWithinDays(days) {
        var start = page.dateKey(Math.max(0, Number(days) - 1))
        var end = String(page.snapshot.today || page.dateKey(0))
        for (var habitIndex = 0; habitIndex < page.habits.length; ++habitIndex) {
            var entries = page.valueOf(page.habits[habitIndex], "entries", ({}))
            if (!entries || typeof entries !== "object")
                continue
            var recordedDates = Object.keys(entries)
            for (var dateIndex = 0; dateIndex < recordedDates.length; ++dateIndex) {
                var recordedDate = recordedDates[dateIndex]
                if (recordedDate >= start && recordedDate <= end)
                    return true
            }
        }
        return false
    }

    function pad2(value) {
        return value < 10 ? "0" + value : String(value)
    }

    function entryFor(habit, key) {
        var entries = valueOf(habit, "entries", ({}))
        var entry = valueOf(entries, key, undefined)
        if (entry === undefined) {
            var stats = statFor(habit)
            var series = valueOf(stats, "entries", valueOf(stats, "days", undefined))
            entry = valueOf(series, key, undefined)
        }
        if (entry === undefined)
            return 0
        if (typeof entry === "object" && entry !== null)
            entry = valueOf(entry, "value", valueOf(entry, "count", valueOf(entry, "completed", 0)))
        var number = Number(entry)
        return isFinite(number) ? Math.max(0, number) : 0
    }

    function todayValue(habit) {
        return entryFor(habit, String(valueOf(snapshot, "today", dateKey(0))))
    }

    function isDone(habit) {
        return todayValue(habit) >= habitTarget(habit)
    }

    function habitCreatedOnDate(habit, key) {
        var createdDate = String(valueOf(habit, "createdDate", ""))
        return !/^\d{4}-\d{2}-\d{2}$/.test(createdDate) || key >= createdDate
    }

    function habitDueOnDate(habit, key) {
        var history = asList(valueOf(statFor(habit), "history", []))
        for (var index = 0; index < history.length; ++index) {
            if (String(valueOf(history[index], "date", "")) === key)
                return Boolean(valueOf(history[index], "due", true))
        }
        var schedule = valueOf(habit, "schedule", ({}))
        if (valueOf(schedule, "type", "daily") !== "weekdays")
            return true
        var parsed = new Date(key + "T12:00:00")
        if (!isFinite(parsed.getTime()))
            return true
        var weekday = parsed.getDay() || 7
        return asList(valueOf(schedule, "days", [])).indexOf(weekday) >= 0
    }

    function habitActiveOnDate(habit, key) {
        return habitCreatedOnDate(habit, key) && habitDueOnDate(habit, key)
    }

    function scheduleLabel(habit) {
        var schedule = valueOf(habit, "schedule", ({}))
        if (valueOf(schedule, "type", "daily") !== "weekdays")
            return qsTr("每天")
        var labels = [qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六"), qsTr("日")]
        var days = asList(valueOf(schedule, "days", []))
        var selected = []
        for (var i = 0; i < days.length; ++i) {
            var day = Number(days[i])
            if (day >= 1 && day <= 7)
                selected.push(labels[day - 1])
        }
        return qsTr("每周 %1").arg(selected.join("、"))
    }

    function toggleWeekday(day) {
        var updated = asList(selectedWeekdays)
        var position = updated.indexOf(day)
        if (position >= 0)
            updated.splice(position, 1)
        else
            updated.push(day)
        selectedWeekdays = updated.sort(function(a, b) { return a - b })
    }

    function statFor(habit) {
        var allStats = metrics.habitStats
        var id = habitId(habit)
        if (allStats && typeof allStats === "object" && typeof allStats.length !== "number") {
            var byKey = valueOf(allStats, id, undefined)
            if (byKey !== undefined)
                return byKey
        }
        var statsList = asList(allStats)
        for (var i = 0; i < statsList.length; ++i) {
            var stat = statsList[i]
            if (String(valueOf(stat, "id", valueOf(stat, "key", valueOf(stat, "habitId", "")))) === id)
                return stat
        }
        return ({})
    }

    function heatValue(habit, offset) {
        var key = dateKey(offset)
        if (!habitActiveOnDate(habit, key))
            return 0
        var value = entryFor(habit, key)
        if (value > 0)
            return value
        var completedDates = asList(valueOf(habit, "completedDates", []))
        if (completedDates.indexOf(key) >= 0)
            return habitTarget(habit)
        var stats = statFor(habit)
        var series = valueOf(stats, "heatmap", valueOf(stats, "last30Days", valueOf(stats, "days", undefined)))
        if (series !== undefined) {
            if (typeof series.length === "number") {
                var row = series[offset]
                if (typeof row === "object" && row !== null)
                    row = valueOf(row, "value", valueOf(row, "count", valueOf(row, "completed", 0)))
                var numeric = Number(row)
                if (isFinite(numeric))
                    return Math.max(0, numeric)
            } else {
                var mapped = valueOf(series, key, undefined)
                if (mapped !== undefined) {
                    var mappedNumber = Number(typeof mapped === "object" && mapped !== null
                        ? valueOf(mapped, "value", valueOf(mapped, "count", 0)) : mapped)
                    if (isFinite(mappedNumber))
                        return Math.max(0, mappedNumber)
                }
            }
        }
        return value
    }

    function formattedValue(value) {
        var number = Number(value)
        if (!isFinite(number))
            return "0"
        return Math.round(number * 10) / 10 + ""
    }

    function heatCellDescription(habit, offset) {
        var value = heatValue(habit, offset)
        var key = dateKey(offset)
        if (!habitCreatedOnDate(habit, key)) {
            return qsTr("%1 · %2 · 尚未开始")
                    .arg(String(valueOf(habit, "name", qsTr("未命名习惯"))))
                    .arg(key)
        }
        if (!habitDueOnDate(habit, key))
            return qsTr("%1 · %2 · 非计划日").arg(String(valueOf(habit, "name", qsTr("未命名习惯")))).arg(key)
        var unit = String(valueOf(habit, "unit", "")).trim()
        var valueDescription = ""
        if (habitType(habit) === "check") {
            valueDescription = value >= habitTarget(habit) ? qsTr("已完成") : qsTr("未完成")
        } else if (habitType(habit) === "counter") {
            valueDescription = qsTr("%1 / %2 %3")
                    .arg(formattedValue(value))
                    .arg(formattedValue(habitTarget(habit)))
                    .arg(unit)
                    .trim()
        } else {
            valueDescription = unit
                    ? qsTr("%1 %2").arg(formattedValue(value)).arg(unit)
                    : formattedValue(value)
        }
        return qsTr("%1 · %2 · %3")
                .arg(String(valueOf(habit, "name", qsTr("未命名习惯"))))
                .arg(dateKey(offset))
                .arg(valueDescription)
    }

    function metricNumber(key, fallback) {
        var number = Number(valueOf(metrics, key, fallback))
        return isFinite(number) ? number : fallback
    }

    function completionText() {
        var value = metricNumber("completionRate", 0)
        if (value >= 0 && value <= 1)
            value *= 100
        return Math.round(value) + "%"
    }

    function metricForWeek(index) {
        var week = metrics.week
        if (week && typeof week.length !== "number") {
            var found = valueOf(week, dateKey(6 - index), undefined)
            if (found !== undefined)
                return found
        }
        var rows = asList(week)
        if (rows.length > index)
            return rows[index]
        return null
    }

    function weekValue(index, key, fallback) {
        var row = metricForWeek(index)
        if (row === null || row === undefined)
            return fallback
        if (typeof row !== "object")
            return key === "completed" ? Number(row) : fallback
        return valueOf(row, key, fallback)
    }

    function weekdayLabel(index) {
        var row = metricForWeek(index)
        var supplied = valueOf(row, "label", valueOf(row, "weekday", valueOf(row, "dayName", "")))
        if (supplied)
            return String(supplied).replace("星期", "周")
        var d = new Date()
        d.setHours(12, 0, 0, 0)
        d.setDate(d.getDate() - (6 - index))
        return [qsTr("日"), qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六")][d.getDay()]
    }

    function callResult(result, successText) {
        if (result && result.ok === true) {
            noticeKind = "success"
            notice = successText || qsTr("已保存。")
            return true
        }
        noticeKind = "error"
        notice = String(valueOf(result, "error", qsTr("操作未完成，请重试。")))
        return false
    }

    function readTodayValue(text) {
        var numeric = Number(text)
        return isFinite(numeric) ? Math.max(0, Math.min(9999, numeric)) : 0
    }

    function openDelete(habit) {
        selectedDeleteId = habitId(habit)
        selectedDeleteName = String(valueOf(habit, "name", qsTr("这个习惯")))
        deleteDialog.open()
    }

    function openAddDialog() {
        selectedEditId = ""
        habitNameInput.text = ""
        habitTypeBox.currentIndex = 0
        habitTargetInput.text = "1"
        habitUnitInput.text = "次"
        habitToneBox.currentIndex = 0
        habitFrequencyBox.currentIndex = 0
        selectedWeekdays = []
        addDialogError.text = ""
        addDialog.open()
    }

    function openEdit(habit) {
        selectedEditId = habitId(habit)
        habitNameInput.text = String(valueOf(habit, "name", ""))
        var type = habitType(habit)
        habitTypeBox.currentIndex = type === "counter" ? 1 : type === "number" ? 2 : 0
        habitTargetInput.text = String(valueOf(habit, "target", 1))
        habitUnitInput.text = String(valueOf(habit, "unit", "次"))
        var tones = ["sage", "plum", "terracotta", "sand"]
        habitToneBox.currentIndex = Math.max(0, tones.indexOf(String(valueOf(habit, "tone", "sage"))))
        var schedule = valueOf(habit, "schedule", ({}))
        var isWeekdays = valueOf(schedule, "type", "daily") === "weekdays"
        habitFrequencyBox.currentIndex = isWeekdays ? 1 : 0
        selectedWeekdays = isWeekdays ? asList(valueOf(schedule, "days", [])) : []
        addDialogError.text = ""
        addDialog.open()
    }

    function addCurrentHabit() {
        var name = habitNameInput.text.trim()
        if (!name) {
            addDialogError.text = qsTr("请先填写习惯名称。")
            habitNameInput.forceActiveFocus()
            return
        }
        var type = ["check", "counter", "number"][habitTypeBox.currentIndex]
        var target = type === "check" ? 1 : Number(habitTargetInput.text)
        if (!isFinite(target) || target < 0.1 || target > 999) {
            addDialogError.text = qsTr("目标请填写 0.1 到 999 之间的数字。")
            habitTargetInput.forceActiveFocus()
            return
        }
        if (type !== "check" && habitUnitInput.text.trim().length > 6) {
            addDialogError.text = qsTr("单位最多 6 个字符。")
            habitUnitInput.forceActiveFocus()
            return
        }
        if (habitFrequencyBox.currentIndex === 1 && selectedWeekdays.length === 0) {
            addDialogError.text = qsTr("请至少选择一个计划日。")
            return
        }
        var definition = {
            name: name,
            type: type,
            target: target,
            unit: type === "check" ? "次" : habitUnitInput.text.trim(),
            tone: ["sage", "plum", "terracotta", "sand"][habitToneBox.currentIndex],
            schedule: habitFrequencyBox.currentIndex === 1
                      ? { type: "weekdays", days: asList(selectedWeekdays) }
                      : { type: "daily" }
        }
        var editing = selectedEditId.length > 0
        var result = editing
                     ? controller.updateHabit(selectedEditId, definition)
                     : controller.addHabit(definition)
        if (callResult(result, editing ? qsTr("习惯设置已更新。") : qsTr("新习惯已添加。"))) {
            addDialogError.text = ""
            selectedEditId = ""
            habitNameInput.text = ""
            habitTargetInput.text = "1"
            habitUnitInput.text = "次"
            habitFrequencyBox.currentIndex = 0
            selectedWeekdays = []
            addDialog.close()
        } else {
            addDialogError.text = notice
            if (type !== "check")
                habitTargetInput.forceActiveFocus()
        }
    }

    function toneColor(habit) {
        var tone = String(valueOf(habit, "tone", "sage"))
        if (tone === "terracotta" || tone === "clay" || tone === "red") return page.brand
        if (tone === "plum" || tone === "purple") return page.accentStrong
        if (tone === "sand") return page.warning
        return page.success
    }

    function colorForHeat(habit, offset) {
        var value = heatValue(habit, offset)
        var key = dateKey(offset)
        if (!habitCreatedOnDate(habit, key))
            return page.surfaceSoft
        if (!habitDueOnDate(habit, key))
            return page.line
        if (value <= 0)
            return page.surfaceSoft
        if (value >= habitTarget(habit))
            return toneColor(habit)
        return Qt.lighter(toneColor(habit), 1.55)
    }

    component HabitButton: Button {
        id: habitButton
        property bool primary: false
        property bool destructive: false
        implicitHeight: 40
        leftPadding: 14
        rightPadding: 14
        topPadding: 6
        bottomPadding: 6
        contentItem: Text {
            text: habitButton.text
            color: habitButton.enabled ? (habitButton.primary ? page.surface : (habitButton.destructive ? page.danger : page.ink)) : page.muted
            font.family: page.fontFamily
            font.pixelSize: 13
            font.bold: habitButton.primary
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 10
            color: !habitButton.enabled ? page.surfaceSoft
                  : habitButton.primary ? (habitButton.down ? page.accentStrong : page.accent)
                  : habitButton.destructive ? (habitButton.down ? page.dangerSoft : page.surface)
                  : (habitButton.down ? page.accentSoft : page.surface)
            border.color: habitButton.activeFocus ? page.accent : (habitButton.destructive ? page.dangerSoft : page.controlBorder)
        }
    }

    component HabitTextField: TextField {
        id: habitTextField
        implicitHeight: 40
        color: page.ink
        selectedTextColor: page.surface
        selectionColor: page.accent
        font.family: page.fontFamily
        font.pixelSize: 13
        leftPadding: 12
        rightPadding: 12
        background: Rectangle {
            radius: 10
            color: page.surface
            border.color: habitTextField.activeFocus ? page.accent : page.controlBorder
        }
    }

    component HabitComboBox: ComboBox {
        id: habitCombo
        implicitHeight: 40
        leftPadding: 10
        rightPadding: 28
        contentItem: Text {
            text: habitCombo.displayText
            color: page.ink
            font.family: page.fontFamily
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Canvas {
            x: habitCombo.width - width - 10
            y: (habitCombo.height - height) / 2 - 2
            width: 11
            height: 7
            property color chevronColor: habitCombo.activeFocus ? page.accent : page.muted
            onChevronColorChanged: requestPaint()
            onPaint: {
                const context = getContext("2d")
                context.reset()
                context.strokeStyle = String(chevronColor)
                context.lineWidth = 1.5
                context.lineCap = "round"
                context.lineJoin = "round"
                context.beginPath()
                context.moveTo(1, 1)
                context.lineTo(5.5, 5.5)
                context.lineTo(10, 1)
                context.stroke()
            }
        }
        background: Rectangle {
            radius: 10
            color: page.surface
            border.color: habitCombo.activeFocus ? page.accent : page.controlBorder
        }
        delegate: ItemDelegate {
            id: habitChoice
            required property var modelData
            width: habitCombo.width
            height: 36
            text: String(modelData)
            contentItem: Text {
                text: habitChoice.text
                color: habitChoice.highlighted ? page.blue : page.ink
                font.family: page.fontFamily
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
                leftPadding: 10
            }
            background: Rectangle { color: habitChoice.highlighted ? page.accentSoft : page.surface }
        }
        popup: Popup {
            y: habitCombo.height - 1
            width: habitCombo.width
            padding: 1
            implicitHeight: Math.min(contentItem.implicitHeight + 2, 240)
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: habitCombo.popup.visible ? habitCombo.delegateModel : null
                currentIndex: habitCombo.highlightedIndex
            }
            background: Rectangle { color: page.surface; border.color: page.line; radius: 10 }
        }
    }

    component HabitDialog: Dialog {
        padding: 18
        background: Rectangle { color: page.surface; border.color: page.line; radius: 14 }
    }

    Rectangle {
        anchors.fill: parent
        z: -1
        color: page.canvas
    }

    Flickable {
        id: scroller
        objectName: "habitScrollView"
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: body.implicitHeight + 40
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: body
            x: 28
            y: 24
            width: Math.max(0, scroller.width - 56)
            spacing: 20

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: qsTr("生活记录  /  习惯健康")
                        color: page.blue
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        font.bold: true
                    }
                    Text {
                        text: qsTr("今天打卡")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 32
                        font.bold: true
                    }
                    Text {
                        text: qsTr("完成一点，就算前进。记录留在本机，可随时回看。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
                HabitButton {
                    objectName: "habitAddButton"
                    text: qsTr("＋ 新增习惯")
                    primary: true
                    onClicked: page.openAddDialog()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                visible: page.notice.length > 0
                implicitHeight: visible ? noticeText.implicitHeight + 20 : 0
                radius: 8
                color: page.noticeKind === "error" ? page.dangerSoft : page.noticeKind === "success" ? page.successSoft : page.accentSoft
                border.color: page.noticeKind === "error" ? page.danger : page.noticeKind === "success" ? page.success : page.accent
                Text {
                    id: noticeText
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    anchors.topMargin: 9
                    anchors.bottomMargin: 9
                    text: page.notice
                    color: page.noticeKind === "error" ? page.danger : page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Flow {
                id: summaryFlow
                Layout.fillWidth: true
                spacing: 12
                Repeater {
                    model: [
                        { title: qsTr("今日完成"), value: page.todayHabits.length > 0 ? page.metricNumber("todayCompleted", 0) + " / " + page.metricNumber("totalHabits", page.todayHabits.length) : "—", hint: page.todayHabits.length > 0 ? qsTr("完成目标的习惯") : qsTr("先添加一项习惯") },
                        { title: qsTr("最佳连续"), value: page.hasAnyRecordedHistory ? qsTr("%1 次").arg(page.metricNumber("bestStreak", 0)) : "—", hint: page.hasAnyRecordedHistory ? qsTr("按计划日连续达成") : qsTr("开始记录后显示") },
                        { title: qsTr("30 天完成率"), value: page.hasRecentRecordedHistory ? page.completionText() : "—", hint: page.hasRecentRecordedHistory ? qsTr("近一个月的坚持") : qsTr("最近 30 天还没有记录") }
                    ]
                    delegate: Rectangle {
                        id: summaryCard
                        required property int index
                        required property var modelData
                        width: Math.max(150, Math.floor((summaryFlow.width - summaryFlow.spacing * 2) / 3))
                        height: 108
                        radius: 14
                        color: page.surface
                        border.color: page.line
                        Column {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 7
                            Text { text: summaryCard.modelData.title; color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            Text { objectName: "habitSummaryValue_" + summaryCard.index; text: summaryCard.modelData.value; color: page.ink; font.family: page.fontFamily; font.pixelSize: 22; font.bold: true }
                            Text { objectName: "habitSummaryHint_" + summaryCard.index; text: summaryCard.modelData.hint; color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 14
                color: page.surface
                border.color: page.line
                implicitHeight: todayColumn.implicitHeight + 28
                ColumnLayout {
                    id: todayColumn
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTr("今日习惯"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true }
                        Text { text: page.todayHabits.length ? qsTr("点一下，更新今天的记录") : page.habits.length ? qsTr("今天没有计划打卡的习惯") : qsTr("还没有习惯，先添加一项吧"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    }
                    Repeater {
                        model: page.todayHabits
                        delegate: Rectangle {
                            id: habitRow
                            objectName: "habitRow_" + page.habitId(habitRow.habit)
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            implicitHeight: 68
                            color: "transparent"
                            border.width: 0
                            property var habit: modelData
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                anchors.rightMargin: 4
                                spacing: 10
                                Rectangle {
                                    Layout.preferredWidth: 3
                                    Layout.preferredHeight: 30
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: 2
                                    color: page.toneColor(habitRow.habit)
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: String(page.valueOf(habitRow.habit, "name", qsTr("未命名习惯")))
                                            color: page.ink
                                            font.family: page.fontFamily
                                            font.pixelSize: 13
                                            font.bold: true
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            visible: page.isDone(habitRow.habit)
                                            text: qsTr("✓ 今日完成")
                                                color: page.success
                                            font.family: page.fontFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    Text {
                                        text: page.formattedValue(page.todayValue(habitRow.habit)) + " / " + page.formattedValue(page.habitTarget(habitRow.habit)) + " " + String(page.valueOf(habitRow.habit, "unit", "次")) + "  ·  " + page.scheduleLabel(habitRow.habit)
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                    }
                                }
                                RowLayout {
                                    spacing: 5
                                    visible: page.habitType(habitRow.habit) === "check"
                                    HabitButton {
                                        objectName: "habitCheckButton_" + page.habitId(habitRow.habit)
                                        text: page.isDone(habitRow.habit) ? qsTr("撤销") : qsTr("完成")
                                        primary: !page.isDone(habitRow.habit)
                                        onClicked: page.callResult(page.controller.quickCheck(page.habitId(habitRow.habit)), qsTr("今日记录已更新。"))
                                    }
                                }
                                RowLayout {
                                    spacing: 5
                                    visible: page.habitType(habitRow.habit) === "counter"
                                    HabitButton {
                                        objectName: "habitCounterMinus_" + page.habitId(habitRow.habit)
                                        text: "−"
                                        Accessible.name: qsTr("减少计数")
                                        implicitWidth: 36
                                        enabled: page.todayValue(habitRow.habit) > 0
                                        onClicked: page.callResult(page.controller.adjustCounter(page.habitId(habitRow.habit), -1), qsTr("今日记录已更新。"))
                                    }
                                    HabitButton {
                                        objectName: "habitCounterPlus_" + page.habitId(habitRow.habit)
                                        text: "+"
                                        Accessible.name: qsTr("增加计数")
                                        primary: true
                                        implicitWidth: 36
                                        onClicked: page.callResult(page.controller.adjustCounter(page.habitId(habitRow.habit), 1), qsTr("今日记录已更新。"))
                                    }
                                }
                                RowLayout {
                                    spacing: 5
                                    visible: page.habitType(habitRow.habit) === "number"
                                    HabitTextField {
                                        id: numberInput
                                        objectName: "habitNumberInput_" + page.habitId(habitRow.habit)
                                        property string editingValue: page.formattedValue(page.todayValue(habitRow.habit))
                                        text: activeFocus ? editingValue : page.formattedValue(page.todayValue(habitRow.habit))
                                        implicitWidth: 84
                                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                                        validator: DoubleValidator { bottom: 0; top: 9999; decimals: 1 }
                                        onActiveFocusChanged: {
                                            if (activeFocus)
                                                editingValue = text
                                            else
                                                editingValue = page.formattedValue(page.todayValue(habitRow.habit))
                                        }
                                        onTextEdited: {
                                            editingValue = text
                                        }
                                        onEditingFinished: page.callResult(page.controller.setValue(page.habitId(habitRow.habit), page.readTodayValue(text)), qsTr("今日记录已更新。"))
                                    }
                                    Text { text: String(page.valueOf(habitRow.habit, "unit", "")); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                                }
                                Button {
                                    id: habitMoreButton
                                    objectName: "habitMoreButton_" + page.habitId(habitRow.habit)
                                    text: "⋯"
                                    Accessible.name: qsTr("更多习惯操作")
                                    implicitWidth: 36
                                    implicitHeight: 36
                                    padding: 2
                                    contentItem: Text {
                                        text: "⋯"
                                        color: parent.activeFocus ? page.accent : page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 18
                                        font.bold: true
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        radius: 9
                                        color: habitMoreButton.down ? page.accentSoft : "transparent"
                                        border.color: habitMoreButton.activeFocus ? page.accent : "transparent"
                                    }
                                    onClicked: habitActionsMenu.open()
                                    Menu {
                                        id: habitActionsMenu
                                        objectName: "habitActionsMenu_" + page.habitId(habitRow.habit)
                                        MenuItem {
                                            objectName: "editHabitMenuItem"
                                            text: qsTr("编辑习惯")
                                            onTriggered: page.openEdit(habitRow.habit)
                                        }
                                        MenuItem {
                                            objectName: "deleteHabitMenuItem"
                                            text: qsTr("删除习惯")
                                            onTriggered: page.openDelete(habitRow.habit)
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                visible: habitRow.index < page.habits.length - 1
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 18
                                anchors.rightMargin: 4
                                height: 1
                                color: page.line
                            }
                        }
                    }
                    Text {
                        visible: page.todayHabits.length === 0
                        text: page.habits.length === 0
                              ? qsTr("习惯列表为空。新增一项后，可以用勾选、计数或数值方式记录。")
                              : qsTr("今天没有计划打卡的习惯，休息日不会影响连续记录。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                    }
                }
            }

            Rectangle {
                objectName: "habitHeatmapSection"
                Layout.fillWidth: true
                radius: 10
                color: page.surface
                border.color: page.line
                implicitHeight: heatColumn.implicitHeight + 28
                ColumnLayout {
                    id: heatColumn
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTr("30 天习惯热力图"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true }
                        Text { objectName: "habitHeatmapLegend"; text: qsTr("灰白为无记录，浅色为部分记录，深色为达成目标"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Item { Layout.preferredWidth: 138; Layout.preferredHeight: 16 }
                        Repeater {
                            model: 30
                            delegate: Text {
                                required property int index
                                Layout.fillWidth: true
                                Layout.minimumWidth: 8
                                Layout.preferredWidth: 14
                                Layout.maximumWidth: 22
                                horizontalAlignment: Text.AlignHCenter
                                text: index % 5 === 0 || index === 29 ? String(Number(page.dateKey(29 - index).slice(8, 10))) : ""
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                        }
                    }
                    Repeater {
                        model: page.habits
                        delegate: RowLayout {
                            id: habitHeatRow
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                Layout.preferredWidth: 138
                                text: String(page.valueOf(habitHeatRow.modelData, "name", qsTr("未命名习惯")))
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            Repeater {
                                model: 30
                                delegate: Rectangle {
                                    id: habitHeatCell
                                    required property int index
                                    objectName: "habitHeatCell_" + page.habitId(habitHeatRow.modelData) + "_" + String(index)
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 8
                                    Layout.preferredWidth: 14
                                    Layout.maximumWidth: 22
                                    Layout.preferredHeight: 16
                                    radius: 3
                                    color: page.colorForHeat(habitHeatRow.modelData, 29 - habitHeatCell.index)
                                    border.color: !page.habitDueOnDate(habitHeatRow.modelData, page.dateKey(29 - habitHeatCell.index)) ? page.line : page.heatValue(habitHeatRow.modelData, 29 - habitHeatCell.index) > 0 ? page.toneColor(habitHeatRow.modelData) : "#e4e8e9"
                                    ToolTip.visible: hovered
                                    readonly property string description: page.heatCellDescription(habitHeatRow.modelData, 29 - habitHeatCell.index)
                                    Accessible.role: Accessible.Graphic
                                    Accessible.name: description
                                    ToolTip.text: description
                                    property bool hovered: false
                                    HoverHandler { onHoveredChanged: parent.hovered = hovered }
                                }
                            }
                        }
                    }
                    Text { visible: page.habits.length === 0; text: qsTr("添加习惯后，这里会显示每天的记录。"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: 12
                Rectangle {
                    objectName: "habitRecentWeekCard"
                    width: Math.max(270, Math.floor((parent.width - 12) / 2))
                    height: 172
                    radius: 10
                    color: page.surface
                    border.color: page.line
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: qsTr("最近 7 天"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true }
                            Text { text: qsTr("每日完成概览"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 6
                            Repeater {
                                model: 7
                                delegate: ColumnLayout {
                                    id: weeklyStatColumn
                                    required property int index
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 5
                                    Text {
                                        Layout.fillWidth: true
                                        readonly property int scheduled: Number(page.weekValue(weeklyStatColumn.index, "scheduled", page.weekValue(weeklyStatColumn.index, "total", 0)))
                                        readonly property int eligible: Number(page.weekValue(weeklyStatColumn.index, "total", 0))
                                        text: scheduled === 0 ? qsTr("休息") : eligible === 0 ? qsTr("尚未开始") : page.weekValue(weeklyStatColumn.index, "rate", page.weekValue(weeklyStatColumn.index, "completionRate", 0)) > 1
                                              ? Math.round(Number(page.weekValue(weeklyStatColumn.index, "rate", page.weekValue(weeklyStatColumn.index, "completionRate", 0)))) + "%"
                                              : Math.round(Number(page.weekValue(weeklyStatColumn.index, "rate", page.weekValue(weeklyStatColumn.index, "completionRate", 0))) * 100) + "%"
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                    Item {
                                        objectName: "habitWeeklyChartArea_" + String(weeklyStatColumn.index)
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        Rectangle {
                                            objectName: "habitWeeklyBaseline_" + String(weeklyStatColumn.index)
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 1
                                            color: page.line
                                        }
                                        Rectangle {
                                            anchors.bottom: parent.bottom
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            visible: Number(page.weekValue(weeklyStatColumn.index, "total", 0)) > 0
                                            width: Math.min(25, parent.width - 4)
                                            height: Math.max(6, Math.min(parent.height, parent.height * Math.max(0, Math.min(1, Number(page.weekValue(weeklyStatColumn.index, "rate", page.weekValue(weeklyStatColumn.index, "completionRate", 0)))))))
                                            radius: 4
                                            color: page.blue
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: qsTr("周%1").arg(page.weekdayLabel(weeklyStatColumn.index))
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    objectName: "habitYesterdayReviewCard"
                    width: Math.max(270, Math.floor((parent.width - 12) / 2))
                    height: 172
                    radius: 10
                    color: page.surface
                    border.color: page.line
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        Text { text: qsTr("昨日回顾"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 16; font.bold: true }
                        Text {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: {
                                var review = page.metrics.yesterdayReview
                                if (review === null || review === undefined || review === "")
                                    return page.yesterdayReviewEmptyText
                                if (typeof review === "string")
                                    return review
                                var summary = page.valueOf(review, "summary", page.valueOf(review, "text", page.valueOf(review, "message", "")))
                                var done = page.valueOf(review, "completed", page.valueOf(review, "done", undefined))
                                var total = page.valueOf(review, "total", undefined)
                                var detail = summary ? String(summary) : (total === undefined
                                    ? qsTr("昨天完成 %1 项习惯。").arg(done === undefined ? "—" : String(done))
                                    : qsTr("昨天完成 %1 / %2 项习惯。")
                                        .arg(done === undefined ? "—" : String(done))
                                        .arg(String(total)))
                                return detail
                            }
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignTop
                        }
                        Text {
                            visible: !!(page.metrics.yesterdayReview && typeof page.metrics.yesterdayReview === "object")
                            text: {
                                var review = page.metrics.yesterdayReview
                                var items = page.asList(page.valueOf(review, "items", page.valueOf(review, "habits", [])))
                                return items.map(function(item) {
                                    return "• " + String(page.valueOf(item, "name", page.valueOf(item, "label", qsTr("习惯")))) + qsTr("：") + String(page.valueOf(item, "value", page.valueOf(item, "status", qsTr("已记录"))))
                                }).join("\n")
                            }
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 2
                Text { text: qsTr("本机习惯数据"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.fillWidth: true }
                HabitButton {
                    objectName: "habitClearSamplesButton"
                    text: qsTr("清空样本记录…")
                    visible: page.habits.some(function(habit) { return !!page.valueOf(habit, "sample", false) })
                    onClicked: sampleDialog.open()
                }
            }
        }
    }

    HabitDialog {
        id: addDialog
        objectName: "habitAddDialog"
        title: page.selectedEditId.length > 0 ? qsTr("编辑习惯") : qsTr("新增习惯")
        modal: true
        standardButtons: Dialog.NoButton
        width: Math.min(440, page.width - 32)
        anchors.centerIn: Overlay.overlay
        onOpened: {
            addDialogError.text = ""
        }
        contentItem: ColumnLayout {
            spacing: 10
            Text { text: qsTr("建立一项适合自己的记录计划。"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Text { text: qsTr("名称"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
            HabitTextField { id: habitNameInput; objectName: "habitNameInput"; placeholderText: qsTr("例如：阅读、散步"); maximumLength: 18; Layout.fillWidth: true; onAccepted: habitTargetInput.forceActiveFocus() }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: qsTr("记录方式"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
                    HabitComboBox { id: habitTypeBox; objectName: "habitTypeBox"; Layout.fillWidth: true; model: [qsTr("勾选"), qsTr("计数"), qsTr("数值")] }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: qsTr("目标"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
                    HabitTextField {
                        id: habitTargetInput
                        objectName: "habitTargetInput"
                        Layout.fillWidth: true
                        text: "1"
                        enabled: habitTypeBox.currentIndex !== 0
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        validator: DoubleValidator {
                            bottom: 0.1
                            top: 999
                            decimals: 1
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: qsTr("频率"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
                HabitComboBox {
                    id: habitFrequencyBox
                    objectName: "habitFrequencyBox"
                    Layout.fillWidth: true
                    model: [qsTr("每天"), qsTr("指定星期")]
                    currentIndex: 0
                }
                Flow {
                    objectName: "habitWeekdayPicker"
                    Layout.fillWidth: true
                    spacing: 6
                    visible: habitFrequencyBox.currentIndex === 1
                    Repeater {
                        model: [1, 2, 3, 4, 5, 6, 7]
                        delegate: HabitButton {
                            required property int modelData
                            objectName: "habitWeekdayButton_" + modelData
                            text: [qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六"), qsTr("日")][modelData - 1]
                            checkable: true
                            checked: page.selectedWeekdays.indexOf(modelData) >= 0
                            primary: checked
                            Accessible.name: qsTr("星期%1").arg(text)
                            implicitWidth: 36
                            implicitHeight: 34
                            onClicked: page.toggleWeekday(modelData)
                        }
                    }
                }
                Text {
                    objectName: "habitEditScheduleHint"
                    visible: page.selectedEditId.length > 0
                    text: qsTr("计划从今天起生效，之前的记录仍按旧计划统计。")
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Text {
                    visible: habitFrequencyBox.currentIndex === 1 && page.selectedWeekdays.length === 0
                    text: qsTr("请至少选择一个计划日。")
                    color: page.warning
                    font.family: page.fontFamily
                    font.pixelSize: 12
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: qsTr("单位"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
                    HabitTextField { id: habitUnitInput; objectName: "habitUnitInput"; Layout.fillWidth: true; maximumLength: 6; text: qsTr("次"); placeholderText: qsTr("例如：分钟、页"); enabled: habitTypeBox.currentIndex !== 0 }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: qsTr("色调"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12 }
                    HabitComboBox { id: habitToneBox; objectName: "habitToneBox"; Layout.fillWidth: true; model: [qsTr("鼠尾草绿"), qsTr("柔和紫"), qsTr("陶土色"), qsTr("暖沙色")]; currentIndex: 0 }
                }
            }
                    Text { id: addDialogError; objectName: "habitAddDialogError"; visible: text.length > 0; text: ""; color: page.danger; font.family: page.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                HabitButton { text: qsTr("取消"); onClicked: addDialog.close() }
                HabitButton { objectName: "habitAddConfirmButton"; text: page.selectedEditId.length > 0 ? qsTr("保存修改") : qsTr("添加习惯"); primary: true; onClicked: page.addCurrentHabit() }
            }
        }
    }

    HabitDialog {
        id: deleteDialog
        objectName: "habitDeleteDialog"
        title: qsTr("确认删除")
        modal: true
        standardButtons: Dialog.NoButton
        width: Math.min(390, page.width - 32)
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            spacing: 14
            Text { text: qsTr("删除「%1」及其本机打卡记录？此操作无法撤销。").arg(page.selectedDeleteName); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Text { visible: page.noticeKind === "error" && deleteDialog.visible; text: page.notice; color: page.danger; font.family: page.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                HabitButton { text: qsTr("取消"); onClicked: deleteDialog.close() }
                HabitButton {
                    objectName: "habitDeleteConfirmButton"
                    text: qsTr("删除习惯")
                    destructive: true
                    onClicked: if (page.callResult(page.controller.deleteHabit(page.selectedDeleteId), qsTr("习惯已删除。"))) deleteDialog.close()
                }
            }
        }
    }

    HabitDialog {
        id: sampleDialog
        objectName: "habitSamplesDialog"
        title: qsTr("清空样本习惯记录")
        modal: true
        standardButtons: Dialog.NoButton
        width: Math.min(390, page.width - 32)
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            spacing: 14
            Text { text: qsTr("清空这些样本习惯的打卡记录，并将习惯保留为普通习惯；你自己添加的习惯不会受影响。"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Text { visible: page.noticeKind === "error" && sampleDialog.visible; text: page.notice; color: page.danger; font.family: page.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                HabitButton { text: qsTr("取消"); onClicked: sampleDialog.close() }
                HabitButton { objectName: "habitClearSamplesConfirmButton"; text: qsTr("清空样本记录"); destructive: true; onClicked: if (page.callResult(page.controller.clearSamples(), qsTr("样本习惯记录已清空。"))) sampleDialog.close() }
            }
        }
    }

    Connections {
        target: page.controller
        function onStateChanged() {
            var backendNotice = page.valueOf(page.snapshot, "notice", "")
            if (backendNotice) {
                page.notice = String(backendNotice)
                page.noticeKind = "error"
            }
        }
    }

    Component.onCompleted: {
        var backendNotice = page.valueOf(page.snapshot, "notice", "")
        if (backendNotice) {
            page.notice = String(backendNotice)
            page.noticeKind = "error"
        }
    }
}
