"""Inicia o Sniper de Ofertas: motor + API local + janela do painel.

Uso:
    python run.py                 # abre a janela do app
    python run.py --navegador     # abre o painel no navegador padrão
    python run.py --sem-janela    # só o motor/servidor (painel em http://127.0.0.1:8765)
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from sniper import config
from sniper.server import create_app

BASE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(BASE / "config.toml"))
    ap.add_argument("--navegador", action="store_true")
    ap.add_argument("--sem-janela", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print("config.toml não encontrado. Copie config.exemplo.toml para config.toml e edite.")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(BASE / "data" / "sniper.log", encoding="utf-8")])
    settings = config.load(cfg_path)
    app = create_app(settings)
    url = f"http://127.0.0.1:{settings.port}"

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=settings.port, log_level="warning"))

    if args.sem_janela:
        print(f"Painel em {url}")
        server.run()
        return

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.1)

    if not args.navegador:
        try:
            import webview  # pywebview: janela nativa (Edge WebView2 no Windows)
            webview.create_window("Sniper de Ofertas", url, width=1400, height=880, min_size=(900, 600))
            webview.start()
            server.should_exit = True
            return
        except ImportError:
            print("pywebview não instalado; abrindo no navegador.")

    webbrowser.open(url)
    print(f"Painel em {url}  (Ctrl+C para sair)")
    try:
        t.join()
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    (BASE / "data").mkdir(exist_ok=True)
    main()
