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
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from sniper import config, paths, winsys
from sniper.server import create_app

BASE = paths.dados_dir()


def _ja_rodando(port: int) -> bool:
    """True se já houver algo escutando em 127.0.0.1:<port> (outra instância do Sniper)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _janela(url: str) -> None:
    """Abre o painel na janela nativa (pywebview). Levanta ImportError se não estiver instalado."""
    import webview  # pywebview: janela nativa (Edge WebView2 no Windows)
    webview.settings["ALLOW_DOWNLOADS"] = True  # botão "Exportar CSV" do painel
    webview.create_window("Sniper de Ofertas", url, width=1400, height=880, min_size=(900, 600))
    webview.start()


def _abrir_janela_existente(url: str, navegador: bool) -> None:
    if not navegador:
        try:
            _janela(url)
            return
        except ImportError:
            print("pywebview não instalado; abrindo no navegador.")
    webbrowser.open(url)


def main() -> None:
    if sys.stdout is None:  # .exe sem console: print() e logging no terminal não têm para onde ir
        sys.stdout = sys.stderr = open(os.devnull, "w")
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
    if paths.empacotado():
        paths.garantir_config(cfg_path)
    if not cfg_path.exists():
        print("config.toml não encontrado. Copie config.exemplo.toml para config.toml e edite.")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  RotatingFileHandler(BASE / "data" / "sniper.log", maxBytes=5 * 1024 * 1024,
                                                      backupCount=4, encoding="utf-8")])
    for barulhento in ("httpx", "httpcore"):  # não registra cada requisição: o log fica legível
        logging.getLogger(barulhento).setLevel(logging.WARNING)
    if winsys.impedir_suspensao():
        logging.getLogger("sniper").info("Suspensão do Windows bloqueada enquanto o Sniper roda")
    settings = config.load(cfg_path)
    url = f"http://127.0.0.1:{settings.port}"

    if _ja_rodando(settings.port):
        if args.sem_janela:
            print(f"O Sniper já está rodando em {url}")
            return
        print(f"O Sniper já está rodando em {url}; abrindo o painel.")
        _abrir_janela_existente(url, args.navegador)
        return

    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=settings.port, log_level="warning"))

    if args.sem_janela:
        print(f"Painel em {url}")
        server.run()
        return

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        if not t.is_alive():
            print(f"Não consegui iniciar o servidor na porta {settings.port}.")
            sys.exit(1)
        time.sleep(0.1)

    if not args.navegador:
        try:
            _janela(url)
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
    (BASE / "data").mkdir(parents=True, exist_ok=True)
    main()
