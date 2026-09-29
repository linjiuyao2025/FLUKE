import QtQuick

QtObject {
    property string themeName: "plum"
    readonly property string sansFamily: "Noto Sans SC"
    readonly property string serifFamily: "Noto Serif SC"

    readonly property color canvas: "#f6f5f0"
    readonly property color sidebar: "#efede7"
    readonly property color surface: "#fffefa"
    readonly property color surfaceSoft: "#f4f2ec"
    readonly property color line: "#e2dfd7"
    readonly property color ink: "#273239"
    readonly property color muted: "#586569"
    readonly property color mutedStrong: "#545f63"
    readonly property color controlBorder: "#807d76"
    readonly property color accent: themePrimary(themeName)
    readonly property color accentStrong: themePrimaryStrong(themeName)
    readonly property color accentSoft: themeSoft(themeName)
    readonly property color brand: "#9f4137"
    readonly property color brandSoft: "#f7eae5"
    readonly property color success: "#3d654e"
    readonly property color successSoft: "#eaf2ec"
    readonly property color warning: "#80531b"
    readonly property color warningSoft: "#f6efe2"
    readonly property color danger: "#9d4038"
    readonly property color dangerSoft: "#f8eae7"

    readonly property int controlHeight: 38
    readonly property int compactControlHeight: 34
    readonly property int radiusSmall: 8
    readonly property int radiusMedium: 13
    readonly property int radiusLarge: 18
    readonly property int pageMargin: 28
    readonly property int sectionGap: 20

    function themePrimary(theme) {
        if (theme === "forest") return "#365f53"
        if (theme === "clay") return "#8f4f3b"
        if (theme === "navy") return "#344b63"
        return "#4d3045"
    }

    function themePrimaryStrong(theme) {
        if (theme === "forest") return "#28483e"
        if (theme === "clay") return "#693a2b"
        if (theme === "navy") return "#25394d"
        return "#3a2434"
    }

    function themeSoft(theme) {
        if (theme === "forest") return "#dfe9e4"
        if (theme === "clay") return "#f0ddd6"
        if (theme === "navy") return "#dde4eb"
        return "#e8dfe5"
    }
}
