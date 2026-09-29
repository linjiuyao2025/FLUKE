pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "financePage"
    required property var controller
    property var uiTheme: null
    property var snapshot: controller ? (controller.state || ({})) : ({})
    property string notice: ""
    property bool noticeIsError: false
    property string formNotice: ""
    property string deleteId: ""
    property string deleteTitle: ""

    readonly property var summary: snapshot.summary || ({})
    readonly property var settings: snapshot.settings || ({})
    readonly property var ledgerRows: UiPageUtils.asList(snapshot.records)
    readonly property var categoryRows: UiPageUtils.asList(snapshot.categories)
    readonly property var expenseOptions: UiPageUtils.asList(snapshot.expenseCategories)
    readonly property var incomeOptions: UiPageUtils.asList(snapshot.incomeCategories)
    readonly property var filterOptions: {
        var options = [qsTr("全部分类")].concat(expenseOptions).concat(incomeOptions)
        var selected = String(settings.moneyFilter || "all")
        if (selected !== "all" && options.indexOf(selected) < 0)
            options.push(selected)
        return options
    }

    function focusQuickEntry() {
        amountInput.forceActiveFocus()
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
    readonly property color blue: accent
    readonly property color red: danger
    readonly property string fontFamily: sansFamily

    component PageButton: Button {
        id: control
        property bool destructive: false
        implicitHeight: 40
        leftPadding: 14
        rightPadding: 14
        contentItem: Text {
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

    component PageProgressBar: ProgressBar {
        id: control
        implicitHeight: 8
        background: Rectangle { radius: 4; color: page.surfaceSoft }
        contentItem: Item {
            Rectangle {
                width: parent.width * control.visualPosition
                height: parent.height
                radius: 4
                color: page.accent
            }
        }
    }

    component PageDialog: Dialog {
        padding: 18
        background: Rectangle { color: page.surface; border.color: page.line; radius: 14 }
    }

    function pad2(value) { return value < 10 ? "0" + value : String(value) }
    function localDateKey() {
        return UiPageUtils.localDateKey()
    }
    function money(value) {
        var number = Number(value)
        return "¥" + (isFinite(number) ? (Math.round(number * 100) / 100).toFixed(2) : "0.00")
    }
    function payloadOf(record) { return record && record.data ? record.data : ({}) }
    function messageForAlert() {
        var reason = String(summary.alertReason || "")
        if (reason === "over_budget")
            return qsTr("本月支出超出预算 %1").arg(money(Number(summary.expense || 0) - Number(summary.budget || 0)))
        if (reason === "no_today_record") return qsTr("今天尚无账目；本月统计仅包含已记录的数据。")
        if (reason === "backup_reminder") return qsTr("已新增 20 笔账目，建议导出完整备份。")
        return ""
    }
    function showResult(result, success) {
        if (result && result.ok === true) {
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
        var amount = Number(amountInput.text)
        if (amountInput.text.trim() === "" || !isFinite(amount) || amount <= 0) {
            formNotice = qsTr("金额必须是大于 0 的有效数字。")
            amountInput.forceActiveFocus()
            return
        }
        var options = flowBox.currentIndex === 1 ? incomeOptions : expenseOptions
        if (categoryBox.currentIndex < 0 || categoryBox.currentIndex >= options.length) {
            formNotice = qsTr("请选择有效分类。")
            categoryBox.forceActiveFocus()
            return
        }
        var flow = flowBox.currentIndex === 1 ? "income" : "expense"
        var saved = showResult(controller.addRecord(flow, amountInput.text.trim(),
                                                    options[categoryBox.currentIndex],
                                                    dateInput.text.trim(), noteInput.text.trim()),
                               qsTr("这笔账已保存到本机。"))
        if (saved) {
            formNotice = ""
            amountInput.clear()
            noteInput.clear()
            dateInput.text = page.localDateKey()
        } else {
            formNotice = notice
            if (notice.indexOf("日期") >= 0)
                dateInput.forceActiveFocus()
            else
                amountInput.forceActiveFocus()
        }
    }
    function deleteEntry() {
        if (showResult(controller.deleteRecord(deleteId), qsTr("流水已删除。")))
            deleteDialog.close()
    }
    function dateString(value) {
        return String(value.getFullYear()) + "-" + pad2(value.getMonth() + 1) + "-" + pad2(value.getDate())
    }

    FileDialog {
        id: exportDialog
        title: qsTr("导出记账流水")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Excel 工作簿 (*.xlsx)")]
        defaultSuffix: "xlsx"
        onAccepted: page.showResult(page.controller.exportExcel(exportDialog.selectedFile), qsTr("Excel 流水已导出到所选位置。"))
    }
    PageDialog {
        id: deleteDialog
        objectName: "financeDeleteDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(410, page.width - 28)
        title: qsTr("删除这条流水？")
        background: Rectangle { color: page.surface; border.color: page.line; radius: 14 }
        contentItem: ColumnLayout {
            spacing: 10
            Text {
                objectName: "financeDeleteMessage"
                text: page.deleteTitle + "\n" + qsTr("删除后，这条流水只会从当前本机账本中隐藏；导入的旧版原始数据不会被改动。")
                color: page.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PageButton { text: qsTr("取消"); onClicked: deleteDialog.close() }
                PageButton { objectName: "financeDeleteConfirmButton"; text: qsTr("删除"); destructive: true; onClicked: page.deleteEntry() }
            }
        }
    }
    PageDialog {
        id: calendarDialog
        objectName: "financeCalendarDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(340, page.width - 28)
        title: qsTr("选择日期")
        background: Rectangle { color: page.surface; border.color: page.line; radius: 14 }
        property int displayedYear: new Date().getFullYear()
        property int displayedMonth: new Date().getMonth()
        onOpened: {
            var parts = dateInput.text.split("-")
            var parsed = parts.length === 3 ? new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])) : new Date()
            if (!isNaN(parsed.getTime())) {
                displayedYear = parsed.getFullYear()
                displayedMonth = parsed.getMonth()
            }
        }
        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                PageButton {
                    objectName: "financeCalendarPreviousMonth"
                    text: "‹"
                    Accessible.name: qsTr("上个月")
                    onClicked: {
                        if (calendarDialog.displayedMonth === 0) {
                            calendarDialog.displayedMonth = 11
                            calendarDialog.displayedYear -= 1
                        } else calendarDialog.displayedMonth -= 1
                    }
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("%1年 %2月").arg(String(calendarDialog.displayedYear)).arg(page.pad2(calendarDialog.displayedMonth + 1))
                    color: page.ink
                    font.family: page.fontFamily
                    font.bold: true
                }
                PageButton {
                    objectName: "financeCalendarNextMonth"
                    text: "›"
                    Accessible.name: qsTr("下个月")
                    onClicked: {
                        if (calendarDialog.displayedMonth === 11) {
                            calendarDialog.displayedMonth = 0
                            calendarDialog.displayedYear += 1
                        } else calendarDialog.displayedMonth += 1
                    }
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 7
                columnSpacing: 2
                rowSpacing: 2
                Repeater {
                    model: [qsTr("日"), qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六")]
                    delegate: Text {
                        required property string modelData
                        text: modelData
                        color: page.muted
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                }
                Repeater {
                    model: 42
                    delegate: PageButton {
                        required property int index
                        readonly property var cellDate: new Date(calendarDialog.displayedYear, calendarDialog.displayedMonth,
                            1 - new Date(calendarDialog.displayedYear, calendarDialog.displayedMonth, 1).getDay() + index)
                        readonly property bool inDisplayedMonth: cellDate.getMonth() === calendarDialog.displayedMonth
                        objectName: "financeCalendarDay" + String(index)
                        text: String(cellDate.getDate())
                        enabled: inDisplayedMonth
                        opacity: inDisplayedMonth ? 1 : 0.35
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        onClicked: {
                            dateInput.text = page.dateString(cellDate)
                            calendarDialog.close()
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                PageButton {
                    objectName: "financeCalendarTodayButton"
                    text: qsTr("今天")
                    onClicked: {
                        dateInput.text = page.localDateKey()
                        calendarDialog.close()
                    }
                }
                Item { Layout.fillWidth: true }
                PageButton { text: qsTr("关闭"); onClicked: calendarDialog.close() }
            }
        }
    }

    Rectangle { anchors.fill: parent; z: -1; color: page.canvas }

    ScrollView {
        id: scroll
        objectName: "financeScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: width
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        ColumnLayout {
            width: scroll.width
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                Layout.topMargin: 24
                Text { text: qsTr("收支手账"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 30; font.bold: true; Layout.fillWidth: true }
                PageButton { objectName: "financeExportButton"; text: qsTr("导出 Excel"); onClicked: exportDialog.open() }
            }
            Text {
                objectName: "financeStorageHint"
                text: qsTr("本机保存 · 导入的旧版数据不会被改动")
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                Layout.fillWidth: true
            }
            Text {
                objectName: "financeNotice"
                visible: page.notice !== "" || String(page.snapshot.notice || "") !== ""
                text: page.notice || String(page.snapshot.notice || "")
                color: page.noticeIsError ? page.red : page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                Layout.fillWidth: true
            }
            Text {
                objectName: "financeAlert"
                visible: page.messageForAlert() !== ""
                text: page.messageForAlert()
                color: page.summary.overBudget ? page.red : page.ink
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                Layout.fillWidth: true
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                columns: page.width < 640 ? 2 : 4
                columnSpacing: page.width < 900 ? 8 : 12
                rowSpacing: page.width < 900 ? 8 : 12
                Repeater {
                    model: 4
                    delegate: Rectangle {
                        id: card
                        required property int index
                        objectName: "financeSummaryCard_" + index
                        readonly property var cardLabels: [qsTr("本月收入"), qsTr("本月支出"), qsTr("本月结余"), qsTr("日均支出")]
                        readonly property var cardColors: [page.success, page.red, page.blue, page.brand]
                        function amountAt(position) {
                            if (position === 0) return page.money(page.summary.income || 0)
                            if (position === 1) return page.money(page.summary.expense || 0)
                            if (position === 2) return page.money(page.summary.balance || 0)
                            return page.money((page.snapshot.consumption || {}).dailyAverage || 0)
                        }
                        Layout.fillWidth: true
                        Layout.preferredHeight: page.width < 900 ? 76 : 96
                        color: page.surface
                        border.color: page.line
                        radius: 14
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: page.width < 900 ? 10 : 16
                            spacing: page.width < 900 ? 4 : 10
                            Text { text: card.cardLabels[card.index]; color: page.muted; font.family: page.fontFamily; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }
                            Text { text: card.amountAt(card.index); color: card.cardColors[card.index]; font.family: page.fontFamily; font.pixelSize: page.width < 900 ? 19 : 21; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                    }
                }
            }

            Frame {
                objectName: "financeBudgetPanel"
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                background: Rectangle { color: page.surface; border.color: page.line; radius: 13 }
                ColumnLayout {
                    width: parent.width
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTr("月度预算"); color: page.ink; font.family: page.fontFamily; font.bold: true; Layout.fillWidth: true }
                        Text {
                            objectName: "financeBudgetAmountLabel"
                            text: qsTr("预算 %1").arg(page.money(page.summary.budget === undefined || page.summary.budget === null ? 5000 : page.summary.budget))
                                    + (Boolean(page.settings.budgetIsDefault) ? qsTr(" · 默认值") : "")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                        }
                    }
                    PageProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: Number(page.summary.budgetBarPercent || 0) }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTr("已使用 %1%").arg(String(page.summary.budgetUsedPercent || 0)); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.fillWidth: true }
                        Text { text: qsTr("剩余 %1").arg(page.money(page.summary.budgetRemaining || 0)); color: Number(page.summary.budgetRemaining || 0) < 0 ? page.red : page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            objectName: "financeBudgetField"
                            Layout.fillWidth: true
                            Text { objectName: "financeBudgetLabel"; text: qsTr("本月预算金额"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            PageField {
                                id: budgetInput
                                objectName: "financeBudgetInput"
                                Accessible.name: qsTr("本月预算金额")
                                text: String(page.settings.budget === undefined || page.settings.budget === null ? 5000 : page.settings.budget)
                                placeholderText: qsTr("例如 5000")
                                Layout.fillWidth: true
                            }
                        }
                        PageButton { objectName: "financeBudgetSaveButton"; text: Boolean(page.settings.budgetIsDefault) ? qsTr("设置预算") : qsTr("更新预算"); onClicked: page.showResult(page.controller.setBudget(budgetInput.text.trim()), qsTr("月度预算已更新。")) }
                    }
                    Text {
                        objectName: "financeBudgetDefaultHint"
                        visible: Boolean(page.settings.budgetIsDefault)
                        text: qsTr("当前使用应用默认预算 %1；设置后按你的实际月预算统计。")
                                .arg(page.money(page.summary.budget === undefined || page.summary.budget === null ? 5000 : page.summary.budget))
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Text {
                        text: {
                            var top = (page.snapshot.consumption || {}).topCategory
                            var largest = (page.snapshot.consumption || {}).largestExpense
                            var largestData = page.payloadOf(largest)
                            return (top ? qsTr("本月最多：%1 %2").arg(top.category).arg(page.money(top.amount)) : qsTr("本月尚无支出分类"))
                                    + (largest ? qsTr(" · 单笔最高：%1").arg(page.money(largestData.amount || 0)) : "")
                        }
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Text {
                        text: {
                            var difference = Number(page.summary.expenseDifference || 0)
                            var percent = page.summary.expenseDifferencePercent
                            if (percent === null || percent === undefined)
                                return qsTr("上月支出 %1 · 暂无可比基数").arg(page.money(page.summary.previousExpense || 0))
                            return qsTr("上月支出 %1 · 本月%2 %3（%4%）")
                                    .arg(page.money(page.summary.previousExpense || 0))
                                    .arg(difference > 0 ? qsTr("增加") : (difference < 0 ? qsTr("减少") : qsTr("持平")))
                                    .arg(page.money(Math.abs(difference)))
                                    .arg(percent)
                        }
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                background: Rectangle { color: page.surface; border.color: page.line; radius: 13 }
                ColumnLayout {
                    width: parent.width
                    spacing: 9
                    Text { text: qsTr("记一笔账"); color: page.ink; font.family: page.fontFamily; font.bold: true; font.pixelSize: 14 }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 560 ? 1 : (page.width < 1000 ? 2 : 4)
                        columnSpacing: 7
                        rowSpacing: 7
                        ColumnLayout {
                            objectName: "financeFlowField"
                            Layout.fillWidth: true
                            Text { objectName: "financeFlowLabel"; text: qsTr("类型"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            PageComboBox { id: flowBox; objectName: "financeFlowBox"; Accessible.name: qsTr("收支类型"); model: [qsTr("支出"), qsTr("收入")]; Layout.fillWidth: true }
                        }
                        ColumnLayout {
                            objectName: "financeAmountField"
                            Layout.fillWidth: true
                            Text { objectName: "financeAmountLabel"; text: qsTr("金额"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            PageField {
                                id: amountInput
                                objectName: "financeAmountInput"
                                Accessible.name: qsTr("金额")
                                placeholderText: qsTr("必填，例如 12.50")
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                validator: DoubleValidator { bottom: 0.01; decimals: 2; notation: DoubleValidator.StandardNotation }
                                Layout.fillWidth: true
                            }
                        }
                        ColumnLayout {
                            objectName: "financeCategoryField"
                            Layout.fillWidth: true
                            Text { objectName: "financeCategoryLabel"; text: qsTr("分类"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            PageComboBox {
                                id: categoryBox
                                objectName: "financeCategoryBox"
                                Accessible.name: qsTr("收支分类")
                                model: flowBox.currentIndex === 1 ? page.incomeOptions : page.expenseOptions
                                Layout.fillWidth: true
                            }
                        }
                        ColumnLayout {
                            objectName: "financeDateField"
                            Layout.fillWidth: true
                            Text { objectName: "financeDateLabel"; text: qsTr("日期"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            RowLayout {
                                Layout.fillWidth: true
                                PageField { id: dateInput; objectName: "financeDateInput"; Accessible.name: qsTr("日期"); text: page.localDateKey(); placeholderText: "YYYY-MM-DD"; Layout.fillWidth: true }
                                PageButton { objectName: "financeDatePickerButton"; Accessible.name: qsTr("打开日期选择"); text: qsTr("选日期"); onClicked: calendarDialog.open() }
                                PageButton { objectName: "financeTodayButton"; Accessible.name: qsTr("使用今天"); text: qsTr("今天"); onClicked: dateInput.text = page.localDateKey() }
                            }
                        }
                        ColumnLayout {
                            objectName: "financeNoteField"
                            Layout.fillWidth: true
                            Text { objectName: "financeNoteLabel"; text: qsTr("备注"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            PageField { id: noteInput; objectName: "financeNoteInput"; Accessible.name: qsTr("备注"); placeholderText: qsTr("可选，最多 60 字"); maximumLength: 60; Layout.fillWidth: true }
                        }
                        PageButton {
                            objectName: "financeSaveButton"
                            text: qsTr("记下这笔")
                            highlighted: true
                            enabled: amountInput.acceptableInput && Number(amountInput.text) > 0
                            onClicked: page.saveRecord()
                        }
                    }
                    Text {
                        objectName: "financeFormNotice"
                        visible: page.formNotice !== ""
                        text: page.formNotice
                        color: page.danger
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                background: Rectangle { color: page.surface; border.color: page.line; radius: 13 }
                ColumnLayout {
                    width: parent.width
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                    Text { text: qsTr("消费结构"); color: page.ink; font.family: page.fontFamily; font.bold: true; Layout.fillWidth: true }
                        Text { text: qsTr("%1 · 分类支出").arg(String(page.summary.month || "")); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    }
                    Text { visible: page.categoryRows.length === 0; text: qsTr("本月还没有支出记录。"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    ColumnLayout {
                        objectName: "financeSpendingStructure"
                        visible: page.categoryRows.length > 0
                        Layout.fillWidth: true
                        spacing: 9
                        Repeater {
                            model: page.categoryRows
                            delegate: RowLayout {
                                id: categoryRow
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 9
                                Text { objectName: "financeCategoryName"; text: String(categoryRow.modelData.category || "其他"); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 70; elide: Text.ElideRight }
                                PageProgressBar { Layout.fillWidth: true; from: 0; to: 1; value: Number(categoryRow.modelData.share || 0) }
                                Text { objectName: "financeCategoryShare"; text: Math.round(Number(categoryRow.modelData.share || 0) * 100) + "%"; color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 38; horizontalAlignment: Text.AlignRight }
                                Text { objectName: "financeCategoryAmount"; text: page.money(categoryRow.modelData.amount); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 86; horizontalAlignment: Text.AlignRight }
                            }
                        }
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                Layout.leftMargin: 28
                Layout.rightMargin: 28
                Layout.bottomMargin: 26
                background: Rectangle { color: page.surface; border.color: page.line; radius: 13 }
                ColumnLayout {
                    width: parent.width
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                    Text { text: qsTr("流水"); color: page.ink; font.family: page.fontFamily; font.bold: true; Layout.fillWidth: true }
                        PageComboBox {
                            id: filterBox
                            objectName: "financeFilterBox"
                            model: page.filterOptions
                            Component.onCompleted: currentIndex = Math.max(0, page.filterOptions.indexOf(String(page.settings.moneyFilter || "all")))
                            onActivated: page.showResult(page.controller.setFilter(filterBox.currentIndex === 0 ? "all" : String(page.filterOptions[filterBox.currentIndex])), qsTr("流水筛选已更新。"))
                        }
                    }
                    Text { visible: page.ledgerRows.length === 0; text: qsTr("还没有符合筛选条件的账目。"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                    Repeater {
                        model: page.ledgerRows
                        delegate: Rectangle {
                            id: ledgerRow
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 52
                            color: page.surfaceSoft
                            border.color: page.line
                            radius: 9
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 9
                                anchors.rightMargin: 7
                                spacing: 7
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { text: String(ledgerRow.modelData.date || "") + " · " + String(page.payloadOf(ledgerRow.modelData).category || qsTr("未分类")); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Text { text: String(page.payloadOf(ledgerRow.modelData).note || ""); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                Text {
                                    text: (page.payloadOf(ledgerRow.modelData).flow === "income" ? "+ " : "− ") + page.money(page.payloadOf(ledgerRow.modelData).amount || 0)
                                    color: page.payloadOf(ledgerRow.modelData).flow === "income" ? page.success : page.red
                                    font.family: page.fontFamily
                                    font.pixelSize: 13
                                    font.bold: true
                                }
                                PageButton {
                                    objectName: "financeRecordDeleteButton"
                                    text: qsTr("删除")
                                    onClicked: {
                                        page.deleteId = String(ledgerRow.modelData.id || "")
                                        page.deleteTitle = String(ledgerRow.modelData.date || "") + " · " + String(page.payloadOf(ledgerRow.modelData).category || "") + " · " + page.money(page.payloadOf(ledgerRow.modelData).amount || 0)
                                        deleteDialog.open()
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

}
