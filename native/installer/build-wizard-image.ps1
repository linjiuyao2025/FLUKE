$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logoPath = Join-Path $projectRoot "assets\fluke-logo.png"
$outputPath = Join-Path $PSScriptRoot "fluke-wizard.png"
$smallLogoPath = Join-Path $PSScriptRoot "fluke-small.png"

if (-not (Test-Path -LiteralPath $logoPath)) {
    throw "FLUKE logo was not found at $logoPath."
}

$width = 538
$height = 1030
$bitmap = [System.Drawing.Bitmap]::new(
    $width,
    $height,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$logo = [System.Drawing.Image]::FromFile($logoPath)
$smallBitmap = [System.Drawing.Bitmap]::new(
    512,
    512,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
)
$smallGraphics = [System.Drawing.Graphics]::FromImage($smallBitmap)

$ink = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(34, 36, 38))
$muted = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(99, 104, 106))
$orange = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 74, 18))
$hairline = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(194, 191, 183), 2)
$microFont = [System.Drawing.Font]::new("Segoe UI", 18, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$headingFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 30, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$bodyFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 21, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$captionFont = [System.Drawing.Font]::new("Segoe UI", 16, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)

try {
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::FromArgb(235, 233, 226))

    $smallGraphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $smallGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $smallGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $smallGraphics.Clear([System.Drawing.Color]::Transparent)
    $smallLogoWidth = 472
    $smallLogoHeight = [int][Math]::Round($smallLogoWidth * $logo.Height / $logo.Width)
    $smallLogoX = [int][Math]::Round((512 - $smallLogoWidth) / 2)
    $smallLogoY = [int][Math]::Round((512 - $smallLogoHeight) / 2)
    $smallGraphics.DrawImage($logo, $smallLogoX, $smallLogoY, $smallLogoWidth, $smallLogoHeight)

    $graphics.FillRectangle($orange, 0, 0, 7, $height)
    $graphics.DrawString("FLUKE  /  DESKTOP LOCAL", $microFont, $ink, 54, 96)
    $graphics.FillRectangle($orange, 54, 157, 48, 4)

    $logoWidth = 438
    $logoHeight = [int][Math]::Round($logoWidth * $logo.Height / $logo.Width)
    $logoX = [int][Math]::Round(($width - $logoWidth) / 2)
    $graphics.DrawImage($logo, $logoX, 326, $logoWidth, $logoHeight)

    $graphics.DrawString("把工作台，安放在这里。", $headingFont, $ink, 54, 568)
    $graphics.DrawString("轻一点的界面，稳一点的日常。", $bodyFont, $muted, 54, 632)

    $graphics.DrawLine($hairline, 54, 890, $width - 54, 890)
    $graphics.DrawString("BUILT FOR YOUR EVERYDAY", $captionFont, $ink, 54, 922)
    $graphics.DrawString("WINDOWS  ·  LOCAL WORKSPACE", $captionFont, $muted, 54, 965)

    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $smallBitmap.Save($smallLogoPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    foreach ($resource in @($ink, $muted, $orange, $hairline, $microFont, $headingFont, $bodyFont, $captionFont, $logo, $smallGraphics, $smallBitmap, $graphics, $bitmap)) {
        if ($null -ne $resource) { $resource.Dispose() }
    }
}

Get-Item -LiteralPath $outputPath, $smallLogoPath | Select-Object FullName, Length, LastWriteTime
