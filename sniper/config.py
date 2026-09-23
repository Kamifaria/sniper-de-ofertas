"""Carrega o config.toml (em português) para objetos do motor."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .detector import DetectorConfig
from .filters import FilterConfig
from .models import Watch


@dataclass
class Settings:
    base_dir: Path
    db_path: Path
    port: int = 8765
    min_alert_score: int = 50
    cooldown_min: int = 30
    ml_client_id: str = ""
    ml_client_secret: str = ""
    ml_redirect_uri: str = ""
    telegram_on: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_min_score: int = 70
    windows_on: bool = True
    windows_min_score: int = 70
    demo_on: bool = False
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    watches: list[Watch] = field(default_factory=list)


def load(path: str | Path) -> Settings:
    path = Path(path).resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    g = raw.get("geral", {})
    d = raw.get("detector", {})
    ml = raw.get("mercadolivre", {})
    tg = raw.get("telegram", {})
    win = raw.get("windows", {})
    demo = raw.get("demo", {})
    f = raw.get("filtros", {})
    fc = FilterConfig()
    fc.test_words += [str(x) for x in f.get("palavras_teste_extras", [])]
    fc.accessory_words += [str(x) for x in f.get("acessorios_extras", [])]
    fc.exclude_used = bool(f.get("excluir_usados", fc.exclude_used))
    fc.require_query_terms = bool(f.get("exigir_termos_da_busca", fc.require_query_terms))
    fc.min_seller_sales = int(f.get("min_vendas_vendedor", fc.min_seller_sales))
    fc.min_seller_days = int(f.get("min_dias_conta_vendedor", fc.min_seller_days))
    fc.confirm_before_alert = bool(f.get("reconfirmar_preco", fc.confirm_before_alert))

    watches = []
    for w in raw.get("vigiar", []):
        watches.append(Watch(
            name=w["nome"],
            store=w.get("loja", "mercadolivre"),
            query=w.get("busca", ""),
            category=w.get("categoria", ""),
            item_ids=list(w.get("itens", [])),
            interval=int(w.get("intervalo", 120)),
            floor=w.get("piso"),
            max_pages=int(w.get("paginas", 1)),
            min_price=w.get("preco_minimo"),
            exclude_words=[str(x) for x in w.get("excluir", [])],
            allow_used=bool(w.get("aceitar_usados", False)),
        ))
    if demo.get("ativo"):
        watches.append(Watch(name="Demonstração", store="demo", interval=int(demo.get("intervalo", 5))))

    return Settings(
        base_dir=base,
        db_path=base / g.get("banco", "data/sniper.db"),
        port=int(g.get("porta", 8765)),
        min_alert_score=int(g.get("nota_minima_alerta", 50)),
        cooldown_min=int(g.get("cooldown_minutos", 30)),
        ml_client_id=str(ml.get("client_id", "")),
        ml_client_secret=str(ml.get("client_secret", "")),
        ml_redirect_uri=str(ml.get("redirect_uri", "")),
        telegram_on=bool(tg.get("ativo", False)),
        telegram_token=str(tg.get("bot_token", "")),
        telegram_chat_id=str(tg.get("chat_id", "")),
        telegram_min_score=int(tg.get("nota_minima", 70)),
        windows_on=bool(win.get("notificacao", True)),
        windows_min_score=int(win.get("nota_minima", 70)),
        demo_on=bool(demo.get("ativo", False)),
        detector=DetectorConfig(
            free_threshold=float(d.get("preco_gratis", 1.0)),
            min_history=int(d.get("historico_minimo", 3)),
            min_peers=int(d.get("concorrentes_minimos", 2)),
        ),
        filters=fc,
        watches=watches,
    )
