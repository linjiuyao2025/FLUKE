pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "articleDialog"

    title: qsTr("文章阅读")
    // The content already draws its own breadcrumb and close control. Avoid
    // the default platform header, which duplicates the title and can pick up
    // an unrelated system color scheme.
    header: null
    modal: true
    dim: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    anchors.centerIn: Overlay.overlay

    // The saved-knowledge key in the legacy app is one global switch. It is
    // intentionally not associated with the article currently being read.
    property var article: ({})
    property string date: ""
    property string topic: ""
    property bool savedKnowledgeEnabled: false
    property bool articleClipped: false
    property string feedbackAction: ""
    property bool feedbackAvailable: true
    property bool recommendationFeedbackExpanded: false
    property var uiTheme: null

    signal openExternalLinkRequested(string url)
    signal savedKnowledgeToggleRequested(bool enabled)
    signal clippingToggleRequested(var article, string date, string topic)
    signal feedbackRequested(var article, string date, string action)

    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color softMuted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color paper: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color card: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color softCard: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
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
    readonly property bool compact: width < 560
    readonly property int actionColumns: width < 420 ? 1 : (width < 640 ? 2 : 3)
    readonly property string headline: textValue(article ? article.title : "", qsTr("本期推送"))
    readonly property string sourceTitle: textValue(article ? article.sourceTitle : "", "")
    readonly property string sourceUrl: httpsUrl(article ? article.sourceUrl : "")
    readonly property string imageUrl: imageSource(article ? article.image : null)
    readonly property var bodyParagraphs: paragraphs(article ? article.body : null)
    readonly property var relatedItems: limitedList(article ? article.relatedCoverage : null, 5)
    readonly property var updateItems: limitedList(article ? article.updates : null, 8)

    function textValue(value, fallback) {
        return typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback
    }

    function httpsUrl(value) {
        if (typeof value !== "string")
            return ""
        var url = value.trim()
        return /^https:\/\/[^\s]+$/i.test(url) ? url : ""
    }

    function listFromVariant(value) {
        if (Array.isArray(value))
            return value
        if (!value || typeof value !== "object"
                || typeof value.length !== "number" || value.length < 0)
            return []
        var result = []
        for (var i = 0; i < value.length; ++i)
            result.push(value[i])
        return result
    }

    function paragraphs(value) {
        if (typeof value === "string")
            return value.split(/\n\s*\n/).map(function (part) { return part.trim() }).filter(function (part) { return part.length > 0 })
        var source = listFromVariant(value)
        var result = []
        for (var i = 0; i < source.length; ++i) {
            if (typeof source[i] === "string" && source[i].trim().length > 0)
                result.push(source[i].trim())
        }
        return result
    }

    function limitedList(value, maximum) {
        return listFromVariant(value).slice(0, maximum)
    }

    function imageSource(value) {
        if (!value || typeof value !== "object" || typeof value.src !== "string")
            return ""
        var source = value.src.trim()
        if (!source.length)
            return ""
        if (source.indexOf("assets/") === 0)
            return Qt.resolvedUrl("../../" + source)
        if (source.indexOf("data:image/png;base64,") === 0
                || source.indexOf("data:image/jpeg;base64,") === 0
                || source.indexOf("data:image/webp;base64,") === 0
                || httpsUrl(source).length > 0)
            return source
        return ""
    }

    width: Math.max(260, Math.min(760, (Overlay.overlay ? Overlay.overlay.width : 800) - 28))
    height: Math.max(300, Math.min(850, (Overlay.overlay ? Overlay.overlay.height : 900) - 28))

    onOpened: {
        recommendationFeedbackExpanded = false
        closeButton.forceActiveFocus()
    }

    background: Rectangle {
        color: dialog.paper
        border.color: dialog.line
        radius: 16
    }

    contentItem: ColumnLayout {
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: dialog.compact ? 16 : 28
            Layout.rightMargin: 12
            Layout.topMargin: 12
            Layout.bottomMargin: 10
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: "FLUKE  /  " + qsTr("文章阅读")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 14
                font.letterSpacing: 0.4
                elide: Text.ElideRight
            }

            Button {
                id: closeButton
                objectName: "articleDialogCloseButton"
                Layout.preferredWidth: 36
                Layout.preferredHeight: 36
                text: "×"
                Accessible.name: qsTr("关闭文章阅读")
                onClicked: dialog.close()
                contentItem: Text {
                    text: closeButton.text
                    color: dialog.ink
                    font.family: dialog.fontFamily
                    font.pixelSize: 24
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: closeButton.down ? dialog.softCard : "transparent"
                    border.color: closeButton.activeFocus ? dialog.blue : dialog.controlBorder
                    radius: 18
                }
            }
        }

        ScrollView {
            id: articleScroll
            objectName: "articleDialogScrollView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: articleScroll.availableWidth
                spacing: 14
                anchors.margins: 0

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: dialog.compact ? 18 : 36
                    Layout.rightMargin: dialog.compact ? 18 : 36
                    Layout.topMargin: 8
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: dialog.textValue(dialog.article ? (dialog.article.label || dialog.article.category) : "", qsTr("本期推送"))
                                    + (dialog.article && dialog.article.publishedAt ? "  ·  " + dialog.article.publishedAt : "")
                            color: dialog.red
                            font.family: dialog.fontFamily
                            font.pixelSize: 13
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        Rectangle {
                            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                            radius: 10
                            color: dialog.successSoft
                            implicitWidth: aiLabel.implicitWidth + 16
                            implicitHeight: 24
                            Text {
                                id: aiLabel
                                anchors.centerIn: parent
                                text: qsTr("AI 整理稿")
                                color: dialog.success
                                font.family: dialog.fontFamily
                                font.pixelSize: 12
                                font.bold: true
                            }
                        }
                    }

                    Text {
                        objectName: "articleDialogHeadline"
                        Layout.fillWidth: true
                        text: dialog.headline
                        color: dialog.ink
                        font.family: dialog.serifFamily
                        font.pixelSize: dialog.compact ? 26 : 34
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: dialog.textValue(dialog.article ? dialog.article.summary : "", "")
                        visible: text.length > 0
                        color: dialog.muted
                        font.family: dialog.serifFamily
                        font.pixelSize: 16
                        lineHeight: 1.65
                        wrapMode: Text.Wrap
                    }

                    Text {
                        Layout.fillWidth: true
                text: dialog.textValue(dialog.article ? dialog.article.publisher : "", "FLUKE") + "  ·  " + qsTr("AI 整理")
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: dialog.compact ? 18 : 36
                    Layout.rightMargin: dialog.compact ? 18 : 36
                    Layout.preferredHeight: 1
                    color: dialog.line
                }

                Item {
                    Layout.fillWidth: true
                    Layout.leftMargin: dialog.compact ? 18 : 36
                    Layout.rightMargin: dialog.compact ? 18 : 36
                    Layout.preferredHeight: dialog.imageUrl.length > 0 ? Math.min(width * 0.58, 330) : 86

                    Rectangle {
                        anchors.fill: parent
                        color: dialog.softCard
                        radius: 6
                        visible: dialog.imageUrl.length === 0 || articleImage.status === Image.Error
                        Column {
                            anchors.centerIn: parent
                            spacing: 5
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "萬象來信"
                                color: dialog.success
                                font.family: dialog.serifFamily
                                font.pixelSize: 19
                                font.bold: true
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: dialog.textValue(dialog.article ? (dialog.article.category || dialog.article.label) : "", qsTr("本期視覺"))
                                color: dialog.softMuted
                                font.family: dialog.fontFamily
                                font.pixelSize: 12
                            }
                        }
                    }

                    Image {
                        id: articleImage
                        objectName: "articleDialogImage"
                        anchors.fill: parent
                        source: dialog.imageUrl
                        visible: source.toString().length > 0 && status !== Image.Error
                        asynchronous: true
                        cache: true
                        fillMode: Image.PreserveAspectFit
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: dialog.compact ? 18 : 36
                    Layout.rightMargin: dialog.compact ? 18 : 36
                    Layout.bottomMargin: 3
                    text: dialog.textValue(dialog.article && dialog.article.image ? dialog.article.image.caption : "", "")
                    visible: text.length > 0
                    color: dialog.softMuted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: dialog.compact ? 18 : 36
                    Layout.rightMargin: dialog.compact ? 18 : 36
                    spacing: 12

                    Repeater {
                        model: dialog.bodyParagraphs
                        delegate: Text {
                            required property string modelData
                            Layout.fillWidth: true
                            text: modelData
                            color: dialog.ink
                            font.family: dialog.serifFamily
                            font.pixelSize: 16
                            lineHeight: 1.78
                            wrapMode: Text.Wrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: dialog.textValue(dialog.article ? dialog.article.relevance : "", "").length > 0
                        spacing: 5
                        Text { text: qsTr("与你的关联"); color: dialog.red; font.family: dialog.fontFamily; font.pixelSize: 13; font.bold: true }
                        Text {
                            Layout.fillWidth: true
                            text: dialog.textValue(dialog.article ? dialog.article.relevance : "", "")
                            color: dialog.ink
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            lineHeight: 1.4
                            wrapMode: Text.Wrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: dialog.textValue(dialog.article ? dialog.article.action : "", "").length > 0
                        spacing: 5
                        Text { text: qsTr("可以做什么"); color: dialog.red; font.family: dialog.fontFamily; font.pixelSize: 13; font.bold: true }
                        Text {
                            Layout.fillWidth: true
                            text: dialog.textValue(dialog.article ? dialog.article.action : "", "")
                            color: dialog.ink
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            lineHeight: 1.4
                            wrapMode: Text.Wrap
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        visible: dialog.textValue(dialog.article ? dialog.article.caveats : "", "").length > 0
                        implicitHeight: caveatColumn.implicitHeight + 22
                        color: dialog.warningSoft
                        radius: 3
                        border.color: dialog.warning
                        border.width: 0

                        ColumnLayout {
                            id: caveatColumn
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 13
                            anchors.topMargin: 10
                            anchors.bottomMargin: 10
                            spacing: 5
                            Text { text: qsTr("条件与边界"); color: dialog.warning; font.family: dialog.fontFamily; font.pixelSize: 13; font.bold: true }
                            Text {
                                Layout.fillWidth: true
                                text: dialog.textValue(dialog.article ? dialog.article.caveats : "", "")
                                color: dialog.ink
                                font.family: dialog.fontFamily
                                font.pixelSize: 14
                                lineHeight: 1.4
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: dialog.relatedItems.length > 0
                        spacing: 8

                        Text {
                            text: qsTr("同一事件的其他报道")
                            color: dialog.blue
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }

                        Repeater {
                            objectName: "articleCoverageRepeater"
                            model: dialog.relatedItems
                            delegate: Rectangle {
                                id: coverageCard
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: coverageContent.implicitHeight + 18
                                color: dialog.softCard
                                radius: 4

                                ColumnLayout {
                                    id: coverageContent
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 5

                                    Button {
                                        id: coverageSourceButton
                                        objectName: "coverageSourceButton"
                                        Layout.fillWidth: true
                                        text: String(coverageCard.modelData.publisher || "") + "  ·  " + String(coverageCard.modelData.title || "")
                                        enabled: dialog.httpsUrl(coverageCard.modelData.sourceUrl).length > 0
                                        onClicked: dialog.openExternalLinkRequested(dialog.httpsUrl(coverageCard.modelData.sourceUrl))
                                        contentItem: Text {
                                            text: coverageSourceButton.text
                                            color: coverageSourceButton.enabled ? dialog.blue : dialog.muted
                                            font.family: dialog.fontFamily
                                            font.pixelSize: 13
                                            font.bold: true
                                            wrapMode: Text.Wrap
                                        }
                                        background: Rectangle { color: "transparent"; border.width: 0 }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: String(coverageCard.modelData.publishedAt || "")
                                                + (coverageCard.modelData.summary ? "  ·  " + coverageCard.modelData.summary : "")
                                        visible: text.trim().length > 0
                                        color: dialog.muted
                                        font.family: dialog.fontFamily
                                        font.pixelSize: 12
                                        lineHeight: 1.35
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: dialog.updateItems.length > 0
                        spacing: 8

                        Text {
                            text: qsTr("事件进展")
                            color: dialog.blue
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }

                        Repeater {
                            objectName: "articleUpdatesRepeater"
                            model: dialog.updateItems
                            delegate: Rectangle {
                                id: updateCard
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: updateContent.implicitHeight + 18
                                color: dialog.softCard
                                radius: 4

                                ColumnLayout {
                                    id: updateContent
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 5

                                    Text {
                                        Layout.fillWidth: true
                                        text: String(updateCard.modelData.date || "") + "  ·  " + String(updateCard.modelData.summary || "")
                                        color: dialog.ink
                                        font.family: dialog.fontFamily
                                        font.pixelSize: 13
                                        lineHeight: 1.35
                                        wrapMode: Text.Wrap
                                    }

                                    Button {
                                        id: updateSourceButton
                                        objectName: "updateSourceButton"
                                        Layout.fillWidth: true
                                        text: String(updateCard.modelData.publisher || "") + "  ·  " + qsTr("核对原文 ↗")
                                        enabled: dialog.httpsUrl(updateCard.modelData.sourceUrl).length > 0
                                        onClicked: dialog.openExternalLinkRequested(dialog.httpsUrl(updateCard.modelData.sourceUrl))
                                        contentItem: Text {
                                            text: updateSourceButton.text
                                            color: updateSourceButton.enabled ? dialog.blue : dialog.muted
                                            font.family: dialog.fontFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.Wrap
                                        }
                                        background: Rectangle { color: "transparent"; border.width: 0 }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: dialog.line
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            text: qsTr("资料出处")
                            color: dialog.success
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }

                        Text {
                            Layout.fillWidth: true
                            text: qsTr("原始标题：") + (dialog.sourceTitle.length > 0 ? dialog.sourceTitle : qsTr("内容包未单独提供"))
                            color: dialog.ink
                            font.family: dialog.fontFamily
                            font.pixelSize: 13
                            lineHeight: 1.3
                            wrapMode: Text.Wrap
                        }

                        Text {
                            Layout.fillWidth: true
                            text: dialog.textValue(dialog.article ? dialog.article.publisher : "", qsTr("发布方未提供"))
                                    + "  ·  " + dialog.textValue(dialog.article ? dialog.article.publishedAt : "", qsTr("发布日期未提供"))
                            color: dialog.muted
                            font.family: dialog.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }

                        Text {
                            Layout.fillWidth: true
                            text: dialog.sourceUrl.length > 0 ? dialog.sourceUrl : qsTr("未提供有效的 HTTPS 原文链接")
                            color: dialog.sourceUrl.length > 0 ? dialog.blue : dialog.softMuted
                            font.family: dialog.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WrapAnywhere
                            visible: text.length > 0
                        }

                        Text {
                            Layout.fillWidth: true
                            text: qsTr("上方正文为 AI 整理稿；原始报道链接用于核对，不展示新闻源稿全文。")
                            color: dialog.softMuted
                            font.family: dialog.fontFamily
                            font.pixelSize: 12
                            lineHeight: 1.35
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }

        GridLayout {
            id: actionButtons
            objectName: "articleDialogActions"
            Layout.fillWidth: true
            Layout.leftMargin: dialog.compact ? 14 : 24
            Layout.rightMargin: dialog.compact ? 14 : 24
            Layout.topMargin: 8
            Layout.bottomMargin: 12
            columns: dialog.actionColumns
            rowSpacing: 7
            columnSpacing: 8

            Button {
                id: clippingButton
                objectName: "articleDialogClippingButton"
                Layout.fillWidth: true
                text: dialog.articleClipped ? qsTr("已收进剪报 ✓") : qsTr("收进剪报 +")
                Accessible.name: dialog.articleClipped ? qsTr("从剪报移出这篇文章") : qsTr("将这篇文章收进剪报")
                onClicked: dialog.clippingToggleRequested(dialog.article, dialog.date, dialog.topic)
                contentItem: Text {
                    text: clippingButton.text
                    color: dialog.articleClipped ? dialog.success : dialog.red
                    font.family: dialog.fontFamily
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    color: clippingButton.down ? dialog.redSoft : dialog.card
                    border.color: clippingButton.activeFocus ? dialog.blue : dialog.controlBorder
                    radius: 5
                }
            }

            Button {
                id: originalLinkButton
                objectName: "articleDialogOriginalLinkButton"
                Layout.fillWidth: true
                text: qsTr("打开原始报道 ↗")
                enabled: dialog.sourceUrl.length > 0
                onClicked: dialog.openExternalLinkRequested(dialog.sourceUrl)
                contentItem: Text {
                    text: originalLinkButton.text
                    color: originalLinkButton.enabled ? dialog.card : dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 13
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    color: !originalLinkButton.enabled ? dialog.softCard : (originalLinkButton.down ? dialog.blueStrong : dialog.blue)
                    border.color: originalLinkButton.activeFocus ? dialog.blue : (originalLinkButton.enabled ? dialog.blue : dialog.controlBorder)
                    radius: 5
                }
            }
        }

        ColumnLayout {
            objectName: "articleDialogGlobalReadingSection"
            Layout.fillWidth: true
            Layout.leftMargin: dialog.compact ? 14 : 24
            Layout.rightMargin: dialog.compact ? 14 : 24
            Layout.bottomMargin: 12
            spacing: 4

            Text {
                objectName: "articleDialogGlobalReadingLabel"
                text: qsTr("全局阅读设置")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 12
                font.bold: true
                Layout.fillWidth: true
            }
            Text {
                text: qsTr("稍后读会影响后续文章；它不会把当前文章收进本期剪报。")
                color: dialog.softMuted
                font.family: dialog.fontFamily
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            Button {
                id: savedKnowledgeButton
                objectName: "articleDialogSavedKnowledgeButton"
                Layout.fillWidth: true
                text: dialog.savedKnowledgeEnabled ? qsTr("关闭全局稍后读 ✓") : qsTr("开启全局稍后读 +")
                Accessible.name: dialog.savedKnowledgeEnabled ? qsTr("关闭全局稍后读") : qsTr("开启全局稍后读")
                onClicked: dialog.savedKnowledgeToggleRequested(!dialog.savedKnowledgeEnabled)
                contentItem: Text {
                    text: savedKnowledgeButton.text
                    color: dialog.blue
                    font.family: dialog.fontFamily
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    color: savedKnowledgeButton.down ? dialog.blueSoft : dialog.card
                    border.color: savedKnowledgeButton.activeFocus ? dialog.blue : dialog.controlBorder
                    radius: 5
                }
            }
        }

        ColumnLayout {
            objectName: "articleDialogRecommendationSection"
            Layout.fillWidth: true
            Layout.leftMargin: dialog.compact ? 14 : 24
            Layout.rightMargin: dialog.compact ? 14 : 24
            Layout.bottomMargin: 12
            visible: Boolean(dialog.article && dialog.article.id)

            Button {
                id: recommendationFeedbackToggleButton
                objectName: "articleDialogRecommendationToggleButton"
                Layout.fillWidth: true
                text: dialog.feedbackAction.length > 0
                      ? (dialog.recommendationFeedbackExpanded
                         ? qsTr("收起推荐反馈")
                         : qsTr("已设置推荐反馈 · 修改"))
                      : (dialog.recommendationFeedbackExpanded
                         ? qsTr("收起推荐反馈")
                         : qsTr("告诉本机推荐系统"))
                Accessible.name: qsTr("打开或收起本机推荐反馈")
                Accessible.description: qsTr("只影响这台设备上的推荐，不会点赞、发送消息或改变原文")
                onClicked: dialog.recommendationFeedbackExpanded = !dialog.recommendationFeedbackExpanded
                contentItem: Text {
                    text: recommendationFeedbackToggleButton.text
                    color: dialog.blue
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    color: recommendationFeedbackToggleButton.down ? dialog.blueSoft : dialog.card
                    border.color: recommendationFeedbackToggleButton.activeFocus ? dialog.blue : dialog.controlBorder
                    radius: 5
                }
            }

            GridLayout {
                objectName: "articleDialogRecommendationFeedback"
                Layout.fillWidth: true
                columns: dialog.width < 420 ? 1 : 2
                rowSpacing: 6
                columnSpacing: 8
                visible: dialog.recommendationFeedbackExpanded

                Text {
                    objectName: "articleDialogRecommendationExplanation"
                    Layout.columnSpan: dialog.width < 420 ? 1 : 2
                    Layout.fillWidth: true
                    text: dialog.feedbackAvailable
                          ? qsTr("只影响本机推荐；再次点击可撤销，不会点赞或发送消息。")
                          : qsTr("本机推荐反馈暂不可用；文章阅读和剪报仍可正常使用。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }

                Button {
                    id: usefulFeedbackButton
                    objectName: "articleFeedback_useful"
                    Layout.fillWidth: true
                    text: dialog.feedbackAction === "useful" ? qsTr("这篇有帮助 ✓") : qsTr("这篇有帮助")
                    enabled: dialog.feedbackAvailable
                    onClicked: dialog.feedbackRequested(dialog.article, dialog.date,
                                                         dialog.feedbackAction === "useful" ? "" : "useful")
                    contentItem: Text {
                        text: usefulFeedbackButton.text
                        color: dialog.feedbackAction === "useful" ? dialog.success : dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        color: usefulFeedbackButton.down ? dialog.blueSoft : dialog.card
                        border.color: usefulFeedbackButton.activeFocus ? dialog.blue
                                      : (dialog.feedbackAction === "useful" ? dialog.success : dialog.line)
                        radius: 5
                    }
                }

                Button {
                    id: notInterestedFeedbackButton
                    objectName: "articleFeedback_not_interested"
                    Layout.fillWidth: true
                    text: dialog.feedbackAction === "not_interested" ? qsTr("不感兴趣 ✓") : qsTr("不感兴趣")
                    enabled: dialog.feedbackAvailable
                    onClicked: dialog.feedbackRequested(dialog.article, dialog.date,
                                                         dialog.feedbackAction === "not_interested" ? "" : "not_interested")
                    contentItem: Text {
                        text: notInterestedFeedbackButton.text
                        color: dialog.feedbackAction === "not_interested" ? dialog.success : dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        color: notInterestedFeedbackButton.down ? dialog.blueSoft : dialog.card
                        border.color: notInterestedFeedbackButton.activeFocus ? dialog.blue
                                      : (dialog.feedbackAction === "not_interested" ? dialog.success : dialog.line)
                        radius: 5
                    }
                }

                Button {
                    id: moreTopicFeedbackButton
                    objectName: "articleFeedback_more_topic"
                    Layout.fillWidth: true
                    text: dialog.feedbackAction === "more_topic" ? qsTr("多看这个主题 ✓") : qsTr("多看这个主题")
                    enabled: dialog.feedbackAvailable
                             && Boolean(dialog.textValue(dialog.article ? dialog.article.category : "",
                                                          dialog.textValue(dialog.article ? dialog.article.label : "", "")))
                    onClicked: dialog.feedbackRequested(dialog.article, dialog.date,
                                                         dialog.feedbackAction === "more_topic" ? "" : "more_topic")
                    contentItem: Text {
                        text: moreTopicFeedbackButton.text
                        color: dialog.feedbackAction === "more_topic" ? dialog.success : dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        color: moreTopicFeedbackButton.down ? dialog.blueSoft : dialog.card
                        border.color: moreTopicFeedbackButton.activeFocus ? dialog.blue
                                      : (dialog.feedbackAction === "more_topic" ? dialog.success : dialog.line)
                        radius: 5
                    }
                }

                Button {
                    id: lessSourceFeedbackButton
                    objectName: "articleFeedback_less_source"
                    Layout.fillWidth: true
                    text: dialog.feedbackAction === "less_source" ? qsTr("少看这个来源 ✓") : qsTr("少看这个来源")
                    enabled: dialog.feedbackAvailable
                             && Boolean(dialog.textValue(dialog.article ? dialog.article.publisher : "", ""))
                    onClicked: dialog.feedbackRequested(dialog.article, dialog.date,
                                                         dialog.feedbackAction === "less_source" ? "" : "less_source")
                    contentItem: Text {
                        text: lessSourceFeedbackButton.text
                        color: dialog.feedbackAction === "less_source" ? dialog.success : dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        color: lessSourceFeedbackButton.down ? dialog.blueSoft : dialog.card
                        border.color: lessSourceFeedbackButton.activeFocus ? dialog.blue
                                      : (dialog.feedbackAction === "less_source" ? dialog.success : dialog.line)
                        radius: 5
                    }
                }
            }
        }
    }
}
