"""Move segredos de arquivos de texto (config.toml, ml_token.json) para o cofre do Windows.

Só limpa o arquivo depois de conferir que o cofre devolve o mesmo valor.
Uso: python -m sniper.migracao [pasta-do-app]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from . import segredos

# (seção do config.toml, chave do config.toml, nome no cofre)
CAMPOS = [("mercadolivre", "client_secret", "ml_client_secret"),
          ("telegram", "bot_token", "telegram_bot_token")]


def _guarda_e_confere(nome: str, valor: str) -> None:
    segredos.guardar(nome, valor)
    if segredos.ler(nome) != valor:
        raise segredos.CofreIndisponivel(f"O cofre não devolveu o valor de {nome}; nada foi apagado.")


def migrar(config_path: Path, token_path: Path) -> list[str]:
    """Devolve os nomes migrados. Se algo falhar, levanta antes de alterar qualquer arquivo."""
    config_path, token_path = Path(config_path), Path(token_path)
    feito: list[str] = []
    texto = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    novo = texto
    for secao, chave, nome in CAMPOS:
        m = re.search(rf'(?ms)^\[{secao}\]\s*$.*?(?=^\[|\Z)', novo)
        if not m:
            continue
        linha = re.search(rf'(?m)^({chave}\s*=\s*)"([^"]+)"', m.group(0))
        if not linha:
            continue
        _guarda_e_confere(nome, linha.group(2))
        bloco = m.group(0)[:linha.start()] + f'{linha.group(1)}""' + m.group(0)[linha.end():]
        novo = novo[:m.start()] + bloco + novo[m.end():]
        feito.append(nome)
    if token_path.exists():
        conteudo = token_path.read_text(encoding="utf-8")
        _guarda_e_confere("ml_token", conteudo)
        feito.append("ml_token")
    # tudo conferido: só agora mexe nos arquivos
    if novo != texto:
        config_path.write_text(novo, encoding="utf-8")
    if "ml_token" in feito:
        token_path.unlink()
    return feito


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    print("Migrado para o cofre do Windows:", migrar(base / "config.toml", base / "data" / "ml_token.json") or "nada")
