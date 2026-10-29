"""Avisa quando há versão nova. Você publica um JSON: {"versao": "1.1.0", "url": "https://.../Setup.exe", "notas": "..."}"""
from __future__ import annotations

from typing import Optional

import httpx

from . import versao

# Endereço do JSON de versão (versao.json na raiz do repositório). Vazio = não verifica.
URL_VERSAO = "https://raw.githubusercontent.com/Kamifaria/sniper-de-ofertas/main/versao.json"


def _tupla(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def verificar(url: str, atual: str, transporte: Optional[httpx.BaseTransport] = None) -> Optional[dict]:
    """Devolve {versao, url, notas} se houver versão mais nova; None se não, ou se não deu para checar."""
    if not url:
        return None
    try:
        with httpx.Client(timeout=8, transport=transporte) as c:
            r = c.get(url)
            r.raise_for_status()
            d = r.json()
        nova, link = str(d["versao"]), str(d["url"])
        if not link.startswith("https://") or _tupla(nova) <= _tupla(atual):
            return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return {"versao": nova, "url": link, "notas": str(d.get("notas", ""))}
