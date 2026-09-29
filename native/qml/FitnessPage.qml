pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "fitnessPage"
    required property var controller
    property var uiTheme: null

    property var snapshot: controller ? (controller.state || ({})) : ({})
    property string notice: ""
    property bool noticeIsError: false
    property string formNotice: ""
    property string deleteRecordId: ""
    property string deleteRecordTitle: ""
    property string deletePlanId: ""
    property string deletePlanTitle: ""

    readonly property var summary: snapshot.summary || ({})
    readonly property var profile: snapshot.profile || ({})
    readonly property var profileFields: UiPageUtils.asList(snapshot.profileFields)
    readonly property var records: UiPageUtils.asList(snapshot.records)
    readonly property var weeklyPlan: UiPageUtils.asList(snapshot.weeklyPlan)
    readonly property var trend: UiPageUtils.asList(snapshot.trend)
    readonly property string trendRange: String(snapshot.trendRange || "90")

    function focusQuickEntry() {
        weightInput.forceActiveFocus()
    }

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
    readonly property string trendNoRecordsText: qsTr("记录体重后即可查看趋势")
    readonly property string trendOneRecordText: qsTr("再记录一次体重，就能看到趋势")
    readonly property color green: success
    readonly property color plum: accentStrong
    readonly property color paper: canvas
    readonly property string fontFamily: sansFamily

    component PageText: Text {
        font.family: page.sansFamily
    }

    component PageButton: Button {
        id: control
        property bool destructive: false
        implicitHeight: 40
        leftPadding: 14
        rightPadding: 14
        contentItem: PageText {
            text: control.text
            color: !control.enabled ? page.muted : ((control.highlighted || control.destructive) ? page.surface : page.ink)
            font.family: page.sansFamily
            font.pixelSize: 13
            font.weight: (control.highlighted || control.destructive) ? Font.DemiBold : Font.Medium
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 10
            color: !control.enabled ? page.surfaceSoft
                  : control.destructive ? (control.down ? Qt.darker(page.danger, 1.12) : page.danger)
                  : control.highlighted ? (control.down ? page.accentStrong : page.accent)
                  : control.down ? page.accentSoft : page.surface
            border.color: control.enabled && control.activeFocus ? page.accentStrong
                         : !control.enabled ? page.controlBorder
                         : control.destructive ? page.danger
                         : control.highlighted ? page.accent : page.controlBorder
            border.width: control.enabled && control.activeFocus ? 2 : 1
        }
    }

    component PageField: TextField {
        id: control
        implicitHeight: 40
        font.family: page.sansFamily
        font.pixelSize: 13
        color: page.ink
        placeholderTextColor: page.muted
        leftPadding: 12
        rightPadding: 12
        background: Rectangle {
            radius: 10
            color: page.surface
            border.color: control.activeFocus ? page.accent : page.controlBorder
        }
    }

    component PageComboBox: UiComboBox {
        uiTheme: page.uiTheme
        implicitHeight: 40
        font.pixelSize: 13
    }

    component PageCheckBox: CheckBox {
        id: control
        font.family: page.sansFamily
        font.pixelSize: 13
        spacing: 9
        indicator: Rectangle {
            implicitWidth: 20
            implicitHeight: 20
            radius: 6
            color: control.checked ? page.accent : page.surface
            border.color: control.checked ? page.accent : page.controlBorder
            PageText { anchors.centerIn: parent; visible: control.checked; text: "✓"; color: page.surface; font.pixelSize: 13; font.bold: true }
        }
        contentItem: PageText {
            leftPadding: control.indicator.width + control.spacing
            text: control.text
            color: page.ink
            font.family: page.sansFamily
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
        }
    }

    component PageDialog: Dialog {
        padding: 18
        background: Rectangle { color: page.surface; border.color: page.line; radius: 14 }
    }

    function localDateKey() {
        return UiPageUtils.localDateKey()
    }
    function showResult(result, success) {
        if (result === true || (result && result.ok === true)) {
            notice = success || qsTr("已保存。")
            noticeIsError = false
            return true
        }
        notice = String(result && result.error ? result.error : qsTr("操作未完成，请检查后重试。"))
        noticeIsError = true
        return false
    }
    function saveRecord() {
        formNotice = ""
        var weight = Number(weightInput.text)
        if (weightInput.text.trim() === "" || !isFinite(weight) || weight < 20 || weight > 300) {
            formNotice = qsTr("体重需填写 20–300 kg 的有效数字。")
            weightInput.forceActiveFocus()
            return
        }
        var durationText = durationInput.text.trim()
        var duration = Number(durationText)
        if (durationText !== "" &&
                (!isFinite(duration) || duration < 0 || duration > 1440 ||
                 Math.floor(duration) !== duration)) {
            formNotice = qsTr("运动分钟需为 0–1440 的整数。")
            durationInput.forceActiveFocus()
            return
        }
        var result = controller.addRecord(weightInput.text.trim(), durationInput.text.trim(),
                                          dateInput.text.trim(), noteInput.text.trim())
        if (showResult(result, qsTr("身体记录已保存到本机。"))) {
            formNotice = ""
            weightInput.clear()
            durationInput.clear()
            noteInput.clear()
        } else {
            formNotice = notice
            if (notice.indexOf("日期") >= 0)
                dateInput.forceActiveFocus()
            else
                weightInput.forceActiveFocus()
        }
    }
    function removeRecord() {
        if (showResult(controller.deleteRecord(deleteRecordId), qsTr("记录已删除。")))
            deleteRecordDialog.close()
    }
    function removePlan() {
        if (showResult(controller.deletePlan(deletePlanId), qsTr("周计划已删除。")))
            deletePlanDialog.close()
    }
    function saveFitnessProfile() {
        var result = controller.saveProfile(
                    Number(heightInput.text), Number(targetInput.text), Number(startWeightInput.text))
        if (showResult(result, qsTr("目标档案已保存。")))
            profileDialog.close()
    }
    function addWeeklyPlan() {
        var result = controller.addPlan(planGroup.currentText, planTitle.text.trim(), planNote.text.trim())
        if (showResult(result, qsTr("计划已加入本周安排。"))) {
            planTitle.clear()
            planNote.clear()
            planDialog.close()
        }
    }
    function requestRecordDelete(record) {
        deleteRecordId = String(record && record.id ? record.id : "")
        var data = record && record.data ? record.data : ({})
        deleteRecordTitle = String(data.weight || qsTr("身体")) + " kg · " + String(record && record.date ? record.date : "")
        deleteRecordDialog.open()
    }
    function requestPlanDelete(item) {
        deletePlanId = String(item && item.id ? item.id : "")
        deletePlanTitle = String(item && item.title ? item.title : qsTr("这项计划"))
        deletePlanDialog.open()
    }

    FileDialog {
        id: exportDialog
        title: qsTr("导出健身记录")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Excel 工作簿 (*.xlsx)")]
        defaultSuffix: "xlsx"
        onAccepted: page.showResult(page.controller.exportExcel(selectedFile), qsTr("健身记录已导出。"))
    }

    PageDialog {
        id: deleteRecordDialog
        objectName: "fitnessDeleteRecordDialog"
        title: qsTr("删除这条身体记录？")
        modal: true
        anchors.centerIn: parent
        width: Math.min(410, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 12
            PageText {
                objectName: "fitnessDeleteRecordMessage"
                text: page.deleteRecordTitle + "\n" + qsTr("删除后，这条身体记录不会再出现在当前本机记录中；导入的旧版原始数据不会被改动。")
                color: page.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PageButton { text: qsTr("取消"); onClicked: deleteRecordDialog.close() }
                PageButton { objectName: "fitnessDeleteRecordConfirmButton"; text: qsTr("删除"); destructive: true; onClicked: page.removeRecord() }
            }
        }
    }

    PageDialog {
        id: deletePlanDialog
        objectName: "fitnessDeletePlanDialog"
        title: qsTr("删除这项计划？")
        modal: true
        anchors.centerIn: parent
        width: Math.min(410, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 12
            PageText { text: page.deletePlanTitle; color: page.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PageButton { text: qsTr("取消"); onClicked: deletePlanDialog.close() }
                PageButton { objectName: "fitnessDeletePlanConfirmButton"; text: qsTr("删除"); destructive: true; onClicked: page.removePlan() }
            }
        }
    }

    PageDialog {
        id: profileDialog
        objectName: "fitnessProfileDialog"
        title: qsTr("目标设置")
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, page.width - 32)
        onOpened: {
            heightInput.text = page.profileFields.indexOf("height") >= 0 ? String(page.profile.height) : ""
            targetInput.text = page.profileFields.indexOf("target") >= 0 ? String(page.profile.target) : ""
            startWeightInput.text = page.profileFields.indexOf("startWeight") >= 0 ? String(page.profile.startWeight) : ""
        }
        contentItem: ColumnLayout {
            spacing: 14
            PageText { text: qsTr("起始体重用于计算目标进度；身高和目标体重用于 BMI 与目标估算。"); color: page.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    PageText { text: qsTr("身高（cm）"); color: page.muted; font.pixelSize: 12 }
                    PageField { id: heightInput; objectName: "fitnessHeightInput"; Layout.fillWidth: true; placeholderText: qsTr("例如：165"); validator: IntValidator { bottom: 100; top: 230 } }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    PageText { text: qsTr("起始体重（kg）"); color: page.muted; font.pixelSize: 12 }
                    PageField { id: startWeightInput; objectName: "fitnessStartWeightInput"; Layout.fillWidth: true; placeholderText: qsTr("例如：60.0"); validator: DoubleValidator { bottom: 20; top: 300; decimals: 1 } }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    PageText { text: qsTr("目标体重（kg）"); color: page.muted; font.pixelSize: 12 }
                    PageField { id: targetInput; objectName: "fitnessTargetInput"; Layout.fillWidth: true; placeholderText: qsTr("例如：55.0"); validator: DoubleValidator { bottom: 30; top: 200; decimals: 1 } }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PageButton { objectName: "fitnessProfileCancelButton"; text: qsTr("取消"); onClicked: profileDialog.close() }
                PageButton {
                    objectName: "fitnessSaveProfileButton"
                    text: qsTr("保存目标")
                    highlighted: true
                    enabled: heightInput.text.trim().length > 0 && heightInput.acceptableInput
                             && startWeightInput.text.trim().length > 0 && startWeightInput.acceptableInput
                             && targetInput.text.trim().length > 0 && targetInput.acceptableInput
                    onClicked: page.saveFitnessProfile()
                }
            }
        }
    }

    PageDialog {
        id: planDialog
        objectName: "fitnessPlanDialog"
        title: qsTr("添加周计划")
        modal: true
        anchors.centerIn: parent
        width: Math.min(480, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 12
            PageText { text: qsTr("周计划只用于健身安排，不会创建日程提醒。"); color: page.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            PageText { text: qsTr("类别"); color: page.muted; font.pixelSize: 12 }
            PageComboBox { id: planGroup; objectName: "fitnessPlanGroup"; model: ["运动", "饮食", "恢复", "其他"]; Layout.fillWidth: true }
            PageText { text: qsTr("计划名称"); color: page.muted; font.pixelSize: 12 }
            PageField { id: planTitle; objectName: "fitnessPlanTitle"; Layout.fillWidth: true; maximumLength: 28; placeholderText: qsTr("必填：例如：快走 3 次") }
            PageText { text: qsTr("补充说明"); color: page.muted; font.pixelSize: 12 }
            PageField { id: planNote; objectName: "fitnessPlanNote"; Layout.fillWidth: true; maximumLength: 60; placeholderText: qsTr("频次、时长或具体做法") }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PageButton { text: qsTr("取消"); onClicked: planDialog.close() }
                PageButton {
                    objectName: "fitnessAddPlanButton"
                    text: qsTr("加入计划")
                    highlighted: true
                    enabled: planTitle.text.trim().length > 0
                    onClicked: page.addWeeklyPlan()
                }
            }
        }
    }

    Rectangle { anchors.fill: parent; z: -1; color: page.canvas }

    ScrollView {
        id: scroll
        objectName: "fitnessScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: width
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            x: 28
            width: Math.max(0, scroll.width - 56)
            spacing: 18

            Item { Layout.preferredHeight: 8 }

            RowLayout {
                Layout.fillWidth: true
                PageText { text: qsTr("健康与运动"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 32; font.bold: true; Layout.fillWidth: true }
                PageButton { objectName: "fitnessProfileButton"; text: qsTr("目标设置"); onClicked: profileDialog.open() }
                PageButton { objectName: "fitnessExportButton"; text: qsTr("导出 Excel"); onClicked: exportDialog.open() }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: page.notice.length > 0 ? 42 : 0
                visible: page.notice.length > 0
                radius: 10
                color: page.noticeIsError ? page.dangerSoft : page.successSoft
                PageText { anchors.fill: parent; anchors.margins: 14; text: page.notice; color: page.noticeIsError ? page.danger : page.success; font.family: page.sansFamily; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width < 520 ? 1 : 3
                rowSpacing: 12
                columnSpacing: 12
                Repeater {
                    model: 3
                    delegate: Rectangle {
                        id: statCard
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredHeight: 104
                        radius: 14
                        color: index === 1 ? page.successSoft : (index === 2 ? page.accentSoft : page.brandSoft)
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 7
                            PageText {
                                text: statCard.index === 0
                                      ? qsTr("当前体重")
                                      : (statCard.index === 1
                                         ? (page.profileFields.indexOf("target") >= 0 ? qsTr("距离目标") : qsTr("目标未设置"))
                                         : (page.summary.bmi === null || page.summary.bmi === undefined
                                            ? qsTr("BMI 待计算") : qsTr("当前 BMI")))
                                color: page.muted
                                font.pixelSize: 12
                            }
                            PageText {
                                objectName: "fitnessStatValue_" + statCard.index
                                text: statCard.index === 0
                                      ? (page.summary.current === null || page.summary.current === undefined
                                         ? qsTr("未记录") : Number(page.summary.current).toFixed(1) + " kg")
                                      : (statCard.index === 1
                                         ? (page.summary.remaining === null || page.summary.remaining === undefined
                                            ? "—" : Number(page.summary.remaining).toFixed(1) + " kg")
                                         : (page.summary.bmi === null || page.summary.bmi === undefined
                                            ? "—" : Number(page.summary.bmi).toFixed(1)))
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 23
                                font.bold: true
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 14
                color: page.surface
                border.color: page.line
                implicitHeight: progressColumn.implicitHeight + 32
                ColumnLayout {
                    id: progressColumn
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 2
                            PageText { text: qsTr("目标进度"); color: page.muted; font.pixelSize: 12 }
                            PageText {
                                text: page.summary.progress === null || page.summary.progress === undefined
                                      ? qsTr("先设置个人体重目标")
                                      : (Number(page.summary.remaining || 0) <= 0
                                         ? qsTr("目标已达成")
                                         : qsTr("稳稳向 %1 kg 前进").arg(Number(page.summary.target).toFixed(1)))
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 18
                                font.bold: true
                            }
                        }
                        Item { Layout.fillWidth: true }
                        PageText { visible: page.summary.progress !== null && page.summary.progress !== undefined; text: Math.round(Number(page.summary.progress)) + "%"; color: page.green; font.pixelSize: 22; font.bold: true }
                    }
                    Rectangle {
                        visible: page.summary.progress !== null && page.summary.progress !== undefined
                        Layout.fillWidth: true
                        Layout.preferredHeight: 10
                        radius: 5
                        color: page.surfaceSoft
                        Rectangle { width: parent.width * Math.max(0, Math.min(100, Number(page.summary.progress || 0))) / 100; height: parent.height; radius: parent.radius; color: page.green }
                    }
                    RowLayout {
                        visible: page.summary.progress !== null && page.summary.progress !== undefined
                        Layout.fillWidth: true
                        PageText { text: qsTr("起点 %1 kg").arg(Number(page.summary.start || 60).toFixed(1)); color: page.muted; font.pixelSize: 12 }
                        Item { Layout.fillWidth: true }
                        PageText { text: qsTr("目标 %1 kg").arg(Number(page.summary.target || 55).toFixed(1)); color: page.muted; font.pixelSize: 12 }
                    }
                    PageText {
                        objectName: "fitnessGoalHint"
                        text: page.summary.progress === null || page.summary.progress === undefined
                              ? (page.summary.hasWeightRecord
                                 ? qsTr("请填写身高、起始体重和目标体重后查看进度。")
                                 : qsTr("请先记录体重，再设置身高和体重目标。"))
                              : (Number(page.summary.remaining || 0) <= 0
                                 ? qsTr("已达到当前目标。")
                                 : (page.summary.days === null || page.summary.days === undefined
                                    ? qsTr("记录两次以上后，可参考体重变化估算进度。")
                                    : qsTr("按近期趋势估算，约还需 %1 天。").arg(String(page.summary.days))))
                        color: page.muted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width >= 1040 ? 2 : 1
                columnSpacing: 18
                rowSpacing: 18

                Rectangle {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    radius: 14
                    color: page.surface
                    border.color: page.line
                    implicitHeight: entryColumn.implicitHeight + 32
                    ColumnLayout {
                        id: entryColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 14
                        PageText { text: qsTr("每日记录"); color: page.ink; font.pixelSize: 17; font.bold: true }
                        PageText { text: qsTr("体重记录必填，运动时长可留空。"); color: page.muted; font.pixelSize: 12 }
                        PageText { text: qsTr("体重（kg）"); color: page.muted; font.pixelSize: 12 }
                        PageField {
                            id: weightInput
                            objectName: "fitnessWeightInput"
                            Layout.fillWidth: true
                            placeholderText: qsTr("必填：例如 64.5")
                            validator: DoubleValidator { bottom: 20; top: 300; decimals: 1 }
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                PageText { text: qsTr("运动分钟（选填）"); color: page.muted; font.pixelSize: 12 }
                                PageField {
                                    id: durationInput
                                    objectName: "fitnessDurationInput"
                                    Layout.fillWidth: true
                                    placeholderText: "0–1440"
                                    validator: IntValidator { bottom: 0; top: 1440 }
                                    inputMethodHints: Qt.ImhDigitsOnly
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                PageText { text: qsTr("日期"); color: page.muted; font.pixelSize: 12 }
                                PageField { id: dateInput; objectName: "fitnessDateInput"; Layout.fillWidth: true; text: page.localDateKey(); placeholderText: "YYYY-MM-DD" }
                            }
                        }
                        PageText { text: qsTr("备注（最多 60 字）"); color: page.muted; font.pixelSize: 12 }
                        PageField { id: noteInput; objectName: "fitnessNoteInput"; Layout.fillWidth: true; maximumLength: 60; placeholderText: qsTr("可以留空") }
                        PageButton {
                            objectName: "fitnessSaveRecordButton"
                            text: qsTr("保存身体记录")
                            highlighted: true
                            Layout.fillWidth: true
                            enabled: weightInput.acceptableInput
                            onClicked: page.saveRecord()
                        }
                        PageText {
                            objectName: "fitnessFormNotice"
                            visible: page.formNotice !== ""
                            text: page.formNotice
                            color: page.danger
                            font.family: page.sansFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    radius: 14
                    color: page.surface
                    border.color: page.line
                    implicitHeight: chartColumn.implicitHeight + 32
                    ColumnLayout {
                        id: chartColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            PageText { text: qsTr("体重趋势"); color: page.ink; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true }
                            UiComboBox {
                                id: trendRangeCombo
                                objectName: "fitnessTrendRangeCombo"
                                uiTheme: page.uiTheme
                                accessibleName: qsTr("趋势时间范围")
                                Layout.preferredWidth: 148
                                model: [qsTr("近 30 天"), qsTr("近 90 天"), qsTr("近 1 年"), qsTr("全部")]
                                currentIndex: page.trendRange === "30" ? 0
                                            : page.trendRange === "365" ? 2
                                            : page.trendRange === "all" ? 3 : 1
                                onActivated: function(index) {
                                    page.controller.setTrendRange(["30", "90", "365", "all"][index])
                                }
                            }
                        }
                        PageText {
                            objectName: "fitnessTrendDescription"
                            visible: page.trend.length > 0
                            text: page.trend.length === 0
                                  ? qsTr("记录体重后查看变化")
                                  : page.trend.length === 1
                                    ? qsTr("已有 1 次有效体重记录")
                                    : qsTr("当前范围内 %1 次测量 · 圆点为记录，虚线为最多 7 次均值").arg(String(page.trend.length))
                            color: page.muted
                            font.pixelSize: 12
                            Layout.fillWidth: true
                        }
                        PageText {
                            objectName: "fitnessTrendEmptyState"
                            visible: page.trend.length < 2
                            text: page.trend.length === 0
                                  ? (page.records.length > 0
                                     ? qsTr("这个时间范围内没有体重记录，试试选择更长的范围。")
                                     : page.trendNoRecordsText)
                                  : page.trendOneRecordText
                            color: page.muted
                            font.pixelSize: 13
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                        }
                        Canvas {
                            id: trendCanvas
                            objectName: "fitnessTrendCanvas"
                            visible: page.trend.length >= 2
                            Layout.fillWidth: true
                            Layout.preferredHeight: 190
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                var points = page.trend
                                var values = []
                                var dates = []
                                for (var i = 0; i < points.length; ++i) {
                                    values.push(Number(points[i].weight))
                                    values.push(Number(points[i].average))
                                    var dateParts = String(points[i].date || "").split("-")
                                    dates.push(dateParts.length === 3
                                               ? new Date(Number(dateParts[0]), Number(dateParts[1]) - 1, Number(dateParts[2]), 12).getTime()
                                               : NaN)
                                }
                                var minValue = Math.min.apply(Math, values)
                                var maxValue = Math.max.apply(Math, values)
                                var spread = Math.max(0.4, maxValue - minValue)
                                minValue -= spread * 0.18
                                maxValue += spread * 0.18
                                var left = 48, right = width - 12, top = 14, bottom = height - 25
                                var validDates = dates.filter(function(value) { return isFinite(value) })
                                var minDate = validDates.length ? Math.min.apply(Math, validDates) : 0
                                var maxDate = validDates.length ? Math.max.apply(Math, validDates) : 0
                                function x(index) {
                                    if (points.length <= 1) return (left + right) / 2
                                    if (maxDate > minDate && isFinite(dates[index]))
                                        return left + (dates[index] - minDate) * (right - left) / (maxDate - minDate)
                                    return left + index * (right - left) / (points.length - 1)
                                }
                                function y(value) { return bottom - (value - minValue) * (bottom - top) / (maxValue - minValue) }
                                ctx.strokeStyle = page.line
                                ctx.lineWidth = 1
                                for (var grid = 0; grid < 4; ++grid) {
                                    var gy = top + grid * (bottom - top) / 3
                                    ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(right, gy); ctx.stroke()
                                    ctx.fillStyle = page.muted
                                    ctx.font = "11px '" + page.sansFamily + "'"
                                    ctx.textAlign = "right"
                                    ctx.fillText((maxValue - grid * (maxValue - minValue) / 3).toFixed(1), left - 7, gy + 4)
                                }
                                ctx.strokeStyle = page.accentStrong
                                ctx.lineWidth = 2.5
                                ctx.setLineDash([])
                                ctx.beginPath()
                                for (var j = 0; j < points.length; ++j) {
                                    if (j === 0) ctx.moveTo(x(j), y(Number(points[j].weight)))
                                    else ctx.lineTo(x(j), y(Number(points[j].weight)))
                                }
                                ctx.stroke()
                                ctx.fillStyle = page.accentStrong
                                for (var dot = 0; dot < points.length; ++dot) {
                                    ctx.beginPath()
                                    ctx.arc(x(dot), y(Number(points[dot].weight)), 3.2, 0, Math.PI * 2)
                                    ctx.fill()
                                }
                                ctx.strokeStyle = page.brand
                                ctx.lineWidth = 2
                                ctx.setLineDash([6, 4])
                                ctx.beginPath()
                                for (var k = 0; k < points.length; ++k) {
                                    if (k === 0) ctx.moveTo(x(k), y(Number(points[k].average)))
                                    else ctx.lineTo(x(k), y(Number(points[k].average)))
                                }
                                ctx.stroke()
                                ctx.setLineDash([])
                                ctx.fillStyle = page.muted
                                ctx.font = "12px '" + page.sansFamily + "'"
                                ctx.textAlign = "left"
                                var firstDate = dates.findIndex(function(value) { return isFinite(value) })
                                var lastDate = -1
                                for (var dateIndex = dates.length - 1; dateIndex >= 0; --dateIndex)
                                    if (isFinite(dates[dateIndex])) { lastDate = dateIndex; break }
                                ctx.fillText(firstDate >= 0 ? String(points[firstDate].date || "").slice(5) : "", left, height - 5)
                                ctx.textAlign = "right"
                                ctx.fillText(lastDate >= 0 ? String(points[lastDate].date || "").slice(5) : "", right, height - 5)
                            }
                        }
                        RowLayout {
                            objectName: "fitnessTrendLegend"
                            Layout.fillWidth: true
                            visible: page.trend.length >= 2
                            PageText { text: qsTr("体重（kg）"); color: page.plum; font.pixelSize: 12 }
                            PageText { text: qsTr("最多 7 次均值"); color: page.brand; font.pixelSize: 12 }
                            Item { Layout.fillWidth: true }
                            PageText { text: page.summary.days === null || page.summary.days === undefined ? qsTr("趋势估算待积累") : qsTr("预计约 %1 天").arg(String(page.summary.days)); color: page.muted; font.pixelSize: 12 }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.columnSpan: page.width >= 1040 ? 2 : 1
                    radius: 14
                    color: page.surface
                    border.color: page.line
                    implicitHeight: planColumn.implicitHeight + 32
                    ColumnLayout {
                        id: planColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                spacing: 2
                                PageText { text: qsTr("本周计划"); color: page.ink; font.pixelSize: 17; font.bold: true }
                                PageText {
                                    objectName: "fitnessWeeklyPlanSummary"
                                    visible: page.weeklyPlan.length > 0
                                    text: {
                                        var complete = 0
                                        for (var i = 0; i < page.weeklyPlan.length; ++i)
                                            if (page.weeklyPlan[i].done) complete += 1
                                        return qsTr("%1 / %2 已完成 · 还有 %3 项")
                                            .arg(String(complete))
                                            .arg(String(page.weeklyPlan.length))
                                            .arg(String(page.weeklyPlan.length - complete))
                                    }
                                    color: page.muted
                                    font.pixelSize: 12
                                }
                            }
                            Item { Layout.fillWidth: true }
                            PageButton { objectName: "fitnessAddPlanOpenButton"; text: qsTr("新增计划"); onClicked: planDialog.open() }
                        }
                        ListView {
                            id: weeklyPlanList
                            objectName: "fitnessWeeklyPlanList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 300)
                            implicitHeight: 0
                            model: page.weeklyPlan
                            spacing: 6
                            clip: true
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            delegate: Rectangle {
                                id: planDelegate
                                required property var modelData
                                required property int index
                                width: weeklyPlanList.width
                                height: 54
                                radius: 11
                                color: modelData.done ? page.successSoft : page.surfaceSoft
                                border.color: page.line
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 9
                                    anchors.rightMargin: 8
                                    spacing: 8
                                    PageCheckBox {
                                        objectName: "fitnessPlanCheck_" + String(planDelegate.modelData.id || planDelegate.index)
                                        checked: Boolean(planDelegate.modelData.done)
                                        Accessible.name: checked ? qsTr("标记计划未完成") : qsTr("标记计划已完成")
                                        onToggled: page.showResult(page.controller.togglePlan(String(planDelegate.modelData.id || "")), qsTr("计划完成状态已更新。"))
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        PageText { text: String(planDelegate.modelData.title || qsTr("未命名计划")); color: page.ink; font.pixelSize: 12; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                        PageText { text: String(planDelegate.modelData.group || "其他") + " · " + String(planDelegate.modelData.note || qsTr("按自己的节奏完成")); color: page.muted; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                                    }
                                    PageButton {
                                        objectName: "fitnessDeletePlan_" + String(planDelegate.modelData.id || planDelegate.index)
                                        text: qsTr("删除")
                                        onClicked: page.requestPlanDelete(planDelegate.modelData)
                                    }
                                }
                            }
                        }
                        PageText { visible: page.weeklyPlan.length === 0; text: qsTr("还没有周计划，添加一项适合自己的安排。"); color: page.muted; font.pixelSize: 12; Layout.fillWidth: true }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.columnSpan: page.width >= 1040 ? 2 : 1
                    radius: 14
                    color: page.surface
                    border.color: page.line
                    implicitHeight: recordsColumn.implicitHeight + 32
                    ColumnLayout {
                        id: recordsColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            PageText { text: qsTr("最近身体记录"); color: page.ink; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true }
                            PageText { text: qsTr("显示最近 20 条 · 导出包含全部记录"); color: page.muted; font.pixelSize: 12 }
                        }
                        ListView {
                            id: recordList
                            objectName: "fitnessRecordList"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(contentHeight, 340)
                            implicitHeight: 0
                            model: page.records
                            spacing: 2
                            clip: true
                            delegate: Rectangle {
                                id: recordDelegate
                                required property var modelData
                                required property int index
                                width: recordList.width
                                height: recordDelegate.index < 20 ? 54 : 0
                                visible: recordDelegate.index < 20
                                color: "transparent"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 4
                                    anchors.rightMargin: 4
                                    spacing: 10
                                    PageText { text: String(recordDelegate.modelData.date || ""); color: page.muted; font.pixelSize: 12; Layout.preferredWidth: 94 }
                                    PageText {
                                        text: {
                                            var data = recordDelegate.modelData.data || ({})
                                            return (data.weight ? Number(data.weight).toFixed(1) + " kg" : qsTr("身体记录")) +
                                                   (data.duration ? qsTr(" · %1 分钟运动").arg(String(data.duration)) : "")
                                        }
                                        color: page.ink
                                        font.pixelSize: 12
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    PageText { text: String((recordDelegate.modelData.data || ({})).note || ""); color: page.muted; font.pixelSize: 12; elide: Text.ElideRight; Layout.maximumWidth: 220 }
                                    PageButton { objectName: "fitnessDeleteRecord_" + String(recordDelegate.modelData.id || recordDelegate.index); text: qsTr("删除"); onClicked: page.requestRecordDelete(recordDelegate.modelData) }
                                }
                            }
                        }
                        PageText { objectName: "fitnessNoRecordsText"; visible: page.records.length === 0; text: qsTr("保存后的记录会显示在这里。"); color: page.muted; font.pixelSize: 12; Layout.fillWidth: true }
                    }
                }
            }

            Item { Layout.preferredHeight: 28 }
        }
    }

    Connections {
        target: page.controller
        function onStateChanged() { trendCanvas.requestPaint() }
    }
    onTrendChanged: trendCanvas.requestPaint()
    onUiThemeChanged: trendCanvas.requestPaint()
    onTrendNoRecordsTextChanged: trendCanvas.requestPaint()
    onTrendOneRecordTextChanged: trendCanvas.requestPaint()
}
