pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "UiPageUtils.js" as UiPageUtils

Item {
    id: page
    objectName: "shoppingPage"
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
    readonly property var items: UiPageUtils.asList(snapshot.shoppingRecords)
    readonly property var oldest: summary.earliestPending || ({})
    readonly property string activeFilter: String(snapshot.filter || settings.shoppingFilter || "pending")

    function focusQuickEntry() {
        nameInput.forceActiveFocus()
    }

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

    function money(value) {
        var amount = Number(value)
        return "¥" + (isFinite(amount) ? (Math.round(amount * 100) / 100).toFixed(2) : "0.00")
    }
    function categoryLabel(value) {
        var category = String(value || "其他")
        if (["食品", "日用品", "家居", "数码", "药品", "其他"].indexOf(category) >= 0)
            return qsTr(category)
        return category
    }
    function priorityLabel(value) {
        var priority = String(value || "normal")
        return priority === "high" ? qsTr("急需")
             : priority === "low" ? qsTr("等等再买") : qsTr("有空买")
    }
    function itemCountLabel(value) {
        var count = Number(value || 0)
        return count === 1 ? qsTr("1 件") : qsTr("%1 件").arg(String(count))
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
    function addItem() {
        formNotice = ""
        if (nameInput.text.trim() === "") {
            notice = qsTr("请填写物品名称。")
            noticeIsError = true
            formNotice = notice
            nameInput.forceActiveFocus()
            return
        }
        var result = controller.addItem(nameInput.text, quantityInput.text,
                                        categoryBox.currentValue, priceInput.text,
                                        priorityBox.currentValue, noteInput.text)
        if (showResult(result, qsTr("物品已加入待买清单。"))) {
            formNotice = ""
            nameInput.clear()
            quantityInput.clear()
            priceInput.clear()
            noteInput.clear()
            categoryBox.currentIndex = 0
            priorityBox.currentIndex = 0
        } else {
            formNotice = notice
            if (notice.indexOf("价格") >= 0 || notice.indexOf("金额") >= 0)
                priceInput.forceActiveFocus()
            else
                nameInput.forceActiveFocus()
        }
    }
    function setFilter(value) {
        showResult(controller.setFilter(value), qsTr("已切换清单视图。"))
    }
    function toggleBought(record) {
        var data = record && record.data ? record.data : ({})
        showResult(controller.toggleBought(String(record && record.id || ""), !Boolean(data.bought)),
                   data.bought ? qsTr("已移回待买清单。") : qsTr("已标记为买到。"))
    }
    function requestDelete(record) {
        deleteId = String(record && record.id || "")
        var data = record && record.data ? record.data : ({})
        deleteTitle = String(data.name || qsTr("这件物品"))
        deleteDialog.open()
    }
    function removeItem() {
        if (showResult(controller.deleteItem(deleteId), qsTr("物品已删除。")))
            deleteDialog.close()
    }

    Dialog {
        id: deleteDialog
        objectName: "shoppingDeleteDialog"
        title: qsTr("删除这件物品？")
        modal: true
        anchors.centerIn: parent
        width: Math.min(410, page.width - 32)
        contentItem: ColumnLayout {
            spacing: 18
            Text {
                objectName: "shoppingDeleteMessage"
                text: page.deleteTitle + "\n" + qsTr("删除后，这件物品不会再出现在当前本机待买清单；导入的旧版原始数据不会被改动。")
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
                    objectName: "shoppingDeleteConfirmButton"
                    text: qsTr("删除")
                    destructive: true
                    onClicked: page.removeItem()
                }
            }
        }
    }

    ScrollView {
        id: scroll
        objectName: "shoppingScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.topMargin: 28
                Text {
                    text: qsTr("待买清单")
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 29
                    font.bold: true
                    Layout.fillWidth: true
                }
            }
            Text {
                objectName: "shoppingStorageHint"
                text: qsTr("本机保存 · 导入的旧版数据不会被改动")
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.fillWidth: true
            }
            Text {
                objectName: "shoppingNotice"
                visible: page.notice !== ""
                text: page.notice
                color: page.noticeIsError ? page.red : page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.fillWidth: true
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                columns: page.width < 640 ? 2 : 4
                columnSpacing: page.width < 780 ? 8 : 12
                rowSpacing: page.width < 780 ? 8 : 12
                Repeater {
                    model: 4
                    delegate: Rectangle {
                        id: summaryCard
                        required property int index
                        objectName: "shoppingSummaryCard_" + index
                        readonly property var labels: [qsTr("待买物品", "shopping item count"), qsTr("预计金额"), qsTr("本月买到"), qsTr("加入满七天")]
                        readonly property var values: [
                            page.itemCountLabel(page.summary.pendingCount),
                            page.money(page.summary.pendingAmount || 0),
                            page.itemCountLabel(page.summary.purchasedThisMonthCount),
                            page.itemCountLabel(page.summary.addedAtLeastSevenDaysCount)
                        ]
                        Layout.fillWidth: true
                        Layout.preferredHeight: page.width < 780 ? 76 : 96
                        radius: 16
                        color: page.surface
                        border.color: page.line
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: page.width < 780 ? 10 : 16
                            spacing: page.width < 780 ? 4 : 7
                            Text {
                                text: summaryCard.labels[summaryCard.index]
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                Layout.fillWidth: true
                            }
                            Text {
                                text: summaryCard.values[summaryCard.index]
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
                objectName: "shoppingInsightPanel"
                visible: Number(page.summary.pendingCount || 0) > 0
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: insightColumn.implicitHeight + 24
                radius: 16
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: insightColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6
                    Text {
                        text: qsTr("待买观察")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    Text {
                        visible: Number(page.summary.pendingCount || 0) === 0
                        text: qsTr("当前没有待买条目。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    Text {
                        visible: Number(page.summary.pendingCount || 0) > 0 && Boolean(page.oldest.date)
                        text: qsTr("最早加入 · %1 · %2 · %3 天")
                                   .arg(String(page.oldest.date || ""))
                                   .arg(String(page.oldest.name || qsTr("待买物品", "shopping item fallback")))
                                   .arg(String(page.oldest.days || 0))
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: UiPageUtils.asList(page.summary.insights)
                        delegate: Text {
                            required property var modelData
                            text: qsTr("%1 · %2 · %3")
                                      .arg(String(modelData.name || qsTr("待买物品", "shopping item fallback")))
                                      .arg(Number(modelData.price || 0) > 0
                                           ? qsTr("预计 %1").arg(page.money(modelData.price))
                                           : qsTr("价格待定"))
                                      .arg(modelData.aged ? qsTr("已加入七天以上") : qsTr("加入未满七天"))
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                implicitHeight: entryColumn.implicitHeight + 28
                radius: 18
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: entryColumn
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    Text {
                        text: qsTr("想买先记下")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 15
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width < 680 ? 1 : 2
                        columnSpacing: 10
                        rowSpacing: 8
                        ColumnLayout {
                            objectName: "shoppingNameField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingNameLabel"; text: qsTr("物品名称"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: nameInput
                                uiTheme: page.uiTheme
                                objectName: "shoppingNameInput"
                                accessibleName: qsTr("物品名称")
                                Layout.fillWidth: true
                                maximumLength: 40
                                placeholderText: qsTr("必填，例如：洗衣液、燕麦奶")
                                onAccepted: page.addItem()
                            }
                        }
                        ColumnLayout {
                            objectName: "shoppingQuantityField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingQuantityLabel"; text: qsTr("数量"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: quantityInput
                                uiTheme: page.uiTheme
                                objectName: "shoppingQuantityInput"
                                accessibleName: qsTr("数量")
                                Layout.fillWidth: true
                                maximumLength: 16
                                placeholderText: qsTr("例如：2 盒")
                            }
                        }
                        ColumnLayout {
                            objectName: "shoppingCategoryField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingCategoryLabel"; text: qsTr("商品分类"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: categoryBox
                                uiTheme: page.uiTheme
                                objectName: "shoppingCategoryBox"
                                accessibleName: qsTr("商品分类")
                                Layout.fillWidth: true
                                textRole: "label"
                                valueRole: "value"
                                model: [
                                    {"label": qsTr("食品"), "value": "食品"},
                                    {"label": qsTr("日用品"), "value": "日用品"},
                                    {"label": qsTr("家居"), "value": "家居"},
                                    {"label": qsTr("数码"), "value": "数码"},
                                    {"label": qsTr("药品"), "value": "药品"},
                                    {"label": qsTr("其他"), "value": "其他"}
                                ]
                            }
                        }
                        ColumnLayout {
                            objectName: "shoppingPriceField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingPriceLabel"; text: qsTr("预计单价"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: priceInput
                                uiTheme: page.uiTheme
                                objectName: "shoppingPriceInput"
                                accessibleName: qsTr("预计单价")
                                Layout.fillWidth: true
                                placeholderText: qsTr("元，可留空")
                                validator: DoubleValidator { bottom: 0; decimals: 2; notation: DoubleValidator.StandardNotation }
                            }
                        }
                        ColumnLayout {
                            objectName: "shoppingPriorityField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingPriorityLabel"; text: qsTr("购买优先级"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiComboBox {
                                id: priorityBox
                                uiTheme: page.uiTheme
                                objectName: "shoppingPriorityBox"
                                accessibleName: qsTr("购买优先级")
                                Layout.fillWidth: true
                                textRole: "label"
                                valueRole: "value"
                                model: [
                                    {"label": qsTr("有空买"), "value": "normal"},
                                    {"label": qsTr("急需"), "value": "high"},
                                    {"label": qsTr("等等再买"), "value": "low"}
                                ]
                            }
                        }
                        ColumnLayout {
                            objectName: "shoppingNoteField"
                            Layout.fillWidth: true
                            Text { objectName: "shoppingNoteLabel"; text: qsTr("备注"); color: page.muted; font.family: page.fontFamily; font.pixelSize: 12 }
                            UiTextField {
                                id: noteInput
                                uiTheme: page.uiTheme
                                objectName: "shoppingNoteInput"
                                accessibleName: qsTr("备注")
                                Layout.fillWidth: true
                                maximumLength: 60
                                placeholderText: qsTr("品牌、规格或购买渠道")
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "shoppingAddButton"
                            text: qsTr("加入待买清单")
                            highlighted: true
                            enabled: nameInput.text.trim().length > 0
                            onClicked: page.addItem()
                        }
                    }
                    Text {
                        objectName: "shoppingFormNotice"
                        visible: page.formNotice !== ""
                        text: page.formNotice
                        color: page.red
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Text {
                    text: qsTr("清单")
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 17
                    font.bold: true
                    Layout.fillWidth: true
                }
                Repeater {
                    model: [
                        {"key": "pending", "label": qsTr("待买", "shopping status")},
                        {"key": "all", "label": qsTr("全部")},
                        {"key": "bought", "label": qsTr("已买")}
                    ]
                    delegate: UiButton {
                        uiTheme: page.uiTheme
                        required property var modelData
                        objectName: "shoppingFilter_" + modelData.key
                        text: modelData.label
                        checkable: true
                        checked: page.activeFilter === modelData.key
                        highlighted: checked
                        font.family: page.fontFamily
                        onClicked: page.setFilter(modelData.key)
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.rightMargin: Math.min(32, Math.max(18, page.width * 0.045))
                Layout.bottomMargin: 26
                implicitHeight: listColumn.implicitHeight + 2
                radius: 18
                color: page.surface
                border.color: page.line
                ColumnLayout {
                    id: listColumn
                    width: parent.width
                    spacing: 0
                    Repeater {
                        model: page.items
                        delegate: Rectangle {
                            id: rowItem
                            required property var modelData
                            required property int index
                            readonly property var itemData: modelData && modelData.data ? modelData.data : ({})
                            objectName: "shoppingRow_" + String(modelData && modelData.id || "")
                            Layout.fillWidth: true
                            implicitHeight: 72
                            color: "transparent"
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: rowItem.index === 0 ? 0 : 1
                                color: page.line
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 10
                                Button {
                                    objectName: "shoppingToggle_" + String(rowItem.modelData && rowItem.modelData.id || "")
                                    Layout.preferredWidth: 32
                                    Layout.preferredHeight: 32
                                    checkable: true
                                    checked: Boolean(rowItem.itemData.bought)
                                    text: checked ? "✓" : ""
                                    Accessible.name: checked ? qsTr("移回待买清单") : qsTr("标记为已买")
                                    onClicked: page.toggleBought(rowItem.modelData)
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        text: String(rowItem.itemData.name || qsTr("待买物品", "shopping item fallback"))
                                        color: rowItem.itemData.bought ? page.muted : page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 13
                                        font.bold: true
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: String(rowItem.itemData.quantity || qsTr("数量未填")) + " · " +
                                              page.categoryLabel(rowItem.itemData.category) +
                                              (rowItem.itemData.note ? " · " + String(rowItem.itemData.note) : "")
                                        color: page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                                ColumnLayout {
                                    spacing: 2
                                    Text {
                                        text: Number(rowItem.itemData.price || 0) > 0 ? page.money(rowItem.itemData.price) : qsTr("待定")
                                        color: page.ink
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        horizontalAlignment: Text.AlignRight
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: rowItem.itemData.bought ? qsTr("已买") : page.priorityLabel(rowItem.itemData.priority)
                                        color: rowItem.itemData.bought ? page.muted
                                              : rowItem.itemData.priority === "high" ? page.red
                                              : rowItem.itemData.priority === "low" ? page.warning : page.muted
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        horizontalAlignment: Text.AlignRight
                                        Layout.fillWidth: true
                                    }
                                }
                                Button {
                                    objectName: "shoppingDelete_" + String(rowItem.modelData && rowItem.modelData.id || "")
                                    text: qsTr("删除")
                                    onClicked: page.requestDelete(rowItem.modelData)
                                }
                            }
                        }
                    }
                    Text {
                        visible: page.items.length === 0
                        text: page.activeFilter === "pending" ? qsTr("待买清单已经清空") : qsTr("这里还没有物品")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 58 : 0
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }
}
