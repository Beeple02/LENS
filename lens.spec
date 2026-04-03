# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for LENS

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['lens/main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        # Bundle the stylesheet and SQL schema alongside the code
        ('lens/ui/stylesheet.qss',  'lens/ui'),
        ('lens/db/schema.sql',      'lens/db'),
    ],
    hiddenimports=[
        # PyQt6 modules that may not be auto-detected
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.sip',
        # pyqtgraph internals
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.PlotItem',
        'pyqtgraph.graphicsItems.GraphicsLayout',
        'pyqtgraph.widgets.PlotWidget',
        # Data stack
        'pandas',
        'pandas.core.arrays.integer',
        'pandas.core.arrays.floating',
        'numpy',
        'numpy.core',
        # HTTP + parsing
        'httpx',
        'httpcore',
        'anyio',
        'anyio._backends._asyncio',
        'lxml',
        'lxml.etree',
        'lxml._elementpath',
        # stdlib
        'tomllib',
        'zoneinfo',
        'sqlite3',
        # lens backend
        'lens.config',
        'lens._resources',
        'lens.db.store',
        'lens.data.yahoo',
        'lens.data.euronext',
        'lens.data.parser',
        'lens.portfolio.tracker',
        'lens.portfolio.analytics',
        'lens.screener.engine',
        'lens.ui.workers',
        'lens.ui.main_window',
        'lens.ui.sidebar',
        'lens.ui.screens.dashboard',
        'lens.ui.screens.quote',
        'lens.ui.screens.portfolio',
        'lens.ui.screens.screener',
        'lens.ui.screens.chart',
        'lens.ui.screens.settings',
        'lens.ui.widgets.stat_card',
        'lens.ui.widgets.price_label',
        'lens.ui.widgets.data_table',
        'lens.ui.widgets.search_bar',
        'lens.ui.widgets.chart_widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'IPython',
        'jupyter',
        'textual',
        'rich',
        'plotext',
        'typer',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LENS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # No terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,           # Add icon path here if you have one: 'assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LENS',
)

# macOS .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='LENS.app',
        icon=None,        # 'assets/icon.icns' if you have one
        bundle_identifier='com.lens.app',
        info_plist={
            'CFBundleName': 'LENS',
            'CFBundleDisplayName': 'LENS — Equity Terminal',
            'CFBundleVersion': '0.1.0',
            'CFBundleShortVersionString': '0.1.0',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
