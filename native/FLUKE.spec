# PyInstaller build spec for the FLUKE Qt Quick desktop app.
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH).resolve()

# PyInstaller also scans PATH for DLLs. Keep unrelated application bundles from
# contributing same-named runtime DLLs (for example Poppler's ICU DLLs) to this
# Qt application bundle.
system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
build_path = [
    str(Path(sys.executable).resolve().parent),
    str(system_root / "System32"),
    str(system_root),
]
os.environ["PATH"] = os.pathsep.join(build_path)

datas = [
    (str(project_root / "qml"), "qml"),
    (str(project_root.parent / "assets" / "fonts"), "assets/fonts"),
]
# Converter engines are copied into dist after PyInstaller finishes. Treating
# these executable folders as Analysis datas makes PyInstaller promote some
# third-party DLLs (notably Calibre's bundled Python/Qt runtime) into the
# application's shared _internal directory, where they can conflict with
# PySide6's runtime.
rawpy_root = project_root / "third-party" / "rawpy"
rawpy_notice = rawpy_root / "THIRD-PARTY-NOTICES.md"
if rawpy_notice.is_file():
    datas.append((str(rawpy_notice), "licenses/rawpy"))
for license_file in (rawpy_root / "licenses").rglob("*"):
    if license_file.is_file():
        relative_parent = license_file.parent.relative_to(rawpy_root)
        datas.append((str(license_file), str(Path("licenses/rawpy") / relative_parent)))
rawpy_source_archive = rawpy_root / "source" / "rawpy-0.27.1.tar.gz"
if rawpy_source_archive.is_file():
    datas.append((str(rawpy_source_archive), "licenses/rawpy/source"))
pillow_root = project_root / "third-party" / "pillow"
pillow_notice = pillow_root / "THIRD-PARTY-NOTICES.md"
if pillow_notice.is_file():
    datas.append((str(pillow_notice), "licenses/pillow"))
for license_file in (pillow_root / "licenses").rglob("*"):
    if license_file.is_file():
        relative_parent = license_file.parent.relative_to(pillow_root)
        datas.append((str(license_file), str(Path("licenses/pillow") / relative_parent)))
ofd_engine_build = project_root / "engine" / "ofd" / "build"
if (ofd_engine_build / "bridge.jar").is_file():
    datas.append((str(ofd_engine_build), "engine/ofd/build"))
datas += collect_data_files("tzdata")

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "dateutil.rrule",
        "tzdata",
        "tzlocal",
        "winrt.windows.devices.geolocation",
        "winrt.windows.foundation",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
    optimize=0,
)

# Keep the converter CLI as a separate console executable in the same onedir
# payload. It is analyzed independently so its entry point can remain a normal
# module wrapper without changing the GUI's existing FLUKE.exe startup path.
cli_a = Analysis(
    [str(project_root / "fluke_convert_entry.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
    optimize=0,
)

launcher_a = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "pytest", "unittest"],
    noarchive=False,
    optimize=0,
)

# The Codex runtime may expose Poppler's ICU DLLs on PATH. They are not
# compatible with the ICU API imported by the QtCore wheel and would shadow
# the host ICU that the PySide6 wheel successfully uses at runtime.
for analysis in (a, cli_a, launcher_a):
    analysis.binaries[:] = [
        item
        for item in analysis.binaries
        if not (
            Path(item[0]).name.casefold() in {"icuuc.dll"}
            or Path(item[0]).name.casefold().startswith("icudt")
        )
        or not any(part.casefold() == "poppler" for part in Path(item[1]).parts)
    ]

# PySide6's assetdownloader QML module contains four C++ build outputs
# alongside its runtime files. They are copied as data by collect_data_files,
# but Qt does not load these .obj files and their paths exceed Windows/Inno
# Setup's path limit. Keep every plugin, metadata, and QML resource intact.
qml_build_artifact_dirs = {"objects-debug", "objects-relwithdebinfo"}
qml_assetdownloader_parts = ("pyside6", "qml", "qt", "labs", "assetdownloader")


def is_qml_build_artifact(item):
    target = Path(item[0])
    parts = tuple(part.casefold() for part in target.parts)
    in_assetdownloader = any(
        parts[index : index + len(qml_assetdownloader_parts)]
        == qml_assetdownloader_parts
        for index in range(len(parts) - len(qml_assetdownloader_parts) + 1)
    )
    return (
        target.suffix.casefold() == ".obj"
        and in_assetdownloader
        and any(part in qml_build_artifact_dirs for part in parts)
    )


for analysis in (a, cli_a, launcher_a):
    analysis.datas[:] = [item for item in analysis.datas if not is_qml_build_artifact(item)]

pyz = PYZ(a.pure, cli_a.pure)
launcher_pyz = PYZ(launcher_a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FLUKE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
cli_exe = EXE(
    pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="FLUKE-convert",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
launcher_exe = EXE(
    launcher_pyz,
    launcher_a.scripts,
    launcher_a.binaries,
    launcher_a.datas,
    [],
    exclude_binaries=False,
    name="FLUKE-launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = COLLECT(
    exe,
    cli_exe,
    launcher_exe,
    a.binaries,
    a.datas,
    cli_a.binaries,
    cli_a.datas,
    strip=False,
    upx=True,
    name="FLUKE",
)
