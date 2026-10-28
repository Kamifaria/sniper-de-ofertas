"""Onde ficam os dados do usuário e os recursos do app, rodando do código ou empacotado (.exe)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOME_APP = "SniperOferta"


def empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


def dados_dir() -> Path:
    """Config, banco, log: gravável. Empacotado vai para %APPDATA%; em desenvolvimento, a pasta do projeto."""
    if empacotado():
        return Path(os.environ["APPDATA"]) / NOME_APP
    return RAIZ


def recurso(relativo: str) -> Path:
    """Arquivo que vai dentro do app (ex.: sniper/web). Empacotado, fica em sys._MEIPASS."""
    base = Path(getattr(sys, "_MEIPASS", RAIZ)) if empacotado() else RAIZ
    return base / relativo


def garantir_config(destino: Path) -> None:
    """Primeira execução: copia o config de exemplo (sem credenciais) para a pasta do usuário."""
    if destino.exists():
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(recurso("config.exemplo.toml").read_text(encoding="utf-8"), encoding="utf-8")
