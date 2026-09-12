# PyInstaller recipe for the single-file Windows build: pyinstaller --noconfirm PubCardGen.spec

from PyInstaller.utils.hooks import collect_all

# reportlab loads its fonts and .rl_settings at runtime, so it cannot be trimmed by the analyser.
datas, binaries, hiddenimports = collect_all("reportlab")

a = Analysis(
    ["run_gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # PIL stays: reportlab imports it. numpy/pandas only show up through optional code paths.
    excludes=["numpy", "pandas", "matplotlib", "pytest", "setuptools", "pip"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PubCardGen",
    console=False,
    disable_windowed_traceback=False,
    debug=False,
    strip=False,
    upx=False,  # UPX compression is what most antivirus engines flag.
    bootloader_ignore_signals=False,
    runtime_tmpdir=None,
)
