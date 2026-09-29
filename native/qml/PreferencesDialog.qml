pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "preferencesDialog"
    property var uiTheme: null
    palette.highlight: uiTheme ? uiTheme.accent : "#456b73"

    property var initialState: ({
        topics: [],
        preferences: { subtopics: "", sources: "", presetSources: [] }
    })
    property var appUpdateController: typeof flukeAppUpdateController === "undefined"
                                     ? null : flukeAppUpdateController
    readonly property var appUpdateState: appUpdateController
                                          ? appUpdateController.state : ({})
    signal saveRequested(var state)

    // These defaults mirror TOPIC_OPTIONS and PRESET_SOURCES in
    // wanxiang/preferences.py. The host should bind these properties to those
    // Python constants when it wires this component into the application.
    property var topicOptions: [
        { key: "news", label: "新闻与时事" },
        { key: "domestic", label: "国内" },
        { key: "international", label: "国际" },
        { key: "finance", label: "财经商业" },
        { key: "technology", label: "科技数码" },
        { key: "ai", label: "人工智能" },
        { key: "games", label: "游戏" },
        { key: "culture", label: "文化影视" },
        { key: "health", label: "健康" },
        { key: "life", label: "生活方式" },
        { key: "other", label: "其他" }
    ]
    property var presetSourceOptions: [
        "财新网", "澎湃明查", "端传媒", "新华社", "Reuters",
        "Associated Press", "ProPublica", "Rest of World", "Ars Technica",
        "The Guardian", "Floodlight", "Nature", "Science", "IEEE Spectrum",
        "Game Developer"
    ]

    property var draftTopics: []
    property var draftPresetSources: []
    property string draftSubtopics: ""
    property string draftSources: ""
    property string inputError: ""
    // The host may set this synchronously while handling saveRequested if the
    // SQLite write fails. In that case the dialog stays open for correction.
    property string saveError: ""
    property string fontFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    property color ink: uiTheme ? uiTheme.ink : "#273239"
    property color muted: uiTheme ? uiTheme.muted : "#586569"
    property color controlBorder: uiTheme ? uiTheme.controlBorder : "#807d76"
    property color accent: uiTheme ? uiTheme.accent : "#456b73"
    property color danger: uiTheme ? uiTheme.danger : "#9d4038"
    readonly property var unlistedTopicKeys: {
        var known = []
        for (var i = 0; i < topicOptions.length; ++i)
            known.push(topicKey(topicOptions[i]))
        return draftTopics.filter(function(key) {
            return typeof key === "string" && key.length > 0 && known.indexOf(key) < 0
        })
    }

    title: qsTr("关注主题与候选媒体")
    modal: true
    standardButtons: Dialog.NoButton
    closePolicy: Popup.CloseOnEscape
    width: Math.min(700, (Overlay.overlay ? Overlay.overlay.width : 700) - 32)
    height: Math.min(760, (Overlay.overlay ? Overlay.overlay.height : 760) - 32)
    anchors.centerIn: Overlay.overlay
    padding: 16

    function topicKey(option) {
        if (typeof option === "string")
            return option
        if (Array.isArray(option))
            return String(option.length > 0 ? option[0] : "")
        return option && option.key !== undefined ? String(option.key) : ""
    }

    function topicLabel(option) {
        if (typeof option === "string")
            return option
        if (Array.isArray(option))
            return String(option.length > 1 ? option[1] : topicKey(option))
        return option && option.label !== undefined
                ? String(option.label) : topicKey(option)
    }

    function topicIsSelected(key) {
        return draftTopics.indexOf(key) >= 0
    }

    function sourceIsSelected(source) {
        return draftPresetSources.indexOf(source) >= 0
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

    function syncTopicChoices() {
        for (var i = 0; i < topicRepeater.count; ++i) {
            var choice = topicRepeater.itemAt(i)
            if (choice)
                choice.checked = topicIsSelected(topicKey(topicOptions[i]))
        }
    }

    function syncSourceChoices() {
        for (var i = 0; i < sourceRepeater.count; ++i) {
            var choice = sourceRepeater.itemAt(i)
            if (choice)
                choice.checked = sourceIsSelected(String(presetSourceOptions[i]))
        }
    }

    function toggleTopic(key, checked) {
        if (topicIsSelected(key) === checked)
            return
        saveError = ""
        var next = draftTopics.slice()
        if (checked)
            next.push(key)
        else
            next.splice(next.indexOf(key), 1)
        draftTopics = next
    }

    function togglePresetSource(source, checked) {
        if (sourceIsSelected(source) === checked)
            return
        saveError = ""
        var next = draftPresetSources.slice()
        if (checked)
            next.push(source)
        else
            next.splice(next.indexOf(source), 1)
        draftPresetSources = next
    }

    function removeUnlistedTopic(key) {
        var next = draftTopics.slice()
        var index = next.indexOf(key)
        if (index >= 0) {
            next.splice(index, 1)
            draftTopics = next
            saveError = ""
        }
    }

    function validateSources() {
        var parts = draftSources.split(/[、,，;；]/)
        for (var i = 0; i < parts.length; ++i) {
            var entry = parts[i].trim()
            if (entry.length > 60)
                return qsTr("单个自定义来源最多 60 字，请缩短或拆分后再保存。")
        }
        return ""
    }

    function resetDraft() {
        var state = initialState && typeof initialState === "object" ? initialState : {}
        var preferences = state.preferences && typeof state.preferences === "object"
                ? state.preferences : {}
        draftTopics = listFromVariant(state.topics).slice()
        draftPresetSources = listFromVariant(preferences.presetSources).slice()
        draftSubtopics = typeof preferences.subtopics === "string"
                ? preferences.subtopics.slice(0, 240) : ""
        draftSources = typeof preferences.sources === "string"
                ? preferences.sources.slice(0, 240) : ""
        subtopicsInput.text = draftSubtopics
        customSourcesInput.text = draftSources
        inputError = validateSources()
        saveError = ""
        Qt.callLater(syncTopicChoices)
        Qt.callLater(syncSourceChoices)
    }

    function saveDraft() {
        inputError = validateSources()
        if (inputError.length > 0)
            return

        saveError = ""
        var state = {
            topics: draftTopics.slice(),
            preferences: {
                subtopics: draftSubtopics.trim().slice(0, 240),
                sources: draftSources.trim().slice(0, 240),
                presetSources: draftPresetSources.slice()
            }
        }
        saveRequested(state)
        if (saveError.length === 0)
            close()
    }

    onOpened: resetDraft()
    onDraftTopicsChanged: syncTopicChoices()
    onDraftPresetSourcesChanged: syncSourceChoices()
    onTopicOptionsChanged: Qt.callLater(syncTopicChoices)
    onPresetSourceOptionsChanged: Qt.callLater(syncSourceChoices)

    component PreferenceChoice: CheckBox {
        id: choice
        implicitHeight: 34
        implicitWidth: Math.max(98, contentItem.implicitWidth + leftPadding + rightPadding)
        spacing: 7
        leftPadding: 9
        rightPadding: 9
        topPadding: 4
        bottomPadding: 4
        contentItem: Text {
            text: choice.text
            color: dialog.ink
            font.family: dialog.fontFamily
            font.pixelSize: 12
            leftPadding: choice.indicator.implicitWidth + choice.spacing
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Rectangle {
            implicitWidth: 16
            implicitHeight: 16
            x: choice.leftPadding
            y: choice.topPadding + (choice.availableHeight - height) / 2
            radius: 4
            color: choice.checked ? dialog.accent : "#ffffff"
            border.color: choice.activeFocus ? dialog.accent : "#cfd9de"
            Text {
                anchors.centerIn: parent
                text: "✓"
                color: "#ffffff"
                font.pixelSize: 12
                font.bold: true
                visible: choice.checked
            }
        }
        background: Rectangle {
            radius: 6
            color: choice.checked ? (dialog.uiTheme ? dialog.uiTheme.accentSoft : "#e6efee") : "#fffefa"
            border.color: choice.activeFocus ? dialog.accent
                         : (choice.checked ? dialog.accent : (dialog.uiTheme ? dialog.uiTheme.line : "#e2dfd7"))
        }
    }

    component PreferenceTextField: TextField {
        id: field
        implicitHeight: 38
        color: dialog.ink
        selectedTextColor: "#ffffff"
        selectionColor: dialog.accent
        font.family: dialog.fontFamily
        font.pixelSize: 12
        leftPadding: 10
        rightPadding: 10
        selectByMouse: true
        background: Rectangle {
            radius: 6
            color: dialog.uiTheme ? dialog.uiTheme.surface : "#fffefa"
            border.color: field.activeFocus ? dialog.accent : dialog.controlBorder
        }
    }

    contentItem: Flickable {
        id: scroller
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: formColumn.implicitHeight + 12
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: formColumn
            x: 3
            y: 4
            width: Math.max(0, scroller.width - 10)
            spacing: 16

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: qsTr("选择你希望纳入每日内容准备的方向。")
                    color: dialog.ink
                    font.family: dialog.fontFamily
                    font.pixelSize: 13
                    font.bold: true
                    Layout.fillWidth: true
                }
                Text {
                    text: qsTr("不选主题或媒体也可以保存；这些偏好只用于提示内容准备，不会自动屏蔽其他新闻。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: qsTr("关注主题")
                        color: dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: qsTr("%1 项").arg(dialog.draftTopics.length)
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                    }
                }
                Text {
                    text: qsTr("可多选；具体选题可以在下方补充。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
                Text {
                    objectName: "unlistedTopicsHint"
                    visible: dialog.unlistedTopicKeys.length > 0
                    text: qsTr("以下主题来自旧版设置，当前没有对应的选项；移除只会取消关注，不会删除新闻或历史内容。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Flow {
                    objectName: "topicOptionsFlow"
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        id: topicRepeater
                        model: dialog.topicOptions
                        delegate: PreferenceChoice {
                            required property var modelData
                            property string optionKey: dialog.topicKey(modelData)
                            objectName: "topicCheckBox_" + optionKey
                            text: qsTr(dialog.topicLabel(modelData))
                            onToggled: dialog.toggleTopic(optionKey, checked)
                        }
                    }
                }

                Flow {
                    objectName: "unlistedTopicsFlow"
                    Layout.fillWidth: true
                    spacing: 5
                    visible: dialog.unlistedTopicKeys.length > 0
                    Repeater {
                        model: dialog.unlistedTopicKeys.map(function(key) {
                            return { key: key, owner: dialog }
                        })
                        delegate: Button {
                            id: unlistedTopicRemoveButton
                            required property int index
                            required property var modelData
                            objectName: "unlistedTopicRemove_" + index
                            text: qsTr("旧版主题：%1  × 移除").arg(String(modelData.key))
                            leftPadding: 9
                            rightPadding: 9
                            topPadding: 5
                            bottomPadding: 5
                            contentItem: Text {
                                text: unlistedTopicRemoveButton.text
                                color: dialog.ink
                                font.family: dialog.fontFamily
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                radius: 5
                                color: "#fff8ec"
                                border.color: "#e8d6b7"
                            }
                            onClicked: {
                                modelData.owner.removeUnlistedTopic(String(modelData.key))
                                modelData.owner.saveError = ""
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: qsTr("补充具体选题")
                        color: dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        objectName: "subtopicsLengthCounter"
                        text: dialog.draftSubtopics.length + "/240"
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                    }
                }
                PreferenceTextField {
                    id: subtopicsInput
                    objectName: "subtopicsField"
                    Layout.fillWidth: true
                    maximumLength: 240
                    placeholderText: qsTr("例如：AI Agent、独立游戏")
                    onTextEdited: {
                        dialog.draftSubtopics = text
                        dialog.saveError = ""
                    }
                }
                Text {
                    text: qsTr("最多 240 字；这里只补充关注方向，不代表已自动筛选或核实新闻。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: qsTr("候选媒体")
                        color: dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: qsTr("%1 家预设").arg(dialog.draftPresetSources.length)
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                    }
                }
                Text {
                    text: qsTr("媒体只作为候选范围，不代表质量保证；每篇仍需核对原文、日期、证据和关联度。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Flow {
                    objectName: "presetSourcesFlow"
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        id: sourceRepeater
                        model: dialog.presetSourceOptions
                        delegate: PreferenceChoice {
                            required property var modelData
                            required property int index
                            property string sourceName: String(modelData)
                            objectName: "presetSourceCheckBox_" + index
                            text: sourceName
                            onToggled: dialog.togglePresetSource(sourceName, checked)
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: qsTr("补充其他来源")
                        color: dialog.ink
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        objectName: "customSourcesLengthCounter"
                        text: dialog.draftSources.length + "/240"
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                    }
                }
                PreferenceTextField {
                    id: customSourcesInput
                    objectName: "customSourcesField"
                    Layout.fillWidth: true
                    maximumLength: 240
                    placeholderText: qsTr("输入其他媒体，用顿号、逗号或分号分隔")
                    onTextEdited: {
                        dialog.draftSources = text
                        dialog.inputError = dialog.validateSources()
                        dialog.saveError = ""
                    }
                }
                Text {
                    objectName: "customSourcesHelp"
                    text: qsTr("最多 240 字；多个来源可用顿号、逗号或分号分隔，每个来源最多 60 字。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Text {
                objectName: "preferencesDialogError"
                text: dialog.inputError.length > 0
                      ? qsTr("单个自定义来源最多 60 字，请缩短或拆分后再保存。")
                      : qsTr(String(dialog.saveError))
                visible: text.length > 0
                color: dialog.danger
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            ColumnLayout {
                objectName: "appUpdateSection"
                visible: Boolean(dialog.appUpdateController)
                Layout.fillWidth: true
                spacing: 7

                Text {
                    text: qsTr("FLUKE 应用更新")
                    color: dialog.ink
                    font.family: dialog.fontFamily
                    font.pixelSize: 14
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                         text: qsTr("当前版本：%1。检查 GitHub Releases 中 v0.1.2 及以上的 Windows 安装包。")
                          .arg(String(dialog.appUpdateState.currentVersion || ""))
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: Boolean(dialog.appUpdateState.updateAvailable)
                    text: qsTr("可用版本：%1 · %2").arg(String(dialog.appUpdateState.availableVersion || ""))
                         .arg(String(dialog.appUpdateState.releaseTag || ""))
                    color: dialog.accent
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    Button {
                        objectName: "appUpdateCheckButton"
                        text: Boolean(dialog.appUpdateState.busy) ? qsTr("正在检查…") : qsTr("检查应用更新")
                        enabled: Boolean(dialog.appUpdateController) && !Boolean(dialog.appUpdateState.busy)
                        onClicked: dialog.appUpdateController.checkForUpdates()
                    }
                    Button {
                        objectName: "appUpdateDownloadButton"
                        text: Boolean(dialog.appUpdateState.busy) ? qsTr("正在下载…") : qsTr("下载并校验")
                        visible: Boolean(dialog.appUpdateState.updateAvailable)
                                 && !Boolean(dialog.appUpdateState.verifiedInstallerPath)
                        enabled: visible && !Boolean(dialog.appUpdateState.busy)
                        onClicked: dialog.appUpdateController.downloadAndVerify()
                    }
                    Button {
                        objectName: "appUpdateOpenFolderButton"
                        text: qsTr("打开安装包位置")
                        visible: Boolean(dialog.appUpdateState.verifiedInstallerPath)
                        enabled: !Boolean(dialog.appUpdateState.busy)
                        onClicked: dialog.appUpdateController.openVerifiedDownloadFolder()
                    }
                    Button {
                        objectName: "appUpdateInstallButton"
                        text: Boolean(dialog.appUpdateState.busy) ? qsTr("正在安装…") : qsTr("安全安装并重启")
                        visible: Boolean(dialog.appUpdateState.verifiedInstallerPath)
                                 && Boolean(dialog.appUpdateState.automaticInstallAvailable)
                        enabled: visible && !Boolean(dialog.appUpdateState.busy)
                        onClicked: dialog.appUpdateController.installVerifiedUpdate()
                    }
                    Button {
                        objectName: "appUpdateCancelButton"
                        text: qsTr("取消下载")
                        visible: Boolean(dialog.appUpdateState.cancellable)
                        enabled: visible
                        onClicked: dialog.appUpdateController.cancelCurrentOperation()
                    }
                    Item { Layout.fillWidth: true }
                }
                ProgressBar {
                    objectName: "appUpdateProgress"
                    Layout.fillWidth: true
                    visible: Boolean(dialog.appUpdateState.busy)
                    from: 0
                    to: 100
                    value: Number(dialog.appUpdateState.progress || 0)
                }
                Text {
                    objectName: "appUpdateStatus"
                    Layout.fillWidth: true
                    text: String(dialog.appUpdateState.statusMessage || "")
                    color: dialog.ink
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                     text: Boolean(dialog.appUpdateState.automaticInstallAvailable)
                           ? qsTr("新版会安装到独立版本目录；启动健康检查成功后才切换，失败时自动保留旧版并可回退。")
                           : qsTr("当前安装不是可回滚的 side-by-side 布局，只能下载并校验官方安装包；自动安装已关闭。")
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    footer: RowLayout {
        spacing: 10
        Text {
            text: qsTr("仅点击保存才会提交；取消或按 Esc 会丢弃本次修改。")
            color: dialog.muted
            font.family: dialog.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Button {
            objectName: "preferencesCancelButton"
            text: qsTr("取消")
            font.family: dialog.fontFamily
            onClicked: dialog.close()
        }
        Button {
            objectName: "preferencesSaveButton"
            text: qsTr("保存关注方向")
            font.family: dialog.fontFamily
            highlighted: true
            enabled: dialog.validateSources().length === 0
            onClicked: dialog.saveDraft()
        }
    }

    background: Rectangle {
        radius: dialog.uiTheme ? dialog.uiTheme.radiusLarge : 16
        color: dialog.uiTheme ? dialog.uiTheme.surface : "#fffefa"
        border.color: dialog.uiTheme ? dialog.uiTheme.line : "#e2dfd7"
    }
}
