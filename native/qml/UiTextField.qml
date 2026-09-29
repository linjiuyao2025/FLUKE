pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

TextField {
    id: control

    property var uiTheme: null
    property string accessibleName: ""
    readonly property color inkColor: uiTheme ? uiTheme.ink : "#273239"
    readonly property color mutedColor: uiTheme ? uiTheme.muted : "#586569"
    readonly property color surfaceColor: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color lineColor: uiTheme ? uiTheme.controlBorder : "#807d76"
    readonly property color accentColor: uiTheme ? uiTheme.accent : "#456b73"

    implicitHeight: uiTheme ? uiTheme.controlHeight : 38
    leftPadding: 12
    rightPadding: 12
    font.family: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    font.pixelSize: 12
    color: inkColor
    placeholderTextColor: mutedColor
    selectByMouse: true
    Accessible.name: accessibleName.trim().length ? accessibleName.trim() : placeholderText.trim()

    background: Rectangle {
        radius: control.uiTheme ? control.uiTheme.radiusSmall : 8
        color: control.surfaceColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.accentColor : control.lineColor
    }
}
