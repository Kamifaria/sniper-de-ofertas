"""Segredos no cofre do Windows (Credential Manager). Nunca em arquivo de texto."""
from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICO = "SniperOferta"


class CofreIndisponivel(Exception):
    """Não há cofre do sistema para guardar o segredo."""


def guardar(nome: str, valor: str) -> None:
    try:
        keyring.set_password(SERVICO, nome, valor)
    except KeyringError as e:
        raise CofreIndisponivel(f"Não consegui usar o cofre do Windows: {e}") from e


def ler(nome: str) -> str:
    try:
        return keyring.get_password(SERVICO, nome) or ""
    except KeyringError:
        return ""


def apagar(nome: str) -> None:
    try:
        keyring.delete_password(SERVICO, nome)
    except KeyringError:
        pass
