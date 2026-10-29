"""Banco local SQLite: itens, histórico de preços e alertas."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .detector import causa_bug
from .models import Offer, Verdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    store TEXT, item_id TEXT, title TEXT, url TEXT, thumbnail TEXT,
    category TEXT, watch TEXT, last_price REAL, last_seen REAL,
    PRIMARY KEY (store, item_id)
);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT, item_id TEXT, price REAL, original_price REAL, ts REAL
);
CREATE INDEX IF NOT EXISTS ix_prices_item ON prices (store, item_id, ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT, item_id TEXT, title TEXT, url TEXT, thumbnail TEXT, watch TEXT,
    price REAL, ref_price REAL, drop_pct REAL, score INTEGER, level TEXT,
    reasons TEXT, free_shipping INTEGER, ts REAL, status TEXT DEFAULT 'novo'
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts ON alerts (ts);
CREATE TABLE IF NOT EXISTS sellers (
    store TEXT, seller_id TEXT, nickname TEXT, sales INTEGER, level TEXT,
    registered_days INTEGER, status TEXT, blocked INTEGER DEFAULT 0, block_reason TEXT,
    updated REAL, PRIMARY KEY (store, seller_id)
);
CREATE TABLE IF NOT EXISTS discards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT, item_id TEXT, title TEXT, url TEXT, seller_id TEXT, seller_name TEXT,
    price REAL, score INTEGER, reason TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS ix_discards_ts ON discards (ts);
CREATE TABLE IF NOT EXISTS sweep_state (
    watch TEXT PRIMARY KEY, units TEXT, units_ts REAL, cursor INTEGER DEFAULT 0, cycle_started REAL
);
CREATE TABLE IF NOT EXISTS store_prefs (store TEXT PRIMARY KEY, ativo INTEGER);
"""


def ean_valido(ean: str) -> bool:
    """GTIN-8/12/13/14 com dígito verificador certo. Códigos internos (prefixo 2) e repetidos ficam de fora."""
    if not ean or not ean.isdigit() or len(ean) not in (8, 12, 13, 14) or len(set(ean)) == 1:
        return False
    if len(ean) == 13 and ean.startswith("2"):  # código de uso interno da loja (balança, kits)
        return False
    d = [int(c) for c in ean]
    soma = sum(x * (3 if i % 2 else 1) for i, x in enumerate(reversed(d[:-1]), start=1))
    return (10 - soma % 10) % 10 == d[-1]

# Colunas novas em bancos criados por versões anteriores.
MIGRATIONS = {
    "items": {"catalog_id": "TEXT", "seller_id": "TEXT", "seller_name": "TEXT", "condition": "TEXT"},
    "alerts": {"seller_id": "TEXT", "seller_name": "TEXT", "confirmed": "INTEGER DEFAULT 0",
               "catalog_id": "TEXT", "cart_url": "TEXT"},
    "prices": {"reads": "INTEGER DEFAULT 1"},
}

REGRAVAR_APOS_S = 6 * 3600  # mesmo preço: grava linha nova só depois disso (senão soma em `reads`)


class Database:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_items_catalog ON items (store, catalog_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_items_price ON items (store, last_price)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_items_ean ON items (catalog_id)")
        # O modo demonstração foi removido: apaga o que a loja simulada deixou no banco.
        for table in ("prices", "items", "alerts", "discards", "sellers"):
            self.conn.execute(f"DELETE FROM {table} WHERE store='demo'")
        self.conn.commit()
        self.lock = threading.Lock()

    # ---------- preços ----------
    def history(self, store: str, item_id: str, days: int = 30, limit: int = 500) -> list[float]:
        """Leituras de preço, da mais antiga para a mais nova. Uma linha com `reads`=N conta como N leituras."""
        since = time.time() - days * 86400
        rows = self.conn.execute(
            "SELECT price, COALESCE(reads, 1) AS reads FROM prices WHERE store=? AND item_id=? AND ts>=? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (store, item_id, since, limit),
        ).fetchall()
        out: list[float] = []
        for r in rows:
            out.extend([r["price"]] * min(r["reads"], limit - len(out)))
            if len(out) >= limit:
                break
        return list(reversed(out))

    def history_points(self, store: str, item_id: str, days: int = 30) -> list[dict]:
        since = time.time() - days * 86400
        rows = self.conn.execute(
            "SELECT price, ts FROM prices WHERE store=? AND item_id=? AND ts>=? ORDER BY ts",
            (store, item_id, since),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_offer(self, o: Offer) -> None:
        with self.lock, self.conn:
            last = self.conn.execute(
                "SELECT id, price, original_price, ts FROM prices WHERE store=? AND item_id=? "
                "ORDER BY ts DESC, id DESC LIMIT 1", (o.store, o.item_id)).fetchone()
            if (last is not None and last["price"] == o.price and last["original_price"] == o.original_price
                    and o.collected_at - last["ts"] < REGRAVAR_APOS_S):
                self.conn.execute("UPDATE prices SET reads = COALESCE(reads, 1) + 1 WHERE id=?", (last["id"],))
            else:
                self.conn.execute(
                    "INSERT INTO prices (store,item_id,price,original_price,ts,reads) VALUES (?,?,?,?,?,1)",
                    (o.store, o.item_id, o.price, o.original_price, o.collected_at),
                )
            self.conn.execute(
                """INSERT INTO items (store,item_id,title,url,thumbnail,category,watch,last_price,last_seen,
                     catalog_id,seller_id,seller_name,condition)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(store,item_id) DO UPDATE SET title=excluded.title, url=excluded.url,
                     thumbnail=excluded.thumbnail, last_price=excluded.last_price, last_seen=excluded.last_seen,
                     catalog_id=excluded.catalog_id, seller_id=excluded.seller_id,
                     seller_name=excluded.seller_name, condition=excluded.condition""",
                (o.store, o.item_id, o.title, o.url, o.thumbnail, o.category, o.watch, o.price, o.collected_at,
                 o.catalog_id, o.seller_id, o.seller_name, o.condition),
            )

    # ---------- alertas ----------
    def last_alert(self, store: str, item_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM alerts WHERE store=? AND item_id=? ORDER BY ts DESC LIMIT 1",
            (store, item_id),
        ).fetchone()

    def save_alert(self, o: Offer, v: Verdict) -> dict:
        with self.lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO alerts (store,item_id,title,url,thumbnail,watch,price,ref_price,drop_pct,
                   score,level,reasons,free_shipping,ts,seller_id,seller_name,confirmed,catalog_id,cart_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (o.store, o.item_id, o.title, o.url, o.thumbnail, o.watch, o.price, v.ref_price,
                 v.drop_pct, v.score, v.level, json.dumps(v.reasons, ensure_ascii=False),
                 int(o.free_shipping), o.collected_at, o.seller_id, o.seller_name, int(o.confirmed),
                 o.catalog_id, o.cart_url),
            )
            alert_id = cur.lastrowid
        return self.get_alert(alert_id)

    def get_alert(self, alert_id: int) -> dict:
        r = self.conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return self._alert_dict(r) if r else {}

    def list_alerts(self, limit: int = 100, min_score: int = 0, status: str | None = None,
                    since: float | None = None) -> list[dict]:
        sql = "SELECT * FROM alerts WHERE score>=?"
        args: list = [min_score]
        if status:
            sql += " AND status=?"; args.append(status)
        if since:
            sql += " AND ts>=?"; args.append(since)
        sql += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
        return [self._alert_dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def limpar_alertas(self) -> int:
        """Apaga a lista de alertas. O histórico de preços fica (o detector precisa dele)."""
        with self.lock, self.conn:
            return self.conn.execute("DELETE FROM alerts").rowcount

    def set_alert_status(self, alert_id: int, status: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))

    def stats(self) -> dict:
        day = time.time() - 86400
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        return {
            "itens": q("SELECT COUNT(*) FROM items"),
            "leituras_24h": q("SELECT COALESCE(SUM(COALESCE(reads, 1)), 0) FROM prices WHERE ts>=?", day),
            "alertas_24h": q("SELECT COUNT(*) FROM alerts WHERE ts>=?", day),
            "gratis_24h": q("SELECT COUNT(*) FROM alerts WHERE ts>=? AND level='GRATIS'", day),
            "criticos_24h": q("SELECT COUNT(*) FROM alerts WHERE ts>=? AND level='CRITICO'", day),
            "comprados": q("SELECT COUNT(*) FROM alerts WHERE status='comprado'"),
            "descartados_24h": q("SELECT COUNT(*) FROM discards WHERE ts>=?", day),
            "lojas_bloqueadas": q("SELECT COUNT(*) FROM sellers WHERE blocked=1"),
        }

    # ---------- concorrentes (mesmo produto de catálogo) ----------
    def peer_prices(self, store: str, catalog_id: str, exclude_item: str, max_age_h: float = 48) -> list[float]:
        if not catalog_id:
            return []
        rows = self.conn.execute(
            "SELECT last_price FROM items WHERE store=? AND catalog_id=? AND item_id!=? AND last_seen>=?",
            (store, catalog_id, exclude_item, time.time() - max_age_h * 3600),
        ).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def cross_store_prices(self, ean: str, exclude_store: str, max_age_h: float = 48) -> list[float]:
        """Preço do mesmo código de barras em OUTRAS lojas (um por loja). Loja que usa o EAN em mais
        de um produto (ex.: unidade x caixa) fica de fora, porque aí o código não identifica o produto."""
        if not ean_valido(ean):
            return []
        rows = self.conn.execute(
            "SELECT MAX(last_price) FROM items WHERE catalog_id=? AND store!=? AND last_seen>=? "
            "GROUP BY store HAVING COUNT(*)=1",
            (ean, exclude_store, time.time() - max_age_h * 3600)).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def ean_unico(self, store: str, ean: str) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM items WHERE store=? AND catalog_id=?",
                                 (store, ean)).fetchone()[0] <= 1

    # ---------- lojas escolhidas no painel ----------
    def store_prefs(self) -> dict[str, bool]:
        return {r[0]: bool(r[1]) for r in self.conn.execute("SELECT store, ativo FROM store_prefs")}

    def set_store_pref(self, store: str, ativo: bool) -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO store_prefs (store, ativo) VALUES (?,?) "
                              "ON CONFLICT(store) DO UPDATE SET ativo=excluded.ativo", (store, int(ativo)))

    # ---------- fila rápida ----------
    def catalog_ids(self, store: str, item_ids: list[str]) -> list[str]:
        """Produtos do catálogo (sem repetir, na ordem dos itens) de uma lista de anúncios."""
        out: dict[str, None] = {}
        for i in range(0, len(item_ids), 500):
            lote = item_ids[i:i + 500]
            marks = ",".join("?" * len(lote))
            rows = dict(self.conn.execute(
                f"SELECT item_id, catalog_id FROM items WHERE store=? AND item_id IN ({marks})",
                [store, *lote]).fetchall())
            for iid in lote:
                if rows.get(iid):
                    out[rows[iid]] = None
        return list(out)

    def fast_lane_items(self, store: str, min_price: float, limit: int, max_age_s: float = 48 * 3600) -> list[str]:
        """Itens caros vistos recentemente, do mais caro para o mais barato."""
        rows = self.conn.execute(
            "SELECT item_id FROM items WHERE store=? AND last_price>=? AND last_seen>=? "
            "ORDER BY last_price DESC LIMIT ?",
            (store, min_price, time.time() - max_age_s, limit)).fetchall()
        return [r[0] for r in rows]

    # ---------- vendedores ----------
    def get_seller(self, store: str, seller_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sellers WHERE store=? AND seller_id=?",
                                 (store, seller_id)).fetchone()

    def save_seller(self, store: str, s) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO sellers (store,seller_id,nickname,sales,level,registered_days,status,updated)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(store,seller_id) DO UPDATE SET nickname=excluded.nickname, sales=excluded.sales,
                     level=excluded.level, registered_days=excluded.registered_days,
                     status=excluded.status, updated=excluded.updated""",
                (store, s.seller_id, s.nickname, s.sales, s.level, s.registered_days, s.status, time.time()),
            )

    def block_seller(self, store: str, seller_id: str, nickname: str = "", reason: str = "", blocked: bool = True) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO sellers (store,seller_id,nickname,blocked,block_reason,updated) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(store,seller_id) DO UPDATE SET blocked=excluded.blocked,
                     block_reason=excluded.block_reason,
                     nickname=COALESCE(NULLIF(excluded.nickname,''), sellers.nickname)""",
                (store, seller_id, nickname, int(blocked), reason, time.time()),
            )

    def blocked_sellers(self) -> set[str]:
        return {f"{r[0]}:{r[1]}" for r in
                self.conn.execute("SELECT store, seller_id FROM sellers WHERE blocked=1")}

    def list_blocked(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT store,seller_id,nickname,block_reason,updated FROM sellers WHERE blocked=1 ORDER BY updated DESC")]

    # ---------- varredura ----------
    def get_sweep(self, watch: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM sweep_state WHERE watch=?", (watch,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["units"] = json.loads(d["units"] or "[]")
        return d

    def save_sweep(self, watch: str, units: list[str], units_ts: float, cursor: int,
                   cycle_started: float) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO sweep_state (watch,units,units_ts,cursor,cycle_started) VALUES (?,?,?,?,?)
                   ON CONFLICT(watch) DO UPDATE SET units=excluded.units, units_ts=excluded.units_ts,
                     cursor=excluded.cursor, cycle_started=excluded.cycle_started""",
                (watch, json.dumps(units), units_ts, cursor, cycle_started))

    def save_sweep_cursor(self, watch: str, cursor: int, cycle_started: float) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE sweep_state SET cursor=?, cycle_started=? WHERE watch=?",
                              (cursor, cycle_started, watch))

    # ---------- descartes ----------
    def save_discard(self, o: Offer, score: int, reason: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO discards (store,item_id,title,url,seller_id,seller_name,price,score,reason,ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (o.store, o.item_id, o.title, o.url, o.seller_id, o.seller_name, o.price, score, reason,
                 o.collected_at),
            )

    def recent_discard(self, store: str, item_id: str, within_s: float) -> bool:
        return self.conn.execute("SELECT 1 FROM discards WHERE store=? AND item_id=? AND ts>=? LIMIT 1",
                                 (store, item_id, time.time() - within_s)).fetchone() is not None

    def list_discards(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            """SELECT d.*, COALESCE(s.blocked, 0) AS seller_blocked FROM discards d
               LEFT JOIN sellers s ON s.store=d.store AND s.seller_id=d.seller_id
               ORDER BY d.ts DESC LIMIT ?""", (limit,))]

    def seller_discard_count(self, store: str, seller_id: str, days: int = 7) -> int:
        return self.conn.execute(
            "SELECT COUNT(DISTINCT item_id) FROM discards WHERE store=? AND seller_id=? AND ts>=?",
            (store, seller_id, time.time() - days * 86400)).fetchone()[0]

    def prune(self, days: int = 30) -> None:
        """Apaga cópias de dados do marketplace mais velhas que `days` (termos de uso da API)."""
        corte = time.time() - days * 86400
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM prices WHERE ts<?", (corte,))
            self.conn.execute("DELETE FROM discards WHERE ts<?", (corte,))
            self.conn.execute("DELETE FROM alerts WHERE ts<?", (corte,))
            self.conn.execute("DELETE FROM items WHERE last_seen<?", (corte,))

    @staticmethod
    def _alert_dict(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["reasons"] = json.loads(d["reasons"] or "[]")
        d["free_shipping"] = bool(d["free_shipping"])
        d["confirmed"] = bool(d.get("confirmed"))
        d["bug"] = causa_bug(d["level"], d["reasons"])
        d["tipo"] = "PROMO" if d["level"] == "PROMO" else "BUG"
        return d
