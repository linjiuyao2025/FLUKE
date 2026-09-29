pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

ComboBox {
    id: control

    property var uiTheme: null
    property string accessibleName: ""
    readonly property color inkColor: uiTheme ? uiTheme.ink : "#273239"
    readonly property color mutedColor: uiTheme ? uiTheme.muted : "#586569"
    readonly property color surfaceColor: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color lineColor: uiTheme ? uiTheme.controlBorder : "#807d76"
    readonly property color accentColor: uiTheme ? uiTheme.accent : "#456b73"
    readonly property color accentSoftColor: uiTheme ? uiTheme.accentSoft : "#e6efee"

    implicitHeight: uiTheme ? uiTheme.controlHeight : 38
    leftPadding: 12
    rightPadding: 30
    font.family: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    font.pixelSize: 12
    Accessible.name: accessibleName.trim()

    contentItem: Text {
        leftPadding: control.leftPadding
        rightPadding: control.rightPadding
        text: control.displayText
        color: control.enabled ? control.inkColor : control.mutedColor
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Canvas {
        property color chevronColor: control.activeFocus ? control.accentColor : control.mutedColor
        x: control.width - width - 11
        y: control.topPadding + (control.availableHeight - height) / 2 - 2
        width: 11
        height: 7
        onChevronColorChanged: requestPaint()
        onPaint: {
            const context = getContext("2d")
            context.reset()
            context.strokeStyle = String(chevronColor)
            context.lineWidth = 1.5
            context.lineCap = "round"
            context.lineJoin = "round"
            context.beginPath()
            context.moveTo(1, 1)
            context.lineTo(5.5, 5.5)
            context.lineTo(10, 1)
            context.stroke()
        }
    }

    background: Rectangle {
        radius: control.uiTheme ? control.uiTheme.radiusSmall : 8
        color: control.surfaceColor
        border.width: 1
        border.color: control.activeFocus ? control.accentColor : control.lineColor
    }

    delegate: ItemDelegate {
        id: optionDelegate
        required property int index
        width: control.width
        height: 36
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: control.textAt(optionDelegate.index)
            color: optionDelegate.highlighted ? control.accentColor : control.inkColor
            font.family: control.font.family
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            leftPadding: 10
            rightPadding: 10
        }
        background: Rectangle {
            radius: 6
            color: optionDelegate.highlighted ? control.accentSoftColor : control.surfaceColor
        }
    }

    popup: Popup {
        y: control.height - 1
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 6, 260)
        padding: 3
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
        background: Rectangle {
            radius: control.uiTheme ? control.uiTheme.radiusSmall : 8
            color: control.surfaceColor
            border.color: control.lineColor
        }
    }
}
