"""Licença por chave assinada (Ed25519), com revogação online.

A chave privada fica só com o vendedor (nunca no repositório nem no .exe); o app só tem a pública.
Emitir chaves: python tools/emitir_licenca.py "Nome do cliente" 30
"""
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from . import segredos

PREFIXO = "SNP-"
TOLERANCIA_OFFLINE = timedelta(days=7)
# Arquivo JSON {"revogadas": ["id", ...]} hospedado por você (ex.: GitHub Pages). Vazio = sem checagem online.
URL_REVOGADAS = ""


class LicencaInvalida(Exception):
    """A mensagem já é para mostrar ao cliente."""


@dataclass
class Licenca:
    id: str
    cliente: str
    expira: datetime


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def publica_b64(priv: Ed25519PrivateKey) -> str:
    return _b64(priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def emitir(priv: Ed25519PrivateKey, cliente: str, dias: int, agora: Optional[datetime] = None) -> str:
    agora = agora or datetime.now(timezone.utc)
    corpo = json.dumps({"id": uuid.uuid4().hex[:12], "c": cliente,
                        "e": (agora + timedelta(days=dias)).isoformat()}, separators=(",", ":")).encode()
    return f"{PREFIXO}{_b64(corpo)}.{_b64(priv.sign(corpo))}"


def validar(chave: str, publica: str, agora: Optional[datetime] = None) -> Licenca:
    agora = agora or datetime.now(timezone.utc)
    ruim = LicencaInvalida("Chave inválida. Confira se copiou a chave inteira, sem espaços.")
    chave = chave.strip()
    if not chave.startswith(PREFIXO) or "." not in chave:
        raise ruim
    try:
        corpo_b64, sig_b64 = chave[len(PREFIXO):].split(".", 1)
        corpo, sig = _unb64(corpo_b64), _unb64(sig_b64)
        Ed25519PublicKey.from_public_bytes(_unb64(publica)).verify(sig, corpo)
        d = json.loads(corpo)
        lic = Licenca(d["id"], d["c"], datetime.fromisoformat(d["e"]))
    except (ValueError, KeyError, InvalidSignature, TypeError):
        raise ruim from None
    if agora > lic.expira:
        raise LicencaInvalida(f"Sua licença venceu em {lic.expira:%d/%m/%Y}. Fale com o vendedor para renovar.")
    return lic


def checar_online(lic: Licenca, url: str, transporte: Optional[httpx.BaseTransport] = None,
                  agora: Optional[datetime] = None) -> None:
    """Barra licença cancelada. Sem internet, tolera 7 dias desde a última checagem que deu certo."""
    if not url:
        return
    agora = agora or datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=8, transport=transporte) as c:
            r = c.get(url)
            r.raise_for_status()
            revogadas = r.json().get("revogadas", [])
    except (httpx.HTTPError, ValueError):
        ultima = segredos.ler("licenca_check")
        if ultima and agora - datetime.fromisoformat(ultima) <= TOLERANCIA_OFFLINE:
            return
        raise LicencaInvalida("Não consegui confirmar sua licença. Conecte-se à internet para continuar.") from None
    if lic.id in revogadas:
        raise LicencaInvalida("Esta licença foi cancelada. Fale com o vendedor.")
    segredos.guardar("licenca_check", agora.isoformat())
