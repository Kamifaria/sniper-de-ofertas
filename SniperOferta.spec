# Gera dist/SniperOferta/ (pasta). Rodar: .venv\Scripts\python -m PyInstaller SniperOferta.spec --noconfirm
a = Analysis(
    ["run.py"],
    datas=[("sniper/web", "sniper/web"), ("config.exemplo.toml", ".")],
    hiddenimports=["keyring.backends.Windows", "win32timezone"],
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SniperOferta", console=False,
          icon="assets/icone.ico", version="build_tools/versao_info.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="SniperOferta")
