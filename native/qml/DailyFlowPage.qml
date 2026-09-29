pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "dailyFlowPage"
    implicitHeight: flowContent.implicitHeight + 32

    required property var controller
    required property var plannerBridge
    property var homeLayoutController: null
    property var uiTheme: null
    property int controllerRevision: 0
    property bool followUpDirty: false
    property bool focusTaskDirty: false
    property bool syncingTimerControls: false
    property bool syncingEditableDrafts: false
    property string focusTaskId: ""
    property string focusTrackedTaskId: ""
    property string focusRestoreSessionKey: ""
    property string focusModeSnapshot: "pomodoro"
    property int focusDurationMinutesSnapshot: 25
    property int focusCountdownMinutesDraft: 25
    property int focusElapsedSecondsSnapshot: 0
    property int focusRemainingSecondsSnapshot: 1500
    property bool spotifyUrlDirty: false
    property string notice: ""
    property bool noticeIsError: false
    property int selectedQuestionIndex: -1
    property string selectedQuestionText: ""
    property var reviewSnapshot: ({})
    property var todayWorkSnapshot: ({})
    property var stateSnapshot: ({})
    property string focusDisplaySnapshot: "25:00"
    property real focusProgressSnapshot: 0
    property bool focusRunningSnapshot: false
    property string focusButtonLabelSnapshot: "开始专注"

    readonly property color paper: uiTheme ? uiTheme.canvas : "#f6f5f0"
    readonly property color card: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color softCard: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color controlBorder: uiTheme ? uiTheme.controlBorder : "#807d76"
    readonly property color blue: uiTheme ? uiTheme.accent : "#456b73"
    readonly property color blueStrong: uiTheme ? uiTheme.accentStrong : "#315761"
    readonly property color blueSoft: uiTheme ? uiTheme.accentSoft : "#e6efee"
    readonly property color red: uiTheme ? uiTheme.brand : "#9f4137"
    readonly property color redSoft: uiTheme ? uiTheme.brandSoft : "#f7eae5"
    readonly property color success: uiTheme ? uiTheme.success : "#3d654e"
    readonly property color successSoft: uiTheme ? uiTheme.successSoft : "#eaf2ec"
    readonly property color warning: uiTheme ? uiTheme.warning : "#80531b"
    readonly property color warningSoft: uiTheme ? uiTheme.warningSoft : "#f6efe2"
    readonly property color danger: uiTheme ? uiTheme.danger : "#9d4038"
    readonly property color dangerSoft: uiTheme ? uiTheme.dangerSoft : "#f8eae7"
    readonly property string sansFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property string serifFamily: uiTheme ? uiTheme.serifFamily : "Noto Serif SC"
    readonly property string fontFamily: sansFamily
    readonly property bool compact: width < 720

    readonly property var review: reviewSnapshot
    readonly property var todayWork: todayWorkSnapshot
    readonly property var persistedState: stateSnapshot
    readonly property string focusDisplay: focusDisplaySnapshot
    readonly property real focusProgress: focusProgressSnapshot
    readonly property bool focusRunning: focusRunningSnapshot
    readonly property string focusButtonLabel: focusButtonLabelSnapshot
    readonly property string focusMode: focusModeSnapshot
    readonly property int focusDurationMinutes: focusDurationMinutesSnapshot

    readonly property var reviewItems: toArray(valueOf(review, "items", []))
    readonly property var questions: toArray(valueOf(persistedState, "questions", []))
    readonly property var tasks: toArray(valueOf(todayWork, "tasks", []))
    readonly property var focusCandidates: plannerTaskCandidates()
    readonly property var focusCandidateOptions: [{
        id: "",
        title: qsTr("选择一项今日待办…")
    }].concat(focusCandidates)
    readonly property var focusModeOptions: [
        { value: "pomodoro", label: qsTr("番茄钟") },
        { value: "flowtime", label: qsTr("Flowtime 正向计时") },
        { value: "countdown", label: qsTr("自定义倒计时") }
    ]
    readonly property string todayDateKey: String(valueOf(todayWork, "date", localDateKey()))
    readonly property bool canOpenSpotify: isSpotifyUrl(String(valueOf(persistedState, "spotifyUrl", "")))

    function valueOf(object, key, fallback) {
        return UiPageUtils.valueOf(object, key, fallback)
    }

    function enumLabel(value) {
        return value === null || value === undefined || String(value) === ""
                ? "" : qsTr(String(value))
    }

    function toArray(value) {
        return UiPageUtils.asList(value, true)
    }

    function questionDeskIsVisible() {
        const bridge = page.homeLayoutController
        if (!bridge || !bridge.state)
            return true
        const layout = bridge.state.layout || ({})
        return page.toArray(page.valueOf(layout, "hidden", [])).indexOf("question-desk") < 0
    }

    function plannerTaskCandidates() {
        if (!plannerBridge)
            return toArray(valueOf(todayWork, "focusCandidates", []))
        var rows = toArray(valueOf(plannerBridge.state, "records", []))
        var candidates = []
        for (var i = 0; i < rows.length; ++i) {
            var record = rows[i]
            var data = valueOf(record, "data", ({}))
            var scheduledDay = String(valueOf(data, "plannedDate", ""))
            if (Boolean(valueOf(data, "done", false)))
                continue
            if (String(valueOf(record, "date", "")) !== todayDateKey && scheduledDay !== todayDateKey)
                continue
            candidates.push({
                id: String(valueOf(record, "id", "")),
                title: String(valueOf(data, "title", qsTr("一项日程"))),
                date: String(valueOf(record, "date", ""))
            })
        }
        return candidates
    }

    function sectionPositionY(step) {
        let target = step === 1 ? reviewLayout
                  : step === 2 ? workLayout
                  : step === 3 ? focusLayout : null
        return target ? target.mapToItem(page, 0, 0).y : 0
    }

    function localDateKey() {
        return UiPageUtils.localDateKey()
    }

    function pad2(value) {
        return value < 10 ? "0" + value : String(value)
    }

    function questionText(question) {
        if (typeof question === "string")
            return question
        return String(valueOf(question, "text", ""))
    }

    function questionDate(question) {
        var date = valueOf(question, "createdDate", "")
        return date ? String(date) : qsTr("日期未记录")
    }

    function isSpotifyUrl(value) {
        return /^https:\/\/open\.spotify\.com\/(?:intl-[a-z]{2}(?:-[a-z]{2})?\/)?(?:track|album|playlist|episode|show)\/[A-Za-z0-9]{10,40}\/?(?:[?#].*)?$/i.test(value)
    }

    function openSpotifyLink() {
        var url = String(valueOf(persistedState, "spotifyUrl", ""))
        if (!isSpotifyUrl(url)) {
            notice = "请先保存有效的 Spotify 单曲、专辑、播放列表或播客链接。"
            noticeIsError = true
            return
        }
        try {
            if (Qt.openUrlExternally(url)) {
                notice = "已将链接交给系统默认浏览器或 Spotify 应用。"
                noticeIsError = false
            } else {
                notice = "系统未能打开 Spotify 链接，请检查默认浏览器或 Spotify 应用。"
                noticeIsError = true
            }
        } catch (error) {
            showException(error)
        }
    }

    function todayNote() {
        var notes = valueOf(persistedState, "notes", ({}))
        return String(valueOf(notes, todayDateKey, ""))
    }

    function refreshEditableDrafts() {
        syncingEditableDrafts = true
        try {
            if (!followUpDirty)
                followUpInput.text = todayNote()
            if (!focusTaskDirty)
                focusTaskInput.text = String(valueOf(persistedState, "focusTask", ""))
            if (!spotifyUrlDirty)
                spotifyInput.text = String(valueOf(persistedState, "spotifyUrl", ""))
        } finally {
            syncingEditableDrafts = false
        }
    }

    function syncControllerSnapshot() {
        if (!controller)
            return
        try {
            reviewSnapshot = controller.review || ({})
            todayWorkSnapshot = controller.todayWork || ({})
            stateSnapshot = controller.state || ({})
            focusDisplaySnapshot = String(controller.focusDisplay || "25:00")
            var progress = Number(controller.focusProgress || 0)
            focusProgressSnapshot = isFinite(progress) ? Math.max(0, Math.min(1, progress)) : 0
            focusRunningSnapshot = Boolean(controller.focusRunning)
            focusButtonLabelSnapshot = String(controller.focusButtonLabel || "开始专注")
            var timerState = valueOf(stateSnapshot, "focusTimer", ({}))
            focusModeSnapshot = String(valueOf(timerState, "mode", "pomodoro"))
            focusDurationMinutesSnapshot = Math.max(0, Math.round(Number(valueOf(timerState, "durationSeconds", 1500)) / 60))
            focusElapsedSecondsSnapshot = Math.max(0, Number(valueOf(timerState, "elapsedSeconds", 0)) || 0)
            focusRemainingSecondsSnapshot = Math.max(0, Number(valueOf(timerState, "remainingSeconds", 1500)) || 0)
            if (focusModeSnapshot === "countdown") {
                syncingTimerControls = true
                focusCountdownMinutesDraft = Math.max(5, Math.min(480, focusDurationMinutesSnapshot || 25))
                syncingTimerControls = false
            }
            refreshEditableDrafts()
        } catch (error) {
            showException(error)
        }
    }

    function showResult(result, successText) {
        var failed = result === false ||
                     (result !== null && result !== undefined &&
                      typeof result === "object" && result.ok === false)
        if (failed) {
            notice = result && result.error ? String(result.error)
                                             : "操作未保存，请检查本机存储状态后重试。"
            noticeIsError = true
            return false
        }
        notice = result && result.message ? String(result.message) : successText
        noticeIsError = false
        return true
    }

    function showException(error) {
        notice = error && error.message ? String(error.message) : "操作失败，请稍后重试。"
        noticeIsError = true
    }

    function saveFollowUpDraft() {
        if (!controller)
            return
        try {
            var result = controller.saveFollowUp(todayDateKey, followUpInput.text)
            if (showResult(result,
                           "已保存，明天复盘时回看。"))
                followUpDirty = false
        } catch (error) {
            showException(error)
        }
    }

    function saveFocusTaskDraft() {
        if (!controller)
            return
        try {
            if (showResult(controller.saveFocusTask(focusTaskInput.text), "专注任务已保存。"))
                focusTaskDirty = false
        } catch (error) {
            showException(error)
        }
    }

    function saveSpotifyDraft(clearValue) {
        if (!controller)
            return
        try {
            var value = clearValue ? "" : spotifyInput.text
            if (showResult(controller.saveSpotifyUrl(value),
                           clearValue ? "已移除保存的链接。" : "Spotify 链接已保存。")) {
                spotifyUrlDirty = false
                spotifyInput.text = value
            }
        } catch (error) {
            showException(error)
        }
    }

    function addQuestionDraft() {
        if (!controller || questionInput.text.trim().length === 0)
            return
        try {
            if (showResult(controller.addQuestion(questionInput.text), "问题已收进问题簿。")) {
                questionInput.clear()
                questionInput.forceActiveFocus()
            }
        } catch (error) {
            showException(error)
        }
    }

    function requestRemoveQuestion(index, text) {
        selectedQuestionIndex = Number(index)
        selectedQuestionText = String(text || "")
        questionRemoveDialog.open()
    }

    function confirmRemoveQuestion() {
        if (!controller)
            return
        try {
            if (showResult(controller.removeQuestion(selectedQuestionIndex), "已移除这条问题。"))
                questionRemoveDialog.close()
        } catch (error) {
            showException(error)
        }
    }

    function chooseFocusCandidate(candidate) {
        focusTaskInput.text = String(valueOf(candidate, "title", ""))
        focusTaskDirty = true
        focusTaskId = String(valueOf(candidate, "id", ""))
        saveFocusTaskDraft()
    }

    function focusCandidateIndex() {
        if (focusTaskId) {
            for (var i = 0; i < focusCandidates.length; ++i) {
                if (String(valueOf(focusCandidates[i], "id", "")) === focusTaskId)
                    return i
            }
            return -1
        }
        var taskTitle = String(focusTaskInput.text || "").trim()
        if (!taskTitle)
            return -1
        var matchedIndex = -1
        for (var j = 0; j < focusCandidates.length; ++j) {
            if (String(valueOf(focusCandidates[j], "title", "")) !== taskTitle)
                continue
            if (matchedIndex >= 0)
                return -1
            matchedIndex = j
        }
        return matchedIndex
    }

    function focusModeIndex() {
        for (var i = 0; i < focusModeOptions.length; ++i) {
            if (String(valueOf(focusModeOptions[i], "value", "")) === focusMode)
                return i
        }
        return 0
    }

    function focusModeSummary() {
        if (focusMode === "flowtime")
            return qsTr("Flowtime · 正向计时 · 本机保存")
        if (focusMode === "countdown")
            return qsTr("自定义倒计时 · %1 分钟 · 本机保存").arg(focusDurationMinutes)
        return qsTr("番茄钟 · 25 分钟 · 本机保存")
    }

    function selectedFocusCandidateId() {
        var index = focusCandidateIndex()
        return index >= 0 ? String(valueOf(focusCandidates[index], "id", "")) : ""
    }

    function toggleFocusTimer() {
        if (!controller)
            return
        var timerState = valueOf(persistedState, "focusTimer", ({}))
        var timerTaskId = String(valueOf(timerState, "taskId", ""))
        var timerTaskTitle = String(valueOf(timerState, "taskTitle", ""))
        var active = valueOf(plannerBridge.state, "activeTracking", ({}))
        var activeTaskId = String(valueOf(active, "taskId", ""))
        var selectedTaskId = selectedFocusCandidateId()
        var selectedTitle = String(focusTaskInput.text || "").trim()
        if (focusRunningSnapshot) {
            var pauseResult = controller.toggleFocus(timerTaskId, timerTaskTitle)
            if (!showResult(pauseResult, "专注计时已暂停并保存。"))
                return
            if (focusTrackedTaskId && activeTaskId === focusTrackedTaskId) {
                if (Boolean(valueOf(pauseResult, "completed", false))) {
                    showResult(plannerBridge.stopTrackingTask(), "日程实际用时已记录。")
                    focusTrackedTaskId = ""
                } else {
                    showResult(plannerBridge.pauseTrackingTask(), "日程实际用时已保存。")
                }
            }
            notice = ""
            return
        }

        if (focusTrackedTaskId && focusTrackedTaskId !== selectedTaskId && activeTaskId === focusTrackedTaskId) {
            if (!showResult(plannerBridge.stopTrackingTask(), "上一项日程实际用时已记录。"))
                return
            focusTrackedTaskId = ""
            active = valueOf(plannerBridge.state, "activeTracking", ({}))
            activeTaskId = String(valueOf(active, "taskId", ""))
        }
        if (selectedTaskId) {
            var activeMode = String(valueOf(active, "mode", ""))
            if (activeTaskId && (activeTaskId !== selectedTaskId || activeMode !== focusMode)) {
                if (activeTaskId === focusTrackedTaskId) {
                    if (!showResult(plannerBridge.stopTrackingTask(), "上一项日程实际用时已记录。"))
                        return
                    activeTaskId = ""
                    active = ({})
                    focusTrackedTaskId = ""
                } else {
                    notice = qsTr("请先结束当前任务的计时，再开始另一项。")
                    noticeIsError = true
                    return
                }
            }
            if (activeTaskId === selectedTaskId) {
                if (Boolean(valueOf(active, "paused", false))) {
                    if (!showResult(plannerBridge.resumeTrackingTask(), "日程实际用时已继续记录。"))
                        return
                }
            } else {
                var taskResult = plannerBridge.startFocusTask(selectedTaskId, focusMode, focusDurationMinutes || 25)
                if (!showResult(taskResult, "已开始记录日程实际用时。"))
                    return
            }
            focusTrackedTaskId = selectedTaskId
        } else if (focusTrackedTaskId && activeTaskId === focusTrackedTaskId) {
            if (!showResult(plannerBridge.stopTrackingTask(), "日程实际用时已记录。"))
                return
            focusTrackedTaskId = ""
        }
        var startResult = controller.toggleFocus(selectedTaskId, selectedTitle)
        if (!showResult(startResult, "专注计时已开始。")) {
            active = valueOf(plannerBridge.state, "activeTracking", ({}))
            if (selectedTaskId && String(valueOf(active, "taskId", "")) === selectedTaskId)
                plannerBridge.pauseTrackingTask()
            return
        }
        notice = ""
    }

    function finishLinkedTracking() {
        if (focusRunningSnapshot || focusMode === "flowtime" || focusRemainingSecondsSnapshot > 0 || !focusTrackedTaskId)
            return
        var trackedId = focusTrackedTaskId
        focusTrackedTaskId = ""
        var active = valueOf(plannerBridge.state, "activeTracking", ({}))
        if (String(valueOf(active, "taskId", "")) === trackedId)
            showResult(plannerBridge.stopTrackingTask(), "日程实际用时已记录。")
    }

    function setFocusMode(mode) {
        if (!controller)
            return
        var minutes = mode === "countdown" ? focusCountdownMinutesDraft : 25
        var result = controller.setFocusMode(mode, minutes)
        if (!showResult(result, qsTr("计时方式已保存。")))
            syncControllerSnapshot()
    }

    function restoreLinkedFocusTracking() {
        syncControllerSnapshot()
        var timerState = valueOf(persistedState, "focusTimer", ({}))
        var taskId = String(valueOf(timerState, "taskId", ""))
        var sessionKey = taskId + "/" + String(valueOf(timerState, "sessionId", ""))
                     + "/" + String(valueOf(timerState, "mode", "pomodoro"))
        if (sessionKey === focusRestoreSessionKey)
            return
        focusRestoreSessionKey = sessionKey
        if (!taskId) {
            var previousActive = valueOf(plannerBridge.state, "activeTracking", ({}))
            if (focusTrackedTaskId && String(valueOf(previousActive, "taskId", "")) === focusTrackedTaskId)
                showResult(plannerBridge.stopTrackingTask(), "日程实际用时已记录。")
            focusTrackedTaskId = ""
            return
        }
        focusTrackedTaskId = taskId
        if (!focusRunningSnapshot)
            return
        var active = valueOf(plannerBridge.state, "activeTracking", ({}))
        var activeId = String(valueOf(active, "taskId", ""))
        var mode = String(valueOf(timerState, "mode", "pomodoro"))
        var duration = Math.max(5, Math.round(Number(valueOf(timerState, "durationSeconds", 1500)) / 60))
        if (activeId === taskId) {
            if (Boolean(valueOf(active, "paused", false)))
                showResult(plannerBridge.resumeTrackingTask(), "日程实际用时已继续记录。")
            return
        }
        if (activeId)
            showResult(plannerBridge.stopTrackingTask(), "上一项日程实际用时已记录。")
        showResult(plannerBridge.startFocusTask(taskId, mode, duration || 25), "已恢复记录日程实际用时。")
    }

    function resetFocusTimer() {
        if (!controller)
            return
        var result = controller.resetFocus()
        if (!showResult(result, qsTr("计时已重置。")))
            return
        var active = valueOf(plannerBridge.state, "activeTracking", ({}))
        if (focusTrackedTaskId && String(valueOf(active, "taskId", "")) === focusTrackedTaskId)
            showResult(plannerBridge.stopTrackingTask(), "日程实际用时已记录。")
        focusTrackedTaskId = ""
    }

    component FlowButton: Button {
        id: flowButton
        property bool emphasized: false
        implicitHeight: 38
        leftPadding: 12
        rightPadding: 12
        topPadding: 5
        bottomPadding: 5
        contentItem: Text {
            text: flowButton.text
            color: flowButton.enabled ? (flowButton.emphasized ? page.card : page.ink) : page.muted
            font.family: page.fontFamily
            font.pixelSize: 13
            font.bold: flowButton.emphasized
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: !flowButton.enabled ? page.softCard
                  : flowButton.emphasized ? (flowButton.down ? page.blueStrong : page.blue)
                  : flowButton.down ? page.blueSoft : page.card
            border.color: flowButton.activeFocus ? page.blue
                         : flowButton.emphasized ? page.blue : page.controlBorder
        }
    }

    component FlowTextField: TextField {
        id: flowTextField
        implicitHeight: 42
        leftPadding: 10
        rightPadding: 10
        color: page.ink
        selectionColor: page.blueSoft
        selectedTextColor: page.ink
        font.family: page.fontFamily
        font.pixelSize: 16
        placeholderTextColor: page.muted
        background: Rectangle {
        radius: 8
            color: page.card
            border.color: flowTextField.activeFocus ? page.blue : page.controlBorder
        }
    }

    component FlowTextArea: TextArea {
        id: flowTextArea
        leftPadding: 10
        rightPadding: 10
        topPadding: 9
        bottomPadding: 9
        color: page.ink
        selectionColor: page.blueSoft
        selectedTextColor: page.ink
        font.family: page.fontFamily
        font.pixelSize: 15
        placeholderTextColor: page.muted
        wrapMode: TextEdit.Wrap
        background: Rectangle {
        radius: 8
            color: page.card
            border.color: flowTextArea.activeFocus ? page.blue : page.controlBorder
        }
    }

    component SectionHeader: RowLayout {
        id: sectionHeader
        property string number: ""
        property string title: ""
        property string subtitle: ""
        spacing: 12
        Rectangle {
            Layout.preferredWidth: 30
            Layout.preferredHeight: 30
            radius: 15
            color: page.blueSoft
            border.color: page.line
            Text {
                objectName: "dailySectionNumber_" + sectionHeader.number
                anchors.centerIn: parent
                text: sectionHeader.number
                color: page.blue
                font.family: page.fontFamily
                font.pixelSize: 14
                font.bold: true
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Text {
                Layout.fillWidth: true
                text: sectionHeader.title
                color: page.ink
                font.family: page.fontFamily
                font.pixelSize: 17
                font.bold: true
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: sectionHeader.subtitle
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 14
                wrapMode: Text.WordWrap
            }
        }
    }

    Dialog {
        id: questionRemoveDialog
        objectName: "dailyQuestionRemoveDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(430, page.width - 24)
        title: qsTr("移除问题")
        contentItem: ColumnLayout {
            spacing: 12
            Text {
                objectName: "dailyQuestionRemoveMessage"
                Layout.fillWidth: true
                text: qsTr("确定从问题簿移除“%1”？移除后不会出现在今天工作台。")
                      .arg(page.selectedQuestionText)
                color: page.ink
                font.family: page.fontFamily
                font.pixelSize: 14
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                FlowButton {
                    objectName: "dailyQuestionRemoveCancelButton"
                    text: qsTr("取消")
                    onClicked: questionRemoveDialog.close()
                }
                FlowButton {
                    objectName: "dailyQuestionRemoveConfirmButton"
                    text: qsTr("移除问题")
                    emphasized: true
                    onClicked: page.confirmRemoveQuestion()
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: page.paper
    }

    Item {
        id: flowContentHost
        objectName: "dailyFlowContent"
        anchors.fill: parent

        ColumnLayout {
            id: flowContent
            x: page.compact ? 12 : 28
            y: page.compact ? 12 : 22
            width: Math.max(0, flowContentHost.width - (page.compact ? 24 : 56))
            spacing: page.compact ? 14 : 20

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: "DAILY FLOW · PERSONAL DESK"
                        color: page.blue
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                        font.letterSpacing: 1.5
                    }
                    Text {
                    text: qsTr("把昨天收好，再开始今天。")
                        color: page.ink
                        font.family: page.serifFamily
                        font.pixelSize: page.compact ? 22 : 26
                        font.bold: true
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        text: qsTr("记录回顾、安排待办，为眼前一件事留出完整时间。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                    }
                }
                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    radius: 6
                    color: page.card
                    border.color: page.line
                    implicitWidth: dateLabel.implicitWidth + 20
                    implicitHeight: 34
                    Text {
                        id: dateLabel
                        anchors.centerIn: parent
                        text: page.todayDateKey
                        color: page.blue
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: page.line
            }

            Rectangle {
                objectName: "dailyReviewCard"
                Layout.fillWidth: true
                implicitHeight: reviewLayout.implicitHeight + 30
                radius: 8
                color: page.card
                border.color: page.line

                ColumnLayout {
                    id: reviewLayout
                    objectName: "dailyReviewSection"
                    anchors.fill: parent
                    anchors.margins: page.compact ? 14 : 22
                    spacing: 12

                    SectionHeader {
                        Layout.fillWidth: true
                        number: "02"
                        title: qsTr("昨日回顾")
                        subtitle: String(page.valueOf(page.review, "date", "")) + " · " + qsTr("仅汇总此工作台记录")
                    }

                    GridLayout {
                        objectName: "dailyReviewGrid"
                        Layout.fillWidth: true
                        columns: page.compact ? 1 : 3
                        rowSpacing: 14
                        columnSpacing: 14
                        ColumnLayout {
                            id: reviewRecordColumn
                            objectName: "dailyReviewRecordColumn"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: 1.2
                            spacing: 8
                            RowLayout {
                                objectName: "dailyReviewListHeader"
                                Layout.fillWidth: true
                                Text {
                                    text: qsTr("昨天留下的记录")
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 13
                                    font.bold: true
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    objectName: "dailyReviewCount"
                                    text: qsTr("%1 条").arg(String(page.valueOf(page.review, "count", page.reviewItems.length)))
                                    color: page.blue
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                            }
                            ColumnLayout {
                                objectName: "dailyReviewItems"
                                Layout.fillWidth: true
                                // Do not let an empty repeater stretch to the
                                // height of the follow-up form in the next column.
                                Layout.fillHeight: false
                                spacing: 0
                                Repeater {
                                    model: page.reviewItems
                                    delegate: Rectangle {
                                        id: reviewItem
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: 58
                                        color: "transparent"
                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 1
                                            color: page.line
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            spacing: 9
                                            Rectangle {
                                                Layout.preferredWidth: 47
                                                Layout.preferredHeight: 22
                                                radius: 4
                                                color: page.softCard
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: page.enumLabel(page.valueOf(reviewItem.modelData, "kind", "记录"))
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                }
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(page.valueOf(reviewItem.modelData, "title", ""))
                                                    color: page.ink
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    wrapMode: Text.WordWrap
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: String(page.valueOf(reviewItem.modelData, "detail", ""))
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                    wrapMode: Text.WordWrap
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                objectName: "dailyReviewEmptyCard"
                                Layout.fillWidth: true
                                Layout.minimumHeight: 92
                                visible: page.reviewItems.length === 0
                                radius: 6
                                color: page.softCard
                                border.color: page.line
                                Text {
                                    objectName: "dailyReviewEmpty"
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    text: qsTr(String(page.valueOf(page.review, "emptyMessage",
                                                         "昨天在这套工作台里还没有个人记录。")))
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillHeight: true
                            Layout.preferredWidth: 1
                            Layout.minimumWidth: 1
                            Layout.preferredHeight: 1
                            visible: !page.compact
                            color: page.line
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            spacing: 7
                            Text {
                                text: qsTr("昨天留给今天的线索")
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 13
                                font.bold: true
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: yesterdayFollowUp.implicitHeight + 20
                                radius: 5
                                color: page.softCard
                                border.color: page.line
                                Text {
                                    id: yesterdayFollowUp
                                    objectName: "dailyYesterdayFollowUp"
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    text: String(page.valueOf(page.review, "followUp", "")) ||
                                          qsTr("昨天没有留下“明早跟进”的内容。")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Text {
                                text: qsTr("给明天的自己留一句跟进线索")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            FlowTextArea {
                                id: followUpInput
                                objectName: "dailyFollowUpInput"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 78
                                placeholderText: qsTr("例如：继续跟进昨天没完成的事项……")
                                onTextChanged: {
                                    if (text.length > 500) {
                                        text = text.slice(0, 500)
                                        return
                                    }
                                    if (!page.syncingEditableDrafts)
                                        page.followUpDirty = true
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: followUpInput.text.length + " / 500"
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                }
                                Item { Layout.fillWidth: true }
                                FlowButton {
                                    objectName: "dailyFollowUpSaveButton"
                                    text: qsTr("保存跟进线索")
                                    emphasized: true
                                    onClicked: page.saveFollowUpDraft()
                                }
                            }
                        }
                    }

                    Rectangle {
                        objectName: "dailyQuestionDesk"
                        visible: page.questionDeskIsVisible()
                        Layout.fillWidth: true
                        implicitHeight: questionLayout.implicitHeight + 20
                        radius: 6
                        color: page.softCard
                        border.color: page.line

                        ColumnLayout {
                            id: questionLayout
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: qsTr("问题簿")
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 13
                                    font.bold: true
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    objectName: "dailyQuestionLimitHint"
                                    text: qsTr("最多保留 12 条；新增会替换最早一条")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 7
                                FlowTextField {
                                    id: questionInput
                                    objectName: "dailyQuestionInput"
                                    Layout.fillWidth: true
                                    maximumLength: 160
                                    placeholderText: qsTr("记下今天想弄明白的一件事")
                                    onAccepted: page.addQuestionDraft()
                                }
                                FlowButton {
                                    objectName: "dailyQuestionAddButton"
                                    text: qsTr("收进问题簿 +")
                                    emphasized: true
                                    enabled: questionInput.text.trim().length > 0
                                    onClicked: page.addQuestionDraft()
                                }
                            }
                            Text {
                                visible: page.questions.length === 0
                                text: qsTr("问题簿还是空的。先记下一件想弄明白的事。")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                Repeater {
                                    model: page.questions
                                    delegate: Rectangle {
                                        id: questionCard
                                        required property var modelData
                                        required property int index
                                        Layout.fillWidth: true
                                        implicitHeight: 40
                                        radius: 4
                                        color: page.card
                                        border.color: page.line
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 6
                                            spacing: 8
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 1
                                                Text {
                                                    objectName: "dailyQuestionText_" + questionCard.index
                                                    Layout.fillWidth: true
                                                    text: page.questionText(questionCard.modelData)
                                                    color: page.ink
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    text: page.questionDate(questionCard.modelData)
                                                    color: page.muted
                                                    font.family: page.fontFamily
                                                    font.pixelSize: 12
                                                }
                                            }
                                            FlowButton {
                                                objectName: "dailyQuestionRemove_" + questionCard.index
                                                text: qsTr("移除")
                                                implicitHeight: 28
                                                onClicked: page.requestRemoveQuestion(
                                                               questionCard.index,
                                                               page.questionText(questionCard.modelData))
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "dailyWorkCard"
                Layout.fillWidth: true
                implicitHeight: workLayout.implicitHeight + 30
                radius: 8
                color: page.card
                border.color: page.line

                ColumnLayout {
                    id: workLayout
                    objectName: "dailyWorkSection"
                    anchors.fill: parent
                    anchors.margins: page.compact ? 14 : 22
                    spacing: 11

                    SectionHeader {
                        Layout.fillWidth: true
                        number: "03"
                        title: qsTr("今日工作")
                        subtitle: qsTr("待办摘要 · 邮件与日历尚未连接")
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("今天的待办")
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 13
                            font.bold: true
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            objectName: "dailyTaskCount"
                            text: qsTr("%1 项").arg(String(page.valueOf(page.todayWork, "taskCount", page.tasks.length)))
                            color: page.blue
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            font.bold: true
                        }
                    }

                    Text {
                        objectName: "dailyTasksEmpty"
                        Layout.fillWidth: true
                        visible: page.tasks.length === 0
                        text: qsTr(String(page.valueOf(page.todayWork, "taskEmptyMessage",
                                             "今天还没有待办，给自己留点空间")))
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        padding: 8
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5
                        Repeater {
                            model: page.tasks
                            delegate: Rectangle {
                                id: dailyTaskCard
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: 62
                                radius: 8
                                color: page.valueOf(dailyTaskCard.modelData, "done", false) ? page.softCard : page.card
                                border.color: page.line
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 9
                                    Rectangle {
                                        Layout.preferredWidth: 8
                                        Layout.preferredHeight: 8
                                        radius: 4
                                        color: page.valueOf(dailyTaskCard.modelData, "done", false) ? page.success : page.card
                                        border.color: page.valueOf(dailyTaskCard.modelData, "done", false) ? page.success : page.line
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(page.valueOf(dailyTaskCard.modelData, "title", qsTr("一项日程")))
                                            color: page.ink
                                            font.family: page.fontFamily
                                            font.pixelSize: 12
                                            font.bold: true
                                            font.strikeout: Boolean(page.valueOf(dailyTaskCard.modelData, "done", false))
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: [page.enumLabel(page.valueOf(dailyTaskCard.modelData, "list", "生活")),
                                                  String(page.valueOf(dailyTaskCard.modelData, "note", ""))]
                                                  .filter(function(part) { return part.length > 0 })
                                                  .join(" · ")
                                            color: page.muted
                                            font.family: page.fontFamily
                                            font.pixelSize: 12
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        text: page.enumLabel(page.valueOf(dailyTaskCard.modelData, "time", "全天"))
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        visible: Boolean(page.valueOf(dailyTaskCard.modelData, "done", false))
                                        text: qsTr("已完成")
                                        color: page.success
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: mailLayout.implicitHeight + 18
                        radius: 5
                        color: page.softCard
                        border.color: page.line
                        ColumnLayout {
                            id: mailLayout
                            anchors.fill: parent
                            anchors.margins: 9
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: qsTr("工作收件箱")
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    objectName: "dailyMailIntegrationStatus"
                                    text: qsTr("尚未集成")
                                    color: page.red
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("这里只提供网页邮箱快捷入口；应用不会读取邮件内容或日历事项。")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                FlowButton {
                                    objectName: "dailyOpenGmailButton"
                                    text: qsTr("打开 Gmail 网页 ↗")
                                    onClicked: Qt.openUrlExternally("https://mail.google.com/mail/u/0/#inbox")
                                }
                                FlowButton {
                                    objectName: "dailyOpenOutlookButton"
                                    text: qsTr("打开 Outlook 网页 ↗")
                                    onClicked: Qt.openUrlExternally("https://outlook.office.com/mail/")
                                }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "dailyFocusCard"
                Layout.fillWidth: true
                implicitHeight: focusLayout.implicitHeight + 30
                radius: 8
                color: page.card
                border.color: page.line

                ColumnLayout {
                    id: focusLayout
                    objectName: "dailyFocusSection"
                    anchors.fill: parent
                    anchors.margins: page.compact ? 14 : 22
                    spacing: 11

                    SectionHeader {
                        Layout.fillWidth: true
                        number: "04"
                        title: qsTr("开始专注")
                        subtitle: qsTr("选择一件事，为它留出一段完整时间")
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: width < 700 ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 12

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            implicitHeight: timerLayout.implicitHeight + 22
                            radius: 12
                            color: page.blueSoft
                            border.color: page.line

                            ColumnLayout {
                                id: timerLayout
                                anchors.fill: parent
                                anchors.margins: 11
                                spacing: 9
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "FOCUS SESSION"
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        font.bold: true
                                        font.letterSpacing: 1
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        text: page.focusModeSummary()
                                        color: page.blue
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                    }
                                }
                                Text {
                                    text: qsTr("这一段先做什么？")
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Text {
                                        text: qsTr("计时方式")
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                    }
                                    UiComboBox {
                                        objectName: "dailyFocusModeSelector"
                                        Layout.fillWidth: true
                                        uiTheme: page.uiTheme
                                        accessibleName: qsTr("计时方式")
                                        enabled: !page.focusRunning
                                        model: page.focusModeOptions
                                        textRole: "label"
                                        currentIndex: page.focusModeIndex()
                                        onActivated: function(index) {
                                            if (index >= 0 && index < page.focusModeOptions.length)
                                                page.setFocusMode(String(page.focusModeOptions[index].value))
                                        }
                                    }
                                    SpinBox {
                                        objectName: "dailyFocusDurationInput"
                                        visible: page.focusMode === "countdown"
                                        enabled: !page.focusRunning
                                        from: 5
                                        to: 480
                                        stepSize: 5
                                        editable: true
                                        value: page.focusCountdownMinutesDraft
                                        Accessible.name: qsTr("倒计时分钟")
                                        textFromValue: function(value, locale) {
                                            return qsTr("%1 分钟").arg(value)
                                        }
                                        valueFromText: function(text, locale) {
                                            var parsed = parseInt(text, 10)
                                            return isFinite(parsed) ? parsed : 25
                                        }
                                        onValueModified: {
                                            page.focusCountdownMinutesDraft = Math.max(5, Math.min(480, value))
                                            if (!page.syncingTimerControls && page.focusMode === "countdown")
                                                page.setFocusMode("countdown")
                                        }
                                    }
                                }
                                FlowTextField {
                                    id: focusTaskInput
                                    objectName: "dailyFocusTaskInput"
                                    Layout.fillWidth: true
                                    enabled: !page.focusRunning
                                    maximumLength: 100
                                    placeholderText: qsTr("手动输入本轮任务或下一步")
                                    onTextChanged: {
                                        if (!page.syncingEditableDrafts) {
                                            page.focusTaskDirty = true
                                            page.focusTaskId = ""
                                        }
                                    }
                                    onEditingFinished: page.saveFocusTaskDraft()
                                }
                                UiComboBox {
                                    objectName: "dailyFocusCandidateSelector"
                                    visible: page.focusCandidates.length > 0
                                    Layout.fillWidth: true
                                    uiTheme: page.uiTheme
                                    accessibleName: qsTr("专注任务")
                                    enabled: !page.focusRunning
                                    model: page.focusCandidateOptions
                                    textRole: "title"
                                    currentIndex: Math.max(0, page.focusCandidateIndex() + 1)
                                    onActivated: function(index) {
                                        var candidateIndex = index - 1
                                        if (candidateIndex >= 0 && candidateIndex < page.focusCandidates.length)
                                            page.chooseFocusCandidate(page.focusCandidates[candidateIndex])
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: page.focusRunning
                                          ? qsTr("本轮专注已锁定当前任务；暂停后可以切换任务。")
                                          : page.focusCandidates.length > 0
                                            ? qsTr("选择今日待办后，专注计时会同步记录实际用时；手写任务只运行专注钟。")
                                            : qsTr("今天没有可关联的待办；手写任务会单独运行专注钟。")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        objectName: "dailyFocusDisplay"
                                        text: page.focusDisplay
                                        color: page.blue
                                        font.family: page.fontFamily
                                        font.pixelSize: 34
                                        font.bold: true
                                        font.letterSpacing: 1
                                    }
                                    Item { Layout.fillWidth: true }
                                    FlowButton {
                                        objectName: "dailyFocusToggleButton"
                                        text: qsTr(page.focusButtonLabel)
                                        emphasized: true
                                        onClicked: {
                                            try {
                                                page.toggleFocusTimer()
                                            } catch (error) {
                                                page.showException(error)
                                            }
                                        }
                                    }
                                    FlowButton {
                                        objectName: "dailyFocusResetButton"
                                        text: page.focusMode === "flowtime" ? qsTr("结束并保存") : qsTr("重置")
                                        enabled: page.focusRunning || page.focusElapsedSecondsSnapshot > 0
                                        onClicked: {
                                            try {
                                                page.resetFocusTimer()
                                            } catch (error) {
                                                page.showException(error)
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    objectName: "dailyFocusProgressTrack"
                                    Layout.fillWidth: true
                                    implicitHeight: 5
                                    radius: 3
                                    color: page.line
                                    Rectangle {
                                        objectName: "dailyFocusProgress"
                                        width: parent.width * page.focusProgress
                                        height: parent.height
                                        radius: 3
                                        color: page.red
                                    }
                                }
                                Text {
                                    text: page.focusRunning ? qsTr("计时进行中，进度与工作时段会保存到本机。")
                                          : page.focusElapsedSecondsSnapshot > 0
                                            ? qsTr("已用时间已保存在本机；恢复后可继续或切换任务。")
                                            : qsTr("计时方式、检查点与任务关联保存在本机。")
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.alignment: Qt.AlignTop
                            implicitHeight: audioLayout.implicitHeight + 22
                            radius: 6
                            color: page.softCard
                            border.color: page.line
                            ColumnLayout {
                                id: audioLayout
                                anchors.fill: parent
                                anchors.margins: 11
                                spacing: 9
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "LISTEN WHILE YOU WORK"
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        font.bold: true
                                        font.letterSpacing: 1
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        objectName: "dailySpotifyDecisionStatus"
                                        text: qsTr("Spotify 外部播放")
                                        color: page.success
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: qsTr(String(page.valueOf(page.persistedState, "spotifyDecisionNote",
                                        "Spotify 链接由系统默认浏览器或 Spotify 应用打开。")))
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: qsTr("链接保存在本机。应用不嵌入网页播放器；点击外部打开后由系统默认浏览器或 Spotify 应用接手播放。")
                                    color: page.ink
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }
                                FlowTextField {
                                    id: spotifyInput
                                    objectName: "dailySpotifyUrlInput"
                                    Layout.fillWidth: true
                                    maximumLength: 300
                                    placeholderText: qsTr("Spotify 单曲、专辑、播放列表或播客链接")
                                    inputMethodHints: Qt.ImhUrlCharactersOnly
                                    onTextChanged: {
                                        if (!page.syncingEditableDrafts)
                                            page.spotifyUrlDirty = true
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    FlowButton {
                                        objectName: "dailySpotifyOpenButton"
                                        text: qsTr("在 Spotify 打开 ↗")
                                        enabled: page.canOpenSpotify
                                        onClicked: page.openSpotifyLink()
                                    }
                                    FlowButton {
                                        objectName: "dailySpotifySaveButton"
                                        text: qsTr("保存链接")
                                        emphasized: true
                                        onClicked: page.saveSpotifyDraft(false)
                                    }
                                    FlowButton {
                                        objectName: "dailySpotifyRemoveButton"
                                        text: qsTr("移除保存的链接")
                                        enabled: String(page.valueOf(page.persistedState, "spotifyUrl", "")).trim().length > 0
                                        onClicked: page.saveSpotifyDraft(true)
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "dailyFlowNotice"
                Layout.fillWidth: true
                visible: page.notice.length > 0
                implicitHeight: noticeLabel.implicitHeight + 16
                radius: 5
                color: page.noticeIsError ? page.dangerSoft : page.blueSoft
                border.color: page.noticeIsError ? page.danger : page.line
                Text {
                    id: noticeLabel
                    objectName: "dailyFlowNoticeText"
                    anchors.fill: parent
                    anchors.margins: 8
                    text: qsTr(String(page.notice))
                    color: page.noticeIsError ? page.red : page.blue
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            Item { Layout.preferredHeight: 2 }
        }
    }

    Connections {
        target: page.controller
        ignoreUnknownSignals: true
        function onStateChanged() {
            page.controllerRevision += 1
            Qt.callLater(function() { page.restoreLinkedFocusTracking() })
        }
    }

    Timer {
        interval: 1
        running: true
        repeat: false
        onTriggered: page.syncControllerSnapshot()
    }

    onTodayDateKeyChanged: refreshEditableDrafts()
    onFocusRunningSnapshotChanged: finishLinkedTracking()

    Component.onCompleted: Qt.callLater(function() { page.restoreLinkedFocusTracking() })
}
