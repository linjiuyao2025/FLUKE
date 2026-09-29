pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Button {
    id: control

    property var uiTheme: null
    property bool destructive: false
    readonly property color inkColor: uiTheme ? uiTheme.ink : "#273239"
    readonly property color mutedColor: uiTheme ? uiTheme.muted : "#586569"
    readonly property color surfaceColor: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color surfaceSoftColor: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color lineColor: uiTheme ? uiTheme.controlBorder : "#807d76"
    readonly property color accentColor: uiTheme ? uiTheme.accent : "#456b73"
    readonly property color accentStrongColor: uiTheme ? uiTheme.accentStrong : "#315761"
    readonly property color accentSoftColor: uiTheme ? uiTheme.accentSoft : "#e6efee"
    readonly property color dangerColor: uiTheme ? uiTheme.danger : "#9d4038"

    implicitHeight: uiTheme ? uiTheme.controlHeight : 38
    leftPadding: 14
    rightPadding: 14

    contentItem: Text {
        text: control.text
        color: !control.enabled ? control.mutedColor
             : (control.highlighted || control.destructive) ? control.surfaceColor : control.inkColor
        font.family: control.uiTheme ? control.uiTheme.sansFamily : "Noto Sans SC"
        font.pixelSize: 12
        font.weight: (control.highlighted || control.destructive) ? Font.DemiBold : Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: control.uiTheme ? control.uiTheme.radiusSmall : 8
        color: !control.enabled ? control.surfaceSoftColor
             : control.destructive ? (control.down ? Qt.darker(control.dangerColor, 1.12) : control.dangerColor)
             : control.highlighted ? (control.down ? control.accentStrongColor : control.accentColor)
             : control.down ? control.accentSoftColor : control.surfaceColor
        border.width: control.enabled && control.activeFocus ? 2 : 1
        border.color: control.enabled && control.activeFocus ? control.accentStrongColor
                     : !control.enabled ? control.lineColor
                     : control.destructive ? control.dangerColor
                     : control.highlighted ? control.accentColor : control.lineColor
    }
}
