"""Autoriza o Sniper na sua conta do Mercado Livre (rodar uma vez).

1. Crie um app em https://developers.mercadolivre.com.br/devcenter
   - Redirect URI: use a mesma do config.toml (ex.: https://www.google.com)
2. Preencha client_id, client_secret e redirect_uri no config.toml
3. Rode: python auth_ml.py
"""
from __future__ import annotations

import json
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from sniper import config

BASE = Path(__file__).parent


def main() -> None:
    s = config.load(BASE / "config.toml")
    if not (s.ml_client_id and s.ml_client_secret and s.ml_redirect_uri):
        sys.exit("Preencha [mercadolivre] client_id, client_secret e redirect_uri no config.toml")

    auth_url = "https://auth.mercadolivre.com.br/authorization?" + urlencode({
        "response_type": "code", "client_id": s.ml_client_id, "redirect_uri": s.ml_redirect_uri})
    print("\nAbrindo o navegador para você autorizar o app...\n", auth_url, "\n")
    webbrowser.open(auth_url)
    pasted = input("Depois de autorizar, cole aqui a URL para onde você foi redirecionado\n"
                   "(ou só o código que vem depois de ?code=): ").strip()
    code = parse_qs(urlparse(pasted).query).get("code", [pasted])[0]

    r = httpx.post("https://api.mercadolibre.com/oauth/token", data={
        "grant_type": "authorization_code", "client_id": s.ml_client_id,
        "client_secret": s.ml_client_secret, "code": code, "redirect_uri": s.ml_redirect_uri,
    }, headers={"accept": "application/json"}, timeout=20)
    if r.status_code != 200:
        sys.exit(f"Erro {r.status_code}: {r.text}")
    p = r.json()
    out = BASE / "data" / "ml_token.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "access_token": p["access_token"], "refresh_token": p.get("refresh_token"),
        "expires_at": time.time() + int(p.get("expires_in", 21600)) - 120, "user_id": p.get("user_id"),
    }, indent=2))
    print(f"\nPronto! Token salvo em {out}. Agora rode: python run.py")
    if not p.get("refresh_token"):
        print("Atenção: não veio refresh_token. Ative o escopo 'offline_access' no seu app do ML.")


if __name__ == "__main__":
    main()
