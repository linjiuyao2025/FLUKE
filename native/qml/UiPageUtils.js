.pragma library

function asList(value, includeCountModel) {
    if (value === null || value === undefined)
        return []
    if (typeof value.length === "number") {
        var result = []
        for (var i = 0; i < value.length; ++i)
            result.push(value[i])
        return result
    }
    if (includeCountModel && typeof value.count === "number" && value.get) {
        var counted = []
        for (var j = 0; j < value.count; ++j)
            counted.push(value.get(j))
        return counted
    }
    return []
}

function valueOf(object, key, fallback) {
    if (object === null || object === undefined)
        return fallback
    var result = object[key]
    return result === undefined || result === null ? fallback : result
}

function localDateKey() {
    var now = new Date()
    function pad(value) { return value < 10 ? "0" + value : String(value) }
    return String(now.getFullYear()) + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate())
}
