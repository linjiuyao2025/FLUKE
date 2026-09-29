pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: page
    objectName: "archivePage"
    required property var controller
    property var uiTheme: null
    property var onNavigateToSection: null

    property var snapshot: controller ? (controller.state || ({})) : ({})
    property string notice: ""
    readonly property var groups: snapshot.groups || []
    readonly property var summary: snapshot.summary || ({})
    readonly property string activeFilter: String(snapshot.filter || "all")

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
    readonly property color terra: brand
    readonly property color blue: accent
    readonly property color paper: canvas
    readonly property color white: surface
    readonly property string sansFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property string serifFamily: uiTheme ? uiTheme.serifFamily : "Noto Serif SC"
    readonly property string fontFamily: sansFamily

    function dataOf(record) { return record && record.data ? record.data : ({}) }
    function typeLabel(kind) {
        if (kind === "money") return qsTr("财务")
        if (kind === "fitness") return qsTr("健康")
        if (kind === "planner") return qsTr("日程")
        if (kind === "home") return qsTr("待买")
        return qsTr("记录")
    }
    function filterScopeLabel() {
        return activeFilter === "all" ? qsTr("全部记录") : typeLabel(activeFilter) + qsTr("筛选")
    }
    function typeColor(kind) {
        if (kind === "money") return page.plum
        if (kind === "fitness") return page.green
        if (kind === "planner") return page.blue
        return page.terra
    }
    function money(value) {
        var amount = Number(value)
        return "¥" + (isFinite(amount) ? (Math.round(amount * 100) / 100).toFixed(2) : "0.00")
    }
    function recordTitle(record) {
        var data = dataOf(record)
        if (record.type === "money") return String(data.note || data.category || qsTr("一笔收支"))
        if (record.type === "fitness") return String(data.note || qsTr("身体记录"))
        if (record.type === "planner") return String(data.title || qsTr("一项日程"))
        if (record.type === "home") return String(data.name || qsTr("待买物品"))
        return qsTr("生活记录")
    }
    function recordDetail(record) {
        var data = dataOf(record)
        if (record.type === "money") return String(data.category || qsTr("其他")) + " · " + (data.flow === "income" ? qsTr("收入") : qsTr("支出"))
        if (record.type === "fitness") return data.duration ? qsTr("%1 分钟运动").arg(Number(data.duration)) : qsTr("体重记录")
        if (record.type === "planner") return String(data.list || qsTr("生活")) + " · " + String(data.time || qsTr("全天")) + " · " + (data.done ? qsTr("已完成") : qsTr("待完成"))
        if (record.type === "home") return String(data.quantity || qsTr("数量未填")) + " · " + String(data.category || qsTr("未分类")) + " · " + (data.bought ? qsTr("已买") : qsTr("待买", "purchase status"))
        return ""
    }
    function recordValue(record) {
        var data = dataOf(record)
        if (record.type === "money") return (data.flow === "income" ? "+" : "−") + money(data.amount)
        if (record.type === "fitness" && data.weight) return String(data.weight) + " kg"
        if (record.type === "planner") return String(data.time || "")
        if (record.type === "home" && data.price) return money(data.price)
        return ""
    }
    function dateHeading(value) {
        var key = String(value || "")
        if (key === "未标日期") return qsTr("未标日期")
        var parts = key.split("-")
        if (parts.length !== 3) return key || qsTr("未标日期")
        var parsed = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12)
        if (isNaN(parsed.getTime())) return key
        var todayKey = String(page.summary.today || "")
        if (key === todayKey) return qsTr("今天")
        var todayParts = todayKey.split("-")
        if (todayParts.length === 3) {
            var yesterday = new Date(Number(todayParts[0]), Number(todayParts[1]) - 1, Number(todayParts[2]) - 1, 12)
            function pad(number) { return number < 10 ? "0" + number : String(number) }
            var yesterdayKey = String(yesterday.getFullYear()) + "-" + pad(yesterday.getMonth() + 1) + "-" + pad(yesterday.getDate())
            if (key === yesterdayKey) return qsTr("昨天")
        }
        var weekdays = [qsTr("周日"), qsTr("周一"), qsTr("周二"), qsTr("周三"), qsTr("周四"), qsTr("周五"), qsTr("周六")]
        return qsTr("%1 月 %2 日 · %3").arg(Number(parts[1])).arg(Number(parts[2])).arg(weekdays[parsed.getDay()])
    }
    function monthLabel(value) {
        var parts = String(value || "").split("-")
        return parts.length === 2 ? qsTr("%1 年 %2 月").arg(Number(parts[0])).arg(Number(parts[1])) : String(value || qsTr("本月"))
    }
    function selectFilter(value) {
        var result = controller.setFilter(value)
        if (result && typeof result === "object" && result.ok === false)
            notice = String(result.error || qsTr("筛选暂时无法保存。"))
        else
            notice = ""
    }

    Flickable {
        id: archiveScroll
        objectName: "archiveScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: archiveBody.height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: archiveBody
            width: archiveScroll.width
            height: implicitHeight
            spacing: 18
            padding: Math.min(32, Math.max(18, archiveScroll.width * 0.045))

            Row {
                width: parent.width - 48
                height: 46
                spacing: 12
                Text {
                    objectName: "archiveTitle"
                    text: qsTr("时光档案")
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 30
                    font.bold: true
                    width: parent.width - 160
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: qsTr("只读汇总 · 共 %1 条").arg(String(page.snapshot.recordCount || 0))
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Text {
                width: parent.width - 48
        text: page.activeFilter === "all"
                      ? qsTr("当前统计为本月全部记录；下面可按类别筛选并按日期回看各模块内容。")
                      : qsTr("当前为“%1”，上方统计和下方列表使用同一筛选范围。可切换“全部”查看所有记录。")
                          .arg(page.filterScopeLabel())
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
            Text {
                visible: page.notice !== ""
                width: parent.width - 48
                text: qsTr(String(page.notice))
                color: page.terra
                font.family: page.fontFamily
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }

            Row {
                id: monthStats
                objectName: "archiveMonthStats"
                width: parent.width - 48
                height: 100
                spacing: 12
                Repeater {
                    model: 3
                    delegate: Rectangle {
                        id: metricCard
                        required property int index
                        width: (monthStats.width - 16) / 3
                        height: 96
                        radius: 18
                        color: page.white
                        border.color: page.line
                        Text {
                            x: 16; y: 15
                                    text: metricCard.index === 0 ? (page.activeFilter === "all" ? qsTr("本月记录") : qsTr("筛选范围记录")) : metricCard.index === 1 ? qsTr("最常记录") : qsTr("最近七天")
                            color: page.muted; font.family: page.fontFamily; font.pixelSize: 12
                        }
                        Text {
                            x: 16; y: 37
                            width: metricCard.width - 32
                            text: metricCard.index === 0 ? qsTr("%1 条").arg(String(page.summary.recordCount || 0))
                                : metricCard.index === 1 ? qsTr(String(page.summary.favoriteLabel || "—"))
                                : qsTr("%1 条").arg(String(page.summary.recentSevenDayCount || 0))
                            color: page.ink; font.family: page.fontFamily; font.pixelSize: 20; font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            x: 16; y: 69
                            text: metricCard.index === 0 ? qsTr("%1 个日期").arg(String(page.summary.dateCount || 0))
                                : metricCard.index === 1 ? qsTr("%1 条").arg(String(page.summary.favoriteCount || 0))
                                : qsTr("按记录日期统计")
                            color: page.muted; font.family: page.fontFamily; font.pixelSize: 13
                        }
                    }
                }
            }

            Flow {
                id: archiveFilters
                objectName: "archiveFilters"
                width: parent.width - 48
                height: implicitHeight
                spacing: 8
                Repeater {
                    model: [
                        {key: "all", label: qsTr("全部")},
                        {key: "money", label: qsTr("财务")},
                        {key: "fitness", label: qsTr("健康")},
                        {key: "planner", label: qsTr("日程")},
                        {key: "home", label: qsTr("待买")}
                    ]
                    delegate: Button {
                        id: filterButton
                        required property var modelData
                        objectName: "archiveFilter_" + modelData.key
                        text: modelData.label
                        height: 38
                        padding: 13
                        background: Rectangle {
                            radius: 17
                            color: page.activeFilter === filterButton.modelData.key ? page.accentStrong : page.surface
                            border.color: filterButton.activeFocus ? page.ink
                                         : page.activeFilter === filterButton.modelData.key ? page.accentStrong : page.line
                            border.width: filterButton.activeFocus ? 2 : 1
                        }
                        contentItem: Text {
                            text: filterButton.text
                            color: page.activeFilter === filterButton.modelData.key ? page.surface : page.muted
                            font.family: page.fontFamily; font.pixelSize: 12
                            font.bold: page.activeFilter === filterButton.modelData.key
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: page.selectFilter(filterButton.modelData.key)
                    }
                }
            }

            Column {
                id: archiveGroups
                objectName: "archiveGroups"
                width: parent.width - 48
                spacing: 8
                Repeater {
                    model: page.groups
                    delegate: Column {
                        id: dayGroup
                        required property var modelData
                        required property int index
                        property bool expanded: index < 3
                        objectName: "archiveGroup_" + String(modelData.date || "")
                        width: archiveGroups.width
                        spacing: 4
                        Button {
                            id: archiveGroupToggleButton
                            objectName: "archiveGroupToggle_" + String(dayGroup.modelData.date || "")
                            width: dayGroup.width
                            height: 52
                            padding: 14
                            background: Rectangle {
                                radius: 15
                                color: page.white
                                border.color: archiveGroupToggleButton.activeFocus ? page.accentStrong : page.line
                                border.width: archiveGroupToggleButton.activeFocus ? 2 : 1
                            }
                            contentItem: Row {
                                spacing: 8
                                Text { text: dayGroup.expanded ? "−" : "+"; color: page.green; font.family: page.fontFamily; font.pixelSize: 15; width: 16; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: page.dateHeading(dayGroup.modelData.date); color: page.ink; font.family: page.fontFamily; font.pixelSize: 13; font.bold: true; width: parent.width - 120; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight }
                                Text { text: qsTr("%1 条记录").arg(String(dayGroup.modelData.count || 0)); color: page.muted; font.family: page.fontFamily; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                            }
                            onClicked: dayGroup.expanded = !dayGroup.expanded
                        }
                        Column {
                            id: dayRecords
                            objectName: "archiveGroupRows_" + String(dayGroup.modelData.date || "")
                            visible: dayGroup.expanded
                            width: dayGroup.width - 12
                            x: 12
                            spacing: 5
                            Repeater {
                                model: dayGroup.modelData.records || []
                                delegate: Rectangle {
                                    id: archiveRecord
                                    required property var modelData
                                    width: dayRecords.width
                                    height: 76
                                    radius: 14
                                    color: page.white
                                    border.color: page.line
                                    Row {
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 9
                                        Rectangle {
                                            width: 5; height: 34; radius: 3
                                            color: page.typeColor(String(archiveRecord.modelData.type || ""))
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Column {
                                            width: parent.width - 120
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: 2
                                            Text { text: page.recordTitle(archiveRecord.modelData); color: page.ink; font.family: page.fontFamily; font.pixelSize: 12; font.bold: true; width: parent.width; elide: Text.ElideRight }
                                            Text { text: page.typeLabel(String(archiveRecord.modelData.type || "")) + " · " + page.recordDetail(archiveRecord.modelData); color: page.muted; font.family: page.fontFamily; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
                                        }
                                        Text {
                                            text: page.recordValue(archiveRecord.modelData)
                                            color: page.ink; font.family: page.fontFamily; font.pixelSize: 13; font.bold: true
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                Text {
                    objectName: "archiveEmptyState"
                    visible: page.groups.length === 0
                    width: archiveGroups.width
                    height: visible ? (Number(page.snapshot.recordCount || 0) === 0 ? 150 : 112) : 0
                    Rectangle {
                        anchors.fill: parent
                        radius: 16
                        color: page.surface
                        border.color: page.line
                    }
                    Column {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 36, 850)
                        height: parent.height - 36
                        spacing: 8
                        Text {
                            text: Number(page.snapshot.recordCount || 0) === 0
                                  ? qsTr("还没有可回看的记录") : qsTr("当前分类没有记录")
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 15
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: Number(page.snapshot.recordCount || 0) === 0
                                  ? qsTr("时光档案会汇总其他模块的记录。先去记账、记录运动、安排日程或添加待买事项。")
                                  : qsTr("这个分类暂时为空，可以切换筛选，或查看全部记录。")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        Flow {
                            visible: Number(page.snapshot.recordCount || 0) === 0
                            width: parent.width
                            spacing: 8
                            Repeater {
                                model: [
                                    {key: "finance", label: qsTr("去记账"), section: 1},
                                    {key: "fitness", label: qsTr("记录运动"), section: 3},
                                    {key: "planner", label: qsTr("添加日程"), section: 4},
                                    {key: "shopping", label: qsTr("打开待买清单"), section: 5}
                                ]
                                delegate: Button {
                                    id: archiveEmptyModuleButton
                                    required property var modelData
                                    objectName: "archiveEmptyModule_" + modelData.key
                                    text: modelData.label
                                    height: 34
                                    padding: 11
                                    contentItem: Text {
                                        text: archiveEmptyModuleButton.text
                                        color: page.accentStrong
                                        font.family: page.fontFamily
                                        font.pixelSize: 12
                                        font.bold: true
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        radius: 9
                                        color: page.accentSoft
                                        border.color: page.line
                                    }
                                    onClicked: {
                                        if (typeof page.onNavigateToSection === "function")
                                            page.onNavigateToSection(archiveEmptyModuleButton.modelData.section)
                                    }
                                }
                            }
                        }
                        Button {
                            objectName: "archiveEmptyViewAllButton"
                            visible: Number(page.snapshot.recordCount || 0) > 0
                            text: qsTr("查看全部记录")
                            height: 34
                            padding: 11
                            contentItem: Text {
                                text: qsTr("查看全部记录")
                                color: page.accentStrong
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                radius: 9
                                color: page.accentSoft
                                border.color: page.line
                            }
                            onClicked: page.selectFilter("all")
                        }
                    }
                }
            }
            Rectangle {
                objectName: "archiveRecentActivityPanel"
                width: parent.width - 48
                visible: Number(page.summary.recordCount || 0) > 0
                height: visible ? 62 + (page.summary.recentDays && page.summary.recentDays.length ? page.summary.recentDays.length : 0) * 18 : 0
                radius: 18
                color: page.white
                border.color: page.line
                Column {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 8
                    Row {
                        width: parent.width
                        height: 20
                        Text {
                            text: qsTr("最近七天的生活切片")
                            color: page.ink; font.family: page.fontFamily; font.pixelSize: 14; font.bold: true
                            width: parent.width - 8 - Math.min(220, parent.width * 0.58)
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: qsTr("%1 · 最近七天 %2 条").arg(page.monthLabel(page.summary.month)).arg(String(page.summary.recentSevenDayCount || 0))
                            width: Math.min(220, parent.width * 0.58)
                            color: page.muted; font.family: page.fontFamily; font.pixelSize: 13
                            anchors.verticalCenter: parent.verticalCenter
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }
                    }
                    Column {
                        width: parent.width
                        spacing: 3
                        Repeater {
                            model: page.summary.recentDays || []
                            delegate: Row {
                                id: recentDay
                                required property var modelData
                                width: parent.width
                                height: 18
                                spacing: 7
                                Text {
                                    text: String(recentDay.modelData.date || "").slice(5)
                                    color: page.muted; font.family: page.fontFamily; font.pixelSize: 12
                                    width: 42; anchors.verticalCenter: parent.verticalCenter
                                }
                                Rectangle {
                                    width: parent.width - 75
                                    height: 8
                                    radius: 4
                                    color: page.surfaceSoft
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        width: parent.width * Math.min(1, Number(recentDay.modelData.count || 0) / Math.max(1, Number(page.summary.maxRecentDayCount || 1)))
                                        height: parent.height
                                        radius: parent.radius
                                        color: page.green
                                    }
                                }
                                Text {
                                    text: String(recentDay.modelData.count || 0)
                                    color: page.muted; font.family: page.fontFamily; font.pixelSize: 13
                                    width: 19; horizontalAlignment: Text.AlignRight
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 8 }
        }
    }
}
