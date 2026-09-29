pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: root
    required property var migrationController
    required property var weatherController
    required property var newsController
    required property var habitController
    required property var preferencesController
    required property var readingController
    required property var dailyController
    required property var financeController
    required property var backupController
    required property var fitnessController
    required property var plannerController
    property var webdavPlannerController: null
    required property var shoppingController
    required property var mediaController
    required property var archiveController
    required property var converterController
    property var converterEngineController: null
    required property var brandController
    // Older Main.qml harnesses may omit this staged controller; when present,
    // it must expose state.layout and saveLayout(layout).
    property var homeLayoutController: null
    property var cleanupController: null
    property var localeController: null
    property var trayController: null
    property string homeLayoutSaveStatus: ""
    property bool homeLayoutSaveStatusIsError: false
    property var homeLayoutQuestionDeskItem: null
    onHomeLayoutControllerChanged: Qt.callLater(root.applyHomeLayoutVisuals)
    readonly property var homeLayoutCards: [
        { id: "lead", label: qsTr("显示新闻头条") },
        { id: "briefs", label: qsTr("显示新闻快讯") },
        { id: "weekly", label: qsTr("显示我的一周") },
        { id: "recent", label: qsTr("显示近期记录") },
        { id: "question-desk", label: qsTr("显示问题簿") },
        { id: "habits", label: qsTr("显示习惯打卡") },
        { id: "quick", label: qsTr("显示随手记快捷入口") }
    ]
    property bool closeAfterUnsavedNews: false
    property string unsavedNewsCloseError: ""
    UiTheme {
        id: uiTheme
        themeName: root.shownBrand.theme
    }
    visible: true
    width: 1480
    height: 960
    minimumWidth: 760
    minimumHeight: 620
    title: "万象来信"
    onClosing: function(close) {
        if (!root.closeAfterUnsavedNews
                && root.newsController
                && root.newsController.state
                && Boolean(root.newsController.state.draftUnsaved)) {
            close.accepted = false
            root.unsavedNewsCloseError = ""
            newsUnsavedExitDialog.open()
            return
        }
        if (root.closeAfterUnsavedNews)
            root.closeAfterUnsavedNews = false
        if (!root.trayController) return
        const disposition = root.trayController.closeDisposition()
        if (disposition === "hide") {
            close.accepted = false
            root.hide()
        } else if (disposition === "no_tray" || disposition === "error") {
            close.accepted = false
            trayUnavailableDialog.storageError = disposition === "error"
            trayUnavailableDialog.open()
        }
    }
    function finishUnsavedNewsClose(saveDraft) {
        if (saveDraft) {
            const result = root.newsController.saveDraft()
            if (!result || result.ok !== true) {
                root.unsavedNewsCloseError = result && result.error
                        ? String(result.error) : qsTr("草稿没有保存成功，请返回编辑。")
                return
            }
        }
        root.closeAfterUnsavedNews = true
        root.unsavedNewsCloseError = ""
        newsUnsavedExitDialog.close()
        Qt.callLater(function() { root.close() })
    }
    function restoreSavedNewsDraft() {
        const result = root.newsController.restoreSavedDraft()
        if (!result || result.ok !== true) {
            root.unsavedNewsCloseError = result && result.error
                    ? String(result.error) : qsTr("没有可恢复的已保存草稿。")
            return false
        }
        root.unsavedNewsCloseError = ""
        newsUnsavedExitDialog.close()
        return true
    }
    property int currentFlowStep: 0
    readonly property var flowScrollContent: contentScroll.contentItem
    onCurrentSectionIndexChanged: Qt.callLater(root.syncActiveFlowStep)
    color: uiTheme.canvas
    palette.window: uiTheme.canvas
    palette.windowText: uiTheme.ink
    palette.base: uiTheme.surface
    palette.alternateBase: uiTheme.surfaceSoft
    palette.text: uiTheme.ink
    palette.button: uiTheme.surface
    palette.buttonText: uiTheme.ink
    palette.highlight: root.blue
    palette.highlightedText: "#ffffff"
    palette.placeholderText: uiTheme.muted
    palette.light: "#ffffff"
    palette.midlight: uiTheme.surfaceSoft
    palette.mid: uiTheme.controlBorder
    palette.dark: uiTheme.line
    palette.shadow: uiTheme.line

    property bool compactNavigation: width < 940
    property int currentSectionIndex: 0
    property string quickEntryFocusTarget: ""
    property var previewBrand: null
    readonly property var savedBrand: root.brandController ? root.brandController.brand : ({
        name: "万象来信", avatar: "万", avatarImage: "",
        tagline: "把远方与日常，折进今天", theme: "plum"
    })
    readonly property var shownBrand: previewBrand || savedBrand
    property var theme: uiTheme
    property color paper: uiTheme.canvas
    property color sidebarPaper: uiTheme.sidebar
    property color ink: uiTheme.ink
    property color muted: uiTheme.muted
    property color line: uiTheme.line
    property color controlBorder: uiTheme.controlBorder
    property color blue: uiTheme.accent
    property color red: uiTheme.brand
    property color danger: uiTheme.danger
    property color success: uiTheme.success
    property color warning: uiTheme.warning
    property color card: uiTheme.surface
    property string sansFamily: sansFont.status === FontLoader.Ready ? sansFont.name : uiTheme.sansFamily
    property string serifFamily: serifFont.status === FontLoader.Ready ? serifFont.name : uiTheme.serifFamily
    property url sansFontUrl: Qt.resolvedUrl("../../assets/fonts/NotoSansSC-VF.ttf")
    property url serifFontUrl: Qt.resolvedUrl("../../assets/fonts/NotoSerifSC-VF.ttf")
    readonly property bool bundledSansFontReady: sansFont.status === FontLoader.Ready
    readonly property bool bundledSerifFontReady: serifFont.status === FontLoader.Ready
    component RootText: Text {
        font.family: root.sansFamily
    }
    property var migrationReport: null
    property var importedData: root.migrationController.data
    property string migrationNotice: ""
    property bool migrationRestartRequired: false
    property var backupReport: null
    property string backupNotice: ""
    property url pendingEncryptedBackupUrl: ""
    property string cleanupMode: "samples"
    property var cleanupPreview: ({})
    property string cleanupNotice: ""
    property var selectedArticle: ({})
    property string selectedIssueDate: ""
    property string selectedIssueTopic: ""
    property var readingSnapshot: root.readingController.state || ({})
    property var pendingReminders: []
    property var clockDate: new Date()

    function todayLabel() {
        const d = clockDate
        if (root.localeController && root.localeController.language === "en_US") {
            const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return months[d.getMonth()] + " " + d.getDate() + "  ·  " + days[d.getDay()]
        }
        const days = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"]
        return (d.getMonth() + 1) + " 月 " + d.getDate() + " 日  ·  " + days[d.getDay()]
    }

    function issueLabel() {
        const d = clockDate
        const day = Math.floor((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
                                - Date.UTC(d.getFullYear(), 0, 1)) / 86400000) + 1
        if (root.localeController && root.localeController.language === "en_US")
            return "DAILY EDITION  ·  " + d.getFullYear() + "  ·  ISSUE " + day
        return "DAILY EDITION  ·  " + d.getFullYear() + " 年第 " + day + " 期"
    }

    function issueDateLabel() {
        const d = clockDate
        return d.getFullYear() + " · " + String(d.getMonth() + 1).padStart(2, "0")
                + " · " + String(d.getDate()).padStart(2, "0")
    }

    function dailyHabitValue(habit) {
        const state = root.habitController.state || ({})
        const entries = habit && habit.entries ? habit.entries : ({})
        const value = Number(entries[state.today] || 0)
        return isFinite(value) && value > 0 ? value : 0
    }

    function dailyHabitDueToday(habit) {
        const schedule = habit && habit.schedule ? habit.schedule : {}
        if (String(schedule.type || "daily") !== "weekdays")
            return true
        const state = root.habitController.state || {}
        const key = String(state.today || "")
        const parsed = new Date(key + "T12:00:00")
        if (!isFinite(parsed.getTime()))
            return true
        const weekday = parsed.getDay() || 7
        const days = root.listFromVariant(schedule.days)
        return days.indexOf(weekday) >= 0
    }

    function dailyHabitsForToday() {
        const state = root.habitController.state || {}
        const habits = root.listFromVariant(state.habits)
        return habits.filter(function(habit) { return root.dailyHabitDueToday(habit) })
    }

    function dailyHabitTarget(habit) {
        const target = Number(habit && habit.target || 1)
        return isFinite(target) && target > 0 ? target : 1
    }

    function dailyHabitButtonLabel(habit) {
        const type = String(habit && habit.type || "check")
        if (type === "number")
            return qsTr("输入数值")
        if (dailyHabitValue(habit) >= dailyHabitTarget(habit))
            return qsTr("已完成 · 重置")
        return type === "counter" ? qsTr("记录 +1") : qsTr("快速打卡")
    }

    function dailyHabitIsComplete(habit) {
        return String(habit && habit.type || "check") !== "number"
                && dailyHabitValue(habit) >= dailyHabitTarget(habit)
    }

    function activateDailyHabit(habit) {
        if (!habit || !root.habitController)
            return
        const habitId = String(habit.id || "")
        const type = String(habit.type || "check")
        if (type === "number") {
            root.currentSectionIndex = 2
            return
        }
        if (type === "counter" && dailyHabitValue(habit) < dailyHabitTarget(habit))
            root.habitController.adjustCounter(habitId, 1)
        else
            root.habitController.quickCheck(habitId)
    }

    function openQuickEntry(kind) {
        const destinations = { money: 1, fitness: 3, home: 5 }
        if (!Object.prototype.hasOwnProperty.call(destinations, kind))
            return false
        quickEntryFocusTarget = kind
        currentSectionIndex = destinations[kind]
        quickEntryFocusTimer.restart()
        return true
    }

    onShownBrandChanged: title = String(shownBrand.name || "万象来信")

    Timer {
        id: quickEntryFocusTimer
        interval: 200
        repeat: false
        onTriggered: {
            if (root.quickEntryFocusTarget === "money") financePageItem.focusQuickEntry()
            else if (root.quickEntryFocusTarget === "fitness") fitnessPageItem.focusQuickEntry()
            else if (root.quickEntryFocusTarget === "home") shoppingPageItem.focusQuickEntry()
        }
    }

    function showMigrationPreview(fileUrl) {
        const result = root.migrationController.previewPackage(fileUrl)
        if (result.ok) {
            root.migrationReport = result
            migrationPreviewDialog.open()
        } else {
            root.migrationNotice = result.error
            migrationStatusDialog.open()
        }
    }

    function showFullBackupPreview(fileUrl) {
        const result = root.backupController.previewBackup(fileUrl)
        if (result.requiresPassword) {
            root.pendingEncryptedBackupUrl = fileUrl
            encryptedRestorePasswordInput.text = ""
            encryptedRestorePasswordDialog.open()
            return
        }
        if (result.ok) {
            root.backupReport = result
            fullBackupPreviewDialog.open()
        } else {
            root.backupNotice = result.error
            backupStatusDialog.open()
        }
    }

    function exportFullBackup(fileUrl) {
        const result = root.backupController.exportBackup(fileUrl)
        root.backupNotice = result.ok
                ? (result.warning || "本机完整备份已保存。请妥善保管，不要上传到公开仓库。")
                : "备份失败：" + result.error
        backupStatusDialog.open()
    }

    function previewEncryptedFullBackup() {
        const password = encryptedRestorePasswordInput.text
        encryptedRestorePasswordInput.text = ""
        encryptedRestorePasswordDialog.close()
        const result = root.backupController.previewEncryptedBackup(
                    root.pendingEncryptedBackupUrl, password)
        if (result.ok) {
            root.backupReport = result
            fullBackupPreviewDialog.open()
        } else {
            root.backupNotice = qsTr("加密备份无法预览：%1").arg(result.error || qsTr("请检查密码或文件完整性。"))
            backupStatusDialog.open()
        }
        root.pendingEncryptedBackupUrl = ""
    }

    function exportEncryptedFullBackup() {
        const password = encryptedExportPasswordInput.text
        const confirmation = encryptedExportConfirmationInput.text
        encryptedExportPasswordInput.text = ""
        encryptedExportConfirmationInput.text = ""
        encryptedExportPasswordDialog.close()
        if (!password || password !== confirmation) {
            root.backupNotice = password
                    ? qsTr("两次输入的备份密码不一致。")
                    : qsTr("请输入备份密码。")
            backupStatusDialog.open()
            root.pendingEncryptedBackupUrl = ""
            return
        }
        const result = root.backupController.exportEncryptedBackup(
                    root.pendingEncryptedBackupUrl, password)
        root.pendingEncryptedBackupUrl = ""
        root.backupNotice = result.ok
                ? (result.warning || qsTr("密码保护 Native 备份已保存。请妥善保管密码；旧版无法读取此格式。"))
                : qsTr("备份失败：%1").arg(result.error || qsTr("密码保护备份导出失败。"))
        backupStatusDialog.open()
    }

    function openCleanupDialog(mode) {
        if (!root.cleanupController) {
            cleanupNotice = "本机清理功能暂不可用。"
            cleanupStatusDialog.open()
            return
        }
        const preview = mode === "samples"
                ? root.cleanupController.previewSamples()
                : root.cleanupController.previewAll()
        if (!preview.ok) {
            cleanupNotice = "无法预览本机数据：" + (preview.error || "请检查本机数据库。")
            cleanupStatusDialog.open()
            return
        }
        if (mode === "samples"
                && Number(preview.records || 0) === 0
                && Number(preview.media || 0) === 0
                && Number(preview.habits || 0) === 0) {
            cleanupNotice = "当前没有可清理的示例。"
            cleanupStatusDialog.open()
            return
        }
        cleanupMode = mode
        cleanupPreview = preview
        cleanupConfirmDialog.open()
    }

    function confirmCleanup() {
        const result = cleanupMode === "samples"
                ? root.cleanupController.clearSamples()
                : root.cleanupController.clearAll()
        cleanupConfirmDialog.close()
        cleanupNotice = result.ok
                ? (cleanupMode === "samples"
                   ? "已清理 " + Number(result.records || 0) + " 条示例记录、"
                     + Number(result.media || 0) + " 个示例书影音条目和 "
                     + Number(result.habits || 0) + " 个样本习惯。"
                   : "已清空本机记录、书影音和习惯打卡，周计划已恢复默认值；每日一刊历史与草稿已删除。")
                : "本机清理失败：" + (result.error || "所有改动已回滚。")
        cleanupStatusDialog.open()
    }

    function listFromVariant(value) {
        if (value === null || value === undefined) return []
        if (Array.isArray(value)) return value
        if (typeof value !== "object" || typeof value.length !== "number" || value.length < 0)
            return []
        const rows = []
        for (let index = 0; index < value.length; index++) rows.push(value[index])
        return rows
    }

    function homeLayoutCardVisible(cardId) {
        const controller = root.homeLayoutController
        if (!controller || !controller.state) return true
        const layout = controller.state.layout || ({})
        return root.listFromVariant(layout.hidden).indexOf(cardId) < 0
    }

    function homeLayoutDateKey(date) {
        const pad = function(value) { return value < 10 ? "0" + value : String(value) }
        return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
    }

    function homeLayoutWeekStart() {
        const today = new Date()
        today.setHours(12, 0, 0, 0)
        today.setDate(today.getDate() - ((today.getDay() + 6) % 7))
        return homeLayoutDateKey(today)
    }

    function homeLayoutWeekSummary() {
        const today = new Date()
        today.setHours(12, 0, 0, 0)
        const start = new Date(today.getTime())
        start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
        const startKey = root.homeLayoutDateKey(start)
        const keys = []
        const counts = []
        for (let index = 0; index < 7; index++) {
            const day = new Date(start.getTime())
            day.setDate(day.getDate() + index)
            keys.push(root.homeLayoutDateKey(day))
            counts.push(0)
        }
        const addDate = function(value) {
            const index = keys.indexOf(String(value || ""))
            if (index >= 0 && keys[index] <= root.homeLayoutDateKey(today))
                counts[index] += 1
        }
        const archiveGroups = root.listFromVariant((root.archiveController.state || {}).groups)
        for (let groupIndex = 0; groupIndex < archiveGroups.length; groupIndex++) {
            const group = archiveGroups[groupIndex] || ({})
            const rows = root.listFromVariant(group.records)
            for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                const date = String(rows[rowIndex] && rows[rowIndex].date || group.date || "")
                addDate(date)
            }
        }
        const mediaItems = root.listFromVariant((root.mediaController.state || {}).items)
        for (let index = 0; index < mediaItems.length; index++)
            addDate(mediaItems[index] && mediaItems[index].date)
        let habitCheckIns = 0
        const habits = root.listFromVariant((root.habitController.state || {}).habits)
        for (let habitIndex = 0; habitIndex < habits.length; habitIndex++) {
            const entries = habits[habitIndex] && habits[habitIndex].entries || ({})
            for (let index = 0; index < keys.length; index++) {
                const value = Number(entries[keys[index]] || 0)
                if (keys[index] <= root.homeLayoutDateKey(today) && value > 0) {
                    counts[index] += 1
                    habitCheckIns += 1
                }
            }
        }
        let count = 0
        let activeDays = 0
        for (let index = 0; index < counts.length; index++) {
            count += counts[index]
            if (counts[index] > 0) activeDays++
        }
        return {
            start: startKey,
            count: count,
            activeDays: activeDays,
            habitCheckIns: habitCheckIns,
            dayCounts: counts
        }
    }

    function homeLayoutRecentRecords() {
        const today = new Date()
        today.setHours(12, 0, 0, 0)
        const yesterday = new Date(today.getTime())
        yesterday.setDate(yesterday.getDate() - 1)
        const cutoff = root.homeLayoutWeekStart() < root.homeLayoutDateKey(yesterday)
                ? root.homeLayoutWeekStart() : root.homeLayoutDateKey(yesterday)
        const groups = root.listFromVariant((root.archiveController.state || {}).groups)
        const rows = []
        for (let groupIndex = 0; groupIndex < groups.length; groupIndex++) {
            const group = groups[groupIndex] || ({})
            const day = String(group.date || "")
            if (!day || day >= cutoff) continue
            const records = root.listFromVariant(group.records)
            for (let index = 0; index < records.length && rows.length < 5; index++)
                rows.push(records[index])
            if (rows.length >= 5) break
        }
        return rows
    }

    function homeLayoutRecordTitle(record) {
        const data = record && record.data || ({})
        if (record && record.type === "money") return String(data.note || data.category || qsTr("一笔收支"))
        if (record && record.type === "fitness") return String(data.note || qsTr("身体记录"))
        if (record && record.type === "planner") return String(data.title || qsTr("一项日程"))
        if (record && record.type === "home") return String(data.name || qsTr("待买物品"))
        return qsTr("生活记录")
    }

    function saveHomeLayoutCardVisible(cardId, visibleValue) {
        const controller = root.homeLayoutController
        if (!controller || typeof controller.saveLayout !== "function") {
            root.homeLayoutSaveStatus = qsTr("首页布局服务尚未连接。")
            root.homeLayoutSaveStatusIsError = true
            return false
        }

        const source = (controller.state || {}).layout || ({})
        let nextLayout
        try {
            nextLayout = JSON.parse(JSON.stringify(source))
        } catch (error) {
            root.homeLayoutSaveStatus = qsTr("首页布局保存失败，布局数据无法读取。")
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        const hidden = root.listFromVariant(nextLayout.hidden).map(function(item) { return String(item) })
        const existing = hidden.indexOf(cardId)
        if (visibleValue) {
            while (hidden.indexOf(cardId) >= 0)
                hidden.splice(hidden.indexOf(cardId), 1)
        } else if (existing < 0) {
            hidden.push(cardId)
        }
        nextLayout.hidden = hidden
        try {
            const result = controller.saveLayout(nextLayout)
            if (result && result.ok === false) {
                root.homeLayoutSaveStatus = qsTr("首页布局保存失败：%1").arg(
                            String(result.error || qsTr("保存服务未确认成功。")))
                root.homeLayoutSaveStatusIsError = true
                return false
            }
        } catch (error) {
            root.homeLayoutSaveStatus = qsTr("首页布局保存失败：%1").arg(
                        String(error && error.message ? error.message : error))
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        root.homeLayoutSaveStatus = qsTr("首页布局已保存。")
        root.homeLayoutSaveStatusIsError = false
        return true
    }

    function homeLayoutCardPositionIndex(cardId) {
        const order = root.listFromVariant(((root.homeLayoutController || {}).state || {}).layout?.order)
        const index = order.indexOf(cardId)
        return index >= 0 ? index : root.homeLayoutCards.findIndex(function(card) { return card.id === cardId })
    }

    function homeLayoutCardsInSavedOrder() {
        const cards = root.homeLayoutCards.slice()
        cards.sort(function(left, right) {
            return root.homeLayoutCardPositionIndex(left.id) - root.homeLayoutCardPositionIndex(right.id)
        })
        return cards
    }

    function homeLayoutFindItemByObjectName(parentItem, targetName) {
        if (!parentItem) return null
        if (String(parentItem.objectName || "") === targetName) return parentItem
        const children = root.listFromVariant(parentItem.children)
        for (let index = 0; index < children.length; index++) {
            const found = root.homeLayoutFindItemByObjectName(children[index], targetName)
            if (found) return found
        }
        return null
    }

    function homeLayoutItemsForCard(cardId) {
        let card = null
        if (cardId === "lead") card = newsScopeCard
        else if (cardId === "briefs") card = newsCard
        else if (cardId === "weekly") card = dailyWeeklyCardItem
        else if (cardId === "recent") card = dailyRecentCardItem
        else if (cardId === "question-desk") {
            card = root.homeLayoutQuestionDeskItem
                    || root.homeLayoutFindItemByObjectName(dailyFlowPageItem, "dailyQuestionDesk")
            if (card) root.homeLayoutQuestionDeskItem = card
        }
        else if (cardId === "habits") card = dailyHabitQuickChecksItem
        else if (cardId === "quick") card = dailyQuickAddCardItem
        const items = card ? [card] : []
        if (cardId === "briefs") items.push(newsIssueContentHeaderItem)
        return items
    }

    function homeLayoutFlowForSlot(slotId) {
        if (slotId === "flow-briefing-slot") return homeLayoutBriefingCards
        if (slotId === "flow-review-slot") return homeLayoutReviewCards
        return homeLayoutWorkCards
    }

    function homeLayoutSlotHasVisibleCards(slotId) {
        const cards = root.homeLayoutCardsInSavedOrder()
        for (let index = 0; index < cards.length; index++) {
            if (root.homeLayoutCardSlot(cards[index].id) === slotId
                    && root.homeLayoutCardVisible(cards[index].id))
                return true
        }
        return false
    }

    function applyHomeLayoutVisuals() {
        if (!root.homeLayoutController) return false
        if (!homeLayoutParkingLot) return false
        const cards = root.homeLayoutCardsInSavedOrder()
        const cardItems = ({})
        for (let index = 0; index < cards.length; index++) {
            const cardId = cards[index].id
            cardItems[cardId] = root.homeLayoutItemsForCard(cardId)
            const items = cardItems[cardId]
            for (let itemIndex = 0; itemIndex < items.length; itemIndex++)
                items[itemIndex].parent = homeLayoutParkingLot
        }
        for (let index = 0; index < cards.length; index++) {
            const card = cards[index]
            const items = cardItems[card.id]
            const host = root.homeLayoutFlowForSlot(root.homeLayoutCardSlot(card.id))
            for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
                const item = items[itemIndex]
                item.parent = host
                item.width = Qt.binding(function() { return host.width })
                if (card.id === "habits" || card.id === "quick" || card.id === "question-desk")
                    item.height = Qt.binding(function() { return item.implicitHeight })
            }
        }
        return true
    }

    function homeLayoutCardSlot(cardId) {
        const layout = (((root.homeLayoutController || {}).state || {}).layout || ({}))
        const slots = layout.slots || ({})
        return String(slots[cardId] || (cardId === "lead" || cardId === "briefs"
            ? "flow-briefing-slot"
            : (cardId === "weekly" || cardId === "recent" || cardId === "question-desk"
               ? "flow-review-slot" : "flow-work-slot")))
    }

    function homeLayoutSlotOptions(cardId) {
        const slots = [
            { value: "flow-briefing-slot", label: qsTr("今日速览") },
            { value: "flow-review-slot", label: qsTr("昨日回顾") },
            { value: "flow-work-slot", label: qsTr("今日工作") }
        ]
        const current = root.homeLayoutCardSlot(cardId)
        if (!slots.some(function(slot) { return slot.value === current }))
            slots.push({ value: current, label: qsTr("旧版自定义版面") + " · " + current })
        return slots
    }

    function saveHomeLayoutEdit(nextLayout) {
        const controller = root.homeLayoutController
        if (!controller || typeof controller.saveLayout !== "function") {
            root.homeLayoutSaveStatus = qsTr("首页布局服务尚未连接。")
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        try {
            const result = controller.saveLayout(nextLayout)
            if (result && result.ok === false) {
                root.homeLayoutSaveStatus = qsTr("首页布局保存失败：%1").arg(
                            String(result.error || qsTr("保存服务未确认成功。")))
                root.homeLayoutSaveStatusIsError = true
                return false
            }
        } catch (error) {
            root.homeLayoutSaveStatus = qsTr("首页布局保存失败：%1").arg(
                        String(error && error.message ? error.message : error))
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        root.homeLayoutSaveStatus = qsTr("首页布局已保存。")
        root.homeLayoutSaveStatusIsError = false
        return true
    }

    function saveHomeLayoutCardPosition(cardId, position) {
        const layout = (((root.homeLayoutController || {}).state || {}).layout || ({}))
        let nextLayout
        try { nextLayout = JSON.parse(JSON.stringify(layout)) }
        catch (error) {
            root.homeLayoutSaveStatus = qsTr("首页布局保存失败，布局数据无法读取。")
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        const order = root.listFromVariant(nextLayout.order).map(function(item) { return String(item) })
        const oldPosition = order.indexOf(cardId)
        if (oldPosition < 0) return false
        order.splice(oldPosition, 1)
        order.splice(Math.max(0, Math.min(order.length, Number(position) || 0)), 0, cardId)
        nextLayout.order = order
        return root.saveHomeLayoutEdit(nextLayout)
    }

    function saveHomeLayoutCardSlot(cardId, slotId) {
        const layout = (((root.homeLayoutController || {}).state || {}).layout || ({}))
        let nextLayout
        try { nextLayout = JSON.parse(JSON.stringify(layout)) }
        catch (error) {
            root.homeLayoutSaveStatus = qsTr("首页布局保存失败，布局数据无法读取。")
            root.homeLayoutSaveStatusIsError = true
            return false
        }
        nextLayout.slots = nextLayout.slots || ({})
        nextLayout.slots[cardId] = String(slotId)
        return root.saveHomeLayoutEdit(nextLayout)
    }

    function isSelectedArticleClipped() {
        const articleId = selectedArticle && selectedArticle.id ? String(selectedArticle.id) : ""
        if (!articleId || !selectedIssueDate) return false
        const key = selectedIssueDate + "::" + articleId
        const clips = listFromVariant(readingSnapshot.clippings)
        for (let index = 0; index < clips.length; index++)
            if (clips[index] && String(clips[index].key || "") === key) return true
        return false
    }

    function openArticle(article, issue) {
        selectedArticle = article || ({})
        selectedIssueDate = String(issue && issue.date || "")
        selectedIssueTopic = String(issue && issue.topic || "")
        articleDialog.open()
    }

    function showReminders(rows) {
        pendingReminders = listFromVariant(rows)
        if (pendingReminders.length > 0) {
            reminderPopup.open()
            reminderDismissTimer.restart()
        }
    }

    BrandAppearanceDialog {
        id: brandAppearanceDialog
        uiTheme: root.theme
        localeController: root.localeController
        brandStore: root.brandController
        initialBrand: root.savedBrand
        onPreviewChanged: function(brand) { root.previewBrand = brand }
        onAppearanceSaved: function(brand) { root.previewBrand = brand }
    }

    FontLoader {
        id: sansFont
        objectName: "sansFontLoader"
        source: root.sansFontUrl
    }
    FontLoader {
        id: serifFont
        objectName: "serifFontLoader"
        source: root.serifFontUrl
    }
    Timer {
        interval: 60000
        repeat: true
        running: true
        onTriggered: root.clockDate = new Date()
    }

    Item {
        id: homeLayoutParkingLot
        objectName: "homeLayoutParkingLot"
        visible: false
        width: 0
        height: 0
    }

    Component.onCompleted: Qt.callLater(root.applyHomeLayoutVisuals)

    Connections {
        target: root.plannerController
        function onRemindersDue(rows) { root.showReminders(rows) }
    }

    Connections {
        target: root.homeLayoutController
        function onStateChanged() { Qt.callLater(root.applyHomeLayoutVisuals) }
    }

    Dialog {
        id: trayUnavailableDialog
        objectName: "trayUnavailableCloseDialog"
        anchors.centerIn: Overlay.overlay
        modal: true
        width: 420
        title: trayUnavailableDialog.storageError ? qsTr("无法确认提醒状态") : qsTr("仍有待处理提醒")
        property bool storageError: false
        contentItem: RootText {
            text: trayUnavailableDialog.storageError
                  ? qsTr("日程数据暂时无法检查。为避免漏掉提醒，请先保持窗口打开并检查数据。")
                  : qsTr("当前系统无法提供托盘提醒。为避免错过提醒，请保持窗口打开，或仍然退出软件。")
            color: root.ink
            font.family: root.sansFamily
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
        footer: RowLayout {
            spacing: 8
            Button {
                objectName: "trayUnavailableKeepOpenButton"
                text: qsTr("保持打开")
                onClicked: trayUnavailableDialog.reject()
            }
            Button {
                objectName: "trayUnavailableExitButton"
                text: qsTr("仍然退出")
                onClicked: {
                    trayUnavailableDialog.close()
                    if (root.trayController) root.trayController.exitAnyway()
                }
            }
        }
    }

    Dialog {
        id: homeLayoutDialog
        objectName: "homeLayoutDialog"
        anchors.centerIn: Overlay.overlay
        modal: true
        width: Math.min(590, root.width - 36)
        title: qsTr("今日速览布局")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                Layout.fillWidth: true
                text: qsTr("选择要显示的旧版卡片，并编辑顺序与版面槽位。隐藏问题簿不会隐藏昨日回顾。")
                color: root.muted
                font.family: root.sansFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                RootText { text: qsTr("显示卡片"); color: root.muted; font.pixelSize: 11; Layout.fillWidth: true }
                RootText { text: qsTr("顺序"); color: root.muted; font.pixelSize: 11; Layout.preferredWidth: 82 }
                RootText { text: qsTr("旧版版面槽位"); color: root.muted; font.pixelSize: 11; Layout.preferredWidth: 150 }
            }
            Repeater {
                model: root.homeLayoutCardsInSavedOrder()
                delegate: RowLayout {
                    required property var modelData
                    objectName: "homeLayoutCardRow_" + modelData.id
                    Layout.fillWidth: true
                    spacing: 8
                    CheckBox {
                        objectName: modelData.id === "habits" ? "homeLayoutHabitsSwitch"
                                     : modelData.id === "question-desk" ? "homeLayoutQuestionDeskSwitch"
                                     : modelData.id === "quick" ? "homeLayoutQuickSwitch"
                                     : "homeLayoutVisibleSwitch_" + modelData.id
                        text: modelData.label
                        enabled: Boolean(root.homeLayoutController)
                        checked: root.homeLayoutCardVisible(modelData.id)
                        Layout.fillWidth: true
                        onClicked: root.saveHomeLayoutCardVisible(modelData.id, checked)
                    }
                    ComboBox {
                        objectName: "homeLayoutOrder_" + modelData.id
                        enabled: Boolean(root.homeLayoutController)
                        model: ["1", "2", "3", "4", "5", "6", "7"]
                        currentIndex: root.homeLayoutCardPositionIndex(modelData.id)
                        Layout.preferredWidth: 82
                        onActivated: root.saveHomeLayoutCardPosition(modelData.id, index)
                    }
                    ComboBox {
                        objectName: "homeLayoutSlot_" + modelData.id
                        enabled: Boolean(root.homeLayoutController)
                        model: root.homeLayoutSlotOptions(modelData.id)
                        textRole: "label"
                        valueRole: "value"
                        currentValue: root.homeLayoutCardSlot(modelData.id)
                        Layout.preferredWidth: 150
                        onActivated: root.saveHomeLayoutCardSlot(modelData.id, currentValue)
                    }
                }
            }
            RootText {
                objectName: "homeLayoutSaveStatus"
                visible: root.homeLayoutSaveStatus.length > 0
                Layout.fillWidth: true
                text: root.homeLayoutSaveStatus
                color: root.homeLayoutSaveStatusIsError ? root.danger : root.success
                font.family: root.sansFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            RootText {
                visible: !root.homeLayoutController
                Layout.fillWidth: true
                text: qsTr("首页布局服务尚未连接。")
                color: root.warning
                font.family: root.sansFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            Button {
                objectName: "homeLayoutCloseButton"
                text: qsTr("完成")
                onClicked: homeLayoutDialog.close()
            }
        }
    }

    Popup {
        id: reminderPopup
        objectName: "plannerReminderPopup"
        parent: Overlay.overlay
        x: Math.max(16, root.width - width - 24)
        y: 8
        width: Math.min(340, root.width - 32)
        padding: 12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: 12
            color: "#ffffff"
            border.color: root.blue
            border.width: 1
        }
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: qsTr("日程提醒")
                color: root.ink
                font.family: root.sansFamily
                font.pixelSize: 16
                font.bold: true
            }
            Repeater {
                model: root.pendingReminders
                delegate: ColumnLayout {
                    id: reminderItem
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 2
                    RootText {
                        text: String(reminderItem.modelData.title || qsTr("日程提醒"))
                        color: root.ink
                        font.family: root.sansFamily
                        font.pixelSize: 13
                        font.bold: true
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    RootText {
                        text: String(reminderItem.modelData.body || qsTr("该处理这件日程了。"))
                        color: root.muted
                        font.family: root.sansFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }
            Timer {
                id: reminderDismissTimer
                interval: 12000
                repeat: false
                onTriggered: reminderPopup.close()
            }
        }
        onClosed: reminderDismissTimer.stop()
        onOpened: root.plannerController.sendSystemNotifications(root.pendingReminders)
    }

    component NewsActionButton: Button {
        id: newsAction
        implicitHeight: uiTheme.controlHeight
        leftPadding: 12
        rightPadding: 12
        topPadding: 6
        bottomPadding: 6
        contentItem: RootText {
            text: newsAction.text
            color: !newsAction.enabled ? root.muted : (newsAction.highlighted ? "#ffffff" : root.ink)
            font.family: root.sansFamily
            font.pixelSize: 12
            font.bold: newsAction.highlighted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: uiTheme.radiusSmall
            color: !newsAction.enabled ? "#f0f2f3"
                  : newsAction.highlighted ? (newsAction.down ? uiTheme.accentStrong : root.blue)
                  : newsAction.down ? "#eef2fb" : "#ffffff"
            border.color: newsAction.activeFocus ? root.blue : (newsAction.highlighted ? root.blue : uiTheme.controlBorder)
        }
    }

    component NewsCheckBox: CheckBox {
        id: newsCheckBox
        spacing: 8
        padding: 5
        leftPadding: 8
        rightPadding: 8
        contentItem: RootText {
            text: newsCheckBox.text
            color: newsCheckBox.enabled ? root.ink : root.muted
            font.family: root.sansFamily
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Rectangle {
            implicitWidth: 18
            implicitHeight: 18
            x: newsCheckBox.leftPadding
            y: newsCheckBox.topPadding + (newsCheckBox.availableHeight - height) / 2
            radius: 4
            color: newsCheckBox.checked ? root.blue : "#ffffff"
            border.color: newsCheckBox.activeFocus ? root.blue : uiTheme.controlBorder
            RootText {
                anchors.centerIn: parent
                text: "✓"
                color: "#ffffff"
                font.pixelSize: 12
                font.bold: true
                visible: newsCheckBox.checked
            }
        }
        background: Rectangle {
            color: "#ffffff"
            border.color: newsCheckBox.activeFocus ? root.blue : uiTheme.controlBorder
            radius: 5
        }
    }

    component NewsHistoryComboBox: ComboBox {
        id: newsHistory
        implicitHeight: 36
        leftPadding: 9
        rightPadding: 29
        contentItem: RootText {
            leftPadding: newsHistory.leftPadding
            rightPadding: newsHistory.rightPadding
            text: newsHistory.displayText
            color: newsHistory.enabled ? root.ink : root.muted
            font.family: root.sansFamily
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Canvas {
            x: newsHistory.width - width - newsHistory.rightPadding / 2
            y: newsHistory.topPadding + (newsHistory.availableHeight - height) / 2 - 2
            width: 11
            height: 7
            property color chevronColor: newsHistory.activeFocus ? root.blue : root.muted
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
            color: "#ffffff"
            border.color: newsHistory.activeFocus ? root.blue : uiTheme.controlBorder
            radius: uiTheme.radiusSmall
        }
        delegate: ItemDelegate {
            id: newsHistoryDelegate
            required property var modelData
            width: newsHistory.width
            height: 34
            text: String(modelData)
            contentItem: RootText {
                text: newsHistoryDelegate.text
                color: newsHistoryDelegate.highlighted ? root.blue : root.ink
                font.family: root.sansFamily
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                leftPadding: 9
                rightPadding: 9
            }
            background: Rectangle {
                color: newsHistoryDelegate.highlighted ? "#eaf0fc" : "#ffffff"
            }
        }
        popup: Popup {
            y: newsHistory.height - 1
            width: newsHistory.width
            implicitHeight: Math.min(contentItem.implicitHeight + 2, 300)
            padding: 1
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: newsHistory.popup.visible ? newsHistory.delegateModel : null
                currentIndex: newsHistory.highlightedIndex
                ScrollIndicator.vertical: ScrollIndicator { }
            }
            background: Rectangle {
                color: "#ffffff"
                border.color: "#cfd9de"
                radius: 5
            }
        }
    }

    FileDialog {
        id: migrationFileDialog
        objectName: "migrationFileDialog"
        title: qsTr("选择旧版迁移包")
        nameFilters: [qsTr("旧版数据迁移包 (*.json)"), qsTr("JSON 文件 (*.json)")]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            root.showMigrationPreview(selectedFile)
        }
    }

    FileDialog {
        id: fullBackupSaveDialog
        objectName: "fullBackupSaveDialog"
        title: qsTr("导出本机完整备份")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "wxbak"
        nameFilters: [qsTr("新版完整备份 (*.wxbak)")]
        onAccepted: {
            root.exportFullBackup(selectedFile)
        }
    }

    FileDialog {
        id: fullBackupOpenDialog
        objectName: "fullBackupOpenDialog"
        title: qsTr("选择本机完整备份")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Native 密码保护备份 (*.wxbak2)"),
                      qsTr("旧版密码保护备份 (*.wxbackup)"),
                      qsTr("新版完整备份 (*.wxbak)"),
                      qsTr("旧版完整备份 JSON (*.json)")]
        onAccepted: {
            root.showFullBackupPreview(selectedFile)
        }
    }

    FileDialog {
        id: encryptedBackupSaveDialog
        objectName: "encryptedBackupSaveDialog"
        title: qsTr("导出密码保护 Native 备份")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "wxbak2"
        nameFilters: [qsTr("Native 密码保护备份 (*.wxbak2)")]
        onAccepted: {
            root.pendingEncryptedBackupUrl = selectedFile
            encryptedExportPasswordInput.text = ""
            encryptedExportConfirmationInput.text = ""
            encryptedExportPasswordDialog.open()
        }
        onRejected: root.pendingEncryptedBackupUrl = ""
    }

    Dialog {
        id: encryptedExportPasswordDialog
        objectName: "encryptedExportPasswordDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, root.width - 36)
        title: qsTr("设置备份密码")
        onOpened: {
            encryptedExportPasswordInput.text = ""
            encryptedExportConfirmationInput.text = ""
        }
        onClosed: {
            encryptedExportPasswordInput.text = ""
            encryptedExportConfirmationInput.text = ""
        }
        onRejected: root.pendingEncryptedBackupUrl = ""
        contentItem: ColumnLayout {
            spacing: 10
            RootText {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("Native 密码保护备份采用独立 .wxbak2 格式；旧版软件不能读取。密码只在本次导出时使用，不会保存。")
                color: root.muted
            }
            TextField {
                id: encryptedExportPasswordInput
                objectName: "encryptedExportPasswordInput"
                Layout.fillWidth: true
                placeholderText: qsTr("输入备份密码")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData
            }
            TextField {
                id: encryptedExportConfirmationInput
                objectName: "encryptedExportConfirmationInput"
                Layout.fillWidth: true
                placeholderText: qsTr("再次输入备份密码")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData
            }
        }
        footer: RowLayout {
            Button {
                objectName: "encryptedExportCancelButton"
                text: qsTr("取消")
                onClicked: {
                    root.pendingEncryptedBackupUrl = ""
                    encryptedExportPasswordDialog.close()
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "encryptedExportConfirmButton"
                text: qsTr("导出加密备份")
                onClicked: root.exportEncryptedFullBackup()
            }
        }
    }

    Dialog {
        id: encryptedRestorePasswordDialog
        objectName: "encryptedRestorePasswordDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(430, root.width - 36)
        title: qsTr("输入备份密码")
        onOpened: encryptedRestorePasswordInput.text = ""
        onClosed: encryptedRestorePasswordInput.text = ""
        onRejected: {
            root.backupController.cancelPreview()
            root.pendingEncryptedBackupUrl = ""
        }
        contentItem: ColumnLayout {
            spacing: 10
            RootText {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("密码只在本次恢复预览期间暂存在内存中；取消预览或完成恢复后会清除。")
                color: root.muted
            }
            TextField {
                id: encryptedRestorePasswordInput
                objectName: "encryptedRestorePasswordInput"
                Layout.fillWidth: true
                placeholderText: qsTr("备份密码")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData
            }
        }
        footer: RowLayout {
            Button {
                objectName: "encryptedRestoreCancelButton"
                text: qsTr("取消")
                onClicked: {
                    root.backupController.cancelPreview()
                    root.pendingEncryptedBackupUrl = ""
                    encryptedRestorePasswordDialog.close()
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "encryptedRestoreContinueButton"
                text: qsTr("解密并预览")
                onClicked: root.previewEncryptedFullBackup()
            }
        }
    }

    Dialog {
        id: dataToolsDialog
        objectName: "dataToolsDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(500, root.width - 36)
        title: qsTr("备份与数据")
        contentItem: ColumnLayout {
            spacing: 10
            RootText {
                text: qsTr("可导出普通或密码保护的 Native 完整备份，也可恢复旧版 JSON 与 .wxbackup 加密备份。密码保护的 Native 文件使用独立 .wxbak2 格式，旧版软件无法读取。备份可能含个人数据，请妥善保管。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Button {
                text: qsTr("导出本机完整备份")
                Layout.fillWidth: true
                onClicked: {
                    dataToolsDialog.close()
                    fullBackupSaveDialog.open()
                }
            }
            Button {
                objectName: "exportEncryptedBackupButton"
                text: qsTr("导出密码保护备份…")
                Layout.fillWidth: true
                onClicked: {
                    dataToolsDialog.close()
                    encryptedBackupSaveDialog.open()
                }
            }
            Button {
                text: qsTr("恢复本机完整备份")
                Layout.fillWidth: true
                onClicked: {
                    dataToolsDialog.close()
                    fullBackupOpenDialog.open()
                }
            }
            Button {
                text: qsTr("导入旧版迁移包")
                Layout.fillWidth: true
                onClicked: {
                    dataToolsDialog.close()
                    migrationFileDialog.open()
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: root.line
            }
            RootText {
                text: qsTr("清理本机数据")
                color: root.ink
                font.bold: true
                Layout.fillWidth: true
            }
            RootText {
                text: qsTr("示例清理只移除示例记录，不会删除你添加的内容；全部清空则会另行确认范围。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Button {
                objectName: "clearSamplesButton"
                text: qsTr("清理示例数据…")
                Layout.fillWidth: true
                onClicked: {
                    dataToolsDialog.close()
                    root.openCleanupDialog("samples")
                }
            }
            Button {
                objectName: "clearAllDataButton"
                text: qsTr("清空全部本机数据…")
                Layout.fillWidth: true
                palette.button: root.red
                palette.buttonText: "#ffffff"
                onClicked: {
                    dataToolsDialog.close()
                    root.openCleanupDialog("all")
                }
            }
        }
        footer: Button {
            text: qsTr("关闭")
            onClicked: dataToolsDialog.close()
        }
    }

    Dialog {
        id: cleanupConfirmDialog
        objectName: "cleanupConfirmDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(520, root.width - 36)
        title: root.cleanupMode === "samples" ? qsTr("清理示例数据") : qsTr("清空全部本机数据")
        contentItem: ColumnLayout {
            spacing: 12
            RootText {
                objectName: "cleanupConfirmText"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: root.ink
                text: root.cleanupMode === "samples"
                      ? qsTr("将清除 %1 条示例记录、%2 个示例书影音条目，以及 %3 个样本习惯的打卡历史。你添加的内容、习惯定义和周计划会保留。")
                            .arg(Number(root.cleanupPreview.records || 0))
                            .arg(Number(root.cleanupPreview.media || 0))
                            .arg(Number(root.cleanupPreview.habits || 0))
                        + "\n\n" + qsTr("只修改本机 SQLite；不影响云端账户数据、旧版数据或迁移原件。")
                      : qsTr("将清空 %1 条本机记录、%2 个本机书影音条目和所有习惯打卡历史，并将周计划恢复默认值；删除每日一刊活动内容、历史和草稿。")
                            .arg(Number(root.cleanupPreview.records || 0))
                            .arg(Number(root.cleanupPreview.media || 0))
                        + "\n\n" + qsTr("保留版面、问题簿、关注主题与媒体偏好、剪报、已存知识、品牌主题及其他独立本机设置。")
                        + "\n\n" + qsTr("只修改本机 SQLite；不影响云端账户数据、旧版数据或迁移原件。")
            }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            Button {
                objectName: "cleanupCancelButton"
                text: qsTr("取消")
                onClicked: cleanupConfirmDialog.close()
            }
            Button {
                objectName: "cleanupConfirmButton"
                text: root.cleanupMode === "samples" ? qsTr("确认清理示例") : qsTr("确认清空本机数据")
                palette.button: root.red
                palette.buttonText: "#ffffff"
                onClicked: root.confirmCleanup()
            }
        }
    }

    Dialog {
        id: cleanupStatusDialog
        objectName: "cleanupStatusDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(460, root.width - 36)
        title: qsTr("本机数据清理")
        contentItem: RootText {
            objectName: "cleanupStatusText"
            text: root.cleanupNotice
            color: root.ink
            wrapMode: Text.WordWrap
        }
        footer: Button {
            objectName: "cleanupStatusCloseButton"
            text: qsTr("关闭")
            onClicked: cleanupStatusDialog.close()
        }
    }

    Dialog {
        id: fullBackupPreviewDialog
        objectName: "fullBackupPreviewDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(470, root.width - 36)
        title: qsTr("核对完整备份")
        onClosed: root.backupController.cancelPreview()
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: qsTr("导出时间：%1").arg(String(root.backupReport ? root.backupReport.exportedAt : ""))
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                objectName: "fullBackupPreviewSummary"
                text: {
                    const report = root.backupReport || ({})
                    const summary = report.summary || ({})
                    const legacy = summary.legacy || ({})
                    const sourceFormat = report.sourceFormat || ""
                    const isLegacy = sourceFormat.indexOf("daily-atlas-backup-v1") === 0
                    let label = qsTr("数据表 %1").arg(String(summary.tables || 0))
                    if (isLegacy) {
                        label = sourceFormat.indexOf("encrypted") >= 0
                                ? qsTr("旧版密码保护完整备份")
                                : qsTr("旧版完整备份")
                    } else if (sourceFormat.indexOf("encrypted-v2") >= 0) {
                        label = qsTr("Native 密码保护完整备份")
                    }
                    const databaseSize = String(
                                Math.round(Number(report.databaseBytes || 0) / 1024))
                    if (!isLegacy) {
                        return label + qsTr(" · 完整本机数据库约 %1 KB").arg(databaseSize)
                    }
                    return label + qsTr(" · 旧记录 %1 · 习惯 %2 · 书影音 %3 · 文件约 %4 KB")
                            .arg(String(legacy.records || 0))
                            .arg(String(legacy.habits || 0))
                            .arg(String(legacy.media_items || 0))
                            .arg(databaseSize)
                }
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: (root.backupReport
                       && String(root.backupReport.sourceFormat || "").indexOf("daily-atlas-backup-v1") === 0
                       ? qsTr("旧版备份将替换生活记录和刊期内容；本机独立设置及新闻问题簿会保留，依附旧记录的新版模块覆盖会清除。")
                       : qsTr("恢复会完整替换当前本机数据库。"))
                       + qsTr("确认后应用会自动关闭并重新打开；执行前会再次核验文件，取消不会更改数据库。")
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            Button {
                objectName: "backupPreviewCancelButton"
                text: qsTr("取消")
                onClicked: {
                    root.backupController.cancelPreview()
                    fullBackupPreviewDialog.close()
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "backupPreviewConfirmButton"
                text: qsTr("确认恢复并重启")
                onClicked: {
                    const result = root.backupController.applyPreview()
                    fullBackupPreviewDialog.close()
                    if (!result.ok) {
                        root.backupNotice = qsTr("恢复失败；当前数据库未替换：%1").arg(result.error)
                        backupStatusDialog.open()
                    }
                }
            }
        }
    }

    Dialog {
        id: backupStatusDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, root.width - 36)
        title: qsTr("备份与恢复")
        contentItem: RootText {
            text: root.backupNotice
            color: root.ink
            wrapMode: Text.WordWrap
        }
        footer: Button {
            text: qsTr("确定")
            onClicked: backupStatusDialog.close()
        }
    }

    Dialog {
        id: migrationPreviewDialog
        objectName: "migrationPreviewDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(470, root.width - 36)
        title: qsTr("导入旧版数据")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: qsTr("请核对数量后再导入。该操作只写入新版独立数据库，不改动旧版数据。")
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: {
                    const s = root.migrationReport ? root.migrationReport.summary : {}
                    return qsTr("存储键 %1/%2 · 记录 %3 · 习惯 %4 · 书影音 %5")
                            .arg(s.keys_present || 0)
                            .arg(s.keys_total || 0)
                            .arg(s.records || 0)
                            .arg(s.habits || 0)
                            .arg(s.media_items || 0)
                }
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: {
                    const s = root.migrationReport ? root.migrationReport.summary : {}
                    return qsTr("新闻刊期 %1 · 问题簿 %2 · 关注主题 %3 · 剪报 %4")
                            .arg((s.active_issue || 0) + (s.archived_issues || 0))
                            .arg(s.questions || 0)
                            .arg(s.topics || 0)
                            .arg(s.clippings || 0)
                }
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                objectName: "migrationRevisionNotice"
                visible: Boolean(root.migrationReport
                                 && root.migrationReport.status === "new_snapshot")
                text: qsTr("检测到同一旧版来源的新快照。确认后保留历史快照和本机模块修改，并切换当前数据。")
                color: root.blue
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                objectName: "migrationHistoricalNotice"
                visible: Boolean(root.migrationReport
                                 && root.migrationReport.preview
                                 && root.migrationReport.preview.historicalInactive)
                text: qsTr("这份快照已保存在历史记录中，但不是当前快照。为避免意外回退，不能再次切换它。请从旧版导出当前数据。")
                color: root.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                objectName: "migrationDiffSummary"
                visible: Boolean(root.migrationReport
                                 && root.migrationReport.status === "new_snapshot")
                text: {
                    const preview = root.migrationReport ? root.migrationReport.preview : ({})
                    const keys = preview.keyChangeCounts || ({})
                    const entities = preview.entityChanges || ({})
                    const records = entities.records || ({})
                    const habits = entities.habits || ({})
                    const media = entities.media_items || ({})
                    return qsTr("存储键变化：新增 %1 · 修改 %2 · 移除 %3 · 未变 %4")
                            .arg(keys.added || 0)
                            .arg(keys.changed || 0)
                            .arg(keys.removed || 0)
                            .arg(keys.unchanged || 0)
                            + "\n"
                            + qsTr("记录变化：新增 %1 · 修改 %2 · 移除 %3")
                                    .arg(records.added || 0)
                                    .arg(records.changed || 0)
                                    .arg(records.removed || 0)
                            + "\n"
                            + qsTr("习惯变化：新增 %1 · 修改 %2 · 移除 %3")
                                    .arg(habits.added || 0)
                                    .arg(habits.changed || 0)
                                    .arg(habits.removed || 0)
                            + "\n"
                            + qsTr("书影音变化：新增 %1 · 修改 %2 · 移除 %3")
                                    .arg(media.added || 0)
                                    .arg(media.changed || 0)
                                    .arg(media.removed || 0)
                }
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: root.migrationReport
                      ? qsTr("SHA-256：%1…").arg(root.migrationReport.checksum.slice(0, 16))
                      : ""
                color: root.muted
                font.pixelSize: 12
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            spacing: 10
            Button {
                objectName: "migrationPreviewCancelButton"
                text: qsTr("取消")
                onClicked: {
                    root.migrationController.cancelPreview()
                    migrationPreviewDialog.close()
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "migrationPreviewConfirmButton"
                enabled: !root.migrationReport
                         || !root.migrationReport.preview
                         || root.migrationReport.preview.canApply !== false
                text: root.migrationReport && root.migrationReport.status === "new_snapshot"
                      ? qsTr("确认切换到新快照") : qsTr("确认导入")
                onClicked: {
                    const result = root.migrationController.applyPreview()
                    root.migrationRestartRequired = Boolean(
                                result.ok && result.status === "imported" && result.isActive)
                    root.migrationNotice = !result.ok
                            ? qsTr("导入失败：%1").arg(qsTr(result.error))
                            : (result.status === "already_imported"
                               ? qsTr("这份迁移包已导入过，没有重复写入。")
                               : (root.migrationReport.status === "new_snapshot"
                                  ? qsTr("新快照已设为当前数据，历史快照和本机模块修改均已保留。请重新打开软件以载入更新后的数据。")
                                  : qsTr("导入成功。请重新打开软件以载入所有模块的数据。")))
                    migrationPreviewDialog.close()
                    migrationStatusDialog.open()
                }
            }
        }
    }

    Dialog {
        id: migrationStatusDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(430, root.width - 36)
        title: qsTr("数据迁移")
        contentItem: RootText {
            text: root.migrationNotice
            color: root.ink
            wrapMode: Text.WordWrap
        }
        footer: Button {
            objectName: "migrationStatusConfirmButton"
            text: root.migrationRestartRequired ? qsTr("重新打开软件") : qsTr("确定")
            onClicked: {
                if (root.migrationRestartRequired)
                    root.migrationController.restartApplication()
                else
                    migrationStatusDialog.close()
            }
        }
    }

    ArticleDialog {
        id: articleDialog
        uiTheme: root.theme
        article: root.selectedArticle
        date: root.selectedIssueDate
        topic: root.selectedIssueTopic
        savedKnowledgeEnabled: Boolean(root.readingSnapshot.savedKnowledge)
        articleClipped: root.isSelectedArticleClipped()
        feedbackAction: {
            const state = root.newsController.state || ({})
            const feedback = state.recommendationFeedback || ({})
            const id = root.selectedArticle && root.selectedArticle.id
                    ? String(root.selectedArticle.id) : ""
            return feedback[root.selectedIssueDate + "::" + id] || ""
        }
        feedbackAvailable: !Boolean((root.newsController.state || ({})).recommendationError)
        onOpenExternalLinkRequested: function(url) { Qt.openUrlExternally(url) }
        onSavedKnowledgeToggleRequested: function(enabled) {
            const result = root.readingController.setSavedKnowledge(enabled)
            newsCard.showResult(result, enabled ? "全局稍后读功能已开启。" : "全局稍后读功能已关闭。")
        }
        onClippingToggleRequested: function(article, issueDate, topic) {
            const result = root.readingController.toggleClipping(article, issueDate, topic)
            newsCard.showResult(result, result && result.saved ? "已收进本期剪报。" : "已从本期剪报移出。")
        }
        onFeedbackRequested: function(article, issueDate, action) {
            const result = root.newsController.setArticleFeedback(article, issueDate, action)
            newsCard.showResult(result, action ? "文章反馈已保存到本机。" : "已撤销这条文章反馈。")
        }
    }

    Dialog {
        id: clippingsDialog
        objectName: "clippingsDialog"
        title: qsTr("我的新闻剪报")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(620, (Overlay.overlay ? Overlay.overlay.width : root.width) - 32)
        height: Math.min(660, (Overlay.overlay ? Overlay.overlay.height : root.height) - 32)
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: qsTr("本机保存的报道快照 · %1 / 80").arg(root.listFromVariant(root.readingSnapshot.clippings).length)
                color: root.muted
                font.family: root.sansFamily
                font.pixelSize: 12
                Layout.fillWidth: true
            }
            ScrollView {
                id: clippingsScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                ColumnLayout {
                    width: clippingsScroll.availableWidth
                    spacing: 7
                    RootText {
                        visible: root.listFromVariant(root.readingSnapshot.clippings).length === 0
                        text: qsTr("还没有收进剪报的报道。")
                        color: root.muted
                        font.family: root.sansFamily
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: root.listFromVariant(root.readingSnapshot.clippings)
                        delegate: Rectangle {
                            id: clippingRow
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            implicitHeight: clippingContent.implicitHeight + 18
                            color: "#fbfcfd"
                            border.color: root.line
                            ColumnLayout {
                                id: clippingContent
                                anchors.fill: parent
                                anchors.margins: 9
                                spacing: 5
                                RootText {
                                    text: String(clippingRow.modelData.date || "") + " · "
                                          + String(clippingRow.modelData.topic || clippingRow.modelData.item.label || qsTr("来信剪报"))
                                    color: root.red
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                    Layout.fillWidth: true
                                }
                                RootText {
                                    text: String(clippingRow.modelData.item.title || qsTr("未命名报道"))
                                    color: root.ink
                                    font.family: root.serifFamily
                                    font.pixelSize: 14
                                    font.bold: true
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                RootText {
                                    text: String(clippingRow.modelData.item.summary || "")
                                    visible: text.length > 0
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Item { Layout.fillWidth: true }
                                    NewsActionButton {
                                        objectName: "clippingOpen_" + clippingRow.index
                                        text: qsTr("阅读全文")
                                        onClicked: root.openArticle(
                                                       clippingRow.modelData.item,
                                                       { date: clippingRow.modelData.date, topic: clippingRow.modelData.topic })
                                    }
                                    NewsActionButton {
                                        objectName: "clippingRemove_" + clippingRow.index
                                        text: qsTr("移出剪报")
                                        onClicked: newsCard.showResult(
                                                       root.readingController.removeClipping(String(clippingRow.modelData.key || "")),
                                                       "已从剪报中移出。")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton { text: qsTr("关闭"); onClicked: clippingsDialog.close() }
        }
        background: Rectangle { color: "#ffffff"; border.color: root.line; radius: 9 }
    }

    PreferencesDialog {
        id: preferencesDialog
        uiTheme: root.theme
        initialState: root.preferencesController.state
        topicOptions: root.preferencesController.topicOptions
        presetSourceOptions: root.preferencesController.presetSourceOptions
        onSaveRequested: function(state) {
            const result = root.preferencesController.save(state.topics, state.preferences)
            if (result && result.ok) {
                preferencesDialog.saveError = ""
                newsCard.showResult(result, "关注方向已保存。")
            } else {
                preferencesDialog.saveError = result && result.error
                        ? String(result.error) : qsTr("关注方向保存失败，请重试。")
            }
        }
    }

    FileDialog {
        id: newsFileDialog
        objectName: "newsFileDialog"
        title: qsTr("选择本机新闻 JSON 文件")
        nameFilters: [qsTr("JSON 文件 (*.json)")]
        fileMode: FileDialog.OpenFile
        onAccepted: newsCard.requestPreviewFile(selectedFile)
    }

    FileDialog {
        id: newsExportDialog
        objectName: "newsExportDialog"
        title: qsTr("导出已发布的本期刊物")
        nameFilters: [qsTr("JSON 文件 (*.json)")]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        onAccepted: newsCard.showResult(root.newsController.exportActiveIssue(selectedFile), "本期 JSON 已导出到所选位置。")
    }

    Dialog {
        id: newsJsonDialog
        objectName: "newsJsonDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(700, root.width - 36)
        title: qsTr("粘贴或编辑新闻 JSON")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                objectName: "newsJsonInstruction"
                text: newsCard.draftIssue
                      ? qsTr("当前草稿已载入文本框。修改后请先预览，再选择保存草稿或发布。")
                      : qsTr("粘贴新闻 JSON 后先预览；预览不会直接发布。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                visible: newsCard.noticeIsError
                text: qsTr(newsCard.notice)
                color: root.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            TextArea {
                id: newsJsonEditor
                objectName: "newsJsonInput"
                Accessible.name: qsTr("新闻 JSON 内容")
                Accessible.description: placeholderText
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(390, root.height * 0.52)
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font.family: "Consolas"
                font.pixelSize: 12
                placeholderText: qsTr("粘贴包含 version、date、topic、focus 和 highlights 的 JSON 内容包。")
                background: Rectangle {
                    color: "#fbfcfd"
                    border.color: newsJsonEditor.activeFocus ? root.blue : root.controlBorder
                    radius: 5
                }
            }
        }
        footer: RowLayout {
            spacing: 8
            NewsActionButton {
                text: qsTr("打开 JSON 文件")
                onClicked: {
                    newsJsonDialog.close()
                    newsFileDialog.open()
                }
            }
            Item { Layout.fillWidth: true }
            NewsActionButton {
                text: qsTr("关闭")
                onClicked: newsJsonDialog.close()
            }
            NewsActionButton {
                objectName: "newsPreviewButton"
                text: qsTr("校验并预览")
                highlighted: true
                onClicked: newsCard.previewJsonText(newsJsonEditor.text)
            }
        }
    }

    Dialog {
        id: newsPreviewDialog
        objectName: "newsPreviewDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(760, root.width - 36)
        height: Math.min(720, root.height - 40)
        title: qsTr("新闻刊期预览")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: newsCard.previewIssue
                      ? ((newsCard.previewIssue.date || qsTr("日期待定")) + " · "
                         + (newsCard.previewIssue.topic || qsTr("未命名主题")))
                      : qsTr("没有可显示的预览内容。")
                color: root.ink
                font.family: root.serifFamily
                font.pixelSize: 17
                font.bold: true
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                objectName: "newsPreviewSafetyNote"
                text: qsTr("这是未发布的预览。关闭窗口不会保存；保存草稿或发布都需要你明确点击对应按钮。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                visible: newsCard.noticeIsError
                text: qsTr(newsCard.notice)
                color: root.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            ScrollView {
                id: newsPreviewScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ColumnLayout {
                    width: newsPreviewScroll.availableWidth
                    spacing: 10
                    RootText {
                        visible: Boolean(newsCard.previewIssue && newsCard.previewIssue.editorNote)
                        text: newsCard.previewIssue ? (newsCard.previewIssue.editorNote || "") : ""
                        color: root.muted
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: newsCard.orderedGroups()
                        delegate: ColumnLayout {
                            id: newsPreviewGroup
                            required property var modelData
                            property var previewItems: newsCard.itemsFor(newsCard.previewIssue, modelData.key)
                            visible: previewItems.length > 0 && !newsCard.isGroupHidden(modelData.key)
                            Layout.fillWidth: true
                            spacing: 5
                            RootText {
                                text: qsTr("%1 · %2 条").arg(newsPreviewGroup.modelData.label).arg(newsPreviewGroup.previewItems.length)
                                color: root.red
                                font.family: root.sansFamily
                                font.pixelSize: 12
                                font.bold: true
                                Layout.fillWidth: true
                            }
                            Repeater {
                                model: newsPreviewGroup.previewItems
                                delegate: Rectangle {
                                    id: newsPreviewArticle
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: previewCopy.implicitHeight + 18
                                    color: "#f8fafb"
                                    border.color: root.line
                                    ColumnLayout {
                                        id: previewCopy
                                        anchors.fill: parent
                                        anchors.margins: 9
                                        spacing: 4
                                        RootText {
                                            objectName: "newsPreviewTitle_" + newsPreviewArticle.modelData.id
                                            text: newsCard.itemTitle(newsPreviewArticle.modelData)
                                            color: root.ink
                                            font.family: root.sansFamily
                                            font.pixelSize: 13
                                            font.bold: true
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            objectName: "newsPreviewSummaryText_" + newsPreviewArticle.modelData.id
                                            visible: Boolean(newsPreviewArticle.modelData.summary)
                                            text: newsPreviewArticle.modelData.summary || ""
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            objectName: "newsPreviewBodyText_" + newsPreviewArticle.modelData.id
                                            visible: newsCard.itemBody(newsPreviewArticle.modelData).length > 0
                                            text: newsCard.itemBody(newsPreviewArticle.modelData)
                                            color: "#43535a"
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            objectName: "newsPreviewPublisherText_" + newsPreviewArticle.modelData.id
                                            visible: Boolean(newsPreviewArticle.modelData.publisher || newsPreviewArticle.modelData.publishedAt)
                                            text: [newsPreviewArticle.modelData.publisher || "", newsPreviewArticle.modelData.publishedAt || ""].filter(Boolean).join(" · ")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            objectName: "newsPreviewSourceUrlText_" + newsPreviewArticle.modelData.id
                                            visible: Boolean(newsPreviewArticle.modelData.sourceUrl)
                                            text: newsPreviewArticle.modelData.sourceUrl || ""
                                            color: root.blue
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.WrapAnywhere
                                            Layout.fillWidth: true
                                        }
                                        NewsActionButton {
                                            objectName: "newsPreviewReadArticle_" + newsPreviewArticle.modelData.id
                                            text: qsTr("阅读全文")
                                            Layout.alignment: Qt.AlignLeft
                                            onClicked: root.openArticle(newsPreviewArticle.modelData, newsCard.previewIssue || ({}))
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            NewsActionButton {
                objectName: "newsPreviewReturnButton"
                text: qsTr("返回编辑")
                onClicked: newsPreviewDialog.close()
            }
            NewsActionButton {
                text: qsTr("保存草稿")
                objectName: "newsPreviewSaveDraftButton"
                onClicked: {
                    if (newsCard.showResult(root.newsController.saveDraft(), "草稿已保存到本机。"))
                        newsPreviewDialog.close()
                }
            }
            NewsActionButton {
                text: qsTr("发布本期")
                objectName: "newsPreviewPublishButton"
                highlighted: true
                enabled: Boolean(newsCard.previewIssue)
                onClicked: newsCard.openPublishConfirmation(true)
            }
        }
    }

    Dialog {
        id: newsPublishConfirmDialog
        objectName: "newsPublishConfirmDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(430, root.width - 36)
        title: qsTr("确认发布本期新闻")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                text: newsCard.draftIssue
                      ? qsTr("将发布“%1”，并把当前已发布刊期移入历史。").arg(newsCard.draftIssue.topic || qsTr("未命名主题"))
                      : qsTr("当前没有可发布的草稿。")
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: qsTr("发布会写入本机数据库；你仍需再次点击下方确认。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                visible: newsCard.noticeIsError
                text: qsTr(newsCard.notice)
                color: root.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                text: qsTr("取消")
                objectName: "newsPublishCancelButton"
                onClicked: newsCard.cancelPublishConfirmation()
            }
            NewsActionButton {
                text: qsTr("确认发布")
                objectName: "newsConfirmPublishButton"
                highlighted: true
                enabled: Boolean(newsCard.draftIssue)
                onClicked: newsCard.confirmPublish()
            }
        }
    }

    Dialog {
        id: newsUnsavedExitDialog
        objectName: "newsUnsavedExitDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(500, root.width - 36)
        title: qsTr("有未保存的新闻预览")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                objectName: "newsUnsavedExitSummary"
                text: root.newsController && root.newsController.state && root.newsController.state.draft
                      ? qsTr("当前预览“%1”还没有保存。关闭窗口会丢弃这次预览。")
                            .arg(root.newsController.state.draft.topic || qsTr("未命名主题"))
                      : qsTr("当前新闻预览还没有保存；关闭窗口会丢弃这次预览。")
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: qsTr("你可以保存为本机草稿，或放弃这次预览后退出。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            NewsActionButton {
                objectName: "newsUnsavedExitRestoreButton"
                text: qsTr("恢复上次已保存草稿")
                Layout.fillWidth: true
                onClicked: root.restoreSavedNewsDraft()
            }
            RootText {
                visible: root.unsavedNewsCloseError.length > 0
                objectName: "newsUnsavedExitError"
                text: root.unsavedNewsCloseError
                color: root.red
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                objectName: "newsUnsavedExitReturnButton"
                text: qsTr("返回编辑")
                onClicked: {
                    root.unsavedNewsCloseError = ""
                    newsUnsavedExitDialog.close()
                }
            }
            NewsActionButton {
                objectName: "newsUnsavedExitSaveButton"
                text: qsTr("保存并退出")
                highlighted: true
                onClicked: root.finishUnsavedNewsClose(true)
            }
            NewsActionButton {
                objectName: "newsUnsavedExitDiscardButton"
                text: qsTr("放弃并退出")
                onClicked: root.finishUnsavedNewsClose(false)
            }
        }
    }

    Dialog {
        id: newsHistoryPreviewDialog
        objectName: "newsHistoryPreviewDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(620, root.width - 36)
        height: Math.min(660, root.height - 36)
        title: qsTr("预览历史刊期")
        contentItem: ScrollView {
            id: newsHistoryPreviewScroll
            clip: true
            contentWidth: availableWidth
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            ColumnLayout {
                width: newsHistoryPreviewScroll.availableWidth
                spacing: 10
                RootText {
                    objectName: "newsHistoryPreviewSummary"
                    text: {
                        const issue = newsCard.historyIssue(newsCard.pendingHistoryIndex)
                        return issue
                               ? qsTr("%1 · %2").arg(issue.date || qsTr("日期待定"),
                                                     issue.topic || qsTr("未命名主题"))
                               : qsTr("历史刊期不存在")
                    }
                    color: root.ink
                    font.family: root.serifFamily
                    font.pixelSize: 18
                    font.bold: true
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                RootText {
                    text: qsTr("这是只读预览。选择“载入为草稿”后，才会把它放入编辑工作台；当前草稿不会在这里自动替换。")
                    color: root.muted
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Repeater {
                    model: newsCard.groupDefinitions
                    delegate: ColumnLayout {
                        required property var modelData
                        property var previewItems: newsCard.itemsFor(
                                    newsCard.historyIssue(newsCard.pendingHistoryIndex),
                                    modelData.key)
                        visible: previewItems.length > 0
                        Layout.fillWidth: true
                        spacing: 4
                        RootText {
                            text: qsTr("%1 · %2 条").arg(modelData.label).arg(previewItems.length)
                            color: root.red
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        Repeater {
                            model: previewItems
                            delegate: RootText {
                                required property var modelData
                                text: "• " + newsCard.itemTitle(modelData)
                                color: root.ink
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                objectName: "newsHistoryPreviewCancelButton"
                text: qsTr("关闭")
                onClicked: newsCard.cancelHistoryLoad()
            }
            NewsActionButton {
                objectName: "newsHistoryPreviewLoadButton"
                text: qsTr("载入为草稿")
                highlighted: true
                enabled: newsCard.pendingHistoryIndex >= 0
                onClicked: newsCard.requestHistoryDraftLoad()
            }
        }
    }

    Dialog {
        id: newsHistoryReplaceDialog
        objectName: "newsHistoryReplaceDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(470, root.width - 36)
        title: qsTr("载入历史刊期？")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                objectName: "newsHistoryReplaceSummary"
                text: newsCard.draftIssue
                      ? qsTr("当前草稿“%1”将被历史刊期“%2”替换。").arg(
                                newsCard.draftIssue.topic || qsTr("未命名主题"),
                                newsCard.pendingHistoryTopic)
                      : qsTr("将载入历史刊期“%1”。").arg(newsCard.pendingHistoryTopic)
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: newsCard.stateSnapshot.draftUnsaved
                      ? qsTr("当前预览内容尚未保存；如果继续，返回时无法恢复这份预览。")
                      : qsTr("这会替换当前草稿；已发布刊期和历史记录不会被删除。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                objectName: "newsHistoryReplaceCancelButton"
                text: qsTr("取消")
                onClicked: newsCard.cancelHistoryLoad()
            }
            NewsActionButton {
                objectName: "newsHistoryReplaceConfirmButton"
                text: qsTr("覆盖并载入")
                highlighted: true
                onClicked: newsCard.confirmHistoryLoad()
            }
        }
    }

    Dialog {
        id: newsPreviewReplaceDialog
        objectName: "newsPreviewReplaceDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(470, root.width - 36)
        title: qsTr("替换当前未保存内容？")
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                objectName: "newsPreviewReplaceSummary"
                text: newsCard.draftIssue
                      ? qsTr("当前“%1”还没有保存；继续预览会用新的 JSON 替换它。")
                            .arg(newsCard.draftIssue.topic || qsTr("未命名主题"))
                      : qsTr("当前预览还没有保存；继续会替换它。")
                color: root.ink
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: qsTr("如果想保留当前内容，请先取消并保存草稿。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                objectName: "newsPreviewReplaceCancelButton"
                text: qsTr("取消")
                onClicked: newsCard.cancelPreviewReplacement()
            }
            NewsActionButton {
                objectName: "newsPreviewReplaceConfirmButton"
                text: qsTr("替换并预览")
                highlighted: true
                onClicked: newsCard.confirmPreviewReplacement()
            }
        }
    }

    Dialog {
        id: clearRecommendationFeedbackDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(430, root.width - 36)
        title: qsTr("清除文章反馈画像")
        contentItem: RootText {
            text: qsTr("这会清除你对文章的有用、不感兴趣、主题和来源反馈。手动关注主题、来源偏好、剪报和新闻刊期会保留。")
            color: root.ink
            wrapMode: Text.WordWrap
        }
        footer: RowLayout {
            Item { Layout.fillWidth: true }
            NewsActionButton {
                text: qsTr("取消")
                onClicked: clearRecommendationFeedbackDialog.close()
            }
            NewsActionButton {
                text: qsTr("清除反馈")
                highlighted: true
                onClicked: {
                    newsCard.showResult(root.newsController.clearRecommendationFeedback(), "文章反馈画像已清除；主题偏好和剪报仍保留。")
                    clearRecommendationFeedbackDialog.close()
                }
            }
        }
    }

    Dialog {
        id: newsLayoutDialog
        objectName: "newsLayoutDialog"
        property bool layoutDragging: false
        property int layoutDropTargetIndex: -1
        property string layoutNotice: ""
        modal: true
        anchors.centerIn: parent
        width: Math.min(520, root.width - 36)
        title: qsTr("调整新闻版面")
        function layoutIndexAt(contentY) {
            let destination = 0
            for (let i = 0; i < newsLayoutRepeater.count; ++i) {
                const row = newsLayoutRepeater.itemAt(i)
                if (!row) continue
                const centerY = row.mapToItem(contentItem, 0, row.height / 2).y
                if (contentY >= centerY)
                    destination = i
            }
            return destination
        }
        contentItem: ColumnLayout {
            spacing: 8
            RootText {
                visible: newsLayoutDialog.layoutNotice.length > 0
                objectName: "newsLayoutNotice"
                text: qsTr(newsLayoutDialog.layoutNotice)
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RootText {
                text: qsTr("勾选控制分组显示；拖动左侧手柄或使用上下按钮调整顺序。保存时保留其他版面字段。")
                color: root.muted
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            NewsCheckBox {
                text: qsTr("新闻工作台显示")
                checked: !newsCard.isGroupHidden("news")
                onClicked: {
                    const result = root.newsController.setLayoutGroupVisible("news", checked)
                    newsLayoutDialog.layoutNotice = result && result.ok
                            ? "版面显示设置已保存。" : String(result && result.error || "保存失败。")
                }
            }
            Repeater {
                id: newsLayoutRepeater
                model: newsCard.orderedGroups().map(function(group) {
                    return {
                        group: group,
                        controller: root.newsController,
                        knownKeys: newsCard.groupDefinitions.map(function(item) { return item.key }),
                        dialog: newsLayoutDialog
                    }
                })
                delegate: Rectangle {
                    id: newsLayoutRow
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: layoutRow.implicitHeight + 8
                    radius: 7
                    color: newsLayoutDialog.layoutDragging
                           && newsLayoutDialog.layoutDropTargetIndex === newsLayoutRow.index
                           ? "#edf3ff" : "transparent"
                    border.color: newsLayoutDialog.layoutDragging
                                  && newsLayoutDialog.layoutDropTargetIndex === newsLayoutRow.index
                                  ? root.blue : "transparent"
                    border.width: newsLayoutDialog.layoutDragging
                                 && newsLayoutDialog.layoutDropTargetIndex === newsLayoutRow.index ? 1 : 0
                    DropArea {
                        id: layoutDropArea
                        objectName: "newsLayoutDropArea_" + newsLayoutRow.modelData.group.key
                        anchors.fill: parent
                        keys: ["text/plain"]
                        onDropped: function(drop) {
                            const groupKey = drop.getDataAsString("text/plain")
                            if (groupKey) {
                                const result = newsLayoutRow.modelData.controller.moveLayoutGroupTo(
                                            groupKey, newsLayoutRow.index, newsLayoutRow.modelData.knownKeys)
                                newsLayoutRow.modelData.dialog.layoutNotice = result && result.ok
                                        ? "版面顺序已保存。" : String(result && result.error || "保存失败。")
                            }
                            drop.acceptProposedAction()
                        }
                    }
                    RowLayout {
                        id: layoutRow
                        anchors.fill: parent
                        anchors.margins: 4
                        NewsActionButton {
                            id: layoutDragHandle
                            objectName: "newsLayoutDrag_" + newsLayoutRow.modelData.group.key
                            text: "↕"
                            Accessible.name: qsTr("拖动以调整%1顺序").arg(newsLayoutRow.modelData.group.label)
                            Layout.preferredWidth: 38
                            property int pendingLayoutIndex: -1
                            property bool layoutDragActive: layoutDragMouseArea.pressed
                            opacity: layoutDragActive ? 0.65 : 1.0
                            MouseArea {
                                id: layoutDragMouseArea
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                cursorShape: Qt.SizeAllCursor
                                onPressed: function(mouse) {
                                    layoutDragHandle.pendingLayoutIndex = newsLayoutRow.index
                                    newsLayoutRow.modelData.dialog.layoutDragging = true
                                    newsLayoutRow.modelData.dialog.layoutDropTargetIndex = newsLayoutRow.index
                                }
                                onPositionChanged: function(mouse) {
                                    if (!pressed) return
                                    const point = layoutDragHandle.mapToItem(
                                                newsLayoutRow.modelData.dialog.contentItem, mouse.x, mouse.y)
                                    const destination = newsLayoutRow.modelData.dialog.layoutIndexAt(point.y)
                                    layoutDragHandle.pendingLayoutIndex = destination
                                    newsLayoutRow.modelData.dialog.layoutDropTargetIndex = destination
                                }
                                onReleased: {
                                    if (layoutDragHandle.pendingLayoutIndex >= 0) {
                                        const result = newsLayoutRow.modelData.controller.moveLayoutGroupTo(
                                                    newsLayoutRow.modelData.group.key,
                                                    layoutDragHandle.pendingLayoutIndex,
                                                    newsLayoutRow.modelData.knownKeys)
                                        newsLayoutRow.modelData.dialog.layoutNotice = result && result.ok
                                                ? "版面顺序已保存。" : String(result && result.error || "保存失败。")
                                    }
                                    newsLayoutRow.modelData.dialog.layoutDragging = false
                                    newsLayoutRow.modelData.dialog.layoutDropTargetIndex = -1
                                    layoutDragHandle.pendingLayoutIndex = -1
                                }
                                onCanceled: {
                                    newsLayoutRow.modelData.dialog.layoutDragging = false
                                    newsLayoutRow.modelData.dialog.layoutDropTargetIndex = -1
                                    layoutDragHandle.pendingLayoutIndex = -1
                                }
                            }
                        }
                        NewsCheckBox {
                            text: qsTr("%1显示").arg(newsLayoutRow.modelData.group.label)
                            checked: !newsCard.isGroupHidden(newsLayoutRow.modelData.group.key)
                            onClicked: newsLayoutRow.modelData.controller.setLayoutGroupVisible(
                                           newsLayoutRow.modelData.group.key, checked)
                        }
                        Item { Layout.fillWidth: true }
                        NewsActionButton {
                            text: "↑"
                            Accessible.name: qsTr("上移%1").arg(newsLayoutRow.modelData.group.label)
                            objectName: "newsLayoutUp_" + newsLayoutRow.modelData.group.key
                            enabled: newsLayoutRow.index > 0
                            onClicked: newsLayoutRow.modelData.controller.moveLayoutGroup(
                                           newsLayoutRow.modelData.group.key, -1,
                                           newsLayoutRow.modelData.knownKeys)
                        }
                        NewsActionButton {
                            text: "↓"
                            Accessible.name: qsTr("下移%1").arg(newsLayoutRow.modelData.group.label)
                            objectName: "newsLayoutDown_" + newsLayoutRow.modelData.group.key
                            enabled: newsLayoutRow.index < newsLayoutRow.modelData.knownKeys.length - 1
                            onClicked: newsLayoutRow.modelData.controller.moveLayoutGroup(
                                           newsLayoutRow.modelData.group.key, 1,
                                           newsLayoutRow.modelData.knownKeys)
                        }
                    }
                }
            }
        }
        footer: NewsActionButton {
            text: qsTr("完成")
            onClicked: newsLayoutDialog.close()
        }
    }

    readonly property var personalNav: [
        { label: qsTr("每日流程"), icon: "home" },
        { label: qsTr("记账理财"), icon: "wallet" },
        { label: qsTr("习惯健康"), icon: "habit" },
        { label: qsTr("减脂健身"), icon: "fitness" },
        { label: qsTr("日程统筹"), icon: "calendar" },
        { label: qsTr("待买清单"), icon: "cart" },
        { label: qsTr("书影音"), icon: "books" }
    ]
    readonly property var dataNav: [
        { label: qsTr("时光档案"), icon: "archive" }
    ]
    readonly property var toolNav: [
        { label: qsTr("格式转换"), icon: "convert" }
    ]
    readonly property var flowSteps: [
        { title: qsTr("今日速览"), note: qsTr("天气 · 行业") },
        { title: qsTr("昨日复盘"), note: qsTr("记录 · 想法") },
        { title: qsTr("今日工作"), note: qsTr("待办 · 邮件") },
        { title: qsTr("开始专注"), note: qsTr("任务 · 音频") }
    ]

    function navigateFlowStep(step) {
        root.currentSectionIndex = 0
        root.currentFlowStep = Math.max(0, Math.min(3, step))
        const scrollContent = root.flowScrollContent
        if (!scrollContent)
            return
        if (step <= 0) {
            scrollContent.contentY = 0
            return
        }
        const pageOrigin = dailyFlowPageItem.mapToItem(scrollContent, 0, 0).y
        const sectionOffset = dailyFlowPageItem.sectionPositionY(step)
        const target = Math.max(0, scrollContent.contentY + pageOrigin + sectionOffset - 16)
        scrollContent.contentY = target
    }

    function syncActiveFlowStep() {
        if (root.currentSectionIndex !== 0)
            return
        const scrollContent = root.flowScrollContent
        if (!scrollContent || !dailyFlowPageItem)
            return
        const pageOrigin = dailyFlowPageItem.mapToItem(scrollContent, 0, 0).y
        const viewportTop = 16
        let activeStep = 0
        for (let step = 1; step <= 3; ++step) {
            const sectionTop = pageOrigin + dailyFlowPageItem.sectionPositionY(step)
            if (sectionTop <= viewportTop)
                activeStep = step
        }
        root.currentFlowStep = activeStep
    }

    Connections {
        target: root.flowScrollContent
        function onContentYChanged() { root.syncActiveFlowStep() }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            id: sidebar
            visible: !root.compactNavigation
            Layout.preferredWidth: visible ? 232 : 0
            Layout.fillHeight: true
            color: root.sidebarPaper
            border.color: "#dfd8cf"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.topMargin: 23
                anchors.bottomMargin: 18
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 14
                    spacing: 11

                    Rectangle {
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        radius: 12
                            color: "#2d4657"
                        Rectangle {
                            width: 3
                            height: 32
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            color: root.red
                        }
                        RootText {
                            visible: !String(root.savedBrand.avatarImage || "").length
                            anchors.centerIn: parent
                            text: root.savedBrand.avatar || "万"
                            color: "white"
                            font.family: root.serifFamily
                            font.pixelSize: 20
                            font.bold: true
                        }
                        Image {
                            visible: String(root.savedBrand.avatarImage || "").length > 0
                            anchors.fill: parent
                            anchors.margins: 2
                            source: root.savedBrand.avatarImage || ""
                            fillMode: Image.PreserveAspectCrop
                            clip: true
                            layer.enabled: true
                        }
                    }
                    ColumnLayout {
                        spacing: 3
                        RootText {
                            text: root.savedBrand.name || "万象来信"
                            color: root.ink
                            font.family: root.serifFamily
                            font.pixelSize: 18
                            font.bold: true
                        }
                        RootText {
                            text: root.savedBrand.tagline || "把远方与日常，折进今天"
                            color: root.muted
                            font.family: root.sansFamily
                            font.pixelSize: 12
                        }
                    }
                }

                RootText {
                text: qsTr("个人板块")
                    color: uiTheme.mutedStrong
                    font.family: root.sansFamily
                    font.pixelSize: 12
                    font.bold: true
                    leftPadding: 12
                    bottomPadding: 4
                    topPadding: 9
                }

                Repeater {
                    model: root.personalNav
                    delegate: Rectangle {
                        id: personalNavItem
                        required property var modelData
                        required property int index
                        objectName: "personalNav_" + personalNavItem.index
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        radius: 11
                        color: personalNavItem.index === root.currentSectionIndex ? uiTheme.accentSoft : "transparent"
                        border.color: activeFocus ? uiTheme.accent : "transparent"
                        border.width: activeFocus ? 2 : 1
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: personalNavItem.modelData.label
                        Keys.onReturnPressed: root.currentSectionIndex = personalNavItem.index
                        Keys.onSpacePressed: root.currentSectionIndex = personalNavItem.index

                        Rectangle {
                            visible: personalNavItem.index === root.currentSectionIndex
                            width: 3
                            height: 26
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            color: uiTheme.accent
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 10
                            spacing: 12
                            AppIcon {
                                name: personalNavItem.modelData.icon
                                color: personalNavItem.index === root.currentSectionIndex ? uiTheme.accentStrong : uiTheme.muted
                                Layout.preferredWidth: 18
                                Layout.preferredHeight: 18
                            }
                            RootText {
                                text: personalNavItem.modelData.label
                                color: personalNavItem.index === root.currentSectionIndex ? uiTheme.accentStrong : uiTheme.ink
                                font.family: root.sansFamily
                                font.pixelSize: 13
                                font.bold: personalNavItem.index === root.currentSectionIndex
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                personalNavItem.forceActiveFocus()
                                root.currentSectionIndex = personalNavItem.index
                            }
                        }
                    }
                }

                RootText {
                    text: qsTr("数据")
                    color: uiTheme.mutedStrong
                    font.family: root.sansFamily
                    font.pixelSize: 12
                    font.bold: true
                    leftPadding: 12
                    bottomPadding: 4
                    topPadding: 14
                }
                Repeater {
                    model: root.dataNav
                    delegate: Rectangle {
                        id: dataNavItem
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        radius: 11
                        color: root.currentSectionIndex === 7 ? uiTheme.accentSoft : "transparent"
                        border.color: activeFocus ? uiTheme.accent : "transparent"
                        border.width: activeFocus ? 2 : 1
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: dataNavItem.modelData.label
                        Keys.onReturnPressed: root.currentSectionIndex = 7
                        Keys.onSpacePressed: root.currentSectionIndex = 7
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            spacing: 12
                            AppIcon {
                                name: dataNavItem.modelData.icon
                                color: root.currentSectionIndex === 7 ? uiTheme.accentStrong : uiTheme.muted
                                Layout.preferredWidth: 18
                                Layout.preferredHeight: 18
                            }
                            RootText {
                                text: dataNavItem.modelData.label
                                color: root.currentSectionIndex === 7 ? uiTheme.accentStrong : uiTheme.ink
                                font.family: root.sansFamily
                                font.pixelSize: 13
                                font.bold: root.currentSectionIndex === 7
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                dataNavItem.forceActiveFocus()
                                root.currentSectionIndex = 7
                            }
                        }
                    }
                }
                RootText {
                    text: qsTr("工具")
                    color: uiTheme.mutedStrong
                    font.family: root.sansFamily
                    font.pixelSize: 12
                    font.bold: true
                    leftPadding: 12
                    bottomPadding: 4
                    topPadding: 14
                }
                Repeater {
                    model: root.toolNav
                    delegate: Rectangle {
                        id: toolNavItem
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        radius: 11
                        color: root.currentSectionIndex === 8 ? uiTheme.accentSoft : "transparent"
                        border.color: activeFocus ? uiTheme.accent : "transparent"
                        border.width: activeFocus ? 2 : 1
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: toolNavItem.modelData.label
                        Keys.onReturnPressed: root.currentSectionIndex = 8
                        Keys.onSpacePressed: root.currentSectionIndex = 8
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            spacing: 12
                            AppIcon {
                                name: toolNavItem.modelData.icon
                                color: root.currentSectionIndex === 8 ? uiTheme.accentStrong : uiTheme.muted
                                Layout.preferredWidth: 18
                                Layout.preferredHeight: 18
                            }
                            RootText {
                                text: toolNavItem.modelData.label
                                color: root.currentSectionIndex === 8 ? uiTheme.accentStrong : uiTheme.ink
                                font.family: root.sansFamily
                                font.pixelSize: 13
                                font.bold: root.currentSectionIndex === 8
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                toolNavItem.forceActiveFocus()
                                root.currentSectionIndex = 8
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 124
                    radius: 15
                    color: uiTheme.surface
                    border.color: uiTheme.line
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 6
                        RootText {
                            text: "●  " + qsTr("本地优先")
                            color: "#526d59"
                            font.family: root.sansFamily
                            font.pixelSize: 12
                            font.bold: true
                        }
                        RootText {
                            text: qsTr("个人记录保存在这台设备。")
                            color: "#746d63"
                            font.family: root.sansFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.topMargin: 5
                            Layout.preferredHeight: 4
                            radius: 3
                            color: "#ddd4c7"
                            Rectangle {
                                width: 2
                                height: parent.height
                                radius: 3
                                color: root.red
                            }
                        }
                        RootText {
                            text: {
                                const data = root.importedData || {}
                                if (data.status === "loaded") {
                                    const s = data.summary || {}
                                    const keyCount = Number(s.keys_present || 0)
                                    const recordCount = Number(s.records || 0)
                                    const habitCount = Number(s.habits || 0)
                                    const keys = keyCount === 1 ? qsTr("一个键") : qsTr("%1 个键").arg(keyCount)
                                    const records = recordCount === 1 ? qsTr("一条记录") : qsTr("%1 条记录").arg(recordCount)
                                    const habits = habitCount === 1 ? qsTr("一项习惯") : qsTr("%1 项习惯").arg(habitCount)
                                    return qsTr("已读入旧版数据") + " · " + keys + " · " + records + " · " + habits
                                }
                                if (data.status === "unavailable")
                                    return qsTr("迁移数据暂不可读")
                                return qsTr("尚未导入旧版数据")
                            }
                            color: "#8f8579"
                            font.family: root.sansFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        ColumnLayout {
            id: mainColumn
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: root.compactNavigation ? 64 : 82
                Layout.leftMargin: root.compactNavigation ? 20 : 42
                Layout.rightMargin: root.compactNavigation ? 20 : 42
                spacing: 12

                RootText {
                    text: root.todayLabel()
                    color: root.muted
                    font.family: root.sansFamily
                    font.pixelSize: 12
                    font.letterSpacing: 1.1
                    Layout.fillWidth: true
                }
                Button {
                    id: openBrandAppearanceButton
                    objectName: "openBrandAppearanceButton"
                    Layout.preferredWidth: root.localeController && root.localeController.language === "en_US" ? 108 : 82
                    Layout.preferredHeight: 38
                    text: qsTr("外观")
                    Accessible.name: text
                    onClicked: brandAppearanceDialog.open()
                    contentItem: RowLayout {
                        spacing: 6
                        AppIcon {
                            name: "settings"
                            color: root.muted
                            Layout.preferredWidth: 14
                            Layout.preferredHeight: 14
                        }
                        RootText {
                            text: openBrandAppearanceButton.text
                            color: root.ink
                            font.family: root.sansFamily
                            font.pixelSize: 12
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                            Layout.fillWidth: true
                        }
                    }
                    background: Rectangle {
                        radius: 7
                        color: openBrandAppearanceButton.down ? "#edf1f4" : "#ffffff"
                        border.color: openBrandAppearanceButton.activeFocus ? root.blue : root.controlBorder
                    }
                }
                Button {
                    id: backupDataButton
                    objectName: "backupDataButton"
                    Layout.preferredWidth: root.localeController && root.localeController.language === "en_US" ? 140 : 118
                    Layout.preferredHeight: 38
                    text: qsTr("备份与数据")
                    Accessible.name: text
                    onClicked: dataToolsDialog.open()
                    contentItem: RowLayout {
                        spacing: 6
                        AppIcon {
                            name: "database"
                            color: root.muted
                            Layout.preferredWidth: 14
                            Layout.preferredHeight: 14
                        }
                        RootText {
                            text: backupDataButton.text
                            color: root.ink
                            font.family: root.sansFamily
                            font.pixelSize: 12
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                            Layout.fillWidth: true
                        }
                    }
                    background: Rectangle {
                        radius: 7
                        color: backupDataButton.down ? "#edf1f4" : "#ffffff"
                        border.color: backupDataButton.activeFocus ? root.blue : root.controlBorder
                    }
                }
            }

            StackLayout {
                id: sectionStack
                objectName: "sectionStack"
                currentIndex: Math.min(root.currentSectionIndex, 8)
                Layout.fillWidth: true
                Layout.fillHeight: true

                ScrollView {
                    id: contentScroll
                    objectName: "dailyPageScroll"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: width
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        id: pageContent
                        width: contentScroll.width
                        spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: root.compactNavigation ? 20 : 42
                        Layout.rightMargin: root.compactNavigation ? 20 : 42
                        Layout.topMargin: 8
                        Layout.bottomMargin: 17
                        Layout.preferredHeight: root.compactNavigation
                                               ? (root.height < 700 ? 124 : 174)
                                               : 162
                        color: "transparent"
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                color: "#26353e"
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.topMargin: 17
                                Layout.bottomMargin: 13
                                spacing: 18
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    RootText {
                                        text: root.issueLabel()
                                        color: uiTheme.accentStrong
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        font.bold: true
                                        font.letterSpacing: 1.1
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        RootText {
                                            text: "万象来信："
                                            color: root.red
                                            font.family: root.serifFamily
                                            font.pixelSize: root.compactNavigation ? 26 : 34
                                            font.bold: true
                                        }
                                        RootText {
                                            objectName: "dailyIssueSlogan"
                                            text: qsTr("先看世界，再照顾好今天。")
                                            color: "#202c34"
                                            font.family: root.serifFamily
                                            font.pixelSize: root.compactNavigation ? 26 : 34
                                            font.bold: true
                                        }
                                    }
                                    RootText {
                                        objectName: "dailyIssueDescription"
                                        text: qsTr("把天气、行业动向、昨日复盘与今日工作，收进同一封每日来信。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                                ColumnLayout {
                                    visible: !root.compactNavigation
                                    Layout.preferredWidth: 112
                                    Layout.alignment: Qt.AlignBottom
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 1
                                        color: root.red
                                    }
                                    RootText {
                                        text: root.issueDateLabel()
                                        color: root.red
                                        font.family: root.serifFamily
                                        font.pixelSize: 15
                                        Layout.leftMargin: 8
                                    }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                color: "#cbd4d7"
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: root.compactNavigation ? 20 : 42
                        Layout.rightMargin: root.compactNavigation ? 20 : 42
                        Layout.bottomMargin: root.height < 700 ? 10 : 13
                        columns: root.compactNavigation
                                 ? (root.height < 700 && root.width >= 760 ? 4 : 2)
                                 : 4
                        rowSpacing: root.height < 700 ? 6 : 8
                        columnSpacing: 10

                        Repeater {
                            model: root.flowSteps
                            delegate: Button {
                                id: flowStepCard
                                required property var modelData
                                required property int index
                                objectName: "flowStep_" + flowStepCard.index
                                Accessible.name: flowStepCard.modelData.title + "：" + flowStepCard.modelData.note + "，跳转到该部分"
                                activeFocusOnTab: true
                                onClicked: root.navigateFlowStep(flowStepCard.index)
                                Layout.fillWidth: true
                                Layout.preferredHeight: root.compactNavigation
                                                       ? (root.height < 700 ? 42 : 54)
                                                       : 58
                                padding: 0
                                background: Rectangle {
                                    objectName: "flowStepBackground_" + flowStepCard.index
                                    radius: uiTheme.radiusMedium
                                    color: flowStepCard.index === root.currentFlowStep ? uiTheme.accentSoft
                                          : flowStepCard.down ? uiTheme.accentSoft : uiTheme.surface
                                    border.color: flowStepCard.index === root.currentFlowStep ? "transparent"
                                                 : flowStepCard.activeFocus ? uiTheme.accentStrong : uiTheme.line

                                    Rectangle {
                                        visible: flowStepCard.index === root.currentFlowStep
                                        width: 3
                                        height: 24
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: uiTheme.accent
                                    }
                                }
                                contentItem: RowLayout {
                                    spacing: 10
                                    RootText {
                                        Layout.leftMargin: 14
                                        text: "0" + (flowStepCard.index + 1)
                                        color: uiTheme.brand
                                        font.family: root.serifFamily
                                        font.pixelSize: 13
                                        font.bold: true
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        RootText {
                                            text: flowStepCard.modelData.title
                                            color: flowStepCard.index === root.currentFlowStep ? uiTheme.accentStrong : uiTheme.ink
                                            font.family: root.sansFamily
                                            font.pixelSize: 13
                                            font.bold: true
                                        }
                                        RootText {
                                            objectName: "flowStepNote_" + flowStepCard.index
                                            text: flowStepCard.modelData.note
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            visible: !(root.compactNavigation && root.height < 700)
                                        }
                                    }
                                    Item { Layout.rightMargin: 10 }
                                }
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 8
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: root.compactNavigation ? 20 : 42
                        Layout.rightMargin: root.compactNavigation ? 20 : 42
                        Layout.bottomMargin: 20
                        spacing: 13

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 1
                            color: root.line
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                RootText {
                                    objectName: "dailyOverviewNumber"
                                    text: "01 / LOOK OUTWARD"
                                    color: root.blue
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                    font.letterSpacing: 1.1
                                }
                                RootText {
                                    objectName: "dailyOverviewTitle"
                                    text: qsTr("今日速览")
                                    color: "#20303d"
                                    font.family: root.serifFamily
                                    font.pixelSize: root.height < 700 ? 25 : 29
                                    font.bold: true
                                }
                            }
                            RootText {
                                objectName: "dailyOverviewSubtitle"
                                text: qsTr("先了解天气与值得关注的变化")
                                color: root.muted
                                font.family: root.sansFamily
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignRight
                            }
                            NewsActionButton {
                                objectName: "homeLayoutSettingsButton"
                                text: qsTr("布局设置")
                                enabled: Boolean(root.homeLayoutController)
                                onClicked: homeLayoutDialog.open()
                            }
                        }

                        Flow {
                            id: briefingCards
                            Layout.fillWidth: true
                            Layout.preferredHeight: childrenRect.height
                            spacing: 14

                            Rectangle {
                                id: weatherCard
                                property bool detailsExpanded: false
                                readonly property bool hasWeatherData: root.weatherController.temperature !== undefined
                                                                        && root.weatherController.temperature !== null
                                                                        && String(root.weatherController.temperature).trim() !== ""
                                                                        && Number.isFinite(Number(root.weatherController.temperature))
                                width: briefingCards.width
                                height: root.compactNavigation && !hasWeatherData ? 260 : 320
                                color: "#f4f6f8"
                                border.color: "#d6dfe2"
                                function formatValue(value, unit) {
                                    if (value === undefined || value === null || !Number.isFinite(Number(value)))
                                        return "—"
                                    return Math.round(Number(value)) + unit
                                }
                                function errorMessage() {
                                    if (root.weatherController.busy)
                                        return ""
                                    const status = String(root.weatherController.status || "").trim()
                                    const normalized = status.toLowerCase()
                                    if (normalized === "error" || normalized === "failed" || normalized === "failure")
                                        return qsTr("天气查询失败，请检查城市名称或网络后重试。")
                                    if (normalized === "not_found")
                                        return qsTr("没有找到该城市，请检查名称或尝试输入拼音。")
                                    if (normalized === "invalid_city")
                                        return qsTr("城市名称无效，请重新输入。")
                                    if (status.indexOf("失败") >= 0 || status.indexOf("错误") >= 0
                                            || status.indexOf("超时") >= 0 || status.indexOf("没有找到") >= 0
                                            || status.indexOf("无效") >= 0 || status.indexOf("不可用") >= 0
                                            || status.indexOf("未允许") >= 0 || status.indexOf("权限") >= 0
                                            || status.indexOf("授权") >= 0 || status.indexOf("拒绝") >= 0)
                                        return qsTr(status)
                                    return ""
                                }
                                function statusLabel() {
                                    if (root.weatherController.busy)
                                        return root.weatherController.locationBusy ? qsTr("正在定位") : qsTr("正在查询")
                                    const status = String(root.weatherController.status || "").trim()
                                    const normalized = status.toLowerCase()
                                    if (errorMessage())
                                        return qsTr("查询失败")
                                    if (normalized === "ready" || normalized === "success" || normalized === "ok")
                                        return qsTr("当前天气")
                                    if (normalized === "idle" || normalized === "waiting")
                                        return root.weatherController.city ? qsTr("待查询") : qsTr("待设置")
                                    return status ? qsTr(status) : (root.weatherController.city ? qsTr("待查询") : qsTr("待设置"))
                                }
                                function iconName() {
                                    const glyph = String(root.weatherController.glyph || "")
                                    if (!glyph) return "location"
                                    if (glyph === "☁") return "cloud"
                                    if (glyph === "☂") return "rain"
                                    if (glyph === "❄") return "snow"
                                    if (glyph === "⚡") return "storm"
                                    if (glyph === "≋") return "fog"
                                    if (glyph === "☼") return "sun"
                                    return "location"
                                }

                                Rectangle { x: 0; y: 0; width: parent.width; height: 3; color: root.blue }
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 5
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            text: "LOCAL WEATHER"
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            font.bold: true
                                            font.letterSpacing: 1.1
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            objectName: "weatherStatusLabel"
                                            text: weatherCard.statusLabel()
                                            color: weatherCard.errorMessage() ? root.red : (root.weatherController.busy ? root.blue : root.muted)
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                        }
                                        NewsActionButton {
                                            objectName: "weatherDetailsToggle"
                                            visible: weatherCard.hasWeatherData
                                            text: weatherCard.detailsExpanded ? qsTr("收起") : qsTr("详情")
                                            implicitHeight: 24
                                            Layout.preferredWidth: 48
                                            onClicked: weatherCard.detailsExpanded = !weatherCard.detailsExpanded
                                        }
                                    }
                                    RowLayout {
                                        visible: weatherCard.hasWeatherData
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        Layout.topMargin: 2
                                        Layout.bottomMargin: 2
                                        spacing: 10
                                        Rectangle {
                                            Layout.preferredWidth: 50
                                            Layout.minimumWidth: 50
                                            Layout.maximumWidth: 50
                                            Layout.preferredHeight: 50
                                            radius: 25
                                            color: "#ffffff"
                                            border.color: "#d1dce1"
                                            AppIcon {
                                                objectName: "weatherConditionIcon"
                                                anchors.centerIn: parent
                                                width: 27
                                                height: 27
                                                name: weatherCard.iconName()
                                                color: root.blue
                                                strokeWidth: 1.65
                                            }
                                        }
                                        ColumnLayout {
                                            id: weatherInfo
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 100
                                            Layout.preferredWidth: 180
                                            Layout.maximumWidth: 360
                                            spacing: 3
                                            RootText {
                                                objectName: "weatherCityLabel"
                                                text: root.weatherController.city === "当前位置"
                                                      ? qsTr("当前位置")
                                                      : (root.weatherController.city || qsTr("待设置城市"))
                                                color: "#20303d"
                                                font.family: root.serifFamily
                                                font.pixelSize: 17
                                                font.bold: true
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                elide: Text.ElideRight
                                            }
                                            RootText {
                                            objectName: "weatherConditionText"
                                            text: {
                                                const condition = root.weatherController.condition || ""
                                                if (condition) {
                                                    if (root.localeController
                                                            && root.localeController.language === "en_US"
                                                            && root.weatherController.conditionEnglish)
                                                        return root.weatherController.conditionEnglish
                                                    return condition
                                                }
                                                return root.weatherController.locationBusy
                                                        ? qsTr("正在获取系统位置…")
                                                        : (root.weatherController.busy
                                                           ? qsTr("正在获取天气…")
                                                           : qsTr("输入城市后查询天气"))
                                            }
                                                color: weatherCard.errorMessage() ? root.red : root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                            }
                                        }
                                        RootText {
                                            objectName: "weatherTemperatureText"
                                            visible: weatherCard.hasWeatherData
                                            text: weatherCard.formatValue(root.weatherController.temperature, "°")
                                            color: root.blue
                                            font.family: root.serifFamily
                                            font.pixelSize: 24
                                            font.bold: true
                                            horizontalAlignment: Text.AlignRight
                                            Layout.preferredWidth: 58
                                            Layout.minimumWidth: 52
                                            Layout.maximumWidth: 58
                                        }
                                    }
                                    RootText {
                                        objectName: "weatherEmptyPrompt"
                                        visible: !weatherCard.hasWeatherData
                                        text: qsTr("输入城市，或使用当前位置查看本地天气。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    RowLayout {
                                        visible: weatherCard.detailsExpanded
                                        Layout.fillWidth: true
                                        spacing: 6
                                        RootText {
                                            objectName: "weatherApparentLabel"
                                            text: qsTr("体感 %1").arg(weatherCard.formatValue(root.weatherController.apparentTemperature, "°"))
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                        }
                                        RootText {
                                            objectName: "weatherRangeLabel"
                                            text: qsTr("今日 %1 / %2")
                                                .arg(weatherCard.formatValue(root.weatherController.lowTemperature, "°"))
                                                .arg(weatherCard.formatValue(root.weatherController.highTemperature, "°"))
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            Layout.fillWidth: true
                                        }
                                    }
                                    RootText {
                                        visible: weatherCard.detailsExpanded
                                        objectName: "weatherMetricsLabel"
                                        text: qsTr("湿度 %1 · 风 %2 · 降水 %3")
                                            .arg(weatherCard.formatValue(root.weatherController.humidity, "%"))
                                            .arg(weatherCard.formatValue(root.weatherController.windSpeed, " km/h"))
                                            .arg(weatherCard.formatValue(root.weatherController.rainChance, "%"))
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        UiTextField {
                                            id: cityInput
                                            uiTheme: root.theme
                                            objectName: "weatherCityInput"
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 100
                                            Layout.preferredHeight: 36
                                            text: root.weatherController.city || ""
                                            placeholderText: qsTr("城市名或“城市, 省/国家”")
                                            selectByMouse: true
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            enabled: !root.weatherController.busy || root.weatherController.locationBusy
                                            onAccepted: {
                                                const city = text.trim()
                                                if (city.length > 0
                                                        && (!root.weatherController.busy || root.weatherController.locationBusy))
                                                    root.weatherController.queryCity(city)
                                            }
                                        }
                                        Button {
                                            id: queryWeatherButton
                                            objectName: "queryWeatherButton"
                                            Layout.preferredWidth: 108
                                            Layout.minimumWidth: 108
                                            Layout.maximumWidth: 108
                                            Layout.preferredHeight: 36
                                            text: root.weatherController.locationBusy
                                                  ? qsTr("改用此城市")
                                                  : (root.weatherController.busy ? qsTr("查询中…") : qsTr("查询天气"))
                                            enabled: (!root.weatherController.busy || root.weatherController.locationBusy)
                                                     && cityInput.text.trim().length > 0
                                            onClicked: root.weatherController.queryCity(cityInput.text.trim())
                                            contentItem: RootText {
                                                text: queryWeatherButton.text
                                                color: queryWeatherButton.enabled ? "white" : "#44515c"
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                font.bold: true
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                                elide: Text.ElideRight
                                            }
                                            background: Rectangle {
                                                radius: 5
                                                color: queryWeatherButton.enabled
                                                      ? (queryWeatherButton.down ? uiTheme.accentStrong : root.blue)
                                                      : "#e2e7f2"
                                                border.color: queryWeatherButton.enabled ? root.blue : root.controlBorder
                                            }
                                        }
                                        Button {
                                            id: locateWeatherButton
                                            objectName: "weatherLocateButton"
                                            Layout.preferredWidth: 104
                                            Layout.minimumWidth: 104
                                            Layout.preferredHeight: 36
                                            text: root.weatherController.locationBusy
                                                  ? qsTr("定位中…")
                                                  : (root.weatherController.city === "当前位置" ? qsTr("重新定位") : qsTr("使用当前位置"))
                                            enabled: !root.weatherController.locationBusy && !root.weatherController.busy
                                            onClicked: root.weatherController.requestLocation()
                                            contentItem: RootText {
                                                text: locateWeatherButton.text
                                                color: locateWeatherButton.enabled ? root.blue : root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: root.width < 560 && root.localeController.language === "en_US" ? 10 : 12
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                                elide: Text.ElideRight
                                            }
                                            background: Rectangle {
                                                radius: 5
                                                color: locateWeatherButton.enabled ? "#edf2ff" : "#eef1f2"
                                                border.color: locateWeatherButton.activeFocus ? root.blue : root.controlBorder
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Button {
                                            id: weatherLocationSettingsButton
                                            objectName: "weatherLocationSettingsButton"
                                            Layout.preferredWidth: 98
                                            Layout.minimumWidth: 98
                                            Layout.preferredHeight: 25
                                            text: qsTr("系统位置设置")
                                            enabled: !root.weatherController.locationBusy
                                            onClicked: root.weatherController.openLocationSettings()
                                            contentItem: RootText {
                                                text: weatherLocationSettingsButton.text
                                                color: root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                            background: Rectangle {
                                                radius: 5
                                                color: "#f5f6f7"
                                                border.color: weatherLocationSettingsButton.activeFocus ? root.blue : root.controlBorder
                                            }
                                        }
                                        RootText {
                                            objectName: "weatherLocationPrivacyNote"
                                            text: qsTr("仅保存约 0.1° 精度的位置；也可手动输入城市。")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                    RootText {
                                        objectName: "weatherErrorText"
                                        visible: weatherCard.errorMessage().length > 0
                                        text: weatherCard.errorMessage()
                                        color: root.red
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }

                            Rectangle {
                                id: newsScopeCard
                                objectName: "newsScopeCard"
                                width: briefingCards.width >= 900 ? (briefingCards.width - briefingCards.spacing) / 2 : briefingCards.width
                                height: Math.max(320, newsScopeContent.implicitHeight + 32)
                                visible: root.homeLayoutCardVisible("lead") && !newsCard.isGroupHidden("news")
                                color: uiTheme.surface
                                radius: uiTheme.radiusLarge
                                border.color: uiTheme.line
                                Rectangle { x: 0; y: 0; width: parent.width; height: 3; color: root.red }
                                ColumnLayout {
                                    id: newsScopeContent
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 16
                                    spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            text: qsTr("NEWS SCOPE")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            font.bold: true
                                            font.letterSpacing: 1.0
                                            Layout.fillWidth: true
                                        }
                                        NewsActionButton {
                                            objectName: "newsPreferencesButtonScope"
                                            text: qsTr("关注设置")
                                            onClicked: preferencesDialog.open()
                                        }
                                        RootText {
                                            text: newsCard.draftIssue ? qsTr("草稿预览") : (newsCard.activeIssue ? qsTr("本机刊期") : qsTr("待导入"))
                                            color: newsCard.draftIssue ? root.blue : root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    RootText {
                                        text: qsTr("关注方向")
                                        color: "#20303d"
                                        font.family: root.serifFamily
                                        font.pixelSize: 19
                                        font.bold: true
                                    }
                                    RootText {
                                        text: qsTr("偏好仅用于新闻内容准备提示，不会自动屏蔽其他新闻；每篇内容仍需保留来源与日期。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 54
                                        color: "#f8fafb"
                                        border.color: root.line
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 2
                                            RootText {
                                                objectName: "newsIssueSummaryStatus"
                                                text: newsCard.draftIssue
                                                     ? (newsCard.draftUnsaved ? qsTr("预览未保存") : qsTr("草稿已保存"))
                                                     : newsCard.activeIssue ? qsTr("当前已发布刊期")
                                                                             : qsTr("尚未发布刊期")
                                                color: newsCard.draftUnsaved ? root.red : root.blue
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                font.bold: true
                                            }
                                            RootText {
                                                objectName: "newsIssueSummaryDescription"
                                                text: newsCard.issueDescription(newsCard.draftIssue || newsCard.activeIssue)
                                                color: (newsCard.draftIssue || newsCard.activeIssue) ? root.ink : root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                    RowLayout {
                                        objectName: "newsIssueCounts"
                                        Layout.fillWidth: true
                                        spacing: 8
                                        visible: Boolean(newsCard.draftIssue || newsCard.activeIssue)
                                        Repeater {
                                            model: newsCard.groupDefinitions
                                            delegate: Rectangle {
                                                id: newsGroupCard
                                                required property var modelData
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 43
                                                color: "#ffffff"
                                                border.color: root.line
                                                ColumnLayout {
                                                    anchors.fill: parent
                                                    anchors.margins: 5
                                                    spacing: 1
                                                    RootText {
                                                        text: newsCard.groupLabel(newsGroupCard.modelData.key)
                                                        color: root.muted
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        elide: Text.ElideRight
                                                        Layout.fillWidth: true
                                                    }
                                                    RootText {
                                                        text: newsCard.groupCount(newsGroupCard.modelData.key)
                                                        color: root.ink
                                                        font.family: root.serifFamily
                                                        font.pixelSize: 14
                                                        font.bold: true
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        NewsActionButton {
                                            text: newsCard.draftIssue ? qsTr("编辑本期 JSON") : qsTr("导入本期 JSON")
                                            Layout.fillWidth: true
                                            onClicked: newsCard.openJsonEditor()
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        NewsActionButton {
                                            objectName: "newsCopyPromptButton"
                                            text: qsTr("复制生成提示")
                                            Layout.fillWidth: true
                                            onClicked: newsCard.showResult(
                                                           root.newsController.copyIssuePrompt(root.preferencesController.state,
                                                                                          root.readingSnapshot.clippings),
                                                           "新闻生成提示已复制。")
                                        }
                                        NewsActionButton {
                                            objectName: "newsExportIssueButton"
                                            text: qsTr("导出已发布刊期")
                                            enabled: Boolean(newsCard.activeIssue)
                                            onClicked: {
                                                newsCard.clearNotice()
                                                newsExportDialog.open()
                                            }
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: newsCard
                                objectName: "newsCard"
                                property var stateSnapshot: root.newsController.state || ({})
                                readonly property var groupDefinitions: [
                                    { key: "focus", label: qsTr("关注焦点") },
                                    { key: "highlights", label: qsTr("行业看点") },
                                    { key: "articles", label: qsTr("文章内容") }
                                ]
                                property var previewIssue: null
                                property string notice: ""
                                property bool noticeIsError: false
                                property bool workspaceExpanded: false
                                property bool secondaryActionsExpanded: false
                                property bool publishConfirmationFromPreview: false
                                property int pendingHistoryIndex: -1
                                property string pendingHistoryTopic: ""
                                property string pendingPreviewJson: ""
                                property url pendingPreviewFile: ""
                                property bool pendingPreviewFromEditor: false
                                width: briefingCards.width
                                height: workspaceExpanded ? 600 : 112
                                visible: root.homeLayoutCardVisible("briefs") && !isGroupHidden("news")
                                color: "#ffffff"
                                border.color: "#d6dfe2"
                                readonly property var activeIssue: stateSnapshot.active || null
                                readonly property var draftIssue: stateSnapshot.draft || null
                                readonly property bool draftUnsaved: Boolean(stateSnapshot.draftUnsaved)
                                readonly property var archiveItems: listFromVariant(stateSnapshot.archive)
                                readonly property var inboxItems: listFromVariant(stateSnapshot.linkInbox)

                                function groupLabel(group) {
                                    const item = groupDefinitions.find(function(value) { return value.key === group })
                                    return item ? item.label : group
                                }
                                function groupCount(group) {
                                    return itemsFor(draftIssue || activeIssue, group).length
                                }

                                // Python lists arrive through QVariant as list-like values, which may not
                                // satisfy JavaScript Array.isArray() in every PySide6/Qt combination.
                                function listFromVariant(value) {
                                    if (value === null || value === undefined)
                                        return []
                                    if (Array.isArray(value))
                                        return value
                                    if (typeof value !== "object"
                                            || typeof value.length !== "number" || value.length < 0)
                                        return []
                                    const result = []
                                    for (let index = 0; index < value.length; index++)
                                        result.push(value[index])
                                    return result
                                }

                                function layoutCopy() {
                                    const source = stateSnapshot.layout || ({})
                                    try { return JSON.parse(JSON.stringify(source)) }
                                    catch (error) { return ({}) }
                                }
                                function groupOrder() {
                                    const validKeys = groupDefinitions.map(function(item) { return item.key })
                                    const saved = layoutCopy().order
                                    const order = []
                                    listFromVariant(saved).forEach(function(key) {
                                        if (validKeys.indexOf(key) >= 0 && order.indexOf(key) < 0)
                                            order.push(key)
                                    })
                                    validKeys.forEach(function(key) {
                                        if (order.indexOf(key) < 0) order.push(key)
                                    })
                                    return order
                                }
                                function orderedGroups() {
                                    const order = groupOrder()
                                    return order.map(function(key) {
                                        return groupDefinitions.find(function(item) { return item.key === key })
                                    }).filter(Boolean)
                                }
                                function itemsFor(issue, group) {
                                    return issue ? listFromVariant(issue[group]) : []
                                }
                                function itemTitle(item) {
                                    return item ? String(item.title || item.label || item.sourceTitle || qsTr("未命名条目")) : qsTr("未命名条目")
                                }
                                function itemBody(item) {
                                    if (!item || item.body === undefined || item.body === null)
                                        return ""
                                    if (item.body && typeof item.body === "object"
                                            && typeof item.body.length === "number")
                                        return listFromVariant(item.body).filter(Boolean).join("\n\n")
                                    return String(item.body)
                                }
                                function issueDescription(issue) {
                                    if (!issue) return qsTr("导入并发布本期 JSON 后，这里会显示刊期摘要。")
                                    return String(issue.date || qsTr("日期未填写")) + " · "
                                            + String(issue.topic || qsTr("未命名主题")) + " · "
                                            + qsTr("焦点 %1").arg(itemsFor(issue, "focus").length)
                                            + " · " + qsTr("看点 %1").arg(itemsFor(issue, "highlights").length)
                                            + " · " + qsTr("文章 %1").arg(itemsFor(issue, "articles").length)
                                }
                                function historyLabels() {
                                    return archiveItems.map(function(entry) {
                                        const issue = entry && entry.issue ? entry.issue : ({})
                                        return String(issue.date || entry.publishedAt || qsTr("日期未填写"))
                                                + " · " + String(issue.topic || qsTr("未命名主题"))
                                    })
                                }
                                function historyIssue(index) {
                                    if (index < 0 || index >= archiveItems.length)
                                        return null
                                    const entry = archiveItems[index]
                                    return entry && entry.issue ? entry.issue : null
                                }
                                function loadHistory(index) {
                                    const result = root.newsController.loadHistory(index)
                                    const loaded = showResult(
                                                result,
                                                qsTr("历史刊期已载入为草稿；原草稿已被替换，可继续排序、保存或发布。"))
                                    newsHistorySelector.currentIndex = 0
                                    pendingHistoryIndex = -1
                                    pendingHistoryTopic = ""
                                    return loaded
                                }
                                function requestHistoryLoad(index) {
                                    if (index <= 0)
                                        return
                                    pendingHistoryIndex = index - 1
                                    const issue = historyIssue(pendingHistoryIndex)
                                    pendingHistoryTopic = issue
                                            ? String(issue.topic || qsTr("未命名主题"))
                                            : qsTr("未命名主题")
                                    newsHistoryPreviewDialog.open()
                                }
                                function requestHistoryDraftLoad() {
                                    if (pendingHistoryIndex < 0) {
                                        cancelHistoryLoad()
                                        return false
                                    }
                                    newsHistoryPreviewDialog.close()
                                    if (draftIssue) {
                                        newsHistoryReplaceDialog.open()
                                        return true
                                    }
                                    return loadHistory(pendingHistoryIndex)
                                }
                                function cancelHistoryLoad() {
                                    newsHistorySelector.currentIndex = 0
                                    pendingHistoryIndex = -1
                                    pendingHistoryTopic = ""
                                    newsHistoryPreviewDialog.close()
                                    newsHistoryReplaceDialog.close()
                                }
                                function confirmHistoryLoad() {
                                    if (pendingHistoryIndex < 0) {
                                        cancelHistoryLoad()
                                        return false
                                    }
                                    const loaded = loadHistory(pendingHistoryIndex)
                                    newsHistoryReplaceDialog.close()
                                    return loaded
                                }
                                function isGroupHidden(key) {
                                    const hidden = layoutCopy().hidden
                                    return listFromVariant(hidden).indexOf(key) >= 0
                                }
                                function showResult(result, successText) {
                                    if (!result || result.ok !== true) {
                                        notice = result && result.error ? String(result.error) : "操作未完成，请检查内容后重试。"
                                        noticeIsError = true
                                        return false
                                    }
                                    notice = successText || "操作已完成。"
                                    noticeIsError = false
                                    return true
                                }
                                function clearNotice() {
                                    notice = ""
                                    noticeIsError = false
                                }
                                function openPublishConfirmation(fromPreview) {
                                    publishConfirmationFromPreview = Boolean(fromPreview)
                                    clearNotice()
                                    if (publishConfirmationFromPreview && newsPreviewDialog.visible) {
                                        newsPreviewDialog.close()
                                        // Let the first modal popup finish closing before
                                        // mounting the confirmation footer. Qt Quick can
                                        // otherwise report the dialog visible while its
                                        // footer controls are still absent from the tree.
                                        Qt.callLater(function() { newsPublishConfirmDialog.open() })
                                    } else {
                                        newsPublishConfirmDialog.open()
                                    }
                                }
                                function cancelPublishConfirmation() {
                                    const returnToPreview = publishConfirmationFromPreview && Boolean(previewIssue)
                                    publishConfirmationFromPreview = false
                                    newsPublishConfirmDialog.close()
                                    if (returnToPreview)
                                        newsPreviewDialog.open()
                                }
                                function confirmPublish() {
                                    if (!showResult(root.newsController.publishDraft(), "本期已发布，原刊期已归档。"))
                                        return false
                                    publishConfirmationFromPreview = false
                                    newsPublishConfirmDialog.close()
                                    newsPreviewDialog.close()
                                    return true
                                }
                                function previewIssueResult(result) {
                                    if (!showResult(result, "校验通过，已进入预览；尚未发布。")) return false
                                    const currentState = result.state && typeof result.state === "object" ? result.state : stateSnapshot
                                    previewIssue = currentState.draft || stateSnapshot.draft || null
                                    if (newsJsonDialog.visible) newsJsonDialog.close()
                                    newsPreviewDialog.open()
                                    return true
                                }
                                function requestPreviewText(text) {
                                    if (!draftUnsaved) {
                                        previewIssueResult(root.newsController.previewJson(text))
                                        return true
                                    }
                                    pendingPreviewJson = text
                                    pendingPreviewFile = ""
                                    pendingPreviewFromEditor = true
                                    newsJsonDialog.close()
                                    newsPreviewReplaceDialog.open()
                                    return false
                                }
                                function requestPreviewFile(fileUrl) {
                                    if (!draftUnsaved) {
                                        previewIssueResult(root.newsController.previewFile(fileUrl))
                                        return true
                                    }
                                    pendingPreviewJson = ""
                                    pendingPreviewFile = fileUrl
                                    pendingPreviewFromEditor = false
                                    newsPreviewReplaceDialog.open()
                                    return false
                                }
                                function cancelPreviewReplacement() {
                                    const fromEditor = pendingPreviewFromEditor
                                    pendingPreviewJson = ""
                                    pendingPreviewFile = ""
                                    pendingPreviewFromEditor = false
                                    newsPreviewReplaceDialog.close()
                                    if (fromEditor)
                                        newsJsonDialog.open()
                                }
                                function confirmPreviewReplacement() {
                                    const fromEditor = pendingPreviewFromEditor
                                    const sourceFile = pendingPreviewFile
                                    const sourceJson = pendingPreviewJson
                                    pendingPreviewJson = ""
                                    pendingPreviewFile = ""
                                    pendingPreviewFromEditor = false
                                    newsPreviewReplaceDialog.close()
                                    Qt.callLater(function() {
                                        const result = sourceFile && sourceFile.toString().length > 0
                                                ? root.newsController.previewFile(sourceFile)
                                                : root.newsController.previewJson(sourceJson)
                                        const accepted = previewIssueResult(result)
                                        if (!accepted && fromEditor)
                                            newsJsonDialog.open()
                                    })
                                    return true
                                }
                                function previewJsonText(text) { requestPreviewText(text) }
                                function openJsonEditor() {
                                    clearNotice()
                                    newsJsonEditor.text = draftIssue ? JSON.stringify(draftIssue, null, 2) : ""
                                    newsJsonDialog.open()
                                }
                                function setGroupVisible(group, visibleValue) {
                                    const nextLayout = layoutCopy()
                                    const hidden = listFromVariant(nextLayout.hidden).slice()
                                    const index = hidden.indexOf(group)
                                    if (visibleValue && index >= 0) hidden.splice(index, 1)
                                    else if (!visibleValue && index < 0) hidden.push(group)
                                    nextLayout.hidden = hidden
                                    showResult(root.newsController.saveLayout(nextLayout), "版面显示设置已保存。")
                                }
                                function moveLayoutGroup(group, delta) {
                                    const selectedOrder = groupOrder()
                                    const oldIndex = selectedOrder.indexOf(group)
                                    moveLayoutGroupTo(group, oldIndex + delta)
                                }
                                function moveLayoutGroupTo(group, targetIndex) {
                                    const nextLayout = layoutCopy()
                                    const fullOrder = listFromVariant(nextLayout.order).slice()
                                    const knownKeys = groupDefinitions.map(function(item) { return item.key })
                                    const selectedOrder = groupOrder()
                                    const oldIndex = selectedOrder.indexOf(group)
                                    if (oldIndex < 0 || targetIndex < 0 || targetIndex >= selectedOrder.length
                                            || oldIndex === targetIndex) return
                                    const moving = selectedOrder.splice(oldIndex, 1)[0]
                                    selectedOrder.splice(targetIndex, 0, moving)
                                    let selectedIndex = 0
                                    const updatedOrder = []
                                    fullOrder.forEach(function(key) {
                                        if (knownKeys.indexOf(key) >= 0) {
                                            if (selectedIndex < selectedOrder.length)
                                                updatedOrder.push(selectedOrder[selectedIndex++])
                                        } else {
                                            updatedOrder.push(key)
                                        }
                                    })
                                    while (selectedIndex < selectedOrder.length)
                                        updatedOrder.push(selectedOrder[selectedIndex++])
                                    nextLayout.order = updatedOrder
                                    showResult(root.newsController.saveLayout(nextLayout), "版面顺序已保存。")
                                }
                                function addDroppedLink(url) {
                                    showResult(root.newsController.addLink(url), "网页链接已收进本地素材箱；不会抓取或发布页面。")
                                }
                                function handleDrop(drop) {
                                    const urls = drop && drop.urls ? drop.urls : []
                                    if (urls.length > 1) {
                                        notice = qsTr("请一次拖入一个 JSON 文件或网页链接。")
                                        noticeIsError = true
                                        return
                                    }
                                    let raw = ""
                                    let originalUrl = null
                                    if (urls.length > 0) {
                                        originalUrl = urls[0]
                                        raw = String(originalUrl)
                                    } else {
                                        raw = String(drop && drop.text ? drop.text : "").trim()
                                    }
                                    if (/^https?:\/\//i.test(raw)) {
                                        addDroppedLink(raw)
                                        return
                                    }
                                    if (originalUrl && /^file:/i.test(raw)
                                            && /\.json(?:[?#]|$)/i.test(raw.split(/[?#]/)[0])) {
                                        requestPreviewFile(originalUrl)
                                        return
                                    }
                                    notice = qsTr("请拖入本机 .json 文件，或以 http://、https:// 开头的网页链接。")
                                    noticeIsError = true
                                }

                                Rectangle { x: 0; y: 0; width: parent.width; height: 3; color: root.red }
                                ColumnLayout {
                                    id: newsEditorColumn
                                    visible: newsCard.workspaceExpanded
                                    z: 1
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 7
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            objectName: "newsWorkspaceHeader"
                                            text: qsTr("NEWS SCOPE · 本机刊期工作台")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            font.bold: true
                                            font.letterSpacing: 1.0
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        NewsActionButton {
                                            objectName: "newsWorkspaceCollapseButton"
                                            text: qsTr("收起工作台")
                                            onClicked: newsCard.workspaceExpanded = false
                                        }
                                        NewsActionButton {
                                            objectName: "newsWorkspaceMoreButton"
                                            text: newsCard.secondaryActionsExpanded ? qsTr("收起更多") : qsTr("更多")
                                            Accessible.name: newsCard.secondaryActionsExpanded
                                                           ? qsTr("收起新闻工作台的低频操作")
                                                           : qsTr("打开新闻工作台的低频操作")
                                            onClicked: newsCard.secondaryActionsExpanded = !newsCard.secondaryActionsExpanded
                                        }
                                    }
                                    Frame {
                                        objectName: "newsWorkspaceSecondaryActions"
                                        visible: newsCard.secondaryActionsExpanded
                                        Layout.fillWidth: true
                                        padding: 7
                                        background: Rectangle {
                                            radius: 8
                                            color: "#f8fafb"
                                            border.color: root.line
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            spacing: 5
                                            NewsActionButton {
                                                objectName: "newsLayoutButton"
                                                text: qsTr("版面设置")
                                                onClicked: {
                                                    newsCard.clearNotice()
                                                    newsLayoutDialog.open()
                                                }
                                            }
                                            NewsActionButton {
                                                objectName: "newsPreferencesButton"
                                                text: qsTr("关注设置")
                                                onClicked: preferencesDialog.open()
                                            }
                                            NewsActionButton {
                                                objectName: "newsClippingsButton"
                                                text: qsTr("我的剪报 · %1").arg(root.listFromVariant(root.readingSnapshot.clippings).length)
                                                onClicked: clippingsDialog.open()
                                            }
                                            NewsActionButton {
                                                objectName: "newsSavedKnowledgeButton"
                                                text: root.readingSnapshot.savedKnowledge ? qsTr("关闭全局稍后读") : qsTr("开启全局稍后读")
                                                onClicked: {
                                                    const enabled = !Boolean(root.readingSnapshot.savedKnowledge)
                                                    newsCard.showResult(
                                                        root.readingController.setSavedKnowledge(enabled),
                                                        enabled ? "全局稍后读功能已开启。" : "全局稍后读功能已关闭。")
                                                }
                                            }
                                            Item { Layout.fillWidth: true }
                                        }
                                    }
                                    RootText {
                                        text: qsTr("关注方向与本期编辑")
                                        color: "#20303d"
                                        font.family: root.serifFamily
                                        font.pixelSize: 19
                                        font.bold: true
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                    }
                                    RootText {
                                        text: qsTr("主题和候选媒体只用于生成内容准备提示；每篇新闻仍保留来源、日期和核对边界。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        NewsActionButton {
                                            objectName: "newsPasteButton"
                                            text: newsCard.draftIssue ? qsTr("编辑 / 粘贴 JSON") : qsTr("粘贴 JSON")
                                            Layout.fillWidth: true
                                            onClicked: newsCard.openJsonEditor()
                                        }
                                        NewsActionButton {
                                            objectName: "newsOpenFileButton"
                                            text: qsTr("打开 JSON 文件")
                                            Layout.fillWidth: true
                                            onClicked: {
                                                newsCard.clearNotice()
                                                newsFileDialog.open()
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        NewsActionButton {
                                            objectName: "newsCopyPromptButtonWorkspace"
                                            text: qsTr("复制新闻生成提示")
                                            Layout.fillWidth: true
                                            onClicked: newsCard.showResult(
                                                           root.newsController.copyIssuePrompt(root.preferencesController.state,
                                                                                          root.readingSnapshot.clippings),
                                                           "新闻生成提示已复制。")
                                        }
                                        NewsActionButton {
                                            objectName: "newsExportIssueButtonWorkspace"
                                            text: qsTr("导出本期 JSON")
                                            enabled: Boolean(newsCard.activeIssue)
                                            onClicked: {
                                                newsCard.clearNotice()
                                                newsExportDialog.open()
                                            }
                                        }
                                    }
                                    Rectangle {
                                        id: newsDropZone
                                        property bool hovering: false
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 54
                                        color: hovering ? "#eaf0fc" : "#f8fafb"
                                        border.color: hovering ? root.blue : root.line
                                        border.width: hovering ? 2 : 1
                                        RootText {
                                            anchors.fill: parent
                                            anchors.margins: 7
                                            objectName: "newsWorkspaceDropHint"
                                            text: qsTr("把 .json 文件拖入以预览；把 HTTP(S) 网页链接拖入本地素材箱。链接不会被抓取或发布。")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                            wrapMode: Text.WordWrap
                                        }
                                        DropArea {
                                            id: newsDropArea
                                            objectName: "newsDropArea"
                                            anchors.fill: parent
                                            onEntered: newsDropZone.hovering = true
                                            onExited: newsDropZone.hovering = false
                                            onDropped: function(drop) {
                                                newsDropZone.hovering = false
                                                newsCard.handleDrop(drop)
                                                drop.acceptProposedAction()
                                            }
                                        }
                                    }
                                    RootText {
                                        visible: newsCard.notice.length > 0
                                        objectName: "newsWorkspaceNotice"
                                        text: qsTr(newsCard.notice)
                                        color: newsCard.noticeIsError ? root.red : "#4d7455"
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    ScrollView {
                                        id: newsWorkspaceScroll
                                        objectName: "newsWorkspaceScroll"
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        Layout.minimumHeight: 130
                                        clip: true
                                        WheelHandler {
                                            target: null
                                            blocking: true
                                            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                            onWheel: function(event) {
                                                let delta = event.pixelDelta.y !== 0
                                                        ? event.pixelDelta.y
                                                        : event.angleDelta.y / 120 * 48
                                                if (event.inverted)
                                                    delta = -delta
                                                if (delta === 0) {
                                                    event.accepted = true
                                                    return
                                                }

                                                const inner = newsWorkspaceScroll.contentItem
                                                const outer = root.flowScrollContent
                                                if (!inner || !outer) {
                                                    event.accepted = false
                                                    return
                                                }
                                                const innerMax = Math.max(
                                                            0,
                                                            inner.contentHeight - inner.height)
                                                const currentInnerY = inner.contentY
                                                const requestedInnerY = currentInnerY - delta
                                                const nextInnerY = Math.max(
                                                            0,
                                                            Math.min(innerMax, requestedInnerY))
                                                const unconsumedMovement = -delta
                                                        - (nextInnerY - currentInnerY)
                                                inner.contentY = nextInnerY

                                                if (Math.abs(unconsumedMovement) > 0.01) {
                                                    const outerMax = Math.max(
                                                                0,
                                                                outer.contentHeight - outer.height)
                                                    outer.contentY = Math.max(
                                                                0,
                                                                Math.min(outerMax,
                                                                         outer.contentY + unconsumedMovement))
                                                }
                                                event.accepted = true
                                            }
                                        }
                                        ColumnLayout {
                                            width: newsWorkspaceScroll.availableWidth
                                            spacing: 8
                                            Rectangle {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 54
                                                color: "#f8fafb"
                                                border.color: root.line
                                                ColumnLayout {
                                                    anchors.fill: parent
                                                    anchors.margins: 8
                                                    spacing: 2
                                                    RootText {
                                                        text: qsTr("当前已发布")
                                                        color: root.blue
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                    }
                                                    RootText {
                                                        objectName: "newsWorkspaceIssueDescription"
                                                        text: newsCard.issueDescription(newsCard.activeIssue)
                                                        color: newsCard.activeIssue ? root.ink : root.muted
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        wrapMode: Text.WordWrap
                                                        Layout.fillWidth: true
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 5
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 2
                                                    RootText {
                                                        text: qsTr("草稿与排序")
                                                        color: "#33434a"
                                                        font.family: root.serifFamily
                                                        font.pixelSize: 14
                                                        font.bold: true
                                                    }
                                                    RootText {
                                                        objectName: "newsWorkspaceDraftSaveStatus"
                                                        text: newsCard.draftIssue
                                                              ? (newsCard.draftUnsaved
                                                                 ? qsTr("预览未保存 · 保存后才写入本机")
                                                                 : qsTr("草稿已保存到本机"))
                                                              : qsTr("尚无草稿")
                                                        color: newsCard.draftUnsaved ? root.red : root.blue
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                        wrapMode: Text.WordWrap
                                                        Layout.fillWidth: true
                                                    }
                                                    RootText {
                                                        text: newsCard.draftIssue
                                                              ? newsCard.issueDescription(newsCard.draftIssue)
                                                              : qsTr("尚无草稿；导入 JSON 或载入历史刊期开始编辑。")
                                                        color: root.muted
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        wrapMode: Text.WordWrap
                                                        Layout.fillWidth: true
                                                    }
                                                }
                                                NewsActionButton {
                                                    objectName: "newsSaveDraftButton"
                                                    text: newsCard.draftUnsaved ? qsTr("保存草稿") : qsTr("已保存草稿")
                                                    enabled: Boolean(newsCard.draftIssue && newsCard.draftUnsaved)
                                                    onClicked: newsCard.showResult(root.newsController.saveDraft(), "草稿已保存到本机。")
                                                }
                                                NewsActionButton {
                                                    objectName: "newsPublishButton"
                                                    text: qsTr("发布本期")
                                                    enabled: Boolean(newsCard.draftIssue)
                                                    highlighted: true
                                                    onClicked: newsCard.openPublishConfirmation(false)
                                                }
                                            }
                                            RowLayout {
                                                objectName: "newsRecommendationControls"
                                                Layout.fillWidth: true
                                                spacing: 5
                                                NewsActionButton {
                                                    objectName: "newsGenerateRecommendationButton"
                                                    text: qsTr("生成推荐建议")
                                                    enabled: Boolean(newsCard.draftIssue)
                                                    onClicked: newsCard.showResult(
                                                                   root.newsController.recommendDraft(
                                                                       root.preferencesController.state,
                                                                       root.readingSnapshot.clippings),
                                                                   "已生成组内推荐顺序和理由；草稿尚未修改。")
                                                }
                                                NewsActionButton {
                                                    objectName: "newsApplyRecommendationButton"
                                                    text: qsTr("采用建议排序")
                                                    enabled: Boolean(newsCard.draftIssue
                                                                     && newsCard.stateSnapshot.recommendationSuggestions
                                                                     && newsCard.stateSnapshot.recommendationSuggestions.groups)
                                                    onClicked: newsCard.showResult(
                                                                   root.newsController.applyRecommendation(),
                                                                   "推荐顺序已应用到草稿，可继续手动调整。")
                                                }
                                                NewsActionButton {
                                                    objectName: "newsClearRecommendationButton"
                                                    text: qsTr("清除文章反馈")
                                                    onClicked: clearRecommendationFeedbackDialog.open()
                                                }
                                            }
                                            RootText {
                                                text: qsTr("建议只在原有分组内排序；保存或发布前仍可用上下箭头手动调整。清除反馈不会删除关注设置或剪报。")
                                                color: root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                                Layout.fillWidth: true
                                            }
                                            NewsHistoryComboBox {
                                                id: newsHistorySelector
                                                objectName: "newsHistorySelector"
                                                Layout.fillWidth: true
                                                model: [qsTr("选择历史刊期并载入草稿…")].concat(newsCard.historyLabels())
                                                onActivated: function(index) {
                                                    newsCard.requestHistoryLoad(index)
                                                }
                                            }
                                            RootText {
                                                visible: !newsCard.draftIssue
                                                text: newsCard.activeIssue
                                                      ? qsTr("已发布内容可从上方历史列表载入；当前没有待编辑草稿。")
                                                      : qsTr("导入后会先校验并预览，不会直接发布。")
                                                color: root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                                Layout.fillWidth: true
                                            }
                                            Repeater {
                                                model: newsCard.orderedGroups()
                                                delegate: ColumnLayout {
                                                    id: newsGroupBlock
                                                    required property var modelData
                                                    property var groupItems: newsCard.itemsFor(newsCard.draftIssue || newsCard.activeIssue, modelData.key)
                                                    visible: !newsCard.isGroupHidden(modelData.key) && groupItems.length > 0
                                                    Layout.fillWidth: true
                                                    spacing: 5
                                                    RootText {
                                                        text: qsTr("%1 · %2 条").arg(newsGroupBlock.modelData.label).arg(newsGroupBlock.groupItems.length)
                                                        color: root.red
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                        Layout.fillWidth: true
                                                    }
                                                    RootText {
                                                        property var suggestionRows: {
                                                            const suggestionState = newsCard.stateSnapshot.recommendationSuggestions || ({})
                                                            const groups = suggestionState.groups || ({})
                                                            return groups[newsGroupBlock.modelData.key] || []
                                                        }
                                                        visible: Boolean(newsCard.draftIssue && suggestionRows.length)
                                                        text: {
                                                            const titles = []
                                                            for (let rankIndex = 0; rankIndex < suggestionRows.length; rankIndex++) {
                                                                const itemId = suggestionRows[rankIndex].id
                                                                for (let itemIndex = 0; itemIndex < newsGroupBlock.groupItems.length; itemIndex++) {
                                                                    const candidate = newsGroupBlock.groupItems[itemIndex]
                                                                    if (String(candidate.id || "") === String(itemId)) {
                                                                        titles.push(newsCard.itemTitle(candidate))
                                                                        break
                                                                    }
                                                                }
                                                            }
                                                        return qsTr("建议顺序：%1").arg(titles.join(" → "))
                                                    }
                                                    color: root.blue
                                                    font.family: root.sansFamily
                                                    font.pixelSize: 12
                                                        wrapMode: Text.Wrap
                                                        Layout.fillWidth: true
                                                    }
                                                    Repeater {
                                                        model: newsGroupBlock.groupItems
                                                        delegate: Rectangle {
                                                            required property var modelData
                                                            required property int index
                                                            Layout.fillWidth: true
                                                            implicitHeight: newsItemText.implicitHeight + 20
                                                            color: "#fbfcfd"
                                                            border.color: root.line
                                                            RowLayout {
                                                                anchors.fill: parent
                                                                anchors.margins: 7
                                                                spacing: 6
                                                                ColumnLayout {
                                                                    id: newsItemText
                                                                    Layout.fillWidth: true
                                                                    spacing: 3
                                                                    RootText {
                                                                        objectName: "newsIssueTitle_" + modelData.id
                                                                        text: newsCard.itemTitle(modelData)
                                                                        color: root.ink
                                                                        font.family: root.sansFamily
                                                                        font.pixelSize: 12
                                                                        font.bold: true
                                                                        wrapMode: Text.WordWrap
                                                                        maximumLineCount: 3
                                                                        elide: Text.ElideRight
                                                                        Layout.fillWidth: true
                                                                    }
                                                                    RootText {
                                                                        objectName: "newsIssueSummary_" + modelData.id
                                                                        visible: Boolean(modelData.summary)
                                                                        text: modelData.summary || ""
                                                                        color: root.muted
                                                                        font.family: root.sansFamily
                                                                        font.pixelSize: 12
                                                                        wrapMode: Text.WordWrap
                                                                        maximumLineCount: 3
                                                                        elide: Text.ElideRight
                                                                        Layout.fillWidth: true
                                                                    }
                                                                    RootText {
                                                                        visible: Boolean(modelData.publisher || modelData.publishedAt)
                                                                        text: [modelData.publisher || "", modelData.publishedAt || ""].filter(Boolean).join(" · ")
                                                                        color: root.muted
                                                                        font.family: root.sansFamily
                                                                        font.pixelSize: 12
                                                                        Layout.fillWidth: true
                                                                        elide: Text.ElideRight
                                                                    }
                                                                    RootText {
                                                                        property var suggestion: {
                                                                            const suggestionState = newsCard.stateSnapshot.recommendationSuggestions || ({})
                                                                            const groups = suggestionState.groups || ({})
                                                                            const rows = groups[newsGroupBlock.modelData.key] || []
                                                                            for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                                                                                if (String(rows[rowIndex].id || "") === String(modelData.id || ""))
                                                                                    return rows[rowIndex]
                                                                            }
                                                                            return null
                                                                        }
                                                                        visible: Boolean(newsCard.draftIssue && suggestion)
                                                                        text: suggestion
                                                                              ? (qsTr("推荐第 %1 位").arg(suggestion.rank) + " · " + suggestion.reason)
                                                                              : ""
                                                                        color: root.blue
                                                                        font.family: root.sansFamily
                                                                        font.pixelSize: 12
                                                                        wrapMode: Text.WordWrap
                                                                        Layout.fillWidth: true
                                                                    }
                                                                    NewsActionButton {
                                                                        objectName: "newsReadArticle_" + newsGroupBlock.modelData.key + "_" + index
                                                                        text: qsTr("阅读全文")
                                                                        Layout.alignment: Qt.AlignLeft
                                                                        onClicked: root.openArticle(
                                                                                       modelData,
                                                                                       newsCard.draftIssue || newsCard.activeIssue || ({}))
                                                                    }
                                                                }
                                            ColumnLayout {
                                                spacing: 2
                                                visible: Boolean(newsCard.draftIssue)
                                                NewsActionButton {
                                                    objectName: "newsMoveUp_" + newsGroupBlock.modelData.key + "_" + index
                                                    text: "↑"
                                                                        enabled: index > 0
                                                                        onClicked: newsCard.showResult(
                                                                                       root.newsController.moveDraftItem(newsGroupBlock.modelData.key, index, -1),
                                                                                       "条目顺序已调整。")
                                                }
                                                NewsActionButton {
                                                    objectName: "newsMoveDown_" + newsGroupBlock.modelData.key + "_" + index
                                                    text: "↓"
                                                                        enabled: index < newsGroupBlock.groupItems.length - 1
                                                                        onClicked: newsCard.showResult(
                                                                                       root.newsController.moveDraftItem(newsGroupBlock.modelData.key, index, 1),
                                                                                       "条目顺序已调整。")
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.line }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                RootText {
                                                    text: qsTr("本地链接素材箱 · %1").arg(newsCard.inboxItems.length)
                                                    color: "#33434a"
                                                    font.family: root.serifFamily
                                                    font.pixelSize: 13
                                                    font.bold: true
                                                    Layout.fillWidth: true
                                                }
                                                    RootText {
                                                        text: qsTr("仅保存链接，不抓取页面")
                                                        color: root.muted
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                }
                                            }
                                            RootText {
                                                visible: newsCard.inboxItems.length === 0
                                                text: qsTr("拖入 HTTP(S) 网页链接后，会列在这里供本机管理。")
                                                color: root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                wrapMode: Text.WordWrap
                                                Layout.fillWidth: true
                                            }
                                            Repeater {
                                                model: newsCard.inboxItems
                                                delegate: RowLayout {
                                                    required property var modelData
                                                    required property int index
                                                    Layout.fillWidth: true
                                                    TextEdit {
                                                        text: modelData.url || ""
                                                        color: root.blue
                                                        font.family: root.sansFamily
                                                        font.pixelSize: 12
                                                        readOnly: true
                                                        selectByMouse: true
                                                        wrapMode: TextEdit.NoWrap
                                                        clip: true
                                                        Layout.fillWidth: true
                                                        Layout.preferredHeight: 18
                                                    }
                                                    NewsActionButton {
                                                        objectName: "newsLinkOpen_" + index
                                                        Accessible.name: qsTr("打开素材链接")
                                                        text: qsTr("打开")
                                                        onClicked: Qt.openUrlExternally(String(modelData.url || ""))
                                                    }
                                                    NewsActionButton {
                                                        objectName: "newsLinkRemove_" + index
                                                        text: qsTr("移除")
                                                        onClicked: newsCard.showResult(
                                                                       root.newsController.removeLink(index),
                                                                       "链接已从本地素材箱移除。")
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    objectName: "newsWorkspaceCollapsed"
                                    visible: !newsCard.workspaceExpanded
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 7
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            text: qsTr("本机刊期编辑工作台")
                                            color: "#20303d"
                                            font.family: root.serifFamily
                                            font.pixelSize: 17
                                            font.bold: true
                                            Layout.fillWidth: true
                                        }
                                        NewsActionButton {
                                            objectName: "newsWorkspaceExpandButton"
                                            text: qsTr("打开编辑工作台")
                                            highlighted: true
                                            onClicked: newsCard.workspaceExpanded = true
                                        }
                                    }
                                    RootText {
                                        text: qsTr("刊期草稿、排序和本地素材管理已收起；展开后继续编辑。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 54
                            color: "transparent"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 10
                                spacing: 12
                                Rectangle {
                                    Layout.preferredWidth: 31
                                    Layout.preferredHeight: 31
                                    radius: 16
                                    color: "transparent"
                                    border.color: root.red
                                    RootText { anchors.centerIn: parent; text: "刊"; color: root.red; font.family: root.serifFamily; font.pixelSize: 15; font.bold: true }
                                }
                                    RootText {
                                        text: qsTr("每日一刊 · JSON 导入先预览；草稿、发布和历史刊期保存在本机；低频设置在工作台“更多”中。")
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        Rectangle {
                            id: newsIssueContentHeaderItem
                            objectName: "newsIssueContentHeader"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 46
                            height: 46
                            visible: root.homeLayoutCardVisible("briefs")
                                     && Boolean(newsCard.draftIssue || newsCard.activeIssue)
                            color: "#ffffff"
                            border.color: root.line
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 15
                                anchors.rightMargin: 15
                                RootText { text: qsTr("本期内容"); color: "#33434a"; font.family: root.serifFamily; font.pixelSize: 15; font.bold: true; Layout.fillWidth: true }
                                RootText {
                                    text: newsCard.draftIssue ? qsTr("草稿待编辑 / 发布")
                                          : (newsCard.activeIssue ? qsTr("已载入已发布刊期") : qsTr("尚未载入本期新闻"))
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        ColumnLayout {
                            id: homeLayoutDeck
                            objectName: "homeLayoutDeck"
                            Layout.fillWidth: true
                            Layout.leftMargin: root.compactNavigation ? 20 : 42
                            Layout.rightMargin: root.compactNavigation ? 20 : 42
                            Layout.bottomMargin: 20
                            spacing: 12

                            ColumnLayout {
                                objectName: "homeLayoutGroup_flow-briefing-slot"
                                visible: root.homeLayoutSlotHasVisibleCards("flow-briefing-slot")
                                Layout.fillWidth: true
                                spacing: 4
                                RootText {
                                    text: qsTr("今日速览")
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 11
                                    Layout.fillWidth: true
                                }
                                Flow {
                                    id: homeLayoutBriefingCards
                                    objectName: "homeLayoutCards_flow-briefing-slot"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: childrenRect.height
                                    spacing: 8
                                }
                            }
                            ColumnLayout {
                                objectName: "homeLayoutGroup_flow-review-slot"
                                visible: root.homeLayoutSlotHasVisibleCards("flow-review-slot")
                                Layout.fillWidth: true
                                spacing: 4
                                RootText {
                                    text: qsTr("昨日回顾")
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 11
                                    Layout.fillWidth: true
                                }
                                Flow {
                                    id: homeLayoutReviewCards
                                    objectName: "homeLayoutCards_flow-review-slot"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: childrenRect.height
                                    spacing: 8
                                }
                            }
                            ColumnLayout {
                                objectName: "homeLayoutGroup_flow-work-slot"
                                visible: root.homeLayoutSlotHasVisibleCards("flow-work-slot")
                                Layout.fillWidth: true
                                spacing: 4
                                RootText {
                                    text: qsTr("今日工作")
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 11
                                    Layout.fillWidth: true
                                }
                                Flow {
                                    id: homeLayoutWorkCards
                                    objectName: "homeLayoutCards_flow-work-slot"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: childrenRect.height
                                    spacing: 8
                                }
                            }
                        }

                        DailyFlowPage {
                            id: dailyFlowPageItem
                            objectName: "dailyFlowPage"
                            uiTheme: root.theme
                            Layout.fillWidth: true
                            Layout.preferredHeight: implicitHeight
                            Layout.minimumHeight: implicitHeight
                            controller: root.dailyController
                            plannerBridge: root.plannerController
                            homeLayoutController: root.homeLayoutController
                        }

                        Flow {
                            objectName: "dailyArchiveSummaryCards"
                            Layout.fillWidth: true
                            Layout.leftMargin: root.compactNavigation ? 20 : 42
                            Layout.rightMargin: root.compactNavigation ? 20 : 42
                            Layout.bottomMargin: 20
                            Layout.preferredHeight: childrenRect.height
                            spacing: 12
                            visible: root.homeLayoutCardVisible("weekly")
                                     || root.homeLayoutCardVisible("recent")

                            Rectangle {
                                id: dailyWeeklyCardItem
                                objectName: "dailyWeeklyCard"
                                visible: root.homeLayoutCardVisible("weekly")
                                width: root.compactNavigation ? parent.width : (parent.width - parent.spacing) / 2
                                height: 114
                                radius: uiTheme.radiusLarge
                                color: uiTheme.surface
                                border.color: uiTheme.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 13
                                    spacing: 6
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            text: qsTr("我的一周")
                                            color: root.ink
                                            font.family: root.serifFamily
                                            font.pixelSize: 15
                                            font.bold: true
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            text: qsTr("本周")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    RootText {
                                        text: qsTr("%1 条记录").arg(String(root.homeLayoutWeekSummary().count))
                                        color: root.blue
                                        font.family: root.serifFamily
                                        font.pixelSize: 21
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    RootText {
                                        text: root.homeLayoutWeekSummary().count > 0
                                              ? qsTr("%1 天留下记录 · 习惯打卡 %2 次")
                                                .arg(String(root.homeLayoutWeekSummary().activeDays))
                                                .arg(String(root.homeLayoutWeekSummary().habitCheckIns))
                                              : qsTr("还没有记录，想起什么就记下来。")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                    }
                                    NewsActionButton {
                                        objectName: "dailyWeeklyOpenArchiveButton"
                                        text: qsTr("打开时光档案")
                                        onClicked: root.currentSectionIndex = 7
                                    }
                                }
                            }

                            Rectangle {
                                id: dailyRecentCardItem
                                objectName: "dailyRecentCard"
                                visible: root.homeLayoutCardVisible("recent")
                                width: root.compactNavigation ? parent.width : (parent.width - parent.spacing) / 2
                                height: Math.max(114, dailyRecentContent.implicitHeight + 24)
                                radius: uiTheme.radiusLarge
                                color: uiTheme.surface
                                border.color: uiTheme.line
                                ColumnLayout {
                                    id: dailyRecentContent
                                    anchors.fill: parent
                                    anchors.margins: 13
                                    spacing: 6
                                    RowLayout {
                                        Layout.fillWidth: true
                                        RootText {
                                            text: qsTr("上周与更早")
                                            color: root.ink
                                            font.family: root.serifFamily
                                            font.pixelSize: 15
                                            font.bold: true
                                            Layout.fillWidth: true
                                        }
                                        RootText {
                                            text: qsTr("时光档案")
                                            color: root.muted
                                            font.family: root.sansFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    RootText {
                                        visible: dailyRecentRecords.count === 0
                                        text: qsTr("第一条记录，会从这里开始")
                                        color: root.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Repeater {
                                        id: dailyRecentRecords
                                        objectName: "dailyRecentRecords"
                                        model: root.homeLayoutRecentRecords()
                                        delegate: RowLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 8
                                            RootText {
                                                text: String(modelData.date || "")
                                                color: root.muted
                                                font.family: root.sansFamily
                                                font.pixelSize: 11
                                                Layout.preferredWidth: 76
                                            }
                                            RootText {
                                                text: root.homeLayoutRecordTitle(modelData)
                                                color: root.ink
                                                font.family: root.sansFamily
                                                font.pixelSize: 12
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                    NewsActionButton {
                                        objectName: "dailyRecentOpenArchiveButton"
                                        text: qsTr("打开时光档案")
                                        onClicked: root.currentSectionIndex = 7
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            id: dailyHabitQuickChecksItem
                            objectName: "dailyHabitQuickChecks"
                            visible: root.homeLayoutCardVisible("habits")
                            Layout.fillWidth: true
                            Layout.leftMargin: root.compactNavigation ? 20 : 42
                            Layout.rightMargin: root.compactNavigation ? 20 : 42
                            Layout.topMargin: 8
                            Layout.bottomMargin: 30
                            spacing: 9

                            RowLayout {
                                Layout.fillWidth: true
                                RootText {
                                    text: qsTr("习惯打卡")
                                    color: "#33434a"
                                    font.family: root.serifFamily
                                    font.pixelSize: 15
                                    font.bold: true
                                    Layout.fillWidth: true
                                }
                                RootText {
                                    text: {
                                        const state = root.habitController.state || {}
                                        const metrics = state.metrics || {}
                                        return (metrics.todayCompleted || 0) + " / "
                                                + (metrics.totalHabits || 0) + " 已完成"
                                    }
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                }
                            }
                            RootText {
                                visible: root.dailyHabitsForToday().length === 0
                                text: ((root.habitController.state || {}).habits || []).length
                                      ? "今天没有计划打卡的习惯，休息日不会影响连续记录。"
                                      : "暂无习惯。迁移旧版数据后，或在“习惯健康”中添加习惯。"
                                color: root.muted
                                font.family: root.sansFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            GridLayout {
                                id: dailyHabitQuickGrid
                                objectName: "dailyHabitQuickGrid"
                                Layout.fillWidth: true
                                columns: root.compactNavigation ? 1 : 2
                                columnSpacing: 12
                                rowSpacing: 8

                                Repeater {
                                    model: root.dailyHabitsForToday().slice(0, 5)
                                    delegate: Rectangle {
                                        required property var modelData
                                        required property int index
                                        objectName: "dailyHabitQuickCard_" + index
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 62
                                        radius: root.theme.radiusSmall
                                        color: root.theme.surface
                                        border.color: root.line

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 12
                                            spacing: 12

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                RootText {
                                                    Layout.fillWidth: true
                                                    text: modelData.name || "未命名习惯"
                                                    color: root.ink
                                                    font.family: root.sansFamily
                                                    font.pixelSize: 13
                                                    font.bold: true
                                                    elide: Text.ElideRight
                                                }
                                                RootText {
                                                    Layout.fillWidth: true
                                                    text: {
                                                        const value = root.dailyHabitValue(modelData)
                                                        return value + " / " + Number(modelData.target || 1)
                                                                + " " + String(modelData.unit || "")
                                                    }
                                                    color: root.muted
                                                    font.family: root.sansFamily
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                }
                                            }

                                            NewsActionButton {
                                                objectName: "dailyHabitQuickButton_" + index
                                                Layout.alignment: Qt.AlignVCenter
                                                text: root.dailyHabitButtonLabel(modelData)
                                                highlighted: root.dailyHabitIsComplete(modelData)
                                                onClicked: root.activateDailyHabit(modelData)
                                            }
                                        }
                                    }
                                }
                            }
                            RootText {
                                objectName: "dailyHabitQuickOverflowHint"
                                visible: root.dailyHabitsForToday().length > 5
                                text: qsTr("首页显示前 5 项；还有 %1 项，请打开“习惯健康”查看全部。")
                                      .arg(String(root.dailyHabitsForToday().length - 5))
                                color: root.muted
                                font.family: root.sansFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            RootText {
                                visible: String((root.habitController.state || {}).notice || "") !== ""
                                text: String((root.habitController.state || {}).notice || "")
                                color: root.red
                                font.family: root.sansFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            NewsActionButton {
                                text: qsTr("打开习惯健康")
                                onClicked: root.currentSectionIndex = 2
                            }
                        }

                        ColumnLayout {
                            id: dailyQuickAddCardItem
                            objectName: "dailyQuickAddCard"
                            visible: root.homeLayoutCardVisible("quick")
                            Layout.fillWidth: true
                            Layout.leftMargin: root.compactNavigation ? 20 : 42
                            Layout.rightMargin: root.compactNavigation ? 20 : 42
                            Layout.bottomMargin: 30
                            spacing: 9

                            RowLayout {
                                Layout.fillWidth: true
                                RootText {
                                    text: qsTr("给今天留个注脚")
                                    color: "#33434a"
                                    font.family: root.serifFamily
                                    font.pixelSize: 15
                                    font.bold: true
                                    Layout.fillWidth: true
                                }
                                RootText {
                                    text: qsTr("随手记")
                                    color: root.muted
                                    font.family: root.sansFamily
                                    font.pixelSize: 12
                                }
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 9
                                NewsActionButton {
                                    objectName: "dailyQuickMoneyButton"
                                    text: qsTr("记一笔")
                                    onClicked: root.openQuickEntry("money")
                                }
                                NewsActionButton {
                                    objectName: "dailyQuickFitnessButton"
                                    text: qsTr("记体重")
                                    onClicked: root.openQuickEntry("fitness")
                                }
                                NewsActionButton {
                                    objectName: "dailyQuickShoppingButton"
                                    text: qsTr("待买物品")
                                    onClicked: root.openQuickEntry("home")
                                }
                            }
                        }
                }
                }
                }

                FinancePage {
                    id: financePageItem
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 1
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.financeController
                }

                HabitPage {
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 2
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.habitController
                }

                FitnessPage {
                    id: fitnessPageItem
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 3
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.fitnessController
                }

                PlannerPage {
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 4
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.plannerController
                    webdavController: root.webdavPlannerController
                }

                ShoppingPage {
                    id: shoppingPageItem
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 5
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.shoppingController
                }

                MediaPage {
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 6
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.mediaController
                }

                ArchivePage {
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 7
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.archiveController
                    onNavigateToSection: function(sectionIndex) { root.currentSectionIndex = sectionIndex }
                }

                ConverterPage {
                    uiTheme: root.theme
                    visible: root.currentSectionIndex === 8
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    controller: root.converterController
                    engineController: root.converterEngineController
                }
            }

            Rectangle {
                id: bottomNav
                visible: root.compactNavigation
                Layout.fillWidth: true
                Layout.preferredHeight: 73
                color: uiTheme.surface
                border.color: uiTheme.line
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 5
                    anchors.rightMargin: 5
                    spacing: 0
                    Repeater {
                        model: [
                            { label: qsTr("今日"), icon: "home" },
                            { label: qsTr("记账"), icon: "wallet" },
                            { label: qsTr("习惯"), icon: "habit" },
                            { label: qsTr("健身"), icon: "fitness" },
                            { label: qsTr("日程"), icon: "calendar" },
                            { label: qsTr("待买"), icon: "cart" },
                            { label: qsTr("书影音"), icon: "books" },
                            { label: qsTr("档案"), icon: "archive" },
                            { label: qsTr("转换"), icon: "convert" }
                        ]
                            delegate: Button {
                                id: compactNavButton
                                required property var modelData
                                required property int index
                                objectName: "bottomNav_" + index
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                padding: 2
                                Accessible.name: modelData.label
                                contentItem: ColumnLayout {
                                    spacing: 2
                                    AppIcon {
                                        name: compactNavButton.modelData.icon
                                        color: compactNavButton.index === root.currentSectionIndex ? uiTheme.accentStrong : uiTheme.muted
                                        Layout.preferredWidth: 18
                                        Layout.preferredHeight: 18
                                        Layout.alignment: Qt.AlignHCenter
                                    }
                                    RootText {
                                        text: compactNavButton.modelData.label
                                        color: compactNavButton.index === root.currentSectionIndex ? uiTheme.accentStrong : uiTheme.muted
                                        font.family: root.sansFamily
                                        font.pixelSize: 12
                                        horizontalAlignment: Text.AlignHCenter
                                        Layout.fillWidth: true
                                    }
                                }
                                background: Rectangle {
                                    radius: 8
                                    color: compactNavButton.index === root.currentSectionIndex ? uiTheme.accentSoft : "transparent"
                                    border.color: compactNavButton.activeFocus ? uiTheme.accent : "transparent"
                                    border.width: compactNavButton.activeFocus ? 2 : 1
                                }
                                onClicked: root.currentSectionIndex = index
                            }
                    }
                }
            }
        }
    }
}
