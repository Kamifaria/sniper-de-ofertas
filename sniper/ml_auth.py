"""Autorização OAuth do Mercado Livre feita dentro do app (cada cliente com o próprio app do DevCenter)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH = "https://auth.mercadolivre.com.br/authorization"
TOKEN = "https://api.mercadolibre.com/oauth/token"


class AutorizacaoFalhou(Exception):
    pass


def url_autorizacao(client_id: str, redirect_uri: str) -> str:
    return AUTH + "?" + urlencode({"response_type": "code", "client_id": client_id,
                                   "redirect_uri": redirect_uri})


def extrair_codigo(texto: str) -> str:
    """Aceita a URL de redirecionamento inteira ou só o código."""
    texto = texto.strip()
    return parse_qs(urlparse(texto).query).get("code", [texto])[0]


def trocar_codigo(client_id: str, client_secret: str, redirect_uri: str, codigo: str,
                  transporte: httpx.BaseTransport | None = None) -> dict:
    try:
        with httpx.Client(timeout=20, transport=transporte) as c:
            r = c.post(TOKEN, headers={"accept": "application/json"}, data={
                "grant_type": "authorization_code", "client_id": client_id,
                "client_secret": client_secret, "code": codigo, "redirect_uri": redirect_uri})
    except httpx.HTTPError as e:
        raise AutorizacaoFalhou(f"Sem conexão com o Mercado Livre: {e}") from e
    if r.status_code != 200:
        raise AutorizacaoFalhou(f"O Mercado Livre recusou o código ({r.status_code}): {r.text[:200]}")
    return r.json()
