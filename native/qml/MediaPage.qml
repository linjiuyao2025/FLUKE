pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "mediaPage"
    required property var controller
    property var uiTheme: null

    property var snapshot: controller ? (controller.state || ({})) : ({})
    property string notice: ""
    property bool noticeIsError: false
    property string formNotice: ""
    property string pendingCover: ""
    property string draftStatus: "草稿自动保存"
    property int formRating: 0
    property bool formEdited: false
    property bool draftInitialized: false
    property int pickerYear: Number(String(snapshot.today || "2026").slice(0, 4))
    property int pickerMonth: Number(String(snapshot.today || "2026-01").slice(5, 7)) - 1
    property string deleteId: ""
    property string deleteTitle: ""

    readonly property var summary: snapshot.summary || ({})
    readonly property var settings: snapshot.settings || ({})
    readonly property var entries: UiPageUtils.asList(snapshot.filteredItems)
    readonly property string activeStatus: String(settings.mediaStatusFilter || "all")
    readonly property int activeRating: Number(settings.mediaRatingFilter || 0)
    readonly property bool wallView: String(settings.mediaView || "wall") === "wall"
    readonly property var weekdayLabels: [qsTr("日"), qsTr("一"), qsTr("二"), qsTr("三"), qsTr("四"), qsTr("五"), qsTr("六")]

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
    readonly property color green: success
    readonly property color plum: accent
    readonly property color red: danger
    readonly property color paper: canvas
    readonly property string sansFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property string serifFamily: uiTheme ? uiTheme.serifFamily : "Noto Serif SC"
    readonly property string fontFamily: sansFamily

    component MediaTranslatedComboBox: UiComboBox {
        id: translatedCombo
        contentItem: Text {
            leftPadding: translatedCombo.leftPadding
            rightPadding: translatedCombo.rightPadding
            text: translatedCombo.currentIndex >= 0
                  ? qsTr(translatedCombo.currentText) : translatedCombo.displayText
            color: translatedCombo.enabled ? translatedCombo.inkColor : translatedCombo.mutedColor
            font: translatedCombo.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        delegate: ItemDelegate {
            id: translatedOption
            required property int index
            width: translatedCombo.width
            height: 36
            highlighted: translatedCombo.highlightedIndex === index
            contentItem: Text {
                text: qsTr(translatedCombo.textAt(translatedOption.index))
                color: translatedOption.highlighted ? translatedCombo.accentColor : translatedCombo.inkColor
                font.family: translatedCombo.font.family
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                leftPadding: 10
                rightPadding: 10
            }
            background: Rectangle {
                radius: 6
                color: translatedOption.highlighted ? translatedCombo.accentSoftColor : translatedCombo.surfaceColor
            }
        }
    }

    function ratingLabel(value) {
        var amount = Number(value)
        return amount > 0 ? "★".repeat(Math.max(0, Math.min(5, Math.floor(amount)))) : qsTr("未评分")
    }
    function enumLabel(value) {
        return value === null || value === undefined || String(value) === ""
                ? "" : qsTr(String(value))
    }
    function coverSource(value) {
        var source = String(value || "")
        // Imported external cover references are preserved in SQLite, but are
        // deliberately not fetched. Only inline image data is shown offline.
        return source.indexOf("data:image/") === 0 ? source : ""
    }
    function resultOk(result) {
        return result === true || (result && result.ok === true)
    }
    function showResult(result, success) {
        if (resultOk(result)) {
            notice = success || "已保存。"
            noticeIsError = false
            return true
        }
            notice = String(result && result.error ? result.error : "操作未完成，请检查后重试。")
        noticeIsError = true
        return false
    }
    function showFormError(message, focusTarget) {
        formNotice = message
        notice = ""
        noticeIsError = false
        focusTarget.forceActiveFocus()
        Qt.callLater(function() {
            var flickable = scroll.contentItem as Flickable
            if (!flickable || !formNoticeLabel.visible)
                return
            var content = flickable.contentItem
            var noticeTop = formNoticeLabel.mapToItem(content, 0, 0).y
            var focusTop = focusTarget.mapToItem(content, 0, 0).y
            var viewportTop = Number(flickable.contentY || 0)
            var viewportHeight = Number(flickable.height || 0)
            var margin = 20
            var nextY = viewportTop
            var neededTop = Math.min(noticeTop, focusTop)
            var neededBottom = Math.max(noticeTop + formNoticeLabel.height,
                                        focusTop + focusTarget.height)
            if (neededBottom - neededTop <= viewportHeight - margin * 2) {
                if (neededTop < viewportTop + margin)
                    nextY = neededTop - margin
                else if (neededBottom > viewportTop + viewportHeight - margin)
                    nextY = neededBottom + margin - viewportHeight
            } else if (noticeTop < viewportTop + margin) {
                nextY = noticeTop - margin
            } else if (noticeTop + formNoticeLabel.height > viewportTop + viewportHeight - margin) {
                nextY = noticeTop + formNoticeLabel.height + margin - viewportHeight
            }
            var maxY = Math.max(0, Number(flickable.contentHeight || 0) - viewportHeight)
            flickable.contentY = Math.max(0, Math.min(maxY, nextY))
        })
    }
    function addItem() {
        formNotice = ""
        if (nameField.text.trim() === "") {
            notice = "作品名称不能为空。"
            noticeIsError = true
            showFormError(notice, nameField)
            return
        }
        var result = controller.addItem(
                    nameField.text, typeBox.currentText, statusBox.currentText,
                    formRating, reviewField.text, dateField.text, pendingCover)
        if (showResult(result, "作品已加入书影音清单。")) {
            formNotice = ""
            nameField.clear()
            reviewField.clear()
            formRating = 0
            ratingBox.currentIndex = 0
            typeBox.currentIndex = 0
            statusBox.currentIndex = 0
            dateField.text = String(snapshot.today || "")
            pendingCover = ""
            // The repository keeps the draft separate from the new entry.
            // Persist the cleared form before queued stateChanged callbacks can
            // restore the just-submitted draft into these fields.
            formEdited = true
            page.saveDraft()
            if (noticeIsError) {
            notice = qsTr("作品已加入；但表单草稿清理失败：%1").arg(qsTr(notice))
            } else {
                draftStatus = "草稿自动保存"
                notice = "作品已加入书影音清单。"
            }
        } else {
            if (notice.indexOf("日期") >= 0)
                showFormError(notice, dateField)
            else
                showFormError(notice, nameField)
        }
    }
    function restoreDraft() {
        var draft = snapshot.draft || ({})
        nameField.text = String(draft.name || "")
        typeBox.currentIndex = Math.max(0, typeBox.model.indexOf(String(draft.type || "电影")))
        statusBox.currentIndex = Math.max(0, statusBox.model.indexOf(String(draft.status || "想看")))
        formRating = Math.max(0, Math.min(5, Number(draft.rating || 0)))
        ratingBox.currentIndex = formRating
        reviewField.text = String(draft.review || "")
        dateField.text = String(draft.date || snapshot.today || "")
        formEdited = false
        draftInitialized = true
        draftStatus = "草稿自动保存"
    }
    function saveDraft() {
        if (!controller || !controller.saveDraft) return
        formEdited = true
        var result = controller.saveDraft({
            name: nameField.text,
            type: typeBox.currentText,
            status: statusBox.currentText,
            rating: formRating,
            review: reviewField.text,
            date: dateField.text
        })
        if (!resultOk(result)) {
            notice = String(result && result.error ? result.error : "草稿未保存。")
            noticeIsError = true
            draftStatus = "草稿保存失败"
        } else {
            draftStatus = "草稿已保存"
            draftStatusTimer.restart()
        }
    }
    function openDatePicker() {
        var value = String(dateField.text || snapshot.today || "")
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            pickerYear = Number(value.slice(0, 4))
            pickerMonth = Number(value.slice(5, 7)) - 1
        } else {
            var today = String(snapshot.today || "2026-01-01")
            pickerYear = Number(today.slice(0, 4))
            pickerMonth = Number(today.slice(5, 7)) - 1
        }
        dateDialog.open()
    }
    function movePickerMonth(delta) {
        var shifted = new Date(pickerYear, pickerMonth + delta, 1)
        pickerYear = shifted.getFullYear()
        pickerMonth = shifted.getMonth()
    }
    function choosePickerDay(day) {
        var month = String(pickerMonth + 1).padStart(2, "0")
        var value = String(pickerYear).padStart(4, "0") + "-" + month + "-" + String(day).padStart(2, "0")
        dateField.text = value
        page.saveDraft()
        dateDialog.close()
    }
    function requestDelete(entry) {
        deleteId = String(entry && entry.id || "")
        deleteTitle = String(entry && entry.name || qsTr("这部作品"))
        deleteDialog.open()
    }
    function removeItem() {
        if (showResult(controller.deleteItem(deleteId), "作品已从本机清单移除。"))
            deleteDialog.close()
    }
    function chooseCover() {
        var result = controller.prepareCover(String(coverDialog.selectedFile))
        if (resultOk(result)) {
            pendingCover = String(result.dataUri || "")
            notice = "封面已压缩为本机 JPEG。"
            noticeIsError = false
        } else {
            notice = String(result && result.error ? result.error : "封面处理失败，请重新选择。")
            noticeIsError = true
            pendingCover = ""
        }
    }
    function applyStatusFilter(index) {
        var values = ["all", "想看", "在看", "看完", "弃了"]
        showResult(controller.setStatusFilter(values[index]), "已切换状态筛选。")
    }
    function applyRatingFilter(index) {
        var values = [0, 5, 4, 3]
        showResult(controller.setRatingFilter(values[index]), "已切换评分筛选。")
    }

    FileDialog {
        id: coverDialog
        objectName: "mediaCoverDialog"
        title: qsTr("选择本机封面图片")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("图片或其他文件 (*)")]
        onAccepted: page.chooseCover()
    }

    Connections {
        target: page.controller
        function onStateChanged() {
            if (!page.formEdited && page.draftInitialized) page.restoreDraft()
        }
    }

    Timer {
        id: draftStatusTimer
        interval: 900
        repeat: false
        onTriggered: page.draftStatus = "草稿自动保存"
    }

    Dialog {
        id: deleteDialog
        objectName: "mediaDeleteDialog"
        title: qsTr("从书影音清单删除？")
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 12
            Text {
                objectName: "mediaDeleteMessage"
                text: page.deleteTitle + "\n" + qsTr("移除后，这部作品不会再出现在当前本机书影音清单；导入的旧版原始数据不会被改动。")
                color: page.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                UiButton { uiTheme: page.uiTheme; text: qsTr("取消"); onClicked: deleteDialog.close() }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "mediaDeleteConfirmButton"
                    text: qsTr("删除")
                    destructive: true
                    onClicked: page.removeItem()
                }
            }
        }
    }

    Dialog {
        id: dateDialog
        objectName: "mediaDateDialog"
        title: qsTr("选择记录日期")
        modal: true
        anchors.centerIn: parent
        width: Math.min(380, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 9
            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "‹"
                    Accessible.name: qsTr("上个月")
                    onClicked: page.movePickerMonth(-1)
                }
                Text {
                    text: qsTr("%1 年 %2 月").arg(String(page.pickerYear)).arg(String(page.pickerMonth + 1))
                    color: page.ink
                    font.family: page.fontFamily
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }
                Button {
                    text: "›"
                    Accessible.name: qsTr("下个月")
                    onClicked: page.movePickerMonth(1)
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 7
                columnSpacing: 2
                rowSpacing: 2
                Repeater {
                    model: page.weekdayLabels
                    delegate: Text {
                        id: weekdayCell
                        required property string modelData
                        text: weekdayCell.modelData
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                }
                Repeater {
                    model: 42
                    delegate: Button {
                        id: dayCell
                        objectName: "mediaDateDayCell"
                        required property int index
                        readonly property int firstWeekday: new Date(page.pickerYear, page.pickerMonth, 1).getDay()
                        readonly property int numberOfDays: new Date(page.pickerYear, page.pickerMonth + 1, 0).getDate()
                        readonly property int dayNumber: dayCell.index - dayCell.firstWeekday + 1
                        text: dayNumber > 0 && dayNumber <= numberOfDays ? String(dayNumber) : ""
                        enabled: dayNumber > 0 && dayNumber <= numberOfDays
                        flat: true
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        onClicked: page.choosePickerDay(dayNumber)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: qsTr("今天")
                    onClicked: {
                        var currentDay = new Date()
                        page.pickerYear = currentDay.getFullYear()
                        page.pickerMonth = currentDay.getMonth()
                        page.choosePickerDay(currentDay.getDate())
                    }
                }
                Button { text: qsTr("取消"); onClicked: dateDialog.close() }
            }
        }
    }

    ScrollView {
        id: scroll
        objectName: "mediaScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.topMargin: 28
                Text {
                    text: qsTr("书影音收藏")
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 29
                    font.bold: true
                    Layout.fillWidth: true
                }
            }
            Text {
                objectName: "mediaStorageHint"
                text: qsTr("本机保存 · 封面只在本机处理 · 导入的旧版数据不会被改动")
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Text {
                objectName: "mediaNotice"
                visible: page.notice !== ""
                text: qsTr(String(page.notice))
                color: page.noticeIsError ? page.red : page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: entryColumn.implicitHeight + 28
                radius: 16
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: entryColumn
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("记下一部作品")
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 16
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        Text {
                            objectName: "mediaDraftStatus"
                            text: qsTr(page.draftStatus)
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                    UiTextField {
                        id: nameField
                        uiTheme: page.uiTheme
                        objectName: "mediaNameInput"
                        accessibleName: qsTr("作品名称")
                        placeholderText: qsTr("必填：电影、剧、书或番的名字")
                        maximumLength: 60
                        selectByMouse: true
                        onTextEdited: page.saveDraft()
                        Layout.fillWidth: true
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 600 ? 1 : page.width < 900 ? 2 : 4
                        columnSpacing: 10
                        rowSpacing: 8
                        ColumnLayout {
                            objectName: "mediaTypeField"
                            Layout.fillWidth: true
                            Text { objectName: "mediaTypeLabel"; text: qsTr("作品类型"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            MediaTranslatedComboBox {
                                id: typeBox
                                uiTheme: page.uiTheme
                                objectName: "mediaTypeBox"
                                Accessible.name: qsTr("作品类型")
                                model: ["电影", "剧", "书", "番"]
                                onActivated: page.saveDraft()
                                Layout.fillWidth: true
                            }
                        }
                        ColumnLayout {
                            objectName: "mediaStatusField"
                            Layout.fillWidth: true
                            Text { objectName: "mediaStatusLabel"; text: qsTr("观看状态"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            MediaTranslatedComboBox {
                                id: statusBox
                                uiTheme: page.uiTheme
                                objectName: "mediaStatusBox"
                                Accessible.name: qsTr("观看状态")
                                model: ["想看", "在看", "看完", "弃了"]
                                onActivated: page.saveDraft()
                                Layout.fillWidth: true
                            }
                        }
                        ColumnLayout {
                            objectName: "mediaRatingField"
                            Layout.fillWidth: true
                            Text { objectName: "mediaRatingLabel"; text: qsTr("作品评分"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            MediaTranslatedComboBox {
                                id: ratingBox
                                uiTheme: page.uiTheme
                                objectName: "mediaRatingBox"
                                Accessible.name: qsTr("作品评分")
                                model: ["暂不评分", "★", "★★", "★★★", "★★★★", "★★★★★"]
                                Layout.fillWidth: true
                                onActivated: {
                                    page.formRating = currentIndex
                                    page.saveDraft()
                                }
                            }
                        }
                        ColumnLayout {
                            objectName: "mediaDateField"
                            Layout.fillWidth: true
                            Text { objectName: "mediaDateLabel"; text: qsTr("记录日期"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            RowLayout {
                                Layout.fillWidth: true
                                UiTextField {
                                    id: dateField
                                    uiTheme: page.uiTheme
                                    objectName: "mediaDateInput"
                                    accessibleName: qsTr("记录日期")
                                    placeholderText: qsTr("记录日期 YYYY-MM-DD")
                                    text: String(page.snapshot.today || "")
                                    inputMask: "9999-99-99"
                                    selectByMouse: true
                                    onTextEdited: page.saveDraft()
                                    Layout.fillWidth: true
                                }
                                UiButton {
                                    uiTheme: page.uiTheme
                                    objectName: "mediaDatePickerButton"
                                    text: qsTr("选择日期")
                                    onClicked: page.openDatePicker()
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: -2
                        UiTextField {
                            id: reviewField
                            uiTheme: page.uiTheme
                            objectName: "mediaReviewInput"
                            accessibleName: qsTr("一句话短评")
                            placeholderText: qsTr("一句话短评（最多 100 字）")
                            maximumLength: 100
                            selectByMouse: true
                            onTextEdited: page.saveDraft()
                            Layout.fillWidth: true
                        }
                        Image {
                            objectName: "mediaCoverPreview"
                            visible: page.pendingCover !== ""
                            source: page.pendingCover
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            Layout.preferredWidth: visible ? 46 : 0
                            Layout.preferredHeight: visible ? 60 : 0
                        }
                        Button {
                            objectName: "mediaCoverChooseButton"
                            text: page.pendingCover ? qsTr("封面已就绪") : qsTr("选择本机封面")
                            onClicked: coverDialog.open()
                        }
                        Text {
                            text: page.pendingCover ? qsTr("≤12MB · 处理为 360×480 以内 JPEG") : qsTr("可选 · 不会上传")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.maximumWidth: 150
                        }
                        Button {
                            objectName: "mediaCoverClearButton"
                            visible: page.pendingCover !== ""
                            text: qsTr("移除封面")
                            onClicked: page.pendingCover = ""
                        }
                    }
                    Text {
                        id: formNoticeLabel
                        objectName: "mediaFormNotice"
                        visible: page.formNotice !== ""
                        text: qsTr(String(page.formNotice))
                        color: page.red
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("保存在本机")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            Layout.fillWidth: true
                        }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "mediaAddButton"
                            text: qsTr("加入我的书影音")
                            highlighted: true
                            enabled: nameField.text.trim().length > 0
                            onClicked: page.addItem()
                        }
                    }
                }
            }

            GridLayout {
                objectName: "mediaSummaryGrid"
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                columns: page.width < 520 ? 1 : 3
                columnSpacing: 12
                rowSpacing: 12
                Repeater {
                    model: [
                        { label: page.summary.year ? qsTr("%1 年看完").arg(String(page.summary.year)) : qsTr("今年看完"), value: qsTr("%1 部").arg(String(page.summary.yearFinishedCount || 0)) },
                        { label: qsTr("平均评分"), value: page.summary.yearAverageRating === null || page.summary.yearAverageRating === undefined ? "—" : String(page.summary.yearAverageRating) + " ★" },
                        { label: qsTr("最爱类型"), value: page.enumLabel(page.summary.favoriteType || "—") }
                    ]
                    delegate: Rectangle {
                        id: summaryCard
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        radius: 18
                        color: page.surface
                        border.color: page.line
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 7
                            Text {
                                text: summaryCard.modelData.label
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 13
                                Layout.fillWidth: true
                            }
                            Text {
                                text: summaryCard.modelData.value
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 19
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "mediaRatingsPanel"
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: distributionColumn.implicitHeight + 22
                radius: 18
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: distributionColumn
                    anchors.fill: parent
                    anchors.margins: 11
                    spacing: 8
                    Text {
                        text: qsTr("今年看完作品的评分分布")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        font.bold: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: [1, 2, 3, 4, 5]
                            delegate: Rectangle {
                                id: ratingCard
                                required property int modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 48
                                radius: 9
                                color: page.surfaceSoft
                                ColumnLayout {
                                    anchors.centerIn: parent
                                    spacing: 2
                                    Text {
                                        text: String(page.summary.ratingDistribution && page.summary.ratingDistribution[String(ratingCard.modelData)] || 0)
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 13
                                        font.bold: true
                                        Layout.alignment: Qt.AlignHCenter
                                    }
                                    Text {
                                        text: qsTr("%1 星").arg(String(ratingCard.modelData))
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 13
                                        Layout.alignment: Qt.AlignHCenter
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                objectName: "mediaQueuePanel"
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: queueColumn.implicitHeight + 22
                radius: 18
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: queueColumn
                    anchors.fill: parent
                    anchors.margins: 11
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: qsTr("下一段精神旅程")
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 13
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        Text {
                            text: qsTr("%1 在看 · %2 想看").arg(String(page.summary.inProgressCount || 0)).arg(String(page.summary.wantCount || 0))
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 13
                        }
                    }
                    Repeater {
                        model: UiPageUtils.asList(page.summary.queue)
                        delegate: RowLayout {
                            id: queueEntry
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 8
                            Text {
                                text: String(queueEntry.modelData.name || qsTr("未命名"))
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 13
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Text {
                                text: page.enumLabel(queueEntry.modelData.type) + " · " + page.enumLabel(queueEntry.modelData.status)
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 13
                            }
                        }
                    }
                    Text {
                        visible: UiPageUtils.asList(page.summary.queue).length === 0
                        text: qsTr("待读与在看条目均为 0。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: controlsRow.implicitHeight + 24
                radius: 18
                color: page.surface
                border.color: page.line
                Flow {
                    id: controlsRow
                    x: 12
                    y: 12
                    width: parent.width - 24
                    spacing: 8
                    ButtonGroup { id: viewGroup }
                    UiButton {
                        uiTheme: page.uiTheme
                        objectName: "mediaWallButton"
                        text: qsTr("封面墙")
                        checkable: true
                        checked: page.wallView
                        highlighted: checked
                        ButtonGroup.group: viewGroup
                        onClicked: page.showResult(page.controller.setView("wall"), qsTr("已切换到封面墙。"))
                    }
                    UiButton {
                        uiTheme: page.uiTheme
                        objectName: "mediaListButton"
                        text: qsTr("列表")
                        checkable: true
                        checked: !page.wallView
                        highlighted: checked
                        ButtonGroup.group: viewGroup
                        onClicked: page.showResult(page.controller.setView("list"), qsTr("已切换到列表。"))
                    }
                    MediaTranslatedComboBox {
                        id: statusFilterBox
                        uiTheme: page.uiTheme
                        objectName: "mediaStatusFilter"
                        Accessible.name: qsTr("按观看状态筛选")
                        model: ["全部状态", "想看", "在看", "看完", "弃了"]
                        currentIndex: ["all", "想看", "在看", "看完", "弃了"].indexOf(page.activeStatus)
                        onActivated: (index) => page.applyStatusFilter(index)
                        width: Math.max(132, Math.min(180, page.width * 0.30))
                    }
                    MediaTranslatedComboBox {
                        id: ratingFilterBox
                        uiTheme: page.uiTheme
                        objectName: "mediaRatingFilter"
                        Accessible.name: qsTr("按评分筛选")
                        model: ["全部评分", "5 星", "4 星以上", "3 星以上"]
                        currentIndex: [0, 5, 4, 3].indexOf(page.activeRating)
                        onActivated: (index) => page.applyRatingFilter(index)
                        width: Math.max(132, Math.min(164, page.width * 0.28))
                    }
                }
            }

            GridLayout {
                objectName: "mediaCollection"
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                columns: page.wallView ? (page.width < 620 ? 1 : (page.width < 1000 ? 2 : 3)) : 1
                columnSpacing: 10
                rowSpacing: 10
                Repeater {
                    model: page.entries
                    delegate: Item {
                        id: entryWrapper
                        required property var modelData
                        property var entry: modelData
                        Layout.fillWidth: true
                        implicitHeight: page.wallView ? 318 : 124
                        Loader {
                            id: entryLoader
                            anchors.fill: parent
                            sourceComponent: page.wallView ? wallEntry : listEntry
                            onLoaded: if (item) item.mediaItem = entryWrapper.entry
                        }
                    }
                }
                Text {
                    visible: page.entries.length === 0
                    text: qsTr("这个筛选条件下还没有作品。")
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                    Layout.preferredHeight: 80
                }
            }

            Item { Layout.preferredHeight: 18 }
        }
    }

    Component.onCompleted: page.restoreDraft()

    Component {
        id: wallEntry
        Rectangle {
            id: wallCardRoot
            property var mediaItem: ({})
            radius: 18
            color: page.surface
            border.color: page.line
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 184
                    Image {
                        anchors.fill: parent
                        source: page.coverSource(wallCardRoot.mediaItem.cover)
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        visible: source !== ""
                    }
                    Rectangle {
                        anchors.fill: parent
                        visible: page.coverSource(wallCardRoot.mediaItem.cover) === ""
                        radius: 9
                        color: page.surfaceSoft
                        Text {
                            anchors.centerIn: parent
                            width: parent.width - 26
                            text: String(wallCardRoot.mediaItem.name || qsTr("无封面"))
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 16
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            maximumLineCount: 4
                            elide: Text.ElideRight
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: String(wallCardRoot.mediaItem.name || qsTr("未命名"))
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Button {
                        objectName: "mediaDeleteButton"
                        text: qsTr("删除")
                        onClicked: page.requestDelete(wallCardRoot.mediaItem)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: page.enumLabel(wallCardRoot.mediaItem.type || "电影") + " · " + page.enumLabel(wallCardRoot.mediaItem.status || "想看")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        Layout.fillWidth: true
                    }
                    Text {
                        text: page.ratingLabel(wallCardRoot.mediaItem.rating)
                        color: page.plum
                        font.family: page.fontFamily
                        font.pixelSize: 13
                    }
                }
                Text {
                    visible: String(wallCardRoot.mediaItem.review || "") !== ""
                    text: String(wallCardRoot.mediaItem.review || "")
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    maximumLineCount: 2
                    Layout.fillWidth: true
                }
            }
        }
    }

    Component {
        id: listEntry
        Rectangle {
            id: listCardRoot
            property var mediaItem: ({})
            radius: 13
            color: page.surface
            border.color: page.line
            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 11
                Item {
                    Layout.preferredWidth: 68
                    Layout.preferredHeight: 94
                    Image {
                        anchors.fill: parent
                        source: page.coverSource(listCardRoot.mediaItem.cover)
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: source !== ""
                    }
                    Rectangle {
                        anchors.fill: parent
                        visible: page.coverSource(listCardRoot.mediaItem.cover) === ""
                        radius: 7
                        color: page.surfaceSoft
                        Text {
                            anchors.centerIn: parent
                            width: parent.width - 8
                            text: page.enumLabel(listCardRoot.mediaItem.type || "作品")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 13
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: String(listCardRoot.mediaItem.name || qsTr("未命名"))
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: page.enumLabel(listCardRoot.mediaItem.type || "电影") + " · " + page.enumLabel(listCardRoot.mediaItem.status || "想看") + " · " + String(listCardRoot.mediaItem.date || qsTr("日期未知"))
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Text {
                        text: page.ratingLabel(listCardRoot.mediaItem.rating) + (String(listCardRoot.mediaItem.review || "") ? " · " + String(listCardRoot.mediaItem.review) : "")
                        color: page.plum
                        font.family: page.fontFamily
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
                Button {
                    objectName: "mediaDeleteButton"
                    text: qsTr("删除")
                    onClicked: page.requestDelete(listCardRoot.mediaItem)
                }
            }
        }
    }
}
