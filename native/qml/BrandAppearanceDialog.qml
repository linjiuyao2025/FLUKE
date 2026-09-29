pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "brandAppearanceDialog"

    property var uiTheme: null
    property var localeController: null
    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color controlBorder: uiTheme ? uiTheme.controlBorder : "#807d76"
    readonly property color surface: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color softSurface: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color danger: uiTheme ? uiTheme.danger : "#9d4038"
    readonly property string fontFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    property var brandStore
    property var initialBrand: ({})
    property string draftName: ""
    property string draftTagline: ""
    property string draftTheme: "plum"
    property string draftAvatarImage: ""
    property string avatarMode: "letter"
    property string selectedAvatarUrl: ""
    property string formError: ""
    property string avatarError: ""
    property real cropCenterX: 0.5
    property real cropCenterY: 0.5
    property real cropZoom: 1.0
    property bool cropChanged: false
    property bool inSave: false
    property string languageError: ""

    signal previewChanged(var brand)
    signal appearanceSaved(var brand)

    readonly property var defaults: ({
        name: "万象来信",
        avatar: "万",
        avatarImage: "",
        tagline: "把远方与日常，折进今天",
        theme: "plum"
    })
    readonly property var draftBrand: ({
        name: draftName,
        avatar: firstLetter(draftName),
        avatarImage: avatarMode === "image" ? draftAvatarImage : "",
        tagline: draftTagline,
        theme: draftTheme
    })
    readonly property var themeChoices: [
        { key: "plum", label: qsTr("暮色紫"), color: "#4d3045", soft: "#e8dfe5" },
        { key: "forest", label: qsTr("森林绿"), color: "#365f53", soft: "#dfe9e4" },
        { key: "clay", label: qsTr("陶土棕"), color: "#8f4f3b", soft: "#f0ddd6" },
        { key: "navy", label: qsTr("深海蓝"), color: "#344b63", soft: "#dde4eb" }
    ]
    readonly property var languageChoices: [
        { value: "zh_CN", label: "简体中文 / Chinese" },
        { value: "en_US", label: "English" }
    ]

    title: qsTr("工作台外观")
    palette.window: dialog.surface
    palette.windowText: dialog.ink
    palette.base: dialog.surface
    palette.alternateBase: dialog.softSurface
    palette.text: dialog.ink
    palette.button: dialog.surface
    palette.buttonText: dialog.ink
    palette.highlight: uiTheme ? uiTheme.accent : "#4d3045"
    palette.highlightedText: "#ffffff"
    palette.placeholderText: dialog.muted
    palette.light: "#ffffff"
    palette.midlight: dialog.softSurface
    palette.mid: dialog.line
    palette.dark: dialog.line
    palette.shadow: dialog.line
    modal: true
    standardButtons: Dialog.NoButton
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: Math.min(640, (Overlay.overlay ? Overlay.overlay.width : 640) - 28)
    height: Math.min(
        780,
        (Overlay.overlay ? Overlay.overlay.height : 780) - 28,
        Math.max(620, body.implicitHeight + appearanceFooter.implicitHeight + padding * 2 + 8))
    anchors.centerIn: Overlay.overlay
    padding: 20

    function clone(value) {
        return JSON.parse(JSON.stringify(value || {}))
    }

    function firstLetter(value) {
        var text = String(value || "").trim()
        if (!text.length)
            return "万"
        if (brandStore && brandStore.firstLetter)
            return brandStore.firstLetter(text)
        return Array.from(text)[0]
    }

    function syncLanguageChoice() {
        if (dialog.localeController && languageSelector)
            languageSelector.currentIndex = languageSelector.indexOfValue(dialog.localeController.language)
    }

    function savedBrand() {
        if (brandStore && brandStore.brand)
            return clone(brandStore.brand)
        return clone(initialBrand)
    }

    function publishPreview() {
        previewChanged({
            name: draftName || defaults.name,
            avatar: firstLetter(draftName || defaults.name),
            avatarImage: avatarMode === "image" ? (draftAvatarImage || "") : "",
            tagline: draftTagline || defaults.tagline,
            theme: draftTheme
        })
    }

    function resetDraft() {
        var brand = savedBrand()
        draftName = typeof brand.name === "string" && brand.name.length ? brand.name : defaults.name
        draftTagline = typeof brand.tagline === "string" && brand.tagline.length ? brand.tagline : defaults.tagline
        draftTheme = ["plum", "forest", "clay", "navy"].indexOf(brand.theme) >= 0 ? brand.theme : defaults.theme
        draftAvatarImage = typeof brand.avatarImage === "string" ? brand.avatarImage : ""
        avatarMode = draftAvatarImage.length ? "image" : "letter"
        nameInput.text = draftName
        taglineInput.text = draftTagline
        letterModeButton.checked = avatarMode === "letter"
        imageModeButton.checked = avatarMode === "image"
        selectedAvatarUrl = ""
        cropCenterX = 0.5
        cropCenterY = 0.5
        cropZoom = 1.0
        avatarZoomSlider.value = cropZoom
        cropChanged = false
        formError = ""
        avatarError = ""
        initialBrand = clone(brand)
        Qt.callLater(publishPreview)
    }

    function cancelDraft() {
        if (inSave)
            return
        initialBrand = savedBrand()
        close()
    }

    function chooseAvatar() {
        if (!brandStore) {
            avatarError = qsTr("头像读取服务尚未连接。")
            return
        }
        avatarFileDialog.open()
    }

    function finishSave() {
        formError = ""
        avatarError = ""
        var name = draftName.trim() || defaults.name
        var tagline = draftTagline.trim() || defaults.tagline
        if (name.length > 12) {
            formError = qsTr("页面名称最多 12 个字符。")
            return
        }
        if (tagline.length > 20) {
            formError = qsTr("副标题最多 20 个字符。")
            return
        }
        if (["plum", "forest", "clay", "navy"].indexOf(draftTheme) < 0) {
            formError = qsTr("请选择一个主题色。")
            return
        }
        if (!brandStore) {
            formError = qsTr("外观保存服务尚未连接。")
            return
        }

        var avatarImage = ""
        if (avatarMode === "image") {
            var cropSource = selectedAvatarUrl || draftAvatarImage
            if (!cropSource.length) {
                avatarError = qsTr("先选择并裁剪一张头像图片。")
                return
            }
            if (cropChanged || selectedAvatarUrl.length) {
                var prepared = brandStore.prepareAvatarImage(
                    cropSource, cropCenterX, cropCenterY, cropZoom)
                if (!prepared || !prepared.ok) {
                    avatarError = prepared && prepared.error ? prepared.error : qsTr("头像图片转换失败。")
                    return
                }
                avatarImage = prepared.dataUrl
            } else {
                avatarImage = draftAvatarImage
            }
        }
        if (!brandStore) {
            formError = qsTr("外观保存服务尚未连接。")
            return
        }

        inSave = true
        var result = brandStore.saveBrand({
            name: name,
            avatar: firstLetter(name),
            avatarImage: avatarImage,
            tagline: tagline,
            theme: draftTheme
        })
        inSave = false
        if (!result || !result.ok) {
            formError = result && result.error ? result.error : qsTr("保存外观失败，请重试。")
            return
        }
        initialBrand = clone(result.brand)
        draftName = result.brand.name
        draftTagline = result.brand.tagline
        draftTheme = result.brand.theme
        draftAvatarImage = result.brand.avatarImage || ""
        avatarMode = draftAvatarImage.length ? "image" : "letter"
        nameInput.text = draftName
        taglineInput.text = draftTagline
        letterModeButton.checked = avatarMode === "letter"
        imageModeButton.checked = avatarMode === "image"
        selectedAvatarUrl = ""
        cropChanged = false
        appearanceSaved(result.brand)
        previewChanged(result.brand)
        close()
    }

    function resetAppearance() {
        formError = ""
        avatarError = ""
        draftName = defaults.name
        draftTagline = defaults.tagline
        draftTheme = defaults.theme
        draftAvatarImage = defaults.avatarImage
        avatarMode = "letter"
        nameInput.text = draftName
        taglineInput.text = draftTagline
        letterModeButton.checked = true
        imageModeButton.checked = false
        selectedAvatarUrl = ""
        cropCenterX = 0.5
        cropCenterY = 0.5
        cropZoom = 1.0
        avatarZoomSlider.value = cropZoom
        cropChanged = false
        publishPreview()
    }

    function clampCenter() {
        var imageWidth = previewImage.width
        var imageHeight = previewImage.height
        var halfX = imageWidth <= avatarFrame.width
                ? 0.5 : avatarFrame.width / (2 * imageWidth)
        var halfY = imageHeight <= avatarFrame.height
                ? 0.5 : avatarFrame.height / (2 * imageHeight)
        cropCenterX = Math.max(halfX, Math.min(1 - halfX, cropCenterX))
        cropCenterY = Math.max(halfY, Math.min(1 - halfY, cropCenterY))
    }

    function moveCropByKeyboard(horizontal, vertical) {
        if (previewImage.status !== Image.Ready || previewImage.width <= 0 || previewImage.height <= 0)
            return
        cropCenterX -= horizontal * 12 / previewImage.width
        cropCenterY -= vertical * 12 / previewImage.height
        clampCenter()
        cropChanged = true
        publishPreview()
    }

    onOpened: {
        resetDraft()
        syncLanguageChoice()
        Qt.callLater(function() { nameInput.forceActiveFocus() })
    }
    Component.onCompleted: syncLanguageChoice()
    onClosed: {
        if (!inSave) {
            initialBrand = savedBrand()
            previewChanged(initialBrand)
        }
    }
    Connections {
        target: dialog.localeController
        enabled: dialog.localeController !== null
        function onLanguageChanged() { dialog.syncLanguageChoice() }
    }

    background: Rectangle {
        radius: 18
        color: dialog.surface
        border.color: dialog.line
    }

    header: Rectangle {
        implicitHeight: 44
        color: dialog.softSurface

        Label {
            anchors.fill: parent
            anchors.leftMargin: 20
            anchors.rightMargin: 150
            text: dialog.title
            color: dialog.ink
            font.family: dialog.fontFamily
            font.pixelSize: 15
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }

        Label {
            objectName: "appearanceScrollHint"
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            text: qsTr("可向下滚动查看更多")
            color: dialog.muted
            font.family: dialog.fontFamily
            font.pixelSize: 11
            visible: appearanceScroll.contentHeight > appearanceScroll.height + 1
        }
    }

    contentItem: Flickable {
        id: appearanceScroll
        objectName: "appearanceScroll"
        clip: true
        contentWidth: body.width
        contentHeight: body.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            id: appearanceVerticalScrollBar
            objectName: "appearanceVerticalScrollBar"
            policy: appearanceScroll.contentHeight > appearanceScroll.height + 1
                    ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
        }

        ColumnLayout {
            id: body
            width: Math.max(0, dialog.availableWidth - appearanceVerticalScrollBar.width - 8)
            spacing: 15

            Label {
                text: qsTr("为 FLUKE 工作台设置名称、头像和主题色")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Label {
                objectName: "uiLanguageLabel"
                text: qsTr("界面语言")
                color: dialog.ink
                font.family: dialog.fontFamily
                font.pixelSize: 12
                font.bold: true
            }
            UiComboBox {
                id: languageSelector
                uiTheme: dialog.uiTheme
                objectName: "uiLanguageSelector"
                accessibleName: qsTr("界面语言")
                Layout.fillWidth: true
                model: dialog.languageChoices
                textRole: "label"
                valueRole: "value"
                enabled: dialog.localeController !== null
                onActivated: function(index) {
                    if (!dialog.localeController)
                        return
                    var result = dialog.localeController.setLanguage(currentValue)
                    dialog.languageError = result && result.ok
                            ? "" : (result && result.error
                                    ? result.error : qsTr("界面语言保存失败；已保留当前语言。"))
                    dialog.syncLanguageChoice()
                }
            }
            Label {
                text: qsTr("英文界面正在逐步完善；尚未翻译的页面会继续显示中文。")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Label {
                objectName: "uiLanguageCommitHint"
                text: qsTr("界面语言会立即保存；取消只放弃其他外观修改。")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Label {
                objectName: "uiLanguageError"
                text: dialog.languageError
                color: dialog.danger
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                visible: text.length > 0
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: previewRow.implicitHeight + 24
                radius: 14
                color: dialog.softSurface
                RowLayout {
                    id: previewRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12
                    Rectangle {
                        implicitWidth: 48
                        implicitHeight: 48
                        radius: 14
                        color: dialog.themeColor(dialog.draftTheme)
                        clip: true
                        Image {
                            id: previewLogoImage
                            property real baseScale: implicitWidth > 0 && implicitHeight > 0
                                    ? Math.max(parent.width / implicitWidth,
                                               parent.height / implicitHeight) : 1
                            width: implicitWidth * baseScale * dialog.cropZoom
                            height: implicitHeight * baseScale * dialog.cropZoom
                            x: parent.width / 2 - dialog.cropCenterX * width
                            y: parent.height / 2 - dialog.cropCenterY * height
                            source: dialog.avatarMode === "image"
                                    ? (dialog.selectedAvatarUrl || dialog.draftAvatarImage) : ""
                            fillMode: Image.Stretch
                            visible: source.toString().length > 0
                        }
                        Label {
                            anchors.centerIn: parent
                            visible: !previewLogoImage.visible
                            text: dialog.firstLetter(dialog.draftName || dialog.defaults.name)
                            color: "white"
                            font.family: dialog.fontFamily
                            font.pixelSize: 20
                            font.bold: true
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: dialog.draftName || dialog.defaults.name
                            color: dialog.ink
                            font.family: dialog.fontFamily
                            font.pixelSize: 16
                            font.bold: true
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: dialog.draftTagline || dialog.defaults.tagline
                            color: dialog.muted
                            font.family: dialog.fontFamily
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    Rectangle {
                        implicitWidth: 12
                        implicitHeight: 34
                        radius: 6
                        color: dialog.themeColor(dialog.draftTheme)
                    }
                }
            }

            Label { text: qsTr("页面名称"); color: dialog.ink; font.family: dialog.fontFamily; font.pixelSize: 12; font.bold: true }
            TextField {
                id: nameInput
                objectName: "brandNameInput"
                Accessible.name: qsTr("页面名称")
                text: dialog.draftName
                maximumLength: 12
                placeholderText: "FLUKE"
                color: dialog.ink
                font.family: dialog.fontFamily
                selectionColor: dialog.themeColor(dialog.draftTheme)
                selectedTextColor: "#ffffff"
                background: Rectangle {
                    radius: 7
                    color: dialog.surface
                    border.width: nameInput.activeFocus ? 2 : 1
                    border.color: nameInput.activeFocus ? dialog.themeColor(dialog.draftTheme) : dialog.controlBorder
                }
                Layout.fillWidth: true
                onTextEdited: {
                    dialog.draftName = text
                    dialog.formError = ""
                    dialog.publishPreview()
                }
            }

            Label { text: qsTr("头像"); color: dialog.ink; font.family: dialog.fontFamily; font.pixelSize: 12; font.bold: true }
            RowLayout {
                Layout.fillWidth: true
                ButtonGroup { id: avatarModeGroup }
                RadioButton {
                    font.family: dialog.fontFamily
                    id: letterModeButton
                    objectName: "letterAvatarMode"
                    text: qsTr("名称首字")
                    ButtonGroup.group: avatarModeGroup
                    checked: dialog.avatarMode === "letter"
                    onClicked: {
                        dialog.avatarMode = "letter"
                        dialog.avatarError = ""
                        dialog.publishPreview()
                    }
                }
                RadioButton {
                    id: imageModeButton
                    objectName: "imageAvatarMode"
                    text: qsTr("上传图片")
                    font.family: dialog.fontFamily
                    ButtonGroup.group: avatarModeGroup
                    checked: dialog.avatarMode === "image"
                    onClicked: {
                        dialog.avatarMode = "image"
                        dialog.avatarError = ""
                        dialog.publishPreview()
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    objectName: "chooseBrandAvatarButton"
                    text: qsTr("选择图片")
                    font.family: dialog.fontFamily
                    enabled: dialog.avatarMode === "image"
                    onClicked: dialog.chooseAvatar()
                }
            }

            RowLayout {
                visible: dialog.avatarMode === "image"
                Layout.fillWidth: true
                spacing: 14
                Rectangle {
                    id: avatarFrame
                    objectName: "brandAvatarCropFrame"
                    Layout.preferredWidth: Math.min(180, dialog.availableWidth * 0.38)
                    Layout.preferredHeight: Layout.preferredWidth
                    radius: 14
                    clip: true
                    color: dialog.softSurface
                    border.color: dialog.line
                    Image {
                        id: previewImage
                        objectName: "brandAvatarCropImage"
                        property real baseScale: implicitWidth > 0 && implicitHeight > 0
                                ? Math.max(avatarFrame.width / implicitWidth,
                                           avatarFrame.height / implicitHeight) : 1
                        width: implicitWidth * baseScale * dialog.cropZoom
                        height: implicitHeight * baseScale * dialog.cropZoom
                        x: avatarFrame.width / 2 - dialog.cropCenterX * width
                        y: avatarFrame.height / 2 - dialog.cropCenterY * height
                        source: dialog.selectedAvatarUrl || dialog.draftAvatarImage
                        asynchronous: true
                        cache: false
                        fillMode: Image.Stretch
                        onStatusChanged: {
                            if (status === Image.Error)
                                dialog.avatarError = qsTr("图片无法读取，请换一张图片。")
                            else if (status === Image.Ready)
                                dialog.clampCenter()
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: previewImage.activeFocus ? 2 : 0
                            border.color: dialog.themeColor(dialog.draftTheme)
                            radius: 14
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: previewImage.status === Image.Ready
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        property point lastPoint
                        onPressed: function(mouse) {
                            lastPoint = Qt.point(mouse.x, mouse.y)
                        }
                        onPositionChanged: function(mouse) {
                            if (!pressed || previewImage.width <= 0 || previewImage.height <= 0)
                                return
                            dialog.cropCenterX -= (mouse.x - lastPoint.x) / previewImage.width
                            dialog.cropCenterY -= (mouse.y - lastPoint.y) / previewImage.height
                            lastPoint = Qt.point(mouse.x, mouse.y)
                            dialog.clampCenter()
                            dialog.cropChanged = true
                            dialog.publishPreview()
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    Label {
                        text: qsTr("拖动图片调整位置，也可用方向按钮微调；滑块调整缩放。头像会裁成方形。")
                        color: dialog.muted
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Slider {
                        id: avatarZoomSlider
                        objectName: "brandAvatarZoom"
                        from: 1
                        to: 3
                        stepSize: 0.01
                        value: dialog.cropZoom
                        Layout.fillWidth: true
                        onMoved: {
                            dialog.cropZoom = value
                            dialog.clampCenter()
                            dialog.cropChanged = true
                            dialog.publishPreview()
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label {
                            text: qsTr("位置微调")
                            color: dialog.muted
                            font.family: dialog.fontFamily
                            font.pixelSize: 12
                            Layout.fillWidth: true
                        }
                        ToolButton {
                            objectName: "avatarNudgeLeftButton"
                            text: "←"
                            Accessible.name: qsTr("头像向左微调")
                            enabled: previewImage.status === Image.Ready
                            onClicked: dialog.moveCropByKeyboard(-1, 0)
                        }
                        ToolButton {
                            objectName: "avatarNudgeUpButton"
                            text: "↑"
                            Accessible.name: qsTr("头像向上微调")
                            enabled: previewImage.status === Image.Ready
                            onClicked: dialog.moveCropByKeyboard(0, -1)
                        }
                        ToolButton {
                            objectName: "avatarNudgeDownButton"
                            text: "↓"
                            Accessible.name: qsTr("头像向下微调")
                            enabled: previewImage.status === Image.Ready
                            onClicked: dialog.moveCropByKeyboard(0, 1)
                        }
                        ToolButton {
                            objectName: "avatarNudgeRightButton"
                            text: "→"
                            Accessible.name: qsTr("头像向右微调")
                            enabled: previewImage.status === Image.Ready
                            onClicked: dialog.moveCropByKeyboard(1, 0)
                        }
                    }
                    Label {
                        objectName: "brandAvatarError"
                        text: dialog.avatarError
                        color: dialog.danger
                        font.family: dialog.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        visible: text.length > 0
                        Layout.fillWidth: true
                    }
                }
            }

            Label { text: qsTr("副标题"); color: dialog.ink; font.family: dialog.fontFamily; font.pixelSize: 12; font.bold: true }
            TextField {
                id: taglineInput
                objectName: "brandTaglineInput"
                Accessible.name: qsTr("副标题")
                text: dialog.draftTagline
                maximumLength: 20
                placeholderText: qsTr("把远方与日常，折进今天")
                color: dialog.ink
                font.family: dialog.fontFamily
                selectionColor: dialog.themeColor(dialog.draftTheme)
                selectedTextColor: "#ffffff"
                background: Rectangle {
                    radius: 7
                    color: dialog.surface
                    border.width: taglineInput.activeFocus ? 2 : 1
                    border.color: taglineInput.activeFocus ? dialog.themeColor(dialog.draftTheme) : dialog.controlBorder
                }
                Layout.fillWidth: true
                onTextEdited: {
                    dialog.draftTagline = text
                    dialog.formError = ""
                    dialog.publishPreview()
                }
            }

            Label { text: qsTr("主题色"); color: dialog.ink; font.family: dialog.fontFamily; font.pixelSize: 12; font.bold: true }
            GridLayout {
                columns: 4
                rowSpacing: 8
                columnSpacing: 8
                Layout.fillWidth: true
                Repeater {
                    model: dialog.themeChoices
                    delegate: Button {
                        id: themeButton
                        font.family: dialog.fontFamily
                        required property var modelData
                        objectName: "brandTheme_" + modelData.key
                        Layout.fillWidth: true
                        Layout.minimumWidth: 85
                        Layout.preferredHeight: 70
                        padding: 7
                        onClicked: {
                            dialog.draftTheme = themeButton.modelData.key
                            dialog.publishPreview()
                        }
                        background: Rectangle {
                            radius: 12
                            color: dialog.draftTheme === themeButton.modelData.key ? "#f2eee7" : "#fffdf9"
                            border.width: themeButton.activeFocus ? 3
                                          : dialog.draftTheme === themeButton.modelData.key ? 2 : 1
                            border.color: themeButton.activeFocus ? dialog.ink
                                    : dialog.draftTheme === themeButton.modelData.key
                                      ? themeButton.modelData.color : "#e4ddd2"
                        }
                        contentItem: Column {
                            spacing: 5
                            anchors.centerIn: parent
                            Rectangle {
                                width: 25
                                height: 25
                                radius: 13
                                color: themeButton.modelData.color
                                anchors.horizontalCenter: parent.horizontalCenter
                            }
                            Label {
                                text: themeButton.modelData.label
                                color: dialog.ink
                                font.family: dialog.fontFamily
                                font.pixelSize: 12
                                anchors.horizontalCenter: parent.horizontalCenter
                            }
                        }
                    }
                }
            }

            Label {
                objectName: "brandFormError"
                text: dialog.formError
                color: dialog.danger
                font.family: dialog.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                visible: text.length > 0
                Layout.fillWidth: true
            }

        }
    }

    footer: RowLayout {
        id: appearanceFooter
        spacing: 8
        UiButton {
            uiTheme: dialog.uiTheme
            objectName: "resetBrandButton"
            text: qsTr("恢复默认（待保存）")
            onClicked: dialog.resetAppearance()
        }
        Item { Layout.fillWidth: true }
        UiButton {
            uiTheme: dialog.uiTheme
            objectName: "cancelBrandButton"
            text: qsTr("取消")
            onClicked: dialog.cancelDraft()
        }
        UiButton {
            uiTheme: dialog.uiTheme
            objectName: "saveBrandButton"
            text: qsTr("保存外观")
            highlighted: true
            onClicked: dialog.finishSave()
        }
    }

    FileDialog {
        id: avatarFileDialog
        objectName: "brandAvatarFileDialog"
        title: qsTr("选择头像图片")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("图片文件 (*.png *.jpg *.jpeg *.webp *.gif)"), qsTr("所有文件 (*)")]
        onAccepted: {
            var source = String(selectedFile)
            if (!dialog.brandStore) {
                dialog.avatarError = qsTr("头像读取服务尚未连接。")
                return
            }
            var inspection = dialog.brandStore.inspectAvatar(source)
            if (!inspection || !inspection.ok) {
                dialog.avatarError = inspection && inspection.error
                        ? inspection.error : qsTr("图片无法读取，请换一张图片。")
                return
            }
            dialog.selectedAvatarUrl = source
            dialog.draftAvatarImage = ""
            dialog.avatarMode = "image"
            dialog.cropCenterX = 0.5
            dialog.cropCenterY = 0.5
            dialog.cropZoom = 1.0
            dialog.cropChanged = true
            dialog.avatarError = ""
            dialog.publishPreview()
        }
    }

    function themeColor(theme) {
        for (var i = 0; i < themeChoices.length; ++i) {
            if (themeChoices[i].key === theme)
                return themeChoices[i].color
        }
        return themeChoices[0].color
    }
}
