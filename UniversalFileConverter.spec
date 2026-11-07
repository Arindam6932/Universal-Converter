# Optional PyInstaller spec; build_windows.ps1 is the simpler supported entry point.
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules("app")
a = Analysis(["main.py"], pathex=[], binaries=[], datas=[("app", "app")],
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="UniversalFileConverter",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="UniversalFileConverter")
