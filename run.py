"""Inicia o Sniper de Ofertas: motor + API local + janela do painel.

Uso:
    python run.py                 # abre a janela do app
    python run.py --navegador     # abre o painel no navegador padrão
    python run.py --sem-janela    # só o motor/servidor (painel em http://127.0.0.1:8765)
    python run.py --instalar-inicio   # abre sozinho quando o Windows iniciar
    python run.py --remover-inicio    # desfaz o anterior
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from sniper import config, winsys
from sniper.server import create_app

BASE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(BASE / "config.toml"))
    ap.add_argument("--navegador", action="store_true")
    ap.add_argument("--sem-janela", action="store_true")
    ap.add_argument("--instalar-inicio", action="store_true")
    ap.add_argument("--remover-inicio", action="store_true")
    args = ap.parse_args()

    if args.instalar_inicio:
        lnk = winsys.instalar_inicio(BASE)
        print(f"Atalho criado em {lnk}. O Sniper vai abrir sozinho quando o Windows iniciar.")
        return
    if args.remover_inicio:
        print("Atalho de inicialização removido." if winsys.remover_inicio()
              else "Não havia atalho de inicialização.")
        return

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print("config.toml não encontrado. Copie config.exemplo.toml para config.toml e edite.")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  RotatingFileHandler(BASE / "data" / "sniper.log", maxBytes=5 * 1024 * 1024,
                                                      backupCount=4, encoding="utf-8")])
    if winsys.impedir_suspensao():
        logging.getLogger("sniper").info("Suspensão do Windows bloqueada enquanto o Sniper roda")
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
