import QtQuick

Canvas {
    id: icon

    property string name: "home"
    property color color: "#586569"
    property real strokeWidth: 1.8

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onStrokeWidthChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        if (width <= 0 || height <= 0) return
        ctx.scale(width / 24, height / 24)
        ctx.strokeStyle = String(color)
        ctx.fillStyle = String(color)
        ctx.lineWidth = strokeWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"

        function line(points) {
            ctx.beginPath()
            ctx.moveTo(points[0][0], points[0][1])
            for (let i = 1; i < points.length; i++)
                ctx.lineTo(points[i][0], points[i][1])
            ctx.stroke()
        }

        function rect(x, y, w, h, radius) {
            ctx.beginPath()
            ctx.moveTo(x + radius, y)
            ctx.lineTo(x + w - radius, y)
            ctx.quadraticCurveTo(x + w, y, x + w, y + radius)
            ctx.lineTo(x + w, y + h - radius)
            ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h)
            ctx.lineTo(x + radius, y + h)
            ctx.quadraticCurveTo(x, y + h, x, y + h - radius)
            ctx.lineTo(x, y + radius)
            ctx.quadraticCurveTo(x, y, x + radius, y)
            ctx.stroke()
        }

        switch (name) {
        case "home":
            line([[3, 10], [12, 3], [21, 10]])
            line([[5.5, 9], [5.5, 20], [18.5, 20], [18.5, 9]])
            line([[9.5, 20], [9.5, 14], [14.5, 14], [14.5, 20]])
            break
        case "wallet":
            rect(3, 6, 18, 14, 2)
            line([[3, 9], [21, 9]])
            rect(14, 12, 7, 5, 1.5)
            ctx.beginPath(); ctx.arc(16.5, 14.5, 0.55, 0, Math.PI * 2); ctx.fill()
            break
        case "habit":
            ctx.beginPath(); ctx.arc(12, 12, 9, 0, Math.PI * 2); ctx.stroke()
            line([[8, 12], [10.8, 14.8], [16.5, 9]])
            break
        case "fitness":
            line([[4, 9], [4, 15]])
            line([[7, 7], [7, 17]])
            line([[17, 7], [17, 17]])
            line([[20, 9], [20, 15]])
            line([[7, 12], [17, 12]])
            line([[2.5, 9], [5.5, 9]])
            line([[2.5, 15], [5.5, 15]])
            line([[18.5, 9], [21.5, 9]])
            line([[18.5, 15], [21.5, 15]])
            break
        case "calendar":
            rect(3.5, 5, 17, 16, 2)
            line([[3.5, 9], [20.5, 9]])
            line([[8, 3], [8, 7]])
            line([[16, 3], [16, 7]])
            ctx.beginPath(); ctx.arc(8, 13, 0.75, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.arc(12, 13, 0.75, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.arc(16, 13, 0.75, 0, Math.PI * 2); ctx.fill()
            break
        case "cart":
            line([[3, 4], [5.5, 5], [8, 17], [19, 17], [21, 9], [6.5, 9]])
            ctx.beginPath(); ctx.arc(9, 20, 1, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.arc(18, 20, 1, 0, Math.PI * 2); ctx.fill()
            break
        case "books":
            ctx.beginPath()
            ctx.moveTo(3, 5); ctx.quadraticCurveTo(8, 3, 12, 7)
            ctx.quadraticCurveTo(16, 3, 21, 5); ctx.lineTo(21, 19)
            ctx.quadraticCurveTo(16, 17, 12, 21); ctx.quadraticCurveTo(8, 17, 3, 19)
            ctx.closePath(); ctx.stroke()
            line([[12, 7], [12, 21]])
            line([[6, 8], [9, 9]])
            line([[15, 9], [18, 8]])
            break
        case "archive":
            rect(3.5, 7, 17, 14, 2)
            rect(2.5, 4, 19, 4, 1.5)
            line([[9, 12], [15, 12]])
            break
        case "convert":
            line([[4, 7], [18, 7], [15, 4]])
            line([[18, 7], [15, 10]])
            line([[20, 17], [6, 17], [9, 14]])
            line([[6, 17], [9, 20]])
            break
        case "settings":
            ctx.beginPath(); ctx.arc(12, 12, 4.1, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath(); ctx.arc(12, 12, 8.4, 0, Math.PI * 2); ctx.stroke()
            for (let angle = 0; angle < 8; angle++) {
                const radians = angle * Math.PI / 4
                line([
                    [12 + Math.cos(radians) * 8.4, 12 + Math.sin(radians) * 8.4],
                    [12 + Math.cos(radians) * 10.5, 12 + Math.sin(radians) * 10.5]
                ])
            }
            break
        case "database":
            ctx.beginPath(); ctx.ellipse(12, 6, 8.5, 3, 0, 0, Math.PI * 2); ctx.stroke()
            line([[3.5, 6], [3.5, 18]])
            line([[20.5, 6], [20.5, 18]])
            ctx.beginPath(); ctx.ellipse(12, 18, 8.5, 3, 0, 0, Math.PI); ctx.stroke()
            ctx.beginPath(); ctx.ellipse(12, 11.5, 8.5, 3, 0, 0, Math.PI); ctx.stroke()
            break
        case "trash":
            line([[4, 7], [20, 7]])
            line([[9, 4], [15, 4]])
            line([[6, 7], [7.3, 20], [16.7, 20], [18, 7]])
            line([[10, 10], [10.5, 17]])
            line([[14, 10], [13.5, 17]])
            break
        case "music":
            line([[15, 5], [15, 16]])
            line([[15, 5], [21, 3.5], [21, 14.5]])
            ctx.beginPath(); ctx.ellipse(11, 17, 4, 2.5, -0.3, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath(); ctx.ellipse(17, 15.5, 4, 2.5, -0.3, 0, Math.PI * 2); ctx.stroke()
            break
        case "location":
            ctx.beginPath()
            ctx.moveTo(12, 22)
            ctx.bezierCurveTo(9.5, 18.7, 5, 14.5, 5, 10.2)
            ctx.bezierCurveTo(5, 6.3, 8.1, 3, 12, 3)
            ctx.bezierCurveTo(15.9, 3, 19, 6.3, 19, 10.2)
            ctx.bezierCurveTo(19, 14.5, 14.5, 18.7, 12, 22)
            ctx.stroke()
            ctx.beginPath(); ctx.arc(12, 10, 2.3, 0, Math.PI * 2); ctx.stroke()
            break
        case "sun":
            ctx.beginPath(); ctx.arc(12, 12, 4.3, 0, Math.PI * 2); ctx.stroke()
            line([[12, 2], [12, 5]])
            line([[12, 19], [12, 22]])
            line([[2, 12], [5, 12]])
            line([[19, 12], [22, 12]])
            line([[4.9, 4.9], [7, 7]])
            line([[17, 17], [19.1, 19.1]])
            line([[19.1, 4.9], [17, 7]])
            line([[7, 17], [4.9, 19.1]])
            break
        case "cloud":
        case "rain":
        case "snow":
        case "storm":
            ctx.beginPath()
            ctx.moveTo(5, 17.5)
            ctx.bezierCurveTo(2.3, 17.5, 2.2, 13.2, 5.2, 12.1)
            ctx.bezierCurveTo(5.7, 8.8, 9.8, 7.4, 12.1, 10)
            ctx.bezierCurveTo(15.1, 8.5, 18.7, 10.1, 18.8, 13.1)
            ctx.bezierCurveTo(21.5, 13.4, 21.8, 17.4, 18.6, 17.5)
            ctx.lineTo(5, 17.5)
            ctx.stroke()
            if (name === "rain") {
                line([[8, 19], [7, 22]])
                line([[13, 19], [12, 22]])
                line([[18, 19], [17, 22]])
            } else if (name === "snow") {
                line([[8, 19], [8, 22]])
                line([[6.7, 20.5], [9.3, 20.5]])
                line([[16, 19], [16, 22]])
                line([[14.7, 20.5], [17.3, 20.5]])
            } else if (name === "storm") {
                line([[13, 18], [10.5, 21], [13, 21], [11.7, 23]])
            }
            break
        case "fog":
            line([[4, 9], [20, 9]])
            line([[2.5, 13], [21.5, 13]])
            line([[5, 17], [19, 17]])
            break
        default:
            ctx.beginPath(); ctx.arc(12, 12, 8, 0, Math.PI * 2); ctx.stroke()
        }
    }
}
