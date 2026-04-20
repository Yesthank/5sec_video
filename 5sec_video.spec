# PyInstaller spec for 5sec_video
# Build:  pyinstaller 5sec_video.spec
# Output: dist/5sec_video.exe (single file, windowed, no console)

# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None


# imageio-ffmpeg가 번들한 ffmpeg 실행파일을 EXE에 포함
def _ffmpeg_binary():
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        # PyInstaller가 번들의 imageio_ffmpeg/binaries/ 아래에 그대로 둬야
        # imageio_ffmpeg.get_ffmpeg_exe()가 찾을 수 있음
        return [(exe, os.path.join('imageio_ffmpeg', 'binaries'))]
    except Exception:
        return []


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_ffmpeg_binary() + collect_dynamic_libs('sounddevice'),
    datas=[],
    hiddenimports=[
        'sounddevice',
        'soundfile',
        'imageio_ffmpeg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PySide6의 사용하지 않는 큰 모듈 제외 (배포 크기 절감)
        'PySide6.QtNetwork',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia',
        'PySide6.Qt3DCore',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtSql',
        'PySide6.QtTest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='5sec_video',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # 윈도우 콘솔 없음 (트레이 앱)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
