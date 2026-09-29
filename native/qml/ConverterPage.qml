pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Pdf
import QtMultimedia

Item {
    id: page
    objectName: "converterPage"
    required property var controller
    required property var engineController
    property var uiTheme: null
    property bool formatLimitsExpanded: false
    property string selectedCommonTargetFormat: ""
    property string commonTargetMessage: ""
    property string imageFolderMessage: ""
    property int skippedMergePdfCount: 0
    property var mergeExcludedItems: []
    property bool mergeExcludedExpanded: false
    property string mergePdfNotice: ""
    property string mergeMode: "pdf"
    property string previewKind: ""
    property string previewUrl: ""
    property string previewText: ""
    property string previewTitle: ""
    property bool previewTruncated: false
    property string discardAction: ""
    property string discardJobId: ""
    property string discardMessage: ""

    ConverterEnginesDialog {
        id: enginesDialog
        controller: page.engineController
        uiTheme: page.uiTheme
    }

    readonly property color canvas: uiTheme ? uiTheme.canvas : "#f6f5f0"
    readonly property color surface: uiTheme ? uiTheme.surface : "#fffefa"
    readonly property color surfaceSoft: uiTheme ? uiTheme.surfaceSoft : "#f4f2ec"
    readonly property color line: uiTheme ? uiTheme.line : "#e2dfd7"
    readonly property color ink: uiTheme ? uiTheme.ink : "#273239"
    readonly property color muted: uiTheme ? uiTheme.muted : "#586569"
    readonly property color accent: uiTheme ? uiTheme.accent : "#456b73"
    readonly property color accentStrong: uiTheme ? uiTheme.accentStrong : "#315761"
    readonly property color accentSoft: uiTheme ? uiTheme.accentSoft : "#e6efee"
    readonly property color success: uiTheme ? uiTheme.success : "#3d654e"
    readonly property color successSoft: uiTheme ? uiTheme.successSoft : "#eaf2ec"
    readonly property color warning: uiTheme ? uiTheme.warning : "#80531b"
    readonly property color warningSoft: uiTheme ? uiTheme.warningSoft : "#f6efe2"
    readonly property color danger: uiTheme ? uiTheme.danger : "#9d4038"
    readonly property color dangerSoft: uiTheme ? uiTheme.dangerSoft : "#f8eae7"
    readonly property string fontFamily: uiTheme ? uiTheme.sansFamily : "Noto Sans SC"
    readonly property var videoTargetFormats: ["mp4", "mkv", "mov", "webm", "avi"]
    readonly property var formatLimitSections: [
        {
            title: qsTr("文本与电子书"),
            body: qsTr("EPUB 按章节提取文字并简化复杂样式，不保留书中图片；含加密资源或不安全路径的文件会拒绝处理。TXT 支持 UTF-8、GB18030 和带 BOM 的 UTF-16；超出本机上限的文件会被拒绝。PDF→Word 按页面坐标生成可编辑文字；安装包内置 Tesseract 简体中文和英文模型，可识别扫描页。此方式不嵌入 PDF 图片和矢量图，复杂多栏或旋转内容可能需要人工调整。安装包内置 Calibre，可将无 DRM 的 MOBI 转为 EPUB、PDF、DOCX 或 TXT；两个引擎都可单独检查更新。")
        },
        {
            title: qsTr("PDF"),
            body: qsTr("可合并队列中的未加密 PDF、按页或每 N 页拆分为 ZIP、导出全部页面图片 ZIP，也可用 AES-256 加密或输入原密码解密。多张图片可排序后合成为多页 PDF，也可把文件夹中的图片按文件名顺序生成 PDF；ZIP 图片包也可转换为 PDF。PDF 还可转换为图片（仅第一页）或提取表格与页面正文；安装包内置 Tesseract 简体中文和英文模型，可识别扫描表格并标注单元格置信度，相邻页同列结构会尝试续接。列对齐不稳定、复杂跨页结构和合并单元格需要人工检查。也可生成带文字层的可搜索 PDF。密码只在本机内存中短暂使用，不写入任务记录，任务结束后清除。")
        },
        {
            title: qsTr("图片"),
            body: qsTr("导出为静态图片时只取首帧；可读取的动图在输出 GIF 或 WebP 时保留动画帧与时长。ICO 输出包含 16、24、32、48、64、128、256 像素图标，不足正方形的图片会透明补边。多张图片可以按顺序合成为多页 PDF。")
        },
        {
            title: qsTr("音视频"),
            body: qsTr("安装包已内置 FFmpeg，可离线转换；发布更新后可在“转换引擎”中检查并安装新版本。格式列表按当前编码器支持情况显示。只处理第一条音轨和视频流，不保留字幕、多音轨或复杂章节信息。")
        },
        {
            title: qsTr("Word、Excel 与 PowerPoint"),
            body: qsTr("检测到对应的 Microsoft Office 或 WPS 桌面程序时，PDF 转换会调用本机程序；宏不会运行，Word 和 Excel 不更新外部链接。未安装所需程序时，对应目标格式不会显示。Word 文档的复杂版式、图片、字体、批注和复杂对象不保证保留。")
        },
        {
            title: qsTr("表格"),
            body: qsTr("XLSX 格式转换只读取第一个工作表，不保留样式、图表或公式计算结果；Office 导出 PDF 按工作簿打印设置处理。首行用作列名，重复或空列名会整理；导出 CSV 时可能被识别为公式的文本会加前缀，以降低打开风险。")
        }
    ]

    function countReady() {
        let count = 0
        const rows = controller ? controller.jobs : []
        for (let i = 0; i < rows.length; i++)
            if (rows[i].status === "ready") count++
        return count
    }
    function countReadyConversions() {
        let count = 0
        const rows = controller ? controller.jobs : []
        for (let i = 0; i < rows.length; i++)
            if (rows[i].status === "ready" && rows[i].taskType === "convert" && rows[i].canConvert) count++
        return count
    }
    function countFinished() {
        let count = 0
        const rows = controller ? controller.jobs : []
        for (let i = 0; i < rows.length; i++)
            if (rows[i].status === "done" || rows[i].status === "failed" || rows[i].status === "unsupported") count++
        return count
    }
    function countUnsaved() {
        let count = 0
        const rows = controller ? controller.jobs : []
        for (let i = 0; i < rows.length; i++)
            if (rows[i].status === "done" && Boolean(rows[i].stagedPath) && !rows[i].savePending) count++
        return count
    }
    function saveAllSummary() {
        const rows = controller ? controller.jobs : []
        const directories = []
        let count = 0
        for (let i = 0; i < rows.length; i++) {
            const row = rows[i]
            if (row.status !== "done" || !row.stagedPath || row.savePending)
                continue
            count++
            const directory = String(row.saveDirectory || "")
            if (directory && directories.indexOf(directory) === -1)
                directories.push(directory)
        }
        if (count === 0)
            return ""
        if (directories.length === 1)
            return qsTr("将保存 %1 项到：%2").arg(String(count)).arg(directories[0])
        return qsTr("将保存 %1 项到各自的计划位置").arg(String(count))
    }
    function requestClearFinished() {
        if (countUnsaved() === 0) {
            controller.clearFinished()
            return
        }
        discardAction = "clear"
        discardJobId = ""
        discardMessage = qsTr("清除已完成任务会一并丢弃 %1 个尚未保存的结果。继续吗？").arg(String(countUnsaved()))
        discardDialog.open()
    }
    function requestRemoveJob(job) {
        if (!job.stagedPath) {
            controller.removeJob(job.id)
            return
        }
        discardAction = "remove"
        discardJobId = job.id
        discardMessage = qsTr("移除此任务会丢弃尚未保存的转换结果。继续吗？")
        discardDialog.open()
    }
    function confirmDiscard() {
        if (discardAction === "clear")
            controller.clearFinished()
        else if (discardAction === "remove" && discardJobId !== "")
            controller.removeJob(discardJobId)
        discardAction = ""
        discardJobId = ""
        discardMessage = ""
    }
    function elapsedText(seconds) {
        const total = Math.max(0, Number(seconds || 0))
        const hours = Math.floor(total / 3600)
        const minutes = Math.floor((total % 3600) / 60)
        const remainder = Math.floor(total % 60)
        const pad = value => String(value).padStart(2, "0")
        return hours > 0 ? pad(hours) + ":" + pad(minutes) + ":" + pad(remainder)
                         : pad(minutes) + ":" + pad(remainder)
    }
    function openPreview(job) {
        const info = controller.previewInfo(job.id)
        if (!info || !info.kind || !info.url) return
        previewKind = info.kind
        previewUrl = info.url
        previewTitle = job.fileName
        const textInfo = info.kind === "text" ? controller.previewText(job.id) : {text: "", truncated: false}
        previewText = textInfo.text || ""
        previewTruncated = Boolean(textInfo.truncated)
        previewDialog.open()
    }
    function countMergeablePdfs() {
        let count = 0
        const rows = controller ? controller.jobs : []
        for (let i = 0; i < rows.length; i++) {
            const job = rows[i]
            if (job.taskType !== "pdf-merge" && job.canConvert && job.status !== "running" &&
                    job.status !== "unsupported" && job.targetFormat !== "pdf-decrypt" &&
                    String(job.sourcePath).toLowerCase().endsWith(".pdf"))
                count++
        }
        return count
    }
    function countMergeableImages() {
        const rows = controller ? controller.jobs : []
        if (rows.length < 2) return 0
        const preview = controller.imageMergeCandidates()
        return preview && preview.items ? preview.items.length : 0
    }

    function openPdfMergeDialog() {
        const preview = page.controller.pdfMergeCandidates()
        mergeMode = "pdf"
        mergePdfOrder.clear()
        skippedMergePdfCount = Number(preview.skipped || 0)
        mergeExcludedItems = preview.excluded || []
        mergeExcludedExpanded = false
        mergePdfNotice = ""
        const candidates = preview.items || []
        for (let index = 0; index < candidates.length; index++)
            mergePdfOrder.append(candidates[index])
        mergePdfDialog.open()
    }

    function openImageMergeDialog() {
        const preview = page.controller.imageMergeCandidates()
        mergeMode = "images"
        mergePdfOrder.clear()
        skippedMergePdfCount = Number(preview.skipped || 0)
        mergeExcludedItems = preview.excluded || []
        mergeExcludedExpanded = false
        mergePdfNotice = ""
        const candidates = preview.items || []
        for (let index = 0; index < candidates.length; index++)
            mergePdfOrder.append(candidates[index])
        mergePdfDialog.open()
    }

    function moveMergePdf(index, offset) {
        const target = index + offset
        if (target < 0 || target >= mergePdfOrder.count) return
        mergePdfOrder.move(index, target, 1)
    }

    function mergeExclusionReason(item) {
        const code = item && item.reasonCode ? String(item.reasonCode) : ""
        const pdfReasons = {
            running: qsTr("正在转换"),
            unsupported: qsTr("当前任务暂不支持"),
            not_convertible: qsTr("不是可合并的 PDF 任务"),
            decrypt_first: qsTr("当前任务需要先解密"),
            missing: qsTr("源文件已不存在"),
            invalid: qsTr("文件内容不是可读取的 PDF"),
            encrypted: qsTr("PDF 受密码保护"),
            unreadable: qsTr("无法读取 PDF")
        }
        const imageReasons = {
            running: qsTr("正在转换"),
            unsupported: qsTr("当前任务暂不支持"),
            not_convertible: qsTr("不是可合并的图片任务"),
            missing: qsTr("源文件已不存在"),
            too_large: qsTr("图片尺寸超过本机限制"),
            unreadable: qsTr("图片无法读取")
        }
        return (page.mergeMode === "pdf" ? pdfReasons : imageReasons)[code] || qsTr("当前文件未纳入合并")
    }

    function mergeExclusionAdvice(item) {
        const code = item && item.reasonCode ? String(item.reasonCode) : ""
        const pdfAdvice = {
            running: qsTr("等待当前任务完成后再合并"),
            unsupported: qsTr("检查转换组件或重新添加文件"),
            not_convertible: qsTr("重新添加原始 PDF"),
            decrypt_first: qsTr("先完成解密，再把解密后的 PDF 加入合并"),
            missing: qsTr("重新添加这个文件"),
            invalid: qsTr("重新导出或重新添加有效 PDF"),
            encrypted: qsTr("先输入密码解密，再合并解密后的 PDF"),
            unreadable: qsTr("检查文件是否损坏，再重新添加")
        }
        const imageAdvice = {
            running: qsTr("等待当前任务完成后再合并"),
            unsupported: qsTr("检查转换组件或重新添加文件"),
            not_convertible: qsTr("重新添加原始图片"),
            missing: qsTr("重新添加这个文件"),
            too_large: qsTr("缩小图片后再添加"),
            unreadable: qsTr("检查文件是否损坏，再重新添加")
        }
        return (page.mergeMode === "pdf" ? pdfAdvice : imageAdvice)[code] || qsTr("重新检查后再试")
    }

    function confirmPdfMerge() {
        const jobIds = []
        for (let index = 0; index < mergePdfOrder.count; index++)
            jobIds.push(mergePdfOrder.get(index).jobId)
        const result = page.mergeMode === "pdf"
                ? page.controller.mergePdfJobs(jobIds)
                : page.controller.mergeImagesToPdf(jobIds)
        if (!result || !result.ok) {
            mergePdfNotice = result && result.error
                    ? qsTr(String(result.error)) : qsTr("无法开始合并，请重新检查队列。")
            return
        }
        mergePdfDialog.close()
    }

    function formatLabel(option) {
        if (option.value === "xlsx" && option.label === "PDF 表格提取（XLSX）")
            return qsTr("PDF 表格提取（XLSX）")
        if (option.value === "gif-animation")
            return option.label === "GIF（保留动画帧）"
                    ? qsTr("GIF（保留动画帧）") : qsTr("GIF 图像")
        const labels = {
            bmp: qsTr("BMP"), cur: qsTr("CUR"), gif: qsTr("GIF first frame"), jpg: qsTr("JPEG"), jpeg: qsTr("JPEG"),
            png: qsTr("PNG"), icns: qsTr("ICNS"), ico: qsTr("ICO（多尺寸）"), svg: qsTr("SVG"), webp: qsTr("WebP"),
            tif: qsTr("TIFF"), tiff: qsTr("TIFF"), csv: qsTr("CSV"), tsv: qsTr("TSV"),
            json: qsTr("JSON"), xlsx: qsTr("Excel workbook (XLSX)"), txt: qsTr("Plain text (TXT)"),
            md: qsTr("Markdown (MD)"), html: qsTr("HTML document"), docx: qsTr("Word document (DOCX)"),
            pdf: qsTr("PDF document"), epub: qsTr("EPUB book"),
            "zip-images-pdf": qsTr("ZIP 图片包转 PDF"),
            zip: qsTr("按页或每 N 页拆分（ZIP）"),
            "pdf-images-zip": qsTr("全部页面图片（ZIP）"),
            "pdf-encrypt": qsTr("PDF password protection (AES-256)"),
        "pdf-decrypt": qsTr("Remove PDF password"),
        "pdf-ocr": qsTr("Searchable PDF (OCR)"),
        "image-ocr-txt": qsTr("Extract text (OCR)"),
            "pdf-merge": qsTr("Merged PDF"),
            "images-pdf": qsTr("PDF from ordered images"),
            mp3: qsTr("MP3 audio"), wav: qsTr("WAV audio"), flac: qsTr("FLAC audio"),
            m4a: qsTr("M4A audio"), aac: qsTr("AAC audio"), ogg: qsTr("OGG audio"),
            opus: qsTr("Opus audio"), wma: qsTr("WMA audio"), mp4: qsTr("MP4 video"),
            mkv: qsTr("MKV video"), mov: qsTr("MOV video"), webm: qsTr("WebM video"),
            avi: qsTr("AVI video")
        }
        const base = labels[option.value] || String(option.value).toUpperCase()
        const scoped = option.scope === "first-page"
                ? qsTr("%1 (first page only)").arg(base) : base
        const engines = {
            word: qsTr("Microsoft Word"), excel: qsTr("Microsoft Excel"),
            powerpoint: qsTr("Microsoft PowerPoint")
        }
        return option.engine ? qsTr("%1 · %2").arg(scoped).arg(engines[option.engine] || option.engine) : scoped
    }

    function formatsForPath(path) {
        const source = controller ? controller.formatsForPath(path) : []
        const localized = []
        for (let index = 0; index < source.length; index++)
            localized.push({value: source[index].value, scope: source[index].scope || "",
                            engine: source[index].engine || "", label: formatLabel(source[index])})
        return localized
    }

    function videoCodecLabel(value) {
        const labels = {
            h264: qsTr("H.264 / AVC"), h265: qsTr("H.265 / HEVC"), av1: qsTr("AV1"),
            vp9: qsTr("VP9"), mpeg4: qsTr("MPEG-4 Part 2"), msmpeg4v3: qsTr("MS MPEG-4 v3")
        }
        return labels[value] || String(value)
    }

    function videoCodecsForJob(jobId) {
        const source = controller ? controller.videoCodecsForJob(jobId) : []
        const localized = []
        for (let index = 0; index < source.length; index++)
            localized.push({value: source[index].value, label: videoCodecLabel(source[index].value)})
        return localized
    }

    FileDialog {
        id: inputDialog
        objectName: "converterInputFileDialog"
        title: qsTr("添加要转换的文件")
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            qsTr("支持的文件") + " (" + String(page.controller ? page.controller.inputFilePatterns : "") + ")",
            qsTr("所有文件 (*)")
        ]
        onAccepted: page.controller.addFiles(selectedFiles)
    }
    FolderDialog {
        id: outputDialog
        objectName: "converterOutputFolderDialog"
        title: qsTr("设置默认保存位置")
        onAccepted: page.controller.setOutputDirectory(selectedFolder)
    }
    FolderDialog {
        id: taskOutputDialog
        objectName: "converterTaskOutputFolderDialog"
        title: qsTr("选择本次任务保存位置")
        onAccepted: page.controller.setTaskOutputDirectory(selectedFolder)
    }
    FolderDialog {
        id: imageFolderDialog
        objectName: "converterImageFolderDialog"
        title: qsTr("选择包含图片的文件夹")
        onAccepted: {
            const result = page.controller.addImageFolderToPdf(selectedFolder)
            if (result && result.ok) {
                page.imageFolderMessage = result.skipped > 0
                        ? qsTr("已添加 %1 张图片；另有 %2 个文件无法读取。").arg(String(result.count)).arg(String(result.skipped))
                        : qsTr("已添加 %1 张图片，正在生成 PDF。").arg(String(result.count))
            } else {
                page.imageFolderMessage = result && result.error
                        ? qsTr(String(result.error)) : qsTr("无法读取所选文件夹。")
            }
        }
    }
    Dialog {
        id: discardDialog
        objectName: "converterDiscardUnsavedDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.max(260, Math.min(440, page.width - 40))
        title: qsTr("确认丢弃未保存结果")
        contentItem: Text {
            text: page.discardMessage
            color: page.ink
            font.family: page.fontFamily
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            UiButton {
                uiTheme: page.uiTheme
                text: qsTr("取消")
                onClicked: discardDialog.reject()
            }
            UiButton {
                uiTheme: page.uiTheme
                text: qsTr("丢弃结果")
                highlighted: true
                onClicked: {
                    page.confirmDiscard()
                    discardDialog.accept()
                }
            }
        }
        onRejected: {
            page.discardAction = ""
            page.discardJobId = ""
            page.discardMessage = ""
        }
    }

    MediaPlayer {
        id: previewPlayer
        source: page.previewKind === "audio" || page.previewKind === "video" ? page.previewUrl : ""
        audioOutput: AudioOutput {}
        videoOutput: previewVideoOutput
    }

    Dialog {
        id: previewDialog
        objectName: "converterResultPreviewDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.max(420, Math.min(960, page.width - 40))
        height: Math.max(360, Math.min(760, page.height - 40))
        title: page.previewTitle
        onClosed: {
            previewPlayer.stop()
            page.previewKind = ""
            page.previewUrl = ""
            page.previewText = ""
            page.previewTitle = ""
            page.previewTruncated = false
        }

        contentItem: ColumnLayout {
            spacing: 10

            Image {
                visible: page.previewKind === "image"
                Layout.fillWidth: true
                Layout.fillHeight: true
                source: page.previewKind === "image" ? page.previewUrl : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
            }

            PdfMultiPageView {
                visible: page.previewKind === "pdf"
                Layout.fillWidth: true
                Layout.fillHeight: true
                document: PdfDocument { source: page.previewKind === "pdf" ? page.previewUrl : "" }
            }

            ScrollView {
                visible: page.previewKind === "text"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    objectName: "converterResultPreviewText"
                    Accessible.name: qsTr("转换结果文本预览")
                    text: page.previewText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    font.family: "Consolas"
                    font.pixelSize: 12
                }
            }

            Text {
                visible: page.previewKind === "text" && page.previewTruncated
                Layout.fillWidth: true
                text: qsTr("预览仅显示前 1 MiB；完整结果需保存后写入输出位置。")
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 11
            }

            VideoOutput {
                id: previewVideoOutput
                visible: page.previewKind === "video"
                Layout.fillWidth: true
                Layout.fillHeight: true
                fillMode: VideoOutput.PreserveAspectFit
            }

            Text {
                visible: page.previewKind === "audio"
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: page.previewTitle
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: page.ink
                font.family: page.fontFamily
                font.pixelSize: 18
            }

            RowLayout {
                visible: page.previewKind === "audio" || page.previewKind === "video"
                Layout.fillWidth: true
                UiButton {
                    uiTheme: page.uiTheme
                    text: previewPlayer.playbackState === MediaPlayer.PlayingState ? qsTr("暂停") : qsTr("播放")
                    onClicked: previewPlayer.playbackState === MediaPlayer.PlayingState
                               ? previewPlayer.pause() : previewPlayer.play()
                }
                Slider {
                    Layout.fillWidth: true
                    from: 0
                    to: Math.max(1, previewPlayer.duration)
                    value: previewPlayer.position
                    enabled: previewPlayer.duration > 0
                    onMoved: previewPlayer.position = value
                }
                Text {
                    text: previewPlayer.errorString
                    visible: previewPlayer.errorString !== ""
                    color: page.danger
                    font.family: page.fontFamily
                    font.pixelSize: 11
                }
            }
        }
    }

    ListModel {
        id: mergePdfOrder
        objectName: "converterMergeOrderModel"
    }

    Dialog {
        id: mergePdfDialog
        objectName: "converterPdfMergeDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(680, page.width - 32)
        title: page.mergeMode === "pdf" ? qsTr("合并 PDF") : qsTr("图片合并为 PDF")

        contentItem: ColumnLayout {
            spacing: 10

            Text {
                objectName: "converterMergeSummaryText"
                Layout.fillWidth: true
                text: page.mergeMode === "pdf"
                      ? qsTr("将按下方清单合并 %1 个 PDF；原 PDF 不会被修改。调整顺序后再提交。")
                        .arg(String(mergePdfOrder.count))
                      : qsTr("将按下方清单生成 %1 页 PDF；原图片不会被修改。调整顺序后再提交。")
                        .arg(String(mergePdfOrder.count))
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                visible: page.skippedMergePdfCount > 0
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: page.mergeMode === "pdf"
                          ? qsTr("另有 %1 个 PDF 未纳入合并。")
                            .arg(String(page.skippedMergePdfCount))
                          : qsTr("另有 %1 张图片未纳入合并。")
                            .arg(String(page.skippedMergePdfCount))
                    color: page.warning
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                UiButton {
                    objectName: "converterMergeExcludedToggle"
                    uiTheme: page.uiTheme
                    text: page.mergeExcludedExpanded ? qsTr("收起原因") : qsTr("查看原因")
                    onClicked: page.mergeExcludedExpanded = !page.mergeExcludedExpanded
                }
            }

            ListView {
                objectName: "converterMergeExcludedList"
                Layout.fillWidth: true
                Layout.preferredHeight: page.mergeExcludedExpanded
                        ? Math.min(210, Math.max(66, contentHeight)) : 0
                visible: page.mergeExcludedExpanded && page.mergeExcludedItems.length > 0
                clip: true
                spacing: 6
                model: page.mergeExcludedItems
                delegate: Rectangle {
                    id: mergeExcludedRow
                    required property string fileName
                    required property string folder
                    required property string reasonCode
                    width: parent ? parent.width : 0
                    height: 58
                    radius: 9
                    color: page.warningSoft
                    border.color: page.line

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 1

                        Text {
                            Layout.fillWidth: true
                            text: mergeExcludedRow.fileName + " · " + page.mergeExclusionReason(mergeExcludedRow)
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            font.bold: true
                            elide: Text.ElideMiddle
                        }
                        Text {
                            Layout.fillWidth: true
                            text: page.mergeExclusionAdvice(mergeExcludedRow) + "  ·  " + mergeExcludedRow.folder
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }

            ListView {
                id: mergePdfList
                objectName: "converterMergeOrderList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(300, Math.max(66, contentHeight))
                clip: true
                spacing: 6
                model: mergePdfOrder
                delegate: Rectangle {
                    id: mergePdfRow
                    required property int index
                    required property string jobId
                    required property string fileName
                    required property string folder
                    width: mergePdfList.width
                    height: 56
                    radius: 9
                    color: page.surfaceSoft
                    border.color: page.line

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 8

                        Text {
                            text: String(mergePdfRow.index + 1).padStart(2, "0")
                            color: page.accentStrong
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            font.bold: true
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: mergePdfRow.fileName
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                font.bold: true
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("位置：%1").arg(mergePdfRow.folder)
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 11
                                elide: Text.ElideMiddle
                            }
                        }

                        UiButton {
                            objectName: "converterMergeMoveUp_" + mergePdfRow.index
                            uiTheme: page.uiTheme
                            text: qsTr("↑ 上移")
                            enabled: mergePdfRow.index > 0
                            onClicked: page.moveMergePdf(mergePdfRow.index, -1)
                        }
                        UiButton {
                            objectName: "converterMergeMoveDown_" + mergePdfRow.index
                            uiTheme: page.uiTheme
                            text: qsTr("↓ 下移")
                            enabled: mergePdfRow.index < mergePdfOrder.count - 1
                            onClicked: page.moveMergePdf(mergePdfRow.index, 1)
                        }
                        UiButton {
                            objectName: "converterMergeRemove_" + mergePdfRow.index
                            uiTheme: page.uiTheme
                            text: qsTr("移除")
                            onClicked: mergePdfOrder.remove(mergePdfRow.index)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: mergePdfOrder.count < 2
                text: page.mergeMode === "pdf"
                      ? qsTr("至少需要两份可读取且未加密的 PDF；当前可合并 %1 份。")
                      : qsTr("至少需要两张可读取的图片；当前可合并 %1 张。")
                      .arg(String(mergePdfOrder.count))
                color: page.warning
                font.family: page.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            Text {
                objectName: "converterMergeNotice"
                Layout.fillWidth: true
                visible: page.mergePdfNotice !== ""
                text: page.mergePdfNotice
                color: page.danger
                font.family: page.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }

        footer: RowLayout {
            UiButton {
                uiTheme: page.uiTheme
                text: qsTr("取消")
                onClicked: mergePdfDialog.close()
            }
            Item { Layout.fillWidth: true }
            UiButton {
                objectName: "converterMergeConfirmButton"
                uiTheme: page.uiTheme
                text: page.mergeMode === "pdf"
                      ? qsTr("合并 %1 个 PDF").arg(String(mergePdfOrder.count))
                      : qsTr("合并 %1 张图片").arg(String(mergePdfOrder.count))
                highlighted: true
                enabled: mergePdfOrder.count >= 2
                onClicked: page.confirmPdfMerge()
            }
        }

        background: Rectangle {
            radius: 14
            color: page.surface
            border.color: page.line
        }
    }

    Flickable {
        id: scroll
        objectName: "converterScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: content
            width: scroll.width
            padding: Math.min(32, Math.max(18, scroll.width * 0.045))
            spacing: 18

            RowLayout {
                width: parent.width - 48
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        objectName: "converterTitle"
                        text: qsTr("格式转换")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 30
                        font.bold: true
                    }
                    Text {
                        text: qsTr("本机处理 · 文件不会上传 · 转换结果不会覆盖原文件")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterManageEnginesButton"
                    text: qsTr("转换引擎")
                    enabled: Boolean(page.engineController)
                    onClicked: enginesDialog.open()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                width: parent.width - 48
                implicitHeight: importColumn.implicitHeight + 32
                radius: 16
                color: page.surface
                border.color: page.line

                ColumnLayout {
                    id: importColumn
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12
                    Text {
                        text: qsTr("选择文件或直接拖入")
                        color: page.ink
                        font.family: page.fontFamily
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Text {
                        objectName: "converterIntroDescription"
                        Layout.fillWidth: true
                        text: qsTr("支持常见图片、文档、表格、电子书和 PDF；安装包内置 FFmpeg 音视频、Tesseract 简体中文/英文 OCR 和 Calibre 电子书引擎，可在转换引擎中分别检查更新。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        UiButton {
                            uiTheme: page.uiTheme
                            text: qsTr("添加文件")
                            onClicked: inputDialog.open()
                        }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "converterImageFolderPdfButton"
                            text: qsTr("图片文件夹转 PDF")
                            onClicked: imageFolderDialog.open()
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "converterChooseDefaultOutputButton"
                            text: qsTr("设置默认保存位置")
                            onClicked: {
                                if (page.controller.outputDirectory !== "")
                                    outputDialog.currentFolder = page.controller.outputDirectoryUrl
                                outputDialog.open()
                            }
                        }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "converterChooseTaskOutputButton"
                            text: qsTr("本次任务保存到…")
                            onClicked: {
                                if (page.controller.taskOutputDirectory !== "")
                                    taskOutputDialog.currentFolder = page.controller.taskOutputDirectoryUrl
                                else if (page.controller.outputDirectory !== "")
                                    taskOutputDialog.currentFolder = page.controller.outputDirectoryUrl
                                taskOutputDialog.open()
                            }
                        }
                        UiButton {
                            uiTheme: page.uiTheme
                            objectName: "converterClearTaskOutputButton"
                            visible: page.controller.taskOutputDirectory !== ""
                            text: qsTr("跟随默认位置")
                            onClicked: page.controller.clearTaskOutputDirectory()
                        }
                        Text {
                            objectName: "converterDefaultOutputSummary"
                            Layout.fillWidth: true
                            text: page.controller.outputDirectory
                                  ? qsTr("默认位置（下次仍使用）：%1").arg(page.controller.outputDirectory)
                                  : qsTr("默认位置：与源文件保存在同一文件夹")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                    Text {
                        objectName: "converterTaskOutputSummary"
                        Layout.fillWidth: true
                        text: page.controller.taskOutputDirectory
                              ? qsTr("本次任务位置：%1；开始转换后会固定到每个结果。")
                                .arg(page.controller.taskOutputDirectory)
                              : qsTr("本次任务位置：跟随默认位置；开始转换后会固定到每个结果。")
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        CheckBox {
                            id: rememberTargetFormatsCheckBox
                            objectName: "converterRememberTargetFormats"
                            checked: Boolean(page.controller.rememberTargetFormats)
                            text: qsTr("记住目标格式偏好")
                            Accessible.name: text
                            implicitHeight: 30
                            leftPadding: 4
                            rightPadding: 4
                            spacing: 7
                            contentItem: Text {
                                text: rememberTargetFormatsCheckBox.text
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                leftPadding: rememberTargetFormatsCheckBox.indicator.width + rememberTargetFormatsCheckBox.spacing
                                verticalAlignment: Text.AlignVCenter
                            }
                            indicator: Rectangle {
                                implicitWidth: 16
                                implicitHeight: 16
                                x: rememberTargetFormatsCheckBox.leftPadding
                                y: rememberTargetFormatsCheckBox.topPadding + (rememberTargetFormatsCheckBox.availableHeight - height) / 2
                                radius: 4
                                color: rememberTargetFormatsCheckBox.checked ? page.accentStrong : page.surface
                                border.color: rememberTargetFormatsCheckBox.activeFocus ? page.accentStrong : page.line
                                border.width: rememberTargetFormatsCheckBox.activeFocus ? 2 : 1
                                Text {
                                    anchors.centerIn: parent
                                    text: "✓"
                                    color: page.surface
                                    font.pixelSize: 12
                                    font.bold: true
                                    visible: rememberTargetFormatsCheckBox.checked
                                }
                            }
                            onToggled: page.controller.setRememberTargetFormats(checked)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: rememberTargetFormatsCheckBox.checked
                                  ? qsTr("开启后，之后添加同类型文件会沿用上次选择。")
                                  : qsTr("关闭时只影响当前队列，不改变以后文件的默认格式。")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                    Text {
                        objectName: "converterImageFolderMessage"
                        Layout.fillWidth: true
                        visible: page.imageFolderMessage.length > 0
                        text: page.imageFolderMessage
                        color: page.muted
                        font.family: page.fontFamily
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            RowLayout {
                width: parent.width - 48
                spacing: 10
                Text {
                    Layout.fillWidth: true
                    text: qsTr("转换列表  ·  %1 个文件").arg(String(page.controller.jobs.length))
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 16
                    font.bold: true
                    Layout.alignment: Qt.AlignVCenter
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterClearFinishedButton"
                    text: qsTr("清除已完成")
                    enabled: page.countFinished() > 0
                    onClicked: page.requestClearFinished()
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterSaveAllButton"
                    text: qsTr("保存全部（%1）").arg(String(page.countUnsaved()))
                    enabled: page.countUnsaved() > 0
                    onClicked: page.controller.saveAll()
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterMergePdfButton"
                    visible: page.countMergeablePdfs() >= 2
                    text: qsTr("合并 PDF")
                    enabled: page.countMergeablePdfs() >= 2
                    onClicked: page.openPdfMergeDialog()
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterMergeImagesButton"
                    visible: page.countMergeableImages() >= 2
                    text: qsTr("图片合并为 PDF")
                    enabled: page.countMergeableImages() >= 2
                    onClicked: page.openImageMergeDialog()
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterStartButton"
                    text: qsTr("开始转换（%1）").arg(String(page.countReady()))
                    highlighted: true
                    enabled: page.countReady() > 0
                onClicked: page.controller.convertReady()
            }
            }

            Text {
                objectName: "converterSaveAllSummary"
                width: parent.width - 48
                visible: page.countUnsaved() > 0
                text: page.saveAllSummary()
                color: page.muted
                font.family: page.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            RowLayout {
                objectName: "converterCommonTargetRow"
                width: parent.width - 48
                spacing: 10
                visible: page.controller.commonTargetFormats.length > 0

                Text {
                    Layout.fillWidth: true
                    text: qsTr("共同目标（%1 个可转换文件）").arg(String(page.countReadyConversions()))
                    color: page.ink
                    font.family: page.fontFamily
                    font.pixelSize: 13
                    verticalAlignment: Text.AlignVCenter
                }
                UiComboBox {
                    id: commonTargetFormatSelector
                    objectName: "converterCommonTargetFormat"
                    uiTheme: page.uiTheme
                    accessibleName: qsTr("共同目标格式")
                    Layout.preferredWidth: 220
                    model: page.controller.commonTargetFormats
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: {
                        const options = page.controller.commonTargetFormats
                        for (let i = 0; i < options.length; i++)
                            if (options[i].value === page.selectedCommonTargetFormat) return i
                        return options.length > 0 ? 0 : -1
                    }
                    onActivated: {
                        page.selectedCommonTargetFormat = currentValue
                        page.commonTargetMessage = ""
                    }
                }
                UiButton {
                    uiTheme: page.uiTheme
                    objectName: "converterApplyCommonTargetButton"
                    text: qsTr("应用到所有文件")
                    enabled: page.countReadyConversions() >= 2 && commonTargetFormatSelector.currentValue !== undefined
                    onClicked: {
                        const result = page.controller.setCommonTargetFormat(commonTargetFormatSelector.currentValue)
                        if (result && result.ok) {
                            page.selectedCommonTargetFormat = commonTargetFormatSelector.currentValue
                            page.commonTargetMessage = qsTr("已为当前 %1 个文件设置目标格式。%2")
                                    .arg(String(result.applied))
                                    .arg(page.controller.rememberTargetFormats
                                         ? qsTr("已记为以后同类文件默认。")
                                         : qsTr("未改变以后文件的默认格式。"))
                        } else {
                            page.commonTargetMessage = qsTr("共同目标已变化，请重新选择后再试。")
                        }
                    }
                }
                Text {
                    objectName: "converterCommonTargetMessage"
                    visible: page.commonTargetMessage.length > 0
                    text: page.commonTargetMessage
                    color: page.muted
                    font.family: page.fontFamily
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                objectName: "converterEmptyDropZone"
                visible: page.controller.jobs.length === 0
                width: parent.width - 48
                implicitHeight: 168
                radius: 16
                color: page.surface
                border.color: page.line

                RowLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 36, 660)
                    spacing: 18

                    Rectangle {
                        Layout.preferredWidth: 56
                        Layout.preferredHeight: 56
                        radius: 16
                        color: page.accentSoft
                        Text {
                            anchors.centerIn: parent
                            text: "↓"
                            color: page.accentStrong
                            font.family: page.fontFamily
                            font.pixelSize: 28
                            font.bold: true
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            Layout.fillWidth: true
                            text: qsTr("把文件拖到这里开始")
                            color: page.ink
                            font.family: page.fontFamily
                            font.pixelSize: 15
                            font.bold: true
                        }
                        Text {
                            Layout.fillWidth: true
                            text: qsTr("支持批量添加；可以逐个设置，也可以一次应用所有文件的共同目标格式。")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    UiButton {
                        uiTheme: page.uiTheme
                        objectName: "converterEmptyAddFilesButton"
                        text: qsTr("选择文件")
                        highlighted: true
                        onClicked: inputDialog.open()
                    }
                }
            }

            Repeater {
                objectName: "converterJobsRepeater"
                model: page.controller.jobs
                delegate: Rectangle {
                    id: jobCard
                    required property var modelData
                    readonly property var job: modelData
                    width: content.width - 48
                    implicitHeight: cardColumn.implicitHeight + 26
                    radius: 14
                    color: job.status === "done" ? page.successSoft
                          : (job.status === "failed" || job.status === "unsupported") ? page.dangerSoft
                          : page.surface
                    border.color: page.line

                    ColumnLayout {
                        id: cardColumn
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: jobCard.job.fileName
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 14
                                font.bold: true
                                elide: Text.ElideMiddle
                            }
                            Text {
                                objectName: "converterJobStatus_" + jobCard.job.id
                                text: jobCard.job.status === "done" && Boolean(jobCard.job.stagedPath)
                                      ? (jobCard.job.savePending ? qsTr("正在保存") : qsTr("待保存"))
                                      : qsTr(String(jobCard.job.statusLabel))
                                color: jobCard.job.status === "failed" || jobCard.job.status === "unsupported"
                                       ? page.danger : jobCard.job.status === "done" ? page.success : page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                        }
                        Text {
                            objectName: "converterPlannedSaveDirectory_" + jobCard.job.id
                            Layout.fillWidth: true
                            visible: jobCard.job.status === "done"
                                     && (Boolean(jobCard.job.stagedPath) || Boolean(jobCard.job.savePending))
                            text: qsTr("将保存到：%1").arg(jobCard.job.saveDirectory || "")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Text {
                                text: jobCard.job.taskType === "pdf-merge" || jobCard.job.taskType === "images-pdf"
                                      ? qsTr("合并为") : qsTr("转换为")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            UiComboBox {
                                id: targetFormat
                                objectName: "converterTargetFormat"
                                uiTheme: page.uiTheme
                                accessibleName: qsTr("输出格式")
                                visible: jobCard.job.taskType !== "pdf-merge" && jobCard.job.taskType !== "images-pdf"
                                Layout.preferredWidth: 205
                                Layout.preferredHeight: 34
                                enabled: jobCard.job.status === "ready" && jobCard.job.canConvert
                                textRole: "label"
                                valueRole: "value"
                                model: page.formatsForPath(jobCard.job.sourcePath)
                                currentValue: jobCard.job.targetFormat
                                onActivated: page.controller.setTargetFormat(jobCard.job.id, currentValue)
                            }
                            Text {
                                visible: jobCard.job.taskType === "pdf-merge" || jobCard.job.taskType === "images-pdf"
                                text: jobCard.job.taskType === "images-pdf" ? qsTr("PDF from ordered images") : qsTr("PDF document")
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            Item { Layout.fillWidth: true }
                            UiButton {
                                uiTheme: page.uiTheme
                                objectName: "converterUnsupportedHelp_" + jobCard.job.id
                                visible: jobCard.job.status === "unsupported"
                                text: qsTr("检查转换组件")
                                enabled: Boolean(page.engineController)
                                onClicked: enginesDialog.openForJob(jobCard.job)
                            }
                            UiButton {
                                uiTheme: page.uiTheme
                                visible: jobCard.job.status === "failed"
                                text: qsTr("重试")
                                onClicked: page.controller.retryJob(jobCard.job.id)
                            }
                            UiButton {
                                uiTheme: page.uiTheme
                                text: qsTr("移除")
                                enabled: jobCard.job.status !== "running" && !jobCard.job.savePending
                                onClicked: page.requestRemoveJob(jobCard.job)
                            }
                        }
                        RowLayout {
                            objectName: "converterVideoCodecRow"
                            visible: page.videoTargetFormats.indexOf(jobCard.job.targetFormat) !== -1
                                && (jobCard.job.status === "ready" || jobCard.job.status === "failed")
                            Layout.fillWidth: true
                            spacing: 10
                            Text {
                                text: qsTr("视频编码")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            UiComboBox {
                                objectName: "converterVideoCodec"
                                uiTheme: page.uiTheme
                                accessibleName: qsTr("视频编码器")
                                Layout.preferredWidth: 205
                                Layout.preferredHeight: 34
                                enabled: jobCard.job.status === "ready" || jobCard.job.status === "failed"
                                textRole: "label"
                                valueRole: "value"
                                model: page.videoCodecsForJob(jobCard.job.id)
                                currentValue: page.controller.videoCodecForJob(jobCard.job.id)
                                onActivated: page.controller.setJobVideoCodec(jobCard.job.id, currentValue)
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            objectName: "converterPdfSplitGroupSizeRow"
                            visible: jobCard.job.targetFormat === "zip"
                                && (jobCard.job.status === "ready" || jobCard.job.status === "failed")
                            Layout.fillWidth: true
                            spacing: 10
                            Text {
                                text: qsTr("每份 PDF 页数")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            SpinBox {
                                id: pdfSplitGroupSize
                                objectName: "converterPdfSplitGroupSize"
                                Accessible.name: qsTr("每份 PDF 页数")
                                Layout.preferredWidth: 112
                                Layout.preferredHeight: 34
                                from: 1
                                to: page.controller.maxPdfPages
                                editable: true
                                value: page.controller.pdfSplitGroupSizeForJob(jobCard.job.id)
                                enabled: jobCard.job.status === "ready" || jobCard.job.status === "failed"
                                onValueModified: page.controller.setPdfSplitGroupSize(jobCard.job.id, value)
                            }
                            Text {
                                text: qsTr("相邻页面连续成组，最后一组可少于设定页数")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                        RowLayout {
                            visible: jobCard.job.targetFormat === "pdf-ocr"
                                     || jobCard.job.targetFormat === "image-ocr-txt"
                            Layout.fillWidth: true
                            Text {
                                text: qsTr("识别语言")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            UiComboBox {
                                objectName: "converterOcrLanguage"
                                uiTheme: page.uiTheme
                                accessibleName: qsTr("OCR 识别语言")
                                Layout.preferredWidth: 205
                                Layout.preferredHeight: 34
                                enabled: jobCard.job.status === "ready" || jobCard.job.status === "failed"
                                textRole: "label"
                                valueRole: "value"
                                model: page.controller.ocrLanguages
                                currentValue: page.controller.ocrLanguageForJob(jobCard.job.id)
                                onActivated: page.controller.setJobOcrLanguage(jobCard.job.id, currentValue)
                            }
                            Item { Layout.fillWidth: true }
                        }
                        ColumnLayout {
                            objectName: "converterPdfPasswordGroup"
                            Layout.fillWidth: true
                            visible: (jobCard.job.targetFormat === "pdf-encrypt" || jobCard.job.targetFormat === "pdf-decrypt")
                                     && (jobCard.job.status === "ready" || jobCard.job.status === "failed")
                            spacing: 3
                            Text {
                                objectName: "converterPdfPasswordLabel"
                                Layout.fillWidth: true
                                text: jobCard.job.targetFormat === "pdf-encrypt"
                                      ? qsTr("PDF 加密密码") : qsTr("原 PDF 密码")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                            }
                            TextField {
                                id: pdfPassword
                                objectName: "converterPdfPasswordField"
                                Accessible.name: jobCard.job.targetFormat === "pdf-encrypt"
                                                 ? qsTr("PDF 加密密码") : qsTr("原 PDF 密码")
                                Layout.fillWidth: true
                                enabled: jobCard.job.status === "ready" || jobCard.job.status === "failed"
                                echoMode: TextInput.Password
                                maximumLength: 512
                                text: page.controller.passwordForJob(jobCard.job.id)
                                placeholderText: jobCard.job.targetFormat === "pdf-encrypt"
                                                 ? qsTr("至少 8 个字符")
                                                 : qsTr("输入原密码")
                                onTextEdited: page.controller.setJobPassword(jobCard.job.id, text)
                                Connections {
                                    target: page.controller
                                    function onJobsChanged() {
                                        if (jobCard.job.status !== "ready" ||
                                                (jobCard.job.targetFormat !== "pdf-encrypt" && jobCard.job.targetFormat !== "pdf-decrypt"))
                                            pdfPassword.clear()
                                    }
                                }
                            }
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            visible: jobCard.job.status === "running" || jobCard.job.status === "done"
                            from: 0
                            to: jobCard.job.status === "running" && jobCard.job.progressMode !== "determinate" ? 0 : 100
                            value: jobCard.job.progress
                        }
                        Text {
                            objectName: "converterElapsedTime"
                            Layout.fillWidth: true
                            visible: jobCard.job.status === "running" || jobCard.job.status === "done" || jobCard.job.status === "failed"
                            text: qsTr("耗时：%1").arg(page.elapsedText(jobCard.job.elapsedSeconds))
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 11
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: jobCard.job.status === "running" && jobCard.job.progressMode === "determinate"
                            text: qsTr("%1% complete").arg(String(jobCard.job.progress))
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 11
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: jobCard.job.error !== ""
                            text: qsTr(String(jobCard.job.error))
                            color: page.danger
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: jobCard.job.outputPath !== ""
                            text: qsTr("已保存：%1").arg(jobCard.job.outputPath)
                            color: page.success
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WrapAnywhere
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: jobCard.job.status === "done" && Boolean(jobCard.job.stagedPath)
                            text: jobCard.job.savePending
                                  ? qsTr("正在保存到：%1").arg(jobCard.job.saveDirectory || "")
                                  : qsTr("已生成，待保存到：%1").arg(jobCard.job.saveDirectory || "")
                            color: page.muted
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: jobCard.job.saveError !== ""
                            text: qsTr(String(jobCard.job.saveError))
                            color: page.danger
                            font.family: page.fontFamily
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                        RowLayout {
                            visible: jobCard.job.status === "done" &&
                                     (Boolean(jobCard.job.stagedPath) || Boolean(page.controller.previewInfo(jobCard.job.id).kind))
                            UiButton {
                                objectName: "converterSaveButton_" + jobCard.job.id
                                uiTheme: page.uiTheme
                                visible: Boolean(jobCard.job.stagedPath)
                                enabled: !jobCard.job.savePending
                                text: jobCard.job.savePending ? qsTr("正在保存…") : qsTr("保存到此位置")
                                highlighted: true
                                onClicked: page.controller.saveJob(jobCard.job.id)
                            }
                            UiButton {
                                objectName: "converterPreviewButton_" + jobCard.job.id
                                uiTheme: page.uiTheme
                                visible: Boolean(page.controller.previewInfo(jobCard.job.id).kind)
                                text: qsTr("预览结果")
                                onClicked: page.openPreview(jobCard.job)
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                width: parent.width - 48
                implicitHeight: limitsColumn.implicitHeight + 24
                radius: 14
                color: page.surface
                border.color: page.line

                ColumnLayout {
                    id: limitsColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Text {
                                text: qsTr("格式范围与限制")
                                color: page.ink
                                font.family: page.fontFamily
                                font.pixelSize: 14
                                font.bold: true
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("不同格式的内容保留程度不同；展开查看对应说明。")
                                color: page.muted
                                font.family: page.fontFamily
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }

                        UiButton {
                            objectName: "converterFormatLimitsToggle"
                            uiTheme: page.uiTheme
                            text: page.formatLimitsExpanded ? qsTr("收起说明") : qsTr("查看格式说明")
                            checkable: true
                            checked: page.formatLimitsExpanded
                            highlighted: checked
                            onClicked: page.formatLimitsExpanded = !page.formatLimitsExpanded
                        }
                    }

                    GridLayout {
                        objectName: "converterFormatLimitsGrid"
                        Layout.fillWidth: true
                        visible: page.formatLimitsExpanded
                        columns: page.width >= 1100 ? 2 : 1
                        columnSpacing: 24
                        rowSpacing: 12

                        Repeater {
                            objectName: "converterFormatLimitSections"
                            model: page.formatLimitSections
                            delegate: ColumnLayout {
                                id: sectionCard
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 4

                                Text {
                                    text: sectionCard.modelData.title
                                    color: page.accentStrong
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: sectionCard.modelData.body
                                    color: page.muted
                                    font.family: page.fontFamily
                                    font.pixelSize: 12
                                    lineHeight: 1.25
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) page.controller.addFiles(drop.urls)
        }
    }
}
