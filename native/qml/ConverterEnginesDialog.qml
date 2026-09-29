pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "converterEnginesDialog"
    required property var controller
    property var uiTheme: null
    property string requestedFileName: ""
    property string requestedExtension: ""

    readonly property color canvas: uiTheme ? uiTheme.canvas : "#f6f5f0"
    readonly property color surface: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color accent: uiTheme ? uiTheme.accent : "#456b73"
    readonly property string fontFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property var state: controller ? controller.state : ({})

    title: qsTr("转换引擎")
    modal: true
    standardButtons: Dialog.NoButton
    closePolicy: Popup.CloseOnEscape
    width: Math.min(720, (Overlay.overlay ? Overlay.overlay.width : 720) - 32)
    height: Math.min(670, (Overlay.overlay ? Overlay.overlay.height : 670) - 32)
    anchors.centerIn: Overlay.overlay
    padding: 18

    onOpened: {
        if (controller)
            controller.checkForUpdates()
    }

    function openForJob(job) {
        const fileName = String(job && job.fileName || "")
        const sourcePath = String(job && job.sourcePath || fileName)
        const sourceName = sourcePath.split(/[\\/]/).pop()
        const dot = sourceName.lastIndexOf(".")
        requestedFileName = fileName || sourceName
        requestedExtension = dot > 0 ? sourceName.slice(dot).toLowerCase() : qsTr("未知类型")
        open()
    }

    onClosed: {
        requestedFileName = ""
        requestedExtension = ""
    }

    background: Rectangle {
        radius: 14
        color: dialog.surface
        border.color: dialog.line
    }

    contentItem: ColumnLayout {
        spacing: 12

        Text {
            Layout.fillWidth: true
            text: qsTr("FLUKE 把转换引擎作为独立组件管理。随安装包提供的版本可离线使用；更新会下载安装到当前 Windows 用户的 FLUKE 数据目录。安装失败时旧版保持启用，成功更新后也可在这里恢复到上一版本。")
            color: dialog.muted
            font.family: dialog.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Rectangle {
            objectName: "converterEngineRequestContext"
            visible: dialog.requestedFileName.length > 0
            Layout.fillWidth: true
            implicitHeight: requestContextColumn.implicitHeight + 16
            radius: 8
            color: dialog.canvas
            border.color: dialog.accent

            ColumnLayout {
                id: requestContextColumn
                anchors.fill: parent
                anchors.margins: 8
                spacing: 3
                Text {
                    objectName: "converterEngineRequestContextSummary"
                    Layout.fillWidth: true
                    text: qsTr("正在为“%1”检查转换组件").arg(dialog.requestedFileName)
                    color: dialog.ink
                    font.family: dialog.fontFamily
                    font.pixelSize: 12
                    font.bold: true
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTr("输入类型：%1。安装或更新后，关闭此窗口并重新添加文件，系统会重新检测可用格式。")
                          .arg(dialog.requestedExtension)
                    color: dialog.muted
                    font.family: dialog.fontFamily
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Button {
                objectName: "converterEngineCheckUpdatesButton"
                text: dialog.state.busy ? qsTr("正在处理…") : qsTr("检查更新")
                enabled: Boolean(dialog.controller) && !Boolean(dialog.state.busy)
                onClicked: dialog.controller.checkForUpdates()
            }

            Text {
                objectName: "converterEngineReleaseTag"
                Layout.fillWidth: true
                text: dialog.state.releaseTag
                      ? qsTr("更新通道：%1").arg(String(dialog.state.releaseTag))
                      : qsTr("更新通道：FLUKE GitHub Releases")
                color: dialog.muted
                font.family: dialog.fontFamily
                font.pixelSize: 11
                elide: Text.ElideMiddle
            }
        }

        ProgressBar {
            objectName: "converterEngineUpdateProgress"
            Layout.fillWidth: true
            visible: Boolean(dialog.state.busy)
            from: 0
            to: 100
            value: Number(dialog.state.progress || 0)
        }

        Text {
            objectName: "converterEngineStatus"
            Layout.fillWidth: true
            text: String(dialog.state.statusMessage || "")
            color: dialog.ink
            font.family: dialog.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        ListView {
            id: engineList
            objectName: "converterEngineList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: dialog.state.engines || []
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: engineRow
                required property var modelData
                width: engineList.width
                height: engineDetails.implicitHeight + 26
                radius: 10
                color: dialog.canvas
                border.color: dialog.line

                RowLayout {
                    id: engineDetails
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            Layout.fillWidth: true
                            text: String(engineRow.modelData.label || "")
                            color: dialog.ink
                            font.family: dialog.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: String(engineRow.modelData.description || "")
                            color: dialog.muted
                            font.family: dialog.fontFamily
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            text: String(engineRow.modelData.installedVersion || "")
                                  ? qsTr("当前：%1（%2）").arg(String(engineRow.modelData.installedVersion))
                                       .arg(String(engineRow.modelData.installedSource || ""))
                                  : qsTr("当前：未安装")
                            color: dialog.muted
                            font.family: dialog.fontFamily
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: Boolean(engineRow.modelData.updateAvailable)
                            text: qsTr("可用版本：%1 · 更新包约 %2 MiB").arg(String(engineRow.modelData.availableVersion || ""))
                                       .arg(String(Math.max(1, Math.ceil(Number(engineRow.modelData.downloadSize || 0) / 1048576))))
                            color: dialog.accent
                            font.family: dialog.fontFamily
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        spacing: 6
                        Button {
                            objectName: "converterEngineInstallButton_" + String(engineRow.modelData.id || "")
                            text: !String(engineRow.modelData.installedVersion || "")
                                  ? (String(engineRow.modelData.availableVersion || "")
                                     ? qsTr("安装") : qsTr("暂无安装包"))
                                  : qsTr("更新")
                            enabled: Boolean(engineRow.modelData.updateAvailable) && !Boolean(dialog.state.busy)
                            onClicked: dialog.controller.installOrUpdate(String(engineRow.modelData.id || ""))
                        }
                        Button {
                            objectName: "converterEngineRollbackButton_" + String(engineRow.modelData.id || "")
                            text: String(engineRow.modelData.previousVersion || "")
                                  ? qsTr("回滚到 %1").arg(String(engineRow.modelData.previousVersion))
                                  : qsTr("回滚引擎版本")
                            visible: Boolean(engineRow.modelData.canRollback)
                            enabled: !Boolean(dialog.state.busy)
                            onClicked: dialog.controller.rollbackEngine(String(engineRow.modelData.id || ""))
                        }
                        Button {
                            objectName: "converterEngineLicenseButton_" + String(engineRow.modelData.id || "")
                            text: qsTr("许可说明")
                            visible: Boolean(engineRow.modelData.licenseNoticeAvailable)
                            onClicked: dialog.controller.openLicenseNotice(String(engineRow.modelData.id || ""))
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                objectName: "converterEngineCloseButton"
                text: qsTr("关闭")
                onClicked: dialog.close()
            }
        }
    }
}
