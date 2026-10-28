"""Integração com o Windows para rodar 24 horas: não deixar o PC dormir e abrir junto com o Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
NOME_ATALHO = "Sniper de Ofertas.lnk"


def impedir_suspensao() -> bool:
    """Impede a suspensão enquanto este processo roda (o monitor ainda pode desligar).
    Vale para a thread que chamou; chame da thread principal. Fora do Windows não faz nada."""
    if sys.platform != "win32":
        return False
    import ctypes
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))


def pasta_inicializar() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _ps(texto: str) -> str:
    """String literal do PowerShell (aspas simples, com ' escapada)."""
    return "'" + texto.replace("'", "''") + "'"


def script_atalho(base: Path, lnk: Path) -> str:
    alvo = Path(sys.executable) if getattr(sys, "frozen", False) else base / "iniciar.bat"
    return (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps(str(lnk))}); "
            f"$s.TargetPath = {_ps(str(alvo))}; $s.Arguments = '--sem-janela'; "
            f"$s.WorkingDirectory = {_ps(str(base))}; $s.WindowStyle = 7; $s.Save()")


def instalar_inicio(base: Path) -> Path:
    """Cria o atalho na pasta Inicializar: o Sniper abre minimizado quando o Windows inicia."""
    if sys.platform != "win32":
        raise RuntimeError("Iniciar com o sistema só funciona no Windows")
    lnk = pasta_inicializar() / NOME_ATALHO
    subprocess.run(["powershell", "-NoProfile", "-Command", script_atalho(base, lnk)], check=True)
    return lnk


def remover_inicio() -> bool:
    lnk = pasta_inicializar() / NOME_ATALHO
    if lnk.exists():
        lnk.unlink()
        return True
    return False
