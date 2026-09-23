# Fase 1 — Base multi-loja e modo varredura: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tirar o modo demo e preparar o Sniper para caçar bugs de preço em muitas lojas, rodando 24 horas: registro de lojas com etiqueta oficial/não oficial, limite de consultas por loja, varredura de catálogo em rodízio, fila rápida para itens caros e avisos de saúde no Telegram.

**Architecture:** Um registro (`sniper/stores.py`) diz quais lojas existem e como criar o coletor. O `Engine` cria um `RateLimiter` por loja ativa e roda três tipos de loop sob um supervisor: `vigiar` (busca, como hoje), `varrer` (uma unidade do catálogo por vez, com cursor salvo no SQLite) e fila rápida (relê itens caros em lote). Os três passam as ofertas pelo mesmo pipeline `Engine._process`. O Mercado Livre é a única loja real nesta fase.

**Tech Stack:** Python 3.11+ (o venv usa 3.13), asyncio, httpx, Starlette/uvicorn, SQLite, unittest, HTML/JS puro no painel.

**Spec:** `docs/superpowers/specs/2026-09-23-fase1-base-varredura-design.md`

## Global Constraints

- Nenhuma dependência nova: `requirements.txt` não muda.
- Testes com `unittest`, rodando da raiz do projeto: `.venv\Scripts\python -m unittest discover tests -v` (PowerShell).
- Todo texto de interface, log, config e mensagem de Telegram em **português do Brasil**.
- **Mensagens de commit em português do Brasil**, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- O servidor continua escutando só em `127.0.0.1`.
- Os filtros de anúncio e de vendedor de teste (`filters.check_listing`, `filters.check_seller`, bloqueio automático) **não** podem ser removidos nem enfraquecidos.
- `config.toml` guarda as credenciais da usuária e não é versionado. Só se remove o bloco `[demo]` dele; nada mais é alterado.
- Os testes existentes em `tests/test_sniper.py` precisam continuar passando ao fim de cada tarefa.
- Valores padrão (copiados da spec): pausa por bloqueio de 1/5/15/60 min; teto da fila rápida em 50% da cota; `valor_alto = 300`; `intervalo_rapido = 120`; `max_itens_rapida = 1000`; janela da fila rápida de 48 h; nova linha de preço a cada 6 h; cache de unidades de varredura de 24 h; supervisor reinicia em 30 s; log de 5 MB × 5 arquivos; `avisar_travada_minutos = 30`; `resumo_diario = "09:00"`; Mercado Livre com `por_minuto = 60`.

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `sniper/collectors/demo.py` | **Apagado** |
| `sniper/ratelimit.py` | **Novo.** `RateLimiter`: fichas por minuto, teto da fila rápida, pausa em degraus |
| `sniper/stores.py` | **Novo.** `LojaInfo` + `LOJAS`: nome, etiqueta, fábrica do coletor |
| `sniper/winsys.py` | **Novo.** Bloqueio de suspensão e atalho de inicialização do Windows |
| `sniper/config.py` | `LojaConfig`, `[lojas.*]`, `[[varrer]]`, `[varredura]`, campos novos de `[telegram]`; sai o `[demo]` |
| `sniper/models.py` | `Watch.kind`, `Watch.sweep_categories`, `Watch.cycle_min` |
| `sniper/db.py` | Limpeza do demo, `prices.reads`, `sweep_state`, `fast_lane_items` |
| `sniper/collectors/base.py` | Métodos opcionais de varredura e refresh |
| `sniper/collectors/mercadolivre.py` | Limiter, varredura por categoria, refresh em lote |
| `sniper/engine.py` | Registro de lojas, `_process`, supervisor, loops de varredura/fila rápida/saúde, `lojas_info` |
| `sniper/notify.py` | `TelegramNotifier.send_text` |
| `sniper/server.py` | `GET /api/lojas` |
| `sniper/web/index.html` | Bloco Lojas, progresso da varredura, fila rápida, nomes vindos da API |
| `run.py` | Log rotativo, bloqueio de suspensão, `--instalar-inicio` / `--remover-inicio` |
| `config.exemplo.toml`, `README.md` | Documentação do que mudou |
| `tests/fakes.py` | **Novo.** Coletores e motor falsos compartilhados |
| `tests/test_*.py` | **Novos.** Um arquivo por área |

---

### Task 0: Verificar o acesso real à API do Mercado Livre

Não é código versionado. É o risco da spec, seção 4: a varredura depende de busca por categoria com `sort=price_asc` e dos endpoints de categoria.

- [ ] **Step 1: Ver se existe token**

Run (PowerShell, na raiz do projeto): `Test-Path data\ml_token.json`

Se der `False`, a usuária ainda não autorizou o app (`python auth_ml.py`). **Anote "Verificação do ML: PENDENTE (sem token)" para o relatório final e siga para a Task 1.** Todo o resto do plano usa respostas falsas e não depende disso.

- [ ] **Step 2 (só se existir token): Rodar a verificação**

Salve em `<scratchpad>\verifica_ml.py` (fora do repositório) e rode com `.venv\Scripts\python <scratchpad>\verifica_ml.py` a partir da raiz do projeto:

```python
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")
from sniper import config  # noqa: E402
from sniper.collectors.mercadolivre import API, MercadoLivreCollector  # noqa: E402


async def main():
    s = config.load("config.toml")
    c = MercadoLivreCollector(s.ml_client_id, s.ml_client_secret, Path("data/ml_token.json"))
    try:
        busca = await c._get("/sites/MLB/search", {"category": "MLB1055", "sort": "price_asc", "limit": 5})
        print("busca por categoria, mais barato primeiro:", [r["price"] for r in busca["results"]])
        cat = await c._get("/categories/MLB1055")
        print("MLB1055 tem", len(cat.get("children_categories") or []), "filhas")
        raizes = await c._get("/sites/MLB/categories")
        print("categorias raiz:", len(raizes))
        token = await c.tokens.access_token(c.client)
        r = await c.client.get(f"{API}/sites/MLB/categories/all", timeout=120,
                               headers={"Authorization": f"Bearer {token}"})
        print("dump de categorias: HTTP", r.status_code, "·", len(r.content) // 1024, "KB")
    finally:
        await c.close()


asyncio.run(main())
```

Esperado: a lista de preços em ordem crescente, número de filhas ≥ 0, cerca de 30 raízes e o dump com HTTP 200.

- [ ] **Step 3: Decidir**

- A busca retornou 403, ou os preços **não** vieram em ordem crescente: **PARE** e avise a usuária. A varredura do ML precisa ser repensada antes das Tasks 6 e 7.
- Só o dump falhou: tudo bem. O código da Task 7 cai para a leitura nó a nó. Anote no relatório.
- Tudo ok: anote "Verificação do ML: OK" e siga.

---

### Task 1: Remover o modo demonstração

**Files:**
- Delete: `sniper/collectors/demo.py`
- Modify: `sniper/collectors/__init__.py`, `sniper/engine.py:11,36-37`, `sniper/config.py:29,44,70-71,88`, `sniper/models.py:12`, `sniper/db.py:58-65`, `sniper/web/index.html:153`, `config.exemplo.toml:45-49`, `config.toml` (bloco `[demo]`), `README.md:11,27,69`
- Test: `tests/test_limpeza_demo.py`

**Interfaces:**
- Consumes: nada.
- Produces: `sniper.collectors` exporta só `Collector`, `CollectorError`, `MercadoLivreCollector`. `Settings` não tem mais `demo_on`. `Database.__init__` apaga `store='demo'`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_limpeza_demo.py`:

```python
"""Testes da remoção do modo demonstração."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import collectors, config  # noqa: E402
from sniper.db import Database  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.models import Offer  # noqa: E402


class LimpezaDemoTests(unittest.TestCase):
    def test_banco_apaga_so_linhas_demo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.db"
            db = Database(p)
            for store in ("demo", "mercadolivre"):
                o = Offer(store=store, item_id="I1", title="Produto", price=10.0, url="https://x",
                          seller_id="S1", seller_name="LOJA")
                db.save_offer(o)
                db.save_alert(o, evaluate(o, []))
                db.save_discard(o, 50, "motivo")
                db.block_seller(store, "S1", "LOJA", "teste")
            db.conn.close()

            db = Database(p)
            for table in ("prices", "items", "alerts", "discards", "sellers"):
                stores = {r[0] for r in db.conn.execute(f"SELECT store FROM {table}")}
                self.assertEqual(stores, {"mercadolivre"}, table)
            db.conn.close()

    def test_coletor_demo_nao_existe(self):
        self.assertFalse(hasattr(collectors, "DemoCollector"))

    def test_config_ignora_bloco_demo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[demo]\nativo = true\nintervalo = 5\n", encoding="utf-8")
            s = config.load(p)
            self.assertEqual([w for w in s.watches if w.store == "demo"], [])
            self.assertFalse(hasattr(s, "demo_on"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_limpeza_demo -v`
Expected: 3 FAIL (as linhas demo continuam, `DemoCollector` existe, `demo_on` existe).

- [ ] **Step 3: Remover o coletor**

Apague `sniper/collectors/demo.py` (`git rm sniper/collectors/demo.py`).

`sniper/collectors/__init__.py` inteiro:

```python
from .base import Collector, CollectorError
from .mercadolivre import MercadoLivreCollector

__all__ = ["Collector", "CollectorError", "MercadoLivreCollector"]
```

Em `sniper/engine.py`, linha 11, troque por:

```python
from .collectors import Collector, CollectorError, MercadoLivreCollector
```

e apague as linhas 36-37:

```python
        if settings.demo_on:
            self.collectors["demo"] = DemoCollector()
```

- [ ] **Step 4: Remover do config e do modelo**

Em `sniper/config.py`, apague:
- linha 29: `    demo_on: bool = False`
- linha 44: `    demo = raw.get("demo", {})`
- linhas 70-71: o `if demo.get("ativo"): watches.append(...)`
- linha 88: `        demo_on=bool(demo.get("ativo", False)),`

Em `sniper/models.py`, linha 12, troque o comentário:

```python
    store: str                      # chave da loja em sniper/stores.py (ex.: "mercadolivre")
```

- [ ] **Step 5: Limpar o banco na inicialização**

Em `sniper/db.py`, no `Database.__init__`, logo depois da linha `self.conn.execute("CREATE INDEX IF NOT EXISTS ix_items_catalog ON items (store, catalog_id)")` e antes do `self.conn.commit()`:

```python
        # O modo demonstração foi removido: apaga o que a loja simulada deixou no banco.
        for table in ("prices", "items", "alerts", "discards", "sellers"):
            self.conn.execute(f"DELETE FROM {table} WHERE store='demo'")
```

- [ ] **Step 6: Painel, configs e README**

`sniper/web/index.html`, linha 153:

```js
const STORE = {mercadolivre: "Mercado Livre", shopee: "Shopee", shein: "Shein"};
```

`config.exemplo.toml`: apague as linhas 45-49 (o comentário "Modo demonstração…" e o bloco `[demo]` inteiro). Faça o mesmo em `config.toml`: apague só as linhas do bloco `[demo]` e o comentário acima dele, sem mexer no resto.

`README.md`:
- Linha 11 passa a ser: `3. O painel abre em uma janela própria. Sem loja configurada ele fica vazio: siga "Ligar o Mercado Livre de verdade" abaixo.`
- Apague a linha 27: `4. Em [demo], mude para ativo = false e reinicie.`
- Linha 69 passa a ser: ``sniper/collectors/     um coletor por loja (mercadolivre)``

- [ ] **Step 7: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS (os 3 novos + os existentes).

- [ ] **Step 8: Commit**

```powershell
git add -A sniper tests config.exemplo.toml README.md
git commit -m @'
Remove o modo demonstração e limpa os dados da loja simulada

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 2: Contador de leituras no histórico de preços

**Files:**
- Modify: `sniper/db.py` (`MIGRATIONS`, `history`, `save_offer`, `stats`)
- Test: `tests/test_banco_leituras.py`

**Interfaces:**
- Consumes: nada.
- Produces: `sniper.db.REGRAVAR_APOS_S = 6 * 3600`. `Database.history(store, item_id, days=30, limit=500) -> list[float]` continua com a mesma assinatura e o mesmo significado. `stats()["leituras_24h"]` soma as leituras.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_banco_leituras.py`:

```python
"""Histórico de preços compacto: uma linha por mudança de preço, com contador de leituras."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.db import Database  # noqa: E402
from sniper.models import Offer  # noqa: E402


class LeiturasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")
        self.t = time.time() - 3600

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def o(self, price, dt=0.0, orig=None):
        return Offer(store="t", item_id="X", title="P", price=price, url="https://x",
                     original_price=orig, collected_at=self.t + dt)

    def rows(self):
        return [tuple(r) for r in self.db.conn.execute("SELECT price, reads FROM prices ORDER BY id")]

    def test_preco_igual_nao_cria_linha(self):
        for i in range(3):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.rows(), [(100.0, 3)])
        self.assertEqual(self.db.history("t", "X"), [100.0, 100.0, 100.0])

    def test_preco_mudou_cria_linha(self):
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 1))
        self.db.save_offer(self.o(90.0, 2))
        self.assertEqual(self.rows(), [(100.0, 2), (90.0, 1)])
        self.assertEqual(self.db.history("t", "X"), [100.0, 100.0, 90.0])

    def test_de_por_mudou_cria_linha(self):
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 1, orig=200.0))
        self.assertEqual(len(self.rows()), 2)

    def test_depois_de_6h_cria_linha(self):
        self.t = time.time() - 8 * 3600
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 7 * 3600))
        self.assertEqual(self.rows(), [(100.0, 1), (100.0, 1)])

    def test_limite_conta_leituras(self):
        for i in range(5):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.db.history("t", "X", limit=3), [100.0, 100.0, 100.0])

    def test_stats_soma_leituras(self):
        for i in range(3):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.db.stats()["leituras_24h"], 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_banco_leituras -v`
Expected: FAIL (`no such column: reads`).

- [ ] **Step 3: Implementar**

Em `sniper/db.py`, acima de `class Database`:

```python
REGRAVAR_APOS_S = 6 * 3600  # mesmo preço: grava linha nova só depois disso (senão soma em `reads`)
```

Em `MIGRATIONS`, acrescente a chave `"prices"`:

```python
MIGRATIONS = {
    "items": {"catalog_id": "TEXT", "seller_id": "TEXT", "seller_name": "TEXT", "condition": "TEXT"},
    "alerts": {"seller_id": "TEXT", "seller_name": "TEXT", "confirmed": "INTEGER DEFAULT 0",
               "catalog_id": "TEXT"},
    "prices": {"reads": "INTEGER DEFAULT 1"},
}
```

Troque `history` por:

```python
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
```

Troque o primeiro `self.conn.execute(... INSERT INTO prices ...)` de `save_offer` por:

```python
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
```

(O `INSERT ... INTO items ... ON CONFLICT` que vem depois fica igual.)

Em `stats`, troque a linha de `leituras_24h` por:

```python
            "leituras_24h": q("SELECT COALESCE(SUM(COALESCE(reads, 1)), 0) FROM prices WHERE ts>=?", day),
```

- [ ] **Step 4: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 5: Commit**

```powershell
git add sniper/db.py tests/test_banco_leituras.py
git commit -m @'
Compacta o histórico de preços com contador de leituras

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 3: Limite de consultas por loja (`RateLimiter`)

**Files:**
- Create: `sniper/ratelimit.py`
- Test: `tests/test_ratelimit.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `RateLimiter(por_minuto: int, clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)`
  - `await acquire(fila: str = "normal") -> None` (`fila="rapida"` respeita o teto de 50%)
  - `penalize(motivo: str = "") -> float` (segundos de pausa: 60, 300, 900, 3600, 3600…)
  - `success() -> None` (zera o degrau)
  - propriedade `pausada -> bool`
  - `estado() -> {"pausada_ate": float | None, "degrau": int, "ultimo_minuto": int, "limite": int, "motivo": str}`
  - atributos públicos: `por_minuto`, `degrau`, `pausada_ate`, `motivo`

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_ratelimit.py`:

```python
"""Limite de consultas por loja."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.ratelimit import RateLimiter  # noqa: E402


class Relogio:
    """Relógio falso: sleep() só avança o tempo."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.r = Relogio()

    def lim(self, n):
        return RateLimiter(n, clock=self.r, sleep=self.r.sleep)

    def test_respeita_limite_por_minuto(self):
        lim = self.lim(3)

        async def go():
            for _ in range(3):
                await lim.acquire()
            self.assertEqual(self.r.t, 1000.0)
            await lim.acquire()

        asyncio.run(go())
        self.assertGreaterEqual(self.r.t, 1060.0)
        self.assertLess(self.r.t, 1061.0)

    def test_fila_rapida_usa_no_maximo_metade(self):
        lim = self.lim(4)

        async def go():
            await lim.acquire("rapida")
            await lim.acquire("rapida")
            await lim.acquire("normal")        # a fila normal não espera
            self.assertEqual(self.r.t, 1000.0)
            await lim.acquire("rapida")        # 3ª rápida no mesmo minuto: espera

        asyncio.run(go())
        self.assertGreaterEqual(self.r.t, 1060.0)

    def test_pausa_em_degraus(self):
        lim = self.lim(60)
        self.assertEqual([lim.penalize("429") for _ in range(5)], [60, 300, 900, 3600, 3600])

    def test_acquire_espera_o_fim_da_pausa(self):
        lim = self.lim(60)
        lim.penalize("bloqueio")
        e = lim.estado()
        self.assertEqual((e["pausada_ate"], e["motivo"]), (1060.0, "bloqueio"))
        self.assertTrue(lim.pausada)
        asyncio.run(lim.acquire())
        self.assertGreaterEqual(self.r.t, 1060.0)
        self.assertIsNone(lim.estado()["pausada_ate"])
        self.assertEqual(lim.estado()["motivo"], "")

    def test_sucesso_zera_degrau(self):
        lim = self.lim(60)
        lim.penalize()
        lim.penalize()
        lim.success()
        self.assertEqual(lim.degrau, 0)
        self.assertEqual(lim.penalize(), 60)

    def test_estado_conta_ultimo_minuto(self):
        lim = self.lim(10)

        async def go():
            await lim.acquire()
            await lim.acquire()

        asyncio.run(go())
        e = lim.estado()
        self.assertEqual((e["ultimo_minuto"], e["limite"], e["degrau"]), (2, 10, 0))
        self.r.t += 61
        self.assertEqual(lim.estado()["ultimo_minuto"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_ratelimit -v`
Expected: ERROR `No module named 'sniper.ratelimit'`.

- [ ] **Step 3: Implementar**

Crie `sniper/ratelimit.py`:

```python
"""Limite de consultas por loja: fichas por minuto + pausa em degraus quando a loja bloqueia."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable, Optional

DEGRAUS_S = (60, 300, 900, 3600)   # pausa de 1, 5, 15 e 60 minutos
COTA_RAPIDA = 0.5                  # a fila rápida usa no máximo metade das consultas da loja
JANELA_S = 60.0
MAX_ESPERA_S = 5.0                 # reavalia a cada 5 s enquanto espera


class RateLimiter:
    def __init__(self, por_minuto: int, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.por_minuto = max(1, int(por_minuto))
        self.clock = clock
        self.sleep = sleep
        self._usos: deque[tuple[float, str]] = deque()  # (instante, fila) das consultas no último minuto
        self._lock = asyncio.Lock()
        self.pausada_ate: Optional[float] = None
        self.degrau = 0
        self.motivo = ""

    def _limpa(self, agora: float) -> None:
        while self._usos and agora - self._usos[0][0] >= JANELA_S:
            self._usos.popleft()

    def _espera(self, fila: str, agora: float) -> float:
        if self.pausada_ate is not None and agora < self.pausada_ate:
            return self.pausada_ate - agora
        self._limpa(agora)
        if len(self._usos) >= self.por_minuto:
            return JANELA_S - (agora - self._usos[0][0])
        if fila == "rapida":
            rapidas = [t for t, f in self._usos if f == "rapida"]
            if len(rapidas) >= max(1, int(self.por_minuto * COTA_RAPIDA)):
                return JANELA_S - (agora - rapidas[0])
        return 0.0

    async def acquire(self, fila: str = "normal") -> None:
        """Espera até poder fazer uma consulta. fila="rapida" respeita o teto da fila rápida."""
        while True:
            async with self._lock:
                agora = self.clock()
                espera = self._espera(fila, agora)
                if espera <= 0:
                    self._usos.append((agora, fila))
                    return
            await self.sleep(min(espera, MAX_ESPERA_S))

    def penalize(self, motivo: str = "") -> float:
        """A loja bloqueou (429/403): pausa por um degrau maior a cada vez. Retorna os segundos de pausa."""
        dur = DEGRAUS_S[min(self.degrau, len(DEGRAUS_S) - 1)]
        self.degrau += 1
        self.pausada_ate = self.clock() + dur
        self.motivo = motivo
        return dur

    def success(self) -> None:
        self.degrau = 0

    @property
    def pausada(self) -> bool:
        return self.pausada_ate is not None and self.clock() < self.pausada_ate

    def estado(self) -> dict:
        self._limpa(self.clock())
        pausada = self.pausada
        return {"pausada_ate": self.pausada_ate if pausada else None, "degrau": self.degrau,
                "ultimo_minuto": len(self._usos), "limite": self.por_minuto,
                "motivo": self.motivo if pausada else ""}
```

- [ ] **Step 4: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 5: Commit**

```powershell
git add sniper/ratelimit.py tests/test_ratelimit.py
git commit -m @'
Adiciona limite de consultas por loja com pausa em degraus

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 4: Registro de lojas, config `[lojas.*]` e limiter no Mercado Livre

**Files:**
- Create: `sniper/stores.py`
- Modify: `sniper/config.py`, `sniper/engine.py` (`__init__`, `start`), `sniper/collectors/mercadolivre.py` (`__init__`, `_get`)
- Test: `tests/test_lojas.py`

**Interfaces:**
- Consumes: `RateLimiter` (Task 3).
- Produces:
  - `sniper.config.LojaConfig(ativo: bool = False, por_minuto: Optional[int] = None)`; `Settings.lojas: dict[str, LojaConfig]`
  - `sniper.stores.LojaInfo(chave, nome, oficial, criar, por_minuto, motivo_sem_config)`; `sniper.stores.LOJAS: dict[str, LojaInfo]`
  - `Engine.limiters: dict[str, RateLimiter]`; `Engine.store_status: dict[str, {"configurada": bool, "motivo": str}]`; `Engine._motivo_sem_coletor(store) -> str`
  - `MercadoLivreCollector(client_id, client_secret, token_path, max_concurrency=4, limiter: RateLimiter | None = None)`; atributos `limiter` e `_sleep`; `_get(path, params=None, fila="normal", timeout=None)`

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_lojas.py`:

```python
"""Registro de lojas, config [lojas.*] e limiter no Mercado Livre."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config  # noqa: E402
from sniper.collectors import CollectorError, MercadoLivreCollector  # noqa: E402
from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.config import LojaConfig, Settings  # noqa: E402
from sniper.engine import Engine  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402


def carregar(texto: str) -> Settings:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text(texto, encoding="utf-8")
        return config.load(p)


class ConfigLojasTests(unittest.TestCase):
    def test_formato_novo(self):
        s = carregar("[lojas.mercadolivre]\nativo = true\npor_minuto = 30\n")
        self.assertEqual(s.lojas["mercadolivre"], LojaConfig(ativo=True, por_minuto=30))

    def test_formato_antigo_com_client_id_liga_o_ml(self):
        s = carregar('[mercadolivre]\nclient_id = "abc"\n')
        self.assertEqual(s.lojas["mercadolivre"], LojaConfig(ativo=True, por_minuto=None))

    def test_sem_nada_nenhuma_loja(self):
        self.assertEqual(carregar("").lojas, {})

    def test_formato_novo_vence_o_antigo(self):
        s = carregar('[lojas.mercadolivre]\nativo = false\n[mercadolivre]\nclient_id = "abc"\n')
        self.assertFalse(s.lojas["mercadolivre"].ativo)


class RegistroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)  # registrado primeiro = roda por último (depois de fechar o banco)
        self.base = Path(self.tmp.name)

    def engine(self, **kw) -> Engine:
        s = Settings(base_dir=self.base, db_path=self.base / "t.db", windows_on=False, **kw)
        eng = Engine(s)
        self.addCleanup(eng.db.conn.close)
        self.addCleanup(lambda: asyncio.run(eng.stop()))
        return eng

    def test_ml_no_registro_e_oficial(self):
        self.assertEqual((LOJAS["mercadolivre"].nome, LOJAS["mercadolivre"].oficial), ("Mercado Livre", True))

    def test_cria_loja_ativa_e_configurada_com_limiter(self):
        eng = self.engine(ml_client_id="id", ml_client_secret="s",
                          lojas={"mercadolivre": LojaConfig(ativo=True, por_minuto=30)})
        col = eng.collectors["mercadolivre"]
        self.assertIsInstance(col, MercadoLivreCollector)
        self.assertIs(col.limiter, eng.limiters["mercadolivre"])
        self.assertEqual(col.limiter.por_minuto, 30)
        self.assertTrue(eng.store_status["mercadolivre"]["configurada"])

    def test_limite_padrao_da_loja(self):
        eng = self.engine(ml_client_id="id", lojas={"mercadolivre": LojaConfig(ativo=True)})
        self.assertEqual(eng.limiters["mercadolivre"].por_minuto, LOJAS["mercadolivre"].por_minuto)

    def test_loja_ativa_sem_credencial(self):
        eng = self.engine(lojas={"mercadolivre": LojaConfig(ativo=True)})
        self.assertNotIn("mercadolivre", eng.collectors)
        self.assertFalse(eng.store_status["mercadolivre"]["configurada"])
        self.assertIn("auth_ml.py", eng.store_status["mercadolivre"]["motivo"])
        self.assertIn("mercadolivre", eng.limiters)

    def test_loja_desligada_nao_cria_nada(self):
        eng = self.engine(ml_client_id="id", lojas={"mercadolivre": LojaConfig(ativo=False)})
        self.assertEqual((eng.collectors, eng.limiters), ({}, {}))
        self.assertIn("desligada", eng._motivo_sem_coletor("mercadolivre"))

    def test_motivo_loja_inexistente_e_nao_configurada(self):
        eng = self.engine()
        self.assertIn("não existe", eng._motivo_sem_coletor("xpto"))
        self.assertIn("auth_ml.py", eng._motivo_sem_coletor("mercadolivre"))


class MLLimiteTests(unittest.TestCase):
    def rodar(self, handler, limiter, chamadas=1):
        async def run():
            with tempfile.TemporaryDirectory() as d:
                tok = Path(d) / "tok.json"
                tok.write_text(json.dumps({"access_token": "OK", "refresh_token": "R",
                                           "expires_at": time.time() + 3600}))
                c = MercadoLivreCollector("id", "secret", tok, limiter=limiter)
                c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

                async def sem_espera(_):
                    return None
                c._sleep = sem_espera
                orig = mlmod.API
                mlmod.API = "https://api.test"
                try:
                    for _ in range(chamadas):
                        await c._get("/sites/MLB/search", {"q": "x"})
                finally:
                    mlmod.API = orig
                    await c.close()
        asyncio.run(run())

    def test_429_persistente_pausa_a_loja(self):
        lim = RateLimiter(60)
        with self.assertRaises(CollectorError):
            self.rodar(lambda req: httpx.Response(429), lim)
        self.assertIsNotNone(lim.estado()["pausada_ate"])
        self.assertEqual(lim.degrau, 1)

    def test_403_pausa_a_loja(self):
        lim = RateLimiter(60)
        with self.assertRaises(CollectorError):
            self.rodar(lambda req: httpx.Response(403, text="forbidden"), lim)
        self.assertTrue(lim.pausada)

    def test_sucesso_zera_degrau_e_conta_consulta(self):
        lim = RateLimiter(60)
        lim.degrau = 2
        self.rodar(lambda req: httpx.Response(200, json={"results": []}), lim, chamadas=2)
        self.assertEqual(lim.degrau, 0)
        self.assertEqual(lim.estado()["ultimo_minuto"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_lojas -v`
Expected: ERROR `cannot import name 'LojaConfig'`.

- [ ] **Step 3: Config**

Em `sniper/config.py`, troque `from dataclasses import dataclass, field` por `from dataclasses import dataclass, field` + `from typing import Optional` e adicione, acima de `class Settings`:

```python
@dataclass
class LojaConfig:
    """Bloco [lojas.<chave>] do config.toml."""
    ativo: bool = False
    por_minuto: Optional[int] = None   # None = limite padrão da loja em sniper/stores.py
```

Em `Settings`, logo depois de `watches: list[Watch] = ...`:

```python
    lojas: dict[str, LojaConfig] = field(default_factory=dict)
```

Em `load`, antes do `return Settings(`:

```python
    lojas: dict[str, LojaConfig] = {}
    for chave, lc in raw.get("lojas", {}).items():
        pm = lc.get("por_minuto")
        lojas[str(chave)] = LojaConfig(ativo=bool(lc.get("ativo", True)),
                                       por_minuto=int(pm) if pm is not None else None)
    if "mercadolivre" not in lojas and ml.get("client_id"):
        lojas["mercadolivre"] = LojaConfig(ativo=True)  # config antigo: só [mercadolivre]
```

e no `return Settings(...)` acrescente o argumento `lojas=lojas,`.

- [ ] **Step 4: Registro**

Crie `sniper/stores.py`:

```python
"""Registro de lojas: nome, etiqueta oficial/não oficial, limite padrão e como criar o coletor.

Para ligar uma loja nova: escreva o coletor em sniper/collectors/ e acrescente uma LojaInfo em LOJAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .collectors import Collector, MercadoLivreCollector
from .config import Settings
from .ratelimit import RateLimiter


@dataclass
class LojaInfo:
    chave: str
    nome: str
    oficial: bool                                                   # API oficial (True) ou endpoint público (False)
    criar: Callable[[Settings, RateLimiter], Optional[Collector]]   # None = falta credencial
    por_minuto: int                                                 # limite padrão de consultas
    motivo_sem_config: str = ""                                     # mostrado quando criar() devolve None


def _mercadolivre(s: Settings, lim: RateLimiter) -> Optional[Collector]:
    if not s.ml_client_id:
        return None
    return MercadoLivreCollector(s.ml_client_id, s.ml_client_secret,
                                 s.base_dir / "data" / "ml_token.json", limiter=lim)


LOJAS: dict[str, LojaInfo] = {i.chave: i for i in [
    LojaInfo("mercadolivre", "Mercado Livre", True, _mercadolivre, 60,
             "Preencha [mercadolivre] no config.toml e rode python auth_ml.py"),
]}
```

- [ ] **Step 5: Engine usa o registro**

Em `sniper/engine.py`, troque o import das coletoras por:

```python
from .collectors import Collector, CollectorError
```

e acrescente:

```python
from .ratelimit import RateLimiter
from .stores import LOJAS
```

No `__init__`, troque o bloco `if settings.ml_client_id: ... MercadoLivreCollector(...)` por:

```python
        self.limiters: dict[str, RateLimiter] = {}
        self.store_status: dict[str, dict] = {}
        for chave, info in LOJAS.items():
            lc = settings.lojas.get(chave)
            if not lc or not lc.ativo:
                continue
            lim = RateLimiter(lc.por_minuto or info.por_minuto)
            self.limiters[chave] = lim
            col = info.criar(settings, lim)
            if col is None:
                self.store_status[chave] = {"configurada": False, "motivo": info.motivo_sem_config}
                continue
            self.collectors[chave] = col
            self.store_status[chave] = {"configurada": True, "motivo": ""}
```

Acrescente o método (depois de `log`):

```python
    def _motivo_sem_coletor(self, store: str) -> str:
        info = LOJAS.get(store)
        if info is None:
            return f"Loja '{store}' não existe"
        lc = self.s.lojas.get(store)
        if lc is not None and not lc.ativo:
            return f"Loja '{store}' desligada. Use [lojas.{store}] ativo = true no config.toml"
        return info.motivo_sem_config
```

Em `start`, troque o valor de `"error"` do `watch_status` "sem coletor" (as duas linhas `(f"Loja '{w.store}' não configurada..." + (...))`) por:

```python
                                             "error": self._motivo_sem_coletor(w.store),
```

- [ ] **Step 6: Mercado Livre usa o limiter**

Em `sniper/collectors/mercadolivre.py`, acrescente o import `from ..ratelimit import RateLimiter`.

Troque o `__init__` de `MercadoLivreCollector` por:

```python
    def __init__(self, client_id: str, client_secret: str, token_path: Path, max_concurrency: int = 4,
                 limiter: Optional[RateLimiter] = None):
        self.tokens = TokenStore(token_path, client_id, client_secret)
        self.client = httpx.AsyncClient(timeout=15, headers={"user-agent": "sniper-ofertas/0.1"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade
```

Troque `_get` inteiro por:

```python
    async def _get(self, path: str, params: dict | None = None, fila: str = "normal",
                   timeout: float | None = None) -> dict | list:
        token = await self.tokens.access_token(self.client)
        extra = {"timeout": timeout} if timeout else {}
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{API}{path}", params=params,
                                          headers={"Authorization": f"Bearer {token}"}, **extra)
            status = r.status_code
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 401:
                self.tokens.data["expires_at"] = 0
                token = await self.tokens.access_token(self.client)
                continue
            if status == 403:
                self._penalize(f"ML recusou {path} (403)")
                raise CollectorError(f"ML recusou {path} (403). Confira se o app tem permissão "
                                     f"para esse recurso. Resposta: {r.text[:160]}")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429:
            self._penalize("ML: muitas requisições (429)")
        raise CollectorError(f"ML não respondeu em {path} após várias tentativas")

    def _penalize(self, motivo: str) -> None:
        if self.limiter:
            dur = self.limiter.penalize(motivo)
            log.warning("Mercado Livre pausado por %d min: %s", dur // 60, motivo)
```

- [ ] **Step 7: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS. Se o `EngineTests` antigo reclamar de algo, a causa é o `__init__`. Ele monta `Settings` sem `lojas`, então nenhuma loja real é criada, e isso é o esperado.

- [ ] **Step 8: Commit**

```powershell
git add sniper/stores.py sniper/config.py sniper/engine.py sniper/collectors/mercadolivre.py tests/test_lojas.py
git commit -m @'
Cria registro de lojas com etiqueta oficial e limite de consultas no ML

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 5: Pipeline `_process` reaproveitável e supervisor de loops

**Files:**
- Create: `tests/fakes.py`
- Modify: `sniper/engine.py` (`run_watch`, novo `_process`, novo `_supervise`, `start`, `__init__`)
- Test: `tests/test_motor.py`

**Interfaces:**
- Consumes: `Engine` da Task 4.
- Produces:
  - `Engine._process(w: Watch, col: Collector, offers: list[Offer]) -> {"alertas": int, "descartes": int, "rejeitados": int}` (define `o.watch = w.name` em cada oferta)
  - `Engine._supervise(nome: str, factory: Callable[[], Awaitable[None]]) -> None`; `Engine.restart_delay: float = 30.0`
  - `tests/fakes.py`: `oferta(...)`, `FakeCollector`, `MotorDeTeste`

- [ ] **Step 1: Criar os fakes compartilhados**

Crie `tests/fakes.py`:

```python
"""Coletores e motor falsos compartilhados pelos testes da fase 1."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.collectors.base import Collector  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.engine import Engine  # noqa: E402
from sniper.models import Offer, SellerInfo  # noqa: E402


def oferta(iid: str, price: float, title: str = "Apple iPhone 15 128GB", seller: str = "GOOD",
           store: str = "t", catalog: str = "C1", **kw) -> Offer:
    return Offer(store=store, item_id=iid, title=title, price=price, url="https://x",
                 seller_id=seller, catalog_id=catalog, **kw)


class FakeCollector(Collector):
    store = "t"

    def __init__(self):
        self.batch: list[Offer] = []
        self.sellers = {"GOOD": SellerInfo("GOOD", "BOA_LOJA", 5000, "5_green", 2000)}

    async def collect(self, watch):
        return [Offer(**o.__dict__) for o in self.batch]

    async def seller_info(self, o):
        return self.sellers.get(o.seller_id)

    async def confirm(self, o):
        f = Offer(**o.__dict__)
        f.confirmed = True
        return f


class MotorDeTeste:
    """Engine sobre um banco temporário. Uso: `with MotorDeTeste(watches=[...]) as m: m.engine...`"""

    def __init__(self, watches=(), **settings_kw):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.settings = Settings(base_dir=base, db_path=base / "t.db", windows_on=False, **settings_kw)
        self.settings.watches = list(watches)
        self.engine = Engine(self.settings)

    def reabrir(self) -> Engine:
        """Fecha e recria o Engine sobre o mesmo banco (simula reiniciar o PC)."""
        self.engine.db.conn.close()
        self.engine = Engine(self.settings)
        return self.engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.engine.db.conn.close()
        self.tmp.cleanup()
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/test_motor.py`:

```python
"""Pipeline compartilhado e supervisor de loops."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, oferta  # noqa: E402
from sniper.models import Watch  # noqa: E402


class SupervisorTests(unittest.TestCase):
    def test_reinicia_loop_que_caiu(self):
        with MotorDeTeste() as m:
            eng = m.engine
            eng.restart_delay = 0
            calls = []

            async def loop():
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("boom")

            asyncio.run(eng._supervise("regra X", loop))
            self.assertEqual(len(calls), 2)
            self.assertTrue(any("boom" in e.get("msg", "") for e in eng.events))


class ProcessTests(unittest.TestCase):
    def test_process_gera_alerta_com_nome_da_regra(self):
        w = Watch(name="Varredura X", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            m.engine.collectors["t"] = col
            offers = [oferta("A", 4900), oferta("B", 5000), oferta("C", 4950), oferta("D", 490)]
            r = asyncio.run(m.engine._process(w, col, offers))
            self.assertEqual(r["alertas"], 1)
            self.assertEqual(m.engine.db.list_alerts()[0]["watch"], "Varredura X")

    def test_process_conta_rejeitados(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            r = asyncio.run(m.engine._process(w, col, [oferta("T", 1.0, title="TESTE iPhone 15")]))
            self.assertEqual((r["alertas"], r["rejeitados"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_motor -v`
Expected: FAIL `'Engine' object has no attribute '_supervise'` / `'_process'`.

- [ ] **Step 4: Extrair `_process` e reescrever `run_watch`**

Em `sniper/engine.py`, troque o método `run_watch` inteiro (da linha `async def run_watch` até `return alerts`) por:

```python
    async def run_watch(self, w: Watch) -> int:
        st = self.watch_status[w.name]
        st["state"] = "coletando"
        t0 = time.time()
        col = self.collectors[w.store]
        try:
            offers = await col.collect(w)
        except CollectorError as e:
            st.update(state="erro", error=str(e), last_run=time.time())
            self.log("erro", f"[{w.name}] {e}")
            return 0
        except Exception as e:  # noqa: BLE001
            st.update(state="erro", error=f"{type(e).__name__}: {e}", last_run=time.time())
            self.log("erro", f"[{w.name}] falha inesperada: {e}")
            return 0

        r = await self._process(w, col, offers)
        st.update(state="ok", error=None, last_run=time.time(), count=len(offers),
                  duration=round(time.time() - t0, 2), descartados=r["rejeitados"])
        self.emit("watch", name=w.name, status=st)
        if r["alertas"] or r["descartes"]:
            self.log("info", f"[{w.name}] {len(offers)} lidos · {r['alertas']} alerta(s) · "
                             f"{r['descartes']} descartado(s)")
        return r["alertas"]

    async def _process(self, w: Watch, col: Collector, offers: list[Offer]) -> dict:
        """Filtra, avalia, confere vendedor e preço e dispara alertas. Usado por vigiar, varrer e fila rápida."""
        for o in offers:
            o.watch = w.name
        fcfg, det = self.s.filters, self.s.detector
        blocked = self.db.blocked_sellers()

        # 1ª passada: filtro barato do anúncio. Lixo não entra no histórico nem vira referência.
        clean: list[Offer] = []
        rejected: list[tuple[Offer, str]] = []
        for o in offers:
            reason = filters.check_listing(o, w, fcfg, blocked)
            (rejected.append((o, reason)) if reason else clean.append(o))

        # Preços atuais de cada produto de catálogo (concorrentes na mesma coleta).
        by_catalog: dict[str, dict[str, float]] = defaultdict(dict)
        for o in clean:
            if o.catalog_id:
                by_catalog[o.catalog_id][o.item_id] = o.price

        def peers_for(o: Offer) -> list[float]:
            same = [p for iid, p in by_catalog.get(o.catalog_id, {}).items() if iid != o.item_id]
            return same if len(same) >= det.min_peers else self.db.peer_prices(o.store, o.catalog_id, o.item_id)

        discards = 0
        for o, reason in rejected:
            if reason.startswith("Vendedor bloqueado"):
                continue  # loja já bloqueada: ignora em silêncio
            v = detector.evaluate(o, self.db.history(o.store, o.item_id), w, det, peers_for(o))
            if self._alert_worthy(v):  # só registra o que teria virado alerta
                discards += self._discard(o, v.score, reason)

        candidates: list[tuple[Offer, Verdict, list[float], list[float]]] = []
        for o in clean:
            hist = self.db.history(o.store, o.item_id)
            peers = peers_for(o)
            v = detector.evaluate(o, hist, w, det, peers)
            self.db.save_offer(o)
            if self._alert_worthy(v) and self._should_alert(o.store, o.item_id, o.price):
                candidates.append((o, v, hist, peers))

        # 2ª passada, só nos candidatos: checa o vendedor e reconfirma o preço no anúncio.
        alerts = 0
        for o, v, hist, peers in candidates:
            vetted = await self._vet(col, w, o, v, hist, peers)
            if vetted is None:
                discards += 1
                continue
            o, v = vetted
            a = self.db.save_alert(o, v)
            alerts += 1
            self.emit("alert", alert=a)
            for n in self.notifiers:
                asyncio.create_task(n.send(a))
        return {"alertas": alerts, "descartes": discards, "rejeitados": len(rejected)}
```

- [ ] **Step 5: Supervisor**

No `__init__` do `Engine`, depois de `self._tasks: list[asyncio.Task] = []`:

```python
        self.restart_delay = 30.0  # segundos até recriar um loop que caiu
```

Acrescente o método (antes de `_loop`):

```python
    async def _supervise(self, nome: str, factory) -> None:
        """Roda factory(); se cair com erro inesperado, registra e recria depois de restart_delay."""
        while True:
            try:
                await factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("Loop %s caiu", nome)
                self.log("erro", f"[{nome}] loop caiu ({type(e).__name__}: {e}); "
                                 f"reiniciando em {int(self.restart_delay)}s")
                await asyncio.sleep(self.restart_delay)
```

Em `start`, troque `self._tasks.append(asyncio.create_task(self._loop(w)))` por:

```python
            self._tasks.append(asyncio.create_task(self._supervise(w.name, lambda w=w: self._loop(w))))
```

- [ ] **Step 6: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS (inclusive o `EngineTests` antigo, que usa `run_watch`).

- [ ] **Step 7: Commit**

```powershell
git add sniper/engine.py tests/fakes.py tests/test_motor.py
git commit -m @'
Extrai o pipeline de ofertas e adiciona supervisor que reinicia loops

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 6: Modo varredura no motor

**Files:**
- Modify: `sniper/models.py` (`Watch`), `sniper/config.py` (`[[varrer]]`), `sniper/collectors/base.py`, `sniper/db.py` (`sweep_state`), `sniper/engine.py` (`sweep_step`, `_sweep_state`, `_sweep_loop`, `_sweep_gap`, `start`), `tests/fakes.py`
- Test: `tests/test_varredura.py`

**Interfaces:**
- Consumes: `_process`, `_supervise` (Task 5).
- Produces:
  - `Watch.kind: str = "vigiar"`, `Watch.sweep_categories: Optional[list[str]] = None`, `Watch.cycle_min: int = 60`
  - `Collector.supports_sweep`, `Collector.supports_refresh`, `async sweep_units(watch) -> list[str]`, `async sweep(unit, watch) -> list[Offer]`, `async refresh(item_ids) -> list[Offer]`
  - `Database.get_sweep(watch) -> dict | None` (`units` já como lista), `save_sweep(watch, units, units_ts, cursor, cycle_started)`, `save_sweep_cursor(watch, cursor, cycle_started)`
  - `Engine.sweep_step(w) -> int`; `watch_status[nome]` ganha `kind`, `unidade`, `total`, `fim_estimado`
  - `sniper.engine.UNIDADES_TTL_S = 86400`
  - `tests/fakes.py`: `FakeSweepCollector(units)` com `seen`, `fail`, `down`

- [ ] **Step 1: Coletor falso de varredura**

Acrescente ao fim de `tests/fakes.py`:

```python
class FakeSweepCollector(FakeCollector):
    """Loja com varredura: cada unidade devolve uma oferta. `fail` = unidades que dão erro; `down` = sem internet."""
    supports_sweep = True

    def __init__(self, units):
        super().__init__()
        self.units = list(units)
        self.seen: list[str] = []
        self.fail: set[str] = set()
        self.down = False

    async def sweep_units(self, watch):
        return list(self.units)

    async def sweep(self, unit, watch):
        import httpx
        if self.down:
            raise httpx.ConnectError("sem internet")
        if unit in self.fail:
            raise ValueError("categoria sumiu")
        self.seen.append(unit)
        return [oferta(f"{unit}-1", 100.0, title="Produto qualquer", catalog="")]
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/test_varredura.py`:

```python
"""Modo varredura: rodízio pelo catálogo com cursor salvo no banco."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, FakeSweepCollector, MotorDeTeste  # noqa: E402
from sniper import config  # noqa: E402
from sniper.models import Watch  # noqa: E402

W = Watch(name="Varre", store="t", kind="varrer", cycle_min=60)


class VarreduraTests(unittest.TestCase):
    def prepara(self, m, col):
        m.engine.collectors["t"] = col
        m.engine.watch_status[W.name] = {}

    def passo(self, m, n=1):
        for _ in range(n):
            asyncio.run(m.engine.sweep_step(W))

    def test_percorre_todas_e_volta_ao_inicio(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b", "c"])
            self.prepara(m, col)
            self.passo(m, 4)
            self.assertEqual(col.seen, ["a", "b", "c", "a"])
            st = m.engine.watch_status[W.name]
            self.assertEqual((st["unidade"], st["total"], st["state"]), (1, 3, "ok"))

    def test_retoma_de_onde_parou(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeSweepCollector(["a", "b", "c"]))
            self.passo(m, 2)
            m.reabrir()
            col = FakeSweepCollector(["a", "b", "c"])
            self.prepara(m, col)
            self.passo(m)
            self.assertEqual(col.seen, ["c"])

    def test_pula_unidade_com_erro(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b", "c"])
            col.fail = {"b"}
            self.prepara(m, col)
            self.passo(m, 2)
            self.assertIn("b pulada", m.engine.watch_status[W.name]["error"])
            self.passo(m)
            self.assertEqual(col.seen, ["a", "c"])

    def test_sem_internet_nao_avanca(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b"])
            self.prepara(m, col)
            col.down = True
            self.passo(m)
            self.assertEqual(m.engine.watch_status[W.name]["state"], "erro")
            col.down = False
            self.passo(m)
            self.assertEqual(col.seen, ["a"])

    def test_lista_recarregada_mantem_a_unidade_atual(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeSweepCollector(["a", "b", "c"]))
            self.passo(m)                                   # leu "a"; próxima é "b"
            sw = m.engine.db.get_sweep(W.name)
            m.engine.db.save_sweep(W.name, sw["units"], 0.0, sw["cursor"], sw["cycle_started"])  # cache vencido
            col = FakeSweepCollector(["x", "b", "c"])
            self.prepara(m, col)
            self.passo(m)
            self.assertEqual(col.seen, ["b"])

    def test_loja_sem_suporte(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeCollector())
            self.passo(m)
            self.assertEqual(m.engine.watch_status[W.name]["state"], "loja não suporta varredura")


class ConfigVarrerTests(unittest.TestCase):
    def test_bloco_varrer(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[[varrer]]\nnome = "ML geral"\nloja = "mercadolivre"\ncategorias = "todas"\n'
                         'ciclo_minutos = 90\npaginas = 2\n\n'
                         '[[varrer]]\nnome = "Eletro"\ncategorias = ["MLB1000", "MLB5726"]\n',
                         encoding="utf-8")
            ws = config.load(p).watches
        self.assertEqual([(w.name, w.kind, w.sweep_categories, w.cycle_min, w.max_pages) for w in ws], [
            ("ML geral", "varrer", None, 90, 2),
            ("Eletro", "varrer", ["MLB1000", "MLB5726"], 60, 1),
        ])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_varredura -v`
Expected: ERROR `Watch.__init__() got an unexpected keyword argument 'kind'`.

- [ ] **Step 4: Modelo e config**

Em `sniper/models.py`, no fim de `class Watch` (depois de `allow_used`):

```python
    kind: str = "vigiar"             # "vigiar" (busca/itens) ou "varrer" (rodízio pelo catálogo)
    sweep_categories: Optional[list[str]] = None  # varrer: categorias escolhidas; None = todas
    cycle_min: int = 60              # varrer: minutos para dar uma volta completa
```

Em `sniper/config.py`, logo depois do laço `for w in raw.get("vigiar", []): ...`:

```python
    for v in raw.get("varrer", []):
        cats = v.get("categorias", "todas")
        watches.append(Watch(
            name=v["nome"],
            store=v.get("loja", "mercadolivre"),
            kind="varrer",
            sweep_categories=None if cats == "todas" else [str(c) for c in cats],
            cycle_min=int(v.get("ciclo_minutos", 60)),
            max_pages=int(v.get("paginas", 1)),
            min_price=v.get("preco_minimo"),
            exclude_words=[str(x) for x in v.get("excluir", [])],
            allow_used=bool(v.get("aceitar_usados", False)),
        ))
```

- [ ] **Step 5: Interface do coletor**

Em `sniper/collectors/base.py`, dentro de `class Collector`, depois de `store: str = ""`:

```python
    supports_sweep: bool = False     # implementa sweep_units() + sweep()
    supports_refresh: bool = False   # implementa refresh() (fila rápida)
```

e antes de `close`:

```python
    async def sweep_units(self, watch: Watch) -> list[str]:
        """Unidades de varredura (ex.: categorias finais), em ordem estável."""
        raise NotImplementedError

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        """Lê uma unidade de varredura."""
        raise NotImplementedError

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        """Relê vários itens de uma vez (fila rápida)."""
        raise NotImplementedError
```

- [ ] **Step 6: Tabela `sweep_state`**

Em `sniper/db.py`, no fim da string `SCHEMA` (antes das `"""` finais):

```sql
CREATE TABLE IF NOT EXISTS sweep_state (
    watch TEXT PRIMARY KEY, units TEXT, units_ts REAL, cursor INTEGER DEFAULT 0, cycle_started REAL
);
```

E acrescente os métodos (antes de `# ---------- descartes ----------`):

```python
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
```

- [ ] **Step 7: Motor**

Em `sniper/engine.py`, acrescente `import httpx` aos imports e, abaixo de `log = logging.getLogger(...)`:

```python
UNIDADES_TTL_S = 86400  # relê a lista de unidades de varredura (ex.: categorias) uma vez por dia
```

Acrescente os métodos (depois de `_loop`):

```python
    async def _sweep_loop(self, w: Watch) -> None:
        while True:
            if self.paused:
                await asyncio.sleep(5)
                continue
            await self.sweep_step(w)
            await asyncio.sleep(self._sweep_gap(w))

    def _sweep_gap(self, w: Watch) -> float:
        sw = self.db.get_sweep(w.name)
        n = len(sw["units"]) if sw and sw["units"] else 0
        return w.cycle_min * 60 / n if n else 60.0

    async def _sweep_state(self, w: Watch, col: Collector) -> dict:
        sw = self.db.get_sweep(w.name)
        if sw and sw["units"] and time.time() - sw["units_ts"] < UNIDADES_TTL_S:
            return sw
        units = await col.sweep_units(w)
        cursor, started = 0, time.time()
        if sw and sw["units"]:
            atual = sw["units"][sw["cursor"] % len(sw["units"])]
            if atual in units:  # lista recarregada: continua na mesma unidade
                cursor, started = units.index(atual), sw["cycle_started"]
        self.db.save_sweep(w.name, units, time.time(), cursor, started)
        return self.db.get_sweep(w.name)

    async def sweep_step(self, w: Watch) -> int:
        """Lê a próxima unidade da varredura (ex.: uma categoria) e avança o cursor salvo no banco."""
        st = self.watch_status[w.name]
        col = self.collectors[w.store]
        if not col.supports_sweep:
            st.update(state="loja não suporta varredura", error=None, last_run=time.time())
            return 0
        st["state"] = "coletando"
        t0 = time.time()
        try:
            sw = await self._sweep_state(w, col)
        except Exception as e:  # noqa: BLE001
            msg = str(e) if isinstance(e, CollectorError) else f"{type(e).__name__}: {e}"
            st.update(state="erro", error=f"Não consegui listar as unidades: {msg}", last_run=time.time())
            self.log("erro", f"[{w.name}] {st['error']}")
            return 0
        units = sw["units"]
        if not units:
            st.update(state="erro", error="A loja não informou unidades de varredura", last_run=time.time())
            return 0

        cursor = sw["cursor"] % len(units)
        unit = units[cursor]
        offers: list[Offer] = []
        alerts, err, avancar = 0, None, True
        try:
            offers = await col.sweep(unit, w)
            alerts = (await self._process(w, col, offers))["alertas"]
        except (CollectorError, httpx.TransportError) as e:
            err, avancar = f"{unit}: {e}", False  # loja bloqueou ou sem internet: tenta a mesma unidade depois
        except Exception as e:  # noqa: BLE001
            err = f"{unit} pulada: {type(e).__name__}: {e}"  # ex.: categoria sumiu
        if err:
            self.log("erro", f"[{w.name}] {err}")

        nxt, started = cursor, sw["cycle_started"]
        if avancar:
            nxt = cursor + 1
            if nxt >= len(units):
                self.log("info", f"[{w.name}] volta completa: {len(units)} unidade(s) em "
                                 f"{round((time.time() - started) / 60)} min")
                nxt, started = 0, time.time()
            self.db.save_sweep_cursor(w.name, nxt, started)

        gap = w.cycle_min * 60 / len(units)
        st.update(state="erro" if err else "ok", error=err, last_run=time.time(), count=len(offers),
                  duration=round(time.time() - t0, 2), unidade=nxt, total=len(units),
                  fim_estimado=time.time() + (len(units) - nxt) * gap)
        self.emit("watch", name=w.name, status=st)
        return alerts
```

Troque o método `start` inteiro por:

```python
    async def start(self) -> None:
        for w in self.s.watches:
            if w.store not in self.collectors:
                self.watch_status[w.name] = {"store": w.store, "kind": w.kind, "state": "sem coletor",
                                             "error": self._motivo_sem_coletor(w.store),
                                             "count": 0, "interval": w.interval}
                continue
            self.watch_status[w.name] = {"store": w.store, "kind": w.kind, "state": "aguardando",
                                         "last_run": None, "count": 0, "error": None,
                                         "interval": w.interval if w.kind == "vigiar" else None,
                                         "duration": None}
            loop = self._sweep_loop if w.kind == "varrer" else self._loop
            self._tasks.append(asyncio.create_task(
                self._supervise(w.name, lambda w=w, loop=loop: loop(w))))
        self._tasks.append(asyncio.create_task(self._housekeeping()))
        ativas = sum(1 for w in self.s.watches if w.store in self.collectors)
        self.log("info", f"Motor iniciado com {ativas} regra(s) ativa(s)")
```

- [ ] **Step 8: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 9: Commit**

```powershell
git add sniper/models.py sniper/config.py sniper/collectors/base.py sniper/db.py sniper/engine.py tests/fakes.py tests/test_varredura.py
git commit -m @'
Adiciona modo varredura com rodízio pelo catálogo e retomada

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 7: Varredura e refresh no Mercado Livre

**Files:**
- Modify: `sniper/collectors/mercadolivre.py`
- Test: `tests/test_ml_varredura.py`

**Interfaces:**
- Consumes: `_get(path, params, fila, timeout)` (Task 4), interface do coletor (Task 6).
- Produces: `MercadoLivreCollector.supports_sweep = True`, `supports_refresh = True`, `sweep_units(watch)`, `sweep(unit, watch)`, `refresh(item_ids)` (usa `fila="rapida"`, `Watch` de nome `"Fila rápida"`), helpers `_search_pages`, `_items`, `_category_dump`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_ml_varredura.py`:

```python
"""Mercado Livre: categorias finais, busca do mais barato e refresh em lote."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.collectors import mercadolivre as mlmod  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402

RAIZES = [{"id": "A"}, {"id": "B"}]
DUMP = {"A": {"children_categories": [{"id": "A1"}, {"id": "A2"}]},
        "A1": {"children_categories": []}, "A2": {"children_categories": []},
        "B": {"children_categories": []}}
NOS = {"A": [{"id": "A1"}], "A1": [], "B": []}


def rodar(handler, fn, limiter=None):
    """Cria o coletor com transporte falso, roda fn(coletor) e devolve o resultado."""
    async def run():
        with tempfile.TemporaryDirectory() as d:
            tok = Path(d) / "tok.json"
            tok.write_text(json.dumps({"access_token": "OK", "refresh_token": "R",
                                       "expires_at": time.time() + 3600}))
            c = mlmod.MercadoLivreCollector("id", "secret", tok, limiter=limiter)
            c.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            orig = mlmod.API
            mlmod.API = "https://api.test"
            try:
                return await fn(c)
            finally:
                mlmod.API = orig
                await c.close()
    return asyncio.run(run())


class CategoriasTests(unittest.TestCase):
    def test_folhas_pelo_dump(self):
        calls = []

        def h(req):
            calls.append(req.url.path)
            if req.url.path == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if req.url.path == "/sites/MLB/categories/all":
                return httpx.Response(200, json=DUMP)
            return httpx.Response(404)

        leaves = rodar(h, lambda c: c.sweep_units(Watch(name="v", store="mercadolivre", kind="varrer")))
        self.assertEqual(leaves, ["A1", "A2", "B"])
        self.assertFalse(any(p.startswith("/categories/") for p in calls))

    def test_sem_dump_le_no_a_no(self):
        def h(req):
            p = req.url.path
            if p == "/sites/MLB/categories":
                return httpx.Response(200, json=RAIZES)
            if p == "/sites/MLB/categories/all":
                return httpx.Response(404)
            if p.startswith("/categories/"):
                return httpx.Response(200, json={"children_categories": NOS[p.rsplit("/", 1)[1]]})
            return httpx.Response(404)

        leaves = rodar(h, lambda c: c.sweep_units(Watch(name="v", store="mercadolivre", kind="varrer")))
        self.assertEqual(leaves, ["A1", "B"])

    def test_categorias_escolhidas(self):
        calls = []

        def h(req):
            calls.append(req.url.path)
            if req.url.path == "/sites/MLB/categories/all":
                return httpx.Response(200, json=DUMP)
            return httpx.Response(404)

        w = Watch(name="v", store="mercadolivre", kind="varrer", sweep_categories=["A"])
        self.assertEqual(rodar(h, lambda c: c.sweep_units(w)), ["A1", "A2"])
        self.assertNotIn("/sites/MLB/categories", calls)


class SweepRefreshTests(unittest.TestCase):
    def test_sweep_busca_do_mais_barato(self):
        params = []

        def h(req):
            params.append(dict(req.url.params))
            return httpx.Response(200, json={"results": [
                {"id": "MLB1", "title": "TV", "price": 99.0, "permalink": "https://ml/1", "shipping": {}}]})

        w = Watch(name="v", store="mercadolivre", kind="varrer", max_pages=1)
        offers = rodar(h, lambda c: c.sweep("A1", w))
        self.assertEqual([o.item_id for o in offers], ["MLB1"])
        self.assertEqual((params[0]["category"], params[0]["sort"], params[0]["limit"]), ("A1", "price_asc", "50"))

    def test_refresh_em_lotes_de_20_na_fila_rapida(self):
        lotes = []

        def h(req):
            ids = req.url.params["ids"].split(",")
            lotes.append(len(ids))
            return httpx.Response(200, json=[
                {"code": 200, "body": {"id": i, "title": "X", "price": 10.0, "permalink": "https://ml/x",
                                       "status": "active", "shipping": {}}} for i in ids])

        lim = RateLimiter(1000)
        ids = [f"MLB{i}" for i in range(45)]
        offers = rodar(h, lambda c: c.refresh(ids), limiter=lim)
        self.assertEqual(lotes, [20, 20, 5])
        self.assertEqual(len(offers), 45)
        self.assertEqual({o.watch for o in offers}, {"Fila rápida"})
        self.assertEqual({f for _, f in lim._usos}, {"rapida"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_ml_varredura -v`
Expected: ERROR/FAIL (`NotImplementedError` em `sweep_units`).

- [ ] **Step 3: Implementar**

Em `sniper/collectors/mercadolivre.py`, dentro de `class MercadoLivreCollector`, logo depois de `store = "mercadolivre"`:

```python
    supports_sweep = True
    supports_refresh = True
```

Troque os métodos `search` e `items` por:

```python
    async def _search_pages(self, params: dict, watch: Watch, fila: str = "normal") -> list[Offer]:
        offers: list[Offer] = []
        for page in range(max(1, watch.max_pages)):
            data = await self._get(f"/sites/{SITE}/search", {**params, "limit": 50, "offset": page * 50},
                                   fila=fila)
            results = data.get("results", [])
            offers += [o for o in (_to_offer(it, watch) for it in results) if o]
            if len(results) < 50:
                break
        return offers

    async def search(self, watch: Watch) -> list[Offer]:
        params = {}
        if watch.query:
            params["q"] = watch.query
        if watch.category:
            params["category"] = watch.category
        return await self._search_pages(params, watch)

    async def _items(self, ids: list[str], watch: Watch, fila: str = "normal") -> list[Offer]:
        offers: list[Offer] = []
        for i in range(0, len(ids), 20):
            data = await self._get("/items", {"ids": ",".join(ids[i:i + 20]), "attributes": ITEM_FIELDS},
                                   fila=fila)
            for entry in data:
                if entry.get("code") == 200:
                    o = _to_offer(entry.get("body", {}), watch)
                    if o:
                        offers.append(o)
        return offers

    async def items(self, watch: Watch) -> list[Offer]:
        return await self._items(watch.item_ids, watch)
```

Acrescente, antes de `seller_info`:

```python
    # ---------- varredura ----------
    async def _category_dump(self) -> dict[str, list[str]]:
        """Árvore inteira em uma chamada. Se falhar, devolve {} e sweep_units lê nó a nó."""
        try:
            data = await self._get(f"/sites/{SITE}/categories/all", timeout=120)
        except (CollectorError, httpx.HTTPError, ValueError) as e:
            log.warning("Dump de categorias do ML indisponível (%s); lendo a árvore nó a nó", e)
            return {}
        return {cid: [c["id"] for c in (node.get("children_categories") or [])] for cid, node in data.items()}

    async def sweep_units(self, watch: Watch) -> list[str]:
        """Categorias finais (sem filhas) do MLB, ou das categorias escolhidas na regra."""
        roots = watch.sweep_categories or [c["id"] for c in await self._get(f"/sites/{SITE}/categories")]
        tree = await self._category_dump()
        leaves: list[str] = []
        stack, seen = list(reversed(roots)), set()
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            if cid in tree:
                kids = tree[cid]
            else:
                node = await self._get(f"/categories/{cid}")
                kids = [c["id"] for c in (node.get("children_categories") or [])]
            if kids:
                stack.extend(reversed(kids))
            else:
                leaves.append(cid)
        return leaves

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        # Do mais barato para o mais caro: um preço com bug aparece no topo da categoria.
        return await self._search_pages({"category": unit, "sort": "price_asc"}, watch)

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        return await self._items(item_ids, Watch(name="Fila rápida", store=self.store), fila="rapida")
```

- [ ] **Step 4: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS, inclusive `MercadoLivreTests.test_busca_e_refresh_de_token`.

- [ ] **Step 5: Commit**

```powershell
git add sniper/collectors/mercadolivre.py tests/test_ml_varredura.py
git commit -m @'
Varredura por categoria e releitura em lote no Mercado Livre

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 8: Fila rápida

**Files:**
- Modify: `sniper/config.py` (`[varredura]`), `sniper/db.py` (`fast_lane_items` + índice), `sniper/engine.py` (`FILA_RAPIDA`, `fast_lane_step`, `_fast_loop`, `start`), `tests/fakes.py`
- Test: `tests/test_fila_rapida.py`

**Interfaces:**
- Consumes: `Collector.supports_refresh`/`refresh` (Task 6), `_process`/`_supervise` (Task 5).
- Produces:
  - `Settings.valor_alto: float = 300.0`, `Settings.intervalo_rapido: int = 120`, `Settings.max_itens_rapida: int = 1000`
  - `Database.fast_lane_items(store, min_price, limit, max_age_s=48*3600) -> list[str]`
  - `sniper.engine.FILA_RAPIDA = "Fila rápida"`; `Engine.fast_lane_step() -> int`; `watch_status["Fila rápida"]` com `kind="rapida"`
  - `tests/fakes.py`: `FakeRefreshCollector(prices: dict[str, float])`

- [ ] **Step 1: Coletor falso com refresh**

Acrescente ao fim de `tests/fakes.py`:

```python
class FakeRefreshCollector(FakeCollector):
    """Loja com refresh: devolve os preços de `prices` (item_id → preço) para os ids pedidos."""
    supports_refresh = True

    def __init__(self, prices):
        super().__init__()
        self.prices = dict(prices)
        self.pedidos: list[list[str]] = []

    async def refresh(self, item_ids):
        self.pedidos.append(list(item_ids))
        return [oferta(i, self.prices[i], catalog="") for i in item_ids if i in self.prices]
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/test_fila_rapida.py`:

```python
"""Fila rápida: relê itens caros com frequência."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, FakeRefreshCollector, MotorDeTeste, oferta  # noqa: E402
from sniper import config  # noqa: E402
from sniper.engine import FILA_RAPIDA  # noqa: E402


class SelecaoTests(unittest.TestCase):
    def test_itens_caros_recentes_do_mais_caro(self):
        with MotorDeTeste() as m:
            db = m.engine.db
            agora = time.time()
            db.save_offer(oferta("A", 5000, catalog=""))
            db.save_offer(oferta("B", 200, catalog=""))
            db.save_offer(oferta("C", 800, catalog="", collected_at=agora - 50 * 3600))  # visto há 50 h
            db.save_offer(oferta("D", 1000, catalog=""))
            db.save_offer(oferta("E", 9000, catalog="", store="outra"))
            self.assertEqual(db.fast_lane_items("t", 300, 10), ["A", "D"])
            self.assertEqual(db.fast_lane_items("t", 300, 1), ["A"])


class MotorFilaTests(unittest.TestCase):
    def test_bug_na_fila_rapida_vira_alerta(self):
        with MotorDeTeste() as m:
            eng = m.engine
            for _ in range(3):
                eng.db.save_offer(oferta("A", 5000, catalog=""))
            eng.db.save_offer(oferta("B", 3000, catalog=""))
            col = FakeRefreshCollector({"A": 490, "B": 3000})
            eng.collectors["t"] = col
            self.assertEqual(asyncio.run(eng.fast_lane_step()), 1)
            self.assertEqual(col.pedidos, [["A", "B"]])
            a = eng.db.list_alerts()[0]
            self.assertEqual((a["item_id"], a["watch"]), ("A", FILA_RAPIDA))
            st = eng.watch_status[FILA_RAPIDA]
            self.assertEqual((st["count"], st["state"], st["kind"]), (2, "ok", "rapida"))

    def test_loja_sem_refresh_e_ignorada(self):
        with MotorDeTeste() as m:
            m.engine.db.save_offer(oferta("A", 5000, catalog=""))
            m.engine.collectors["t"] = FakeCollector()
            self.assertEqual(asyncio.run(m.engine.fast_lane_step()), 0)
            self.assertEqual(m.engine.watch_status[FILA_RAPIDA]["count"], 0)


class ConfigVarreduraTests(unittest.TestCase):
    def test_bloco_varredura(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[varredura]\nvalor_alto = 500\nintervalo_rapido = 60\nmax_itens_rapida = 200\n",
                         encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.valor_alto, s.intervalo_rapido, s.max_itens_rapida), (500.0, 60, 200))

    def test_padroes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("", encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.valor_alto, s.intervalo_rapido, s.max_itens_rapida), (300.0, 120, 1000))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_fila_rapida -v`
Expected: ERROR `cannot import name 'FILA_RAPIDA'`.

- [ ] **Step 4: Config**

Em `Settings` (`sniper/config.py`), depois de `cooldown_min`:

```python
    valor_alto: float = 300.0        # fila rápida: itens a partir deste preço
    intervalo_rapido: int = 120      # fila rápida: segundos entre voltas
    max_itens_rapida: int = 1000     # fila rápida: teto de itens (os mais caros primeiro)
```

Em `load`, junto dos outros `raw.get(...)`: `vr = raw.get("varredura", {})`. No `return Settings(...)`:

```python
        valor_alto=float(vr.get("valor_alto", 300)),
        intervalo_rapido=int(vr.get("intervalo_rapido", 120)),
        max_itens_rapida=int(vr.get("max_itens_rapida", 1000)),
```

- [ ] **Step 5: Banco**

Em `sniper/db.py`, no `__init__`, logo depois da linha do índice `ix_items_catalog`:

```python
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_items_price ON items (store, last_price)")
```

E o método (depois de `peer_prices`):

```python
    # ---------- fila rápida ----------
    def fast_lane_items(self, store: str, min_price: float, limit: int, max_age_s: float = 48 * 3600) -> list[str]:
        """Itens caros vistos recentemente, do mais caro para o mais barato."""
        rows = self.conn.execute(
            "SELECT item_id FROM items WHERE store=? AND last_price>=? AND last_seen>=? "
            "ORDER BY last_price DESC LIMIT ?",
            (store, min_price, time.time() - max_age_s, limit)).fetchall()
        return [r[0] for r in rows]
```

- [ ] **Step 6: Motor**

Em `sniper/engine.py`, abaixo de `UNIDADES_TTL_S`:

```python
FILA_RAPIDA = "Fila rápida"
```

Métodos (depois de `sweep_step`):

```python
    async def _fast_loop(self) -> None:
        while True:
            if not self.paused:
                await self.fast_lane_step()
            await asyncio.sleep(self.s.intervalo_rapido)

    async def fast_lane_step(self) -> int:
        """Relê em lote os itens caros de cada loja com refresh e passa pelo pipeline."""
        st = self.watch_status.setdefault(FILA_RAPIDA, {"store": "", "kind": "rapida",
                                                        "interval": self.s.intervalo_rapido})
        st["state"] = "coletando"
        t0 = time.time()
        alerts, itens, erros = 0, 0, []
        for store, col in list(self.collectors.items()):
            if not col.supports_refresh:
                continue
            ids = self.db.fast_lane_items(store, self.s.valor_alto, self.s.max_itens_rapida)
            if not ids:
                continue
            itens += len(ids)
            try:
                offers = await col.refresh(ids)
            except Exception as e:  # noqa: BLE001
                msg = str(e) if isinstance(e, CollectorError) else f"{type(e).__name__}: {e}"
                erros.append(f"{store}: {msg}")
                self.log("erro", f"[{FILA_RAPIDA}] {store}: {msg}")
                continue
            alerts += (await self._process(Watch(name=FILA_RAPIDA, store=store), col, offers))["alertas"]
        st.update(state="erro" if erros else "ok", error="; ".join(erros) or None, count=itens,
                  last_run=time.time(), duration=round(time.time() - t0, 2))
        self.emit("watch", name=FILA_RAPIDA, status=st)
        return alerts
```

Em `start`, logo antes de `self._tasks.append(asyncio.create_task(self._housekeeping()))`:

```python
        if any(c.supports_refresh for c in self.collectors.values()):
            self.watch_status[FILA_RAPIDA] = {"store": "", "kind": "rapida", "state": "aguardando",
                                              "count": 0, "error": None, "last_run": None,
                                              "interval": self.s.intervalo_rapido}
            self._tasks.append(asyncio.create_task(self._supervise(FILA_RAPIDA, self._fast_loop)))
```

- [ ] **Step 7: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 8: Commit**

```powershell
git add sniper/config.py sniper/db.py sniper/engine.py tests/fakes.py tests/test_fila_rapida.py
git commit -m @'
Adiciona fila rápida que relê itens caros em lote

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 9: Saúde das lojas e resumo diário no Telegram

**Files:**
- Modify: `sniper/config.py` (`[telegram]`), `sniper/notify.py` (`send_text`), `sniper/engine.py` (`store_errors`, `_store_fail`, `_store_ok`, `_notify_text`, `_nome`, `health_check`, `_health_loop`, `_summary_text`, `_summary_due_day`, ganchos em `run_watch`/`sweep_step`/`fast_lane_step`, `start`), `tests/fakes.py`
- Test: `tests/test_saude.py`

**Interfaces:**
- Consumes: `limiters` (Task 4), `sweep_step` (Task 6), `fast_lane_step` (Task 8).
- Produces:
  - `Settings.telegram_resumo: str = "09:00"` (`""` desliga), `Settings.telegram_travada_min: int = 30`
  - `TelegramNotifier.send_text(text: str) -> None`
  - `Engine.store_errors: dict[str, {"desde": float, "avisado": bool, "msg": str}]`
  - `Engine._store_fail(store, msg, now=None)`, `async Engine._store_ok(store)`, `async Engine.health_check(now=None)`, `Engine._last_summary: str | None`
  - `tests/fakes.py`: `NotificadorFalso` com `textos: list[str]`

- [ ] **Step 1: Notificador falso**

Acrescente ao fim de `tests/fakes.py`:

```python
class NotificadorFalso:
    """Guarda as mensagens de texto em vez de mandar para o Telegram."""

    def __init__(self):
        self.textos: list[str] = []

    async def send(self, alert):
        pass

    async def send_text(self, text):
        self.textos.append(text)
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/test_saude.py`:

```python
"""Aviso de loja travada e resumo diário."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, NotificadorFalso, oferta  # noqa: E402
from sniper import config  # noqa: E402
from sniper.collectors import CollectorError  # noqa: E402
from sniper.models import Watch  # noqa: E402
from sniper.ratelimit import RateLimiter  # noqa: E402


def hoje_as(h, m):
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))


class TravadaTests(unittest.TestCase):
    def test_avisa_uma_vez_depois_de_30_min_e_avisa_a_volta(self):
        with MotorDeTeste(telegram_resumo="") as m:
            eng, n = m.engine, NotificadorFalso()
            eng.notifiers = [n]
            t0 = time.time()
            eng._store_fail("t", "sem internet", now=t0)
            asyncio.run(eng.health_check(now=t0 + 29 * 60))
            self.assertEqual(n.textos, [])
            asyncio.run(eng.health_check(now=t0 + 31 * 60))
            asyncio.run(eng.health_check(now=t0 + 40 * 60))
            self.assertEqual(len(n.textos), 1)
            self.assertIn("sem internet", n.textos[0])
            asyncio.run(eng._store_ok("t"))
            self.assertEqual(len(n.textos), 2)
            self.assertIn("voltou", n.textos[1])
            self.assertEqual(eng.store_errors, {})

    def test_volta_sem_aviso_previo_nao_manda_nada(self):
        with MotorDeTeste(telegram_resumo="") as m:
            n = NotificadorFalso()
            m.engine.notifiers = [n]
            m.engine._store_fail("t", "erro rápido")
            asyncio.run(m.engine._store_ok("t"))
            self.assertEqual(n.textos, [])

    def test_loja_pausada_conta_como_problema(self):
        with MotorDeTeste(telegram_resumo="") as m:
            lim = RateLimiter(60)
            lim.penalize("429")
            m.engine.limiters["t"] = lim
            asyncio.run(m.engine.health_check())
            self.assertIn("pausada", m.engine.store_errors["t"]["msg"])

    def test_run_watch_registra_falha_e_sucesso(self):
        class Quebra(FakeCollector):
            quebrar = True

            async def collect(self, watch):
                if self.quebrar:
                    raise CollectorError("ML fora do ar")
                return [oferta("A", 100.0, title="Produto", catalog="")]

        w = Watch(name="w", store="t")
        with MotorDeTeste(watches=[w], telegram_resumo="") as m:
            col = Quebra()
            m.engine.collectors["t"] = col
            m.engine.watch_status["w"] = {}
            asyncio.run(m.engine.run_watch(w))
            self.assertEqual(m.engine.store_errors["t"]["msg"], "ML fora do ar")
            col.quebrar = False
            asyncio.run(m.engine.run_watch(w))
            self.assertEqual(m.engine.store_errors, {})


class ResumoTests(unittest.TestCase):
    def test_manda_um_resumo_por_dia_depois_do_horario(self):
        with MotorDeTeste(telegram_resumo="09:00") as m:
            eng, n = m.engine, NotificadorFalso()
            eng.notifiers = [n]
            eng._last_summary = None
            asyncio.run(eng.health_check(now=hoje_as(8, 59)))
            self.assertEqual(n.textos, [])
            asyncio.run(eng.health_check(now=hoje_as(9, 1)))
            asyncio.run(eng.health_check(now=hoje_as(15, 0)))
            self.assertEqual(len(n.textos), 1)
            self.assertIn("últimas 24 h", n.textos[0])

    def test_resumo_desligado(self):
        with MotorDeTeste(telegram_resumo="") as m:
            n = NotificadorFalso()
            m.engine.notifiers = [n]
            m.engine._last_summary = None
            asyncio.run(m.engine.health_check(now=hoje_as(9, 1)))
            self.assertEqual(n.textos, [])

    def test_config_telegram(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[telegram]\nresumo_diario = "08:30"\navisar_travada_minutos = 10\n', encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.telegram_resumo, s.telegram_travada_min), ("08:30", 10))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_saude -v`
Expected: ERROR `unexpected keyword argument 'telegram_resumo'`.

- [ ] **Step 4: Config**

Em `Settings`, depois de `telegram_min_score`:

```python
    telegram_resumo: str = "09:00"   # horário do resumo diário; "" desliga
    telegram_travada_min: int = 30   # avisa se uma loja ficar esse tempo com erro ou pausada
```

No `return Settings(...)` de `load`:

```python
        telegram_resumo=str(tg.get("resumo_diario", "09:00")),
        telegram_travada_min=int(tg.get("avisar_travada_minutos", 30)),
```

- [ ] **Step 5: Telegram com texto livre**

Em `sniper/notify.py`, troque o `send` de `TelegramNotifier` por:

```python
    async def send(self, alert: dict) -> None:
        if alert["score"] < self.min_score:
            return
        await self.send_text(format_text(alert))

    async def send_text(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = await self.client.post(url, json={"chat_id": self.chat_id, "text": text,
                                                  "disable_web_page_preview": False})
            if r.status_code != 200:
                log.warning("Telegram respondeu %s: %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("Falha ao enviar Telegram: %s", e)
```

- [ ] **Step 6: Saúde no motor**

Em `sniper/engine.py`, no fim do `__init__`:

```python
        self.store_errors: dict[str, dict] = {}   # loja → {"desde", "avisado", "msg"}
        # Se já passou do horário do resumo hoje, o primeiro resumo sai amanhã.
        self._last_summary = self._summary_due_day(time.time())
```

Métodos novos (depois de `_motivo_sem_coletor`):

```python
    # ---------- saúde das lojas ----------
    def _nome(self, store: str) -> str:
        info = LOJAS.get(store)
        return info.nome if info else store

    def _store_fail(self, store: str, msg: str, now: float | None = None) -> None:
        e = self.store_errors.setdefault(store, {"desde": now or time.time(), "avisado": False})
        e["msg"] = msg

    async def _store_ok(self, store: str) -> None:
        e = self.store_errors.pop(store, None)
        if e and e["avisado"]:
            await self._notify_text(f"✅ {self._nome(store)} voltou a funcionar.")

    async def _notify_text(self, text: str) -> None:
        for n in self.notifiers:
            if hasattr(n, "send_text"):
                await n.send_text(text)

    def _summary_due_day(self, now: float) -> str | None:
        """Data (AAAA-MM-DD) se já passou do horário do resumo nesse dia; None se não passou ou está desligado."""
        if not self.s.telegram_resumo:
            return None
        hh, mm = (int(x) for x in self.s.telegram_resumo.split(":"))
        lt = time.localtime(now)
        return time.strftime("%Y-%m-%d", lt) if (lt.tm_hour, lt.tm_min) >= (hh, mm) else None

    def _summary_text(self) -> str:
        s = self.db.stats()
        prob = "; ".join(f"{self._nome(k)} ({v['msg']})" for k, v in self.store_errors.items()) or "nenhuma"
        leituras = f"{s['leituras_24h']:,}".replace(",", ".")
        return ("📊 Sniper de Ofertas: últimas 24 h\n"
                f"Leituras: {leituras}\n"
                f"Alertas: {s['alertas_24h']} (críticos: {s['criticos_24h']}, grátis: {s['gratis_24h']})\n"
                f"Descartados: {s['descartados_24h']}\n"
                f"Lojas com problema: {prob}")

    async def health_check(self, now: float | None = None) -> None:
        now = now or time.time()
        for store, lim in self.limiters.items():
            est = lim.estado()
            if est["pausada_ate"]:
                ate = time.strftime("%H:%M", time.localtime(est["pausada_ate"]))
                self._store_fail(store, f"pausada por bloqueio até {ate} ({est['motivo']})", now)
        limite = self.s.telegram_travada_min * 60
        for store, e in self.store_errors.items():
            if not e["avisado"] and now - e["desde"] >= limite:
                e["avisado"] = True
                await self._notify_text(f"⚠️ {self._nome(store)} com problema há "
                                        f"{round((now - e['desde']) / 60)} min: {e['msg']}")
        day = self._summary_due_day(now)
        if day and day != self._last_summary:
            self._last_summary = day
            await self._notify_text(self._summary_text())

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.health_check()
```

Ganchos:

- Em `run_watch`, nos dois `except`, antes de cada `return 0`, acrescente `self._store_fail(w.store, st["error"])`. Depois de `r = await self._process(w, col, offers)`, acrescente `await self._store_ok(w.store)`.
- Em `sweep_step`, no `except` de `_sweep_state`, antes do `return 0`: `self._store_fail(w.store, st["error"])`. Logo depois do bloco `if err: self.log(...)`:

  ```python
          if err and not avancar:
              self._store_fail(w.store, err)
          else:
              await self._store_ok(w.store)
  ```
- Em `fast_lane_step`, no `except`, antes do `continue`: `self._store_fail(store, msg)`. Depois da linha `alerts += (await self._process(...))["alertas"]`: `await self._store_ok(store)`.

Em `start`, logo antes de `self._tasks.append(asyncio.create_task(self._housekeeping()))`:

```python
        self._tasks.append(asyncio.create_task(self._supervise("saúde", self._health_loop)))
```

- [ ] **Step 7: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 8: Commit**

```powershell
git add sniper/config.py sniper/notify.py sniper/engine.py tests/fakes.py tests/test_saude.py
git commit -m @'
Avisa no Telegram quando uma loja trava e manda resumo diário

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 10: API `/api/lojas` e painel

**Files:**
- Modify: `sniper/engine.py` (`lojas_info`), `sniper/server.py`, `sniper/web/index.html`
- Test: `tests/test_api_lojas.py`

**Interfaces:**
- Consumes: `LOJAS`, `limiters`, `store_status`, `store_errors`, `watch_status` com `kind`/`unidade`/`total`/`fim_estimado`.
- Produces: `Engine.lojas_info() -> list[dict]`, cada item com `chave, nome, oficial, ativa, configurada, motivo, limite (estado() | None), erro (str | None)`; rota `GET /api/lojas`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_api_lojas.py`:

```python
"""Rota /api/lojas e painel sem lista fixa de lojas."""
import sys
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.config import LojaConfig, Settings  # noqa: E402
from sniper.server import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ApiLojasTests(unittest.TestCase):
    def test_lista_lojas_com_etiqueta_e_estado(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            s = Settings(base_dir=base, db_path=base / "t.db", windows_on=False,
                         lojas={"mercadolivre": LojaConfig(ativo=True)})
            app = create_app(s)
            eng = app.state.engine
            eng.store_errors["mercadolivre"] = {"desde": 0, "avisado": False, "msg": "sem internet"}
            try:
                lojas = TestClient(app).get("/api/lojas").json()   # sem "with": o motor não liga
            finally:
                eng.db.conn.close()
        ml = next(x for x in lojas if x["chave"] == "mercadolivre")
        self.assertEqual((ml["nome"], ml["oficial"], ml["ativa"], ml["configurada"]),
                         ("Mercado Livre", True, True, False))
        self.assertIn("auth_ml.py", ml["motivo"])
        self.assertEqual(ml["limite"]["limite"], 60)
        self.assertEqual(ml["erro"], "sem internet")

    def test_painel_usa_nomes_da_api(self):
        html = (ROOT / "sniper" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("const STORE", html)
        self.assertIn("/api/lojas", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_api_lojas -v`
Expected: FAIL (404 em `/api/lojas`, `const STORE` presente).

- [ ] **Step 3: Engine e rota**

Em `sniper/engine.py`, depois de `_motivo_sem_coletor`:

```python
    def lojas_info(self) -> list[dict]:
        out = []
        for chave, info in LOJAS.items():
            lc = self.s.lojas.get(chave)
            st = self.store_status.get(chave, {})
            lim = self.limiters.get(chave)
            err = self.store_errors.get(chave)
            out.append({"chave": chave, "nome": info.nome, "oficial": info.oficial,
                        "ativa": bool(lc and lc.ativo), "configurada": st.get("configurada", False),
                        "motivo": st.get("motivo") or (self._motivo_sem_coletor(chave) if not st else ""),
                        "limite": lim.estado() if lim else None,
                        "erro": err["msg"] if err else None})
        return out
```

Em `sniper/server.py`, depois da função `watches`:

```python
    async def lojas(_: Request):
        return JSONResponse(engine.lojas_info())
```

e nas `routes`, depois de `Route("/api/watches", watches),`:

```python
        Route("/api/lojas", lojas),
```

- [ ] **Step 4: Painel — CSS e HTML**

Em `sniper/web/index.html`, no fim do `<style>` (antes de `@media`):

```css
#lojas{max-height:28%}
.tag{font:600 10px var(--mono);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-left:4px;vertical-align:middle}
.tag.of{color:var(--accent);border-color:rgba(61,220,151,.4)}
.tag.nof{color:var(--medio);border-color:rgba(245,213,71,.5)}
```

No `<aside>`, troque `<h3>Regras de vigilância</h3>` por:

```html
    <h3>Lojas</h3>
    <div class="watches" id="lojas"></div>
    <h3>Regras de vigilância</h3>
```

- [ ] **Step 5: Painel — JS**

Troque a linha `const STORE = {...};` por:

```js
let LOJAS = {};
const nomeLoja = k => (LOJAS[k] && LOJAS[k].nome) || k || "";
```

Troque cada uso de `STORE`:
- em `card`: `esc((STORE[a.store]||a.store)[0])` → `esc(nomeLoja(a.store)[0] || "?")` e `esc(STORE[a.store] || a.store)` → `esc(nomeLoja(a.store))`
- em `loadBlocked`: `esc(STORE[b.store] || b.store)` → `esc(nomeLoja(b.store))`

Troque `renderWatches` inteira por:

```js
function renderWatches(ws) {
  const html = Object.entries(ws).map(([name, w]) => {
    const cls = w.state === "ok" ? "ok" : w.state === "erro" ? "erro"
      : (w.state === "sem coletor" || w.state === "loja não suporta varredura") ? "sem" : "col";
    const last = w.last_run ? ` · última há ${ago(w.last_run)}` : "";
    let sub;
    if (w.kind === "varrer") {
      const prog = w.total ? `${(w.unidade ?? 0).toLocaleString("pt-BR")}/${w.total.toLocaleString("pt-BR")}` : "iniciando";
      const fim = w.fim_estimado ? ` · volta termina em ~${Math.max(0, Math.round((w.fim_estimado - Date.now() / 1000) / 60))} min` : "";
      sub = `${esc(nomeLoja(w.store))} · varredura ${prog}${fim}${last}`;
    } else if (w.kind === "rapida") {
      sub = `itens caros · ${w.count ?? 0} itens · a cada ${w.interval ?? "-"}s${last}`;
    } else {
      sub = `${esc(nomeLoja(w.store))} · ${w.count ?? 0} itens · a cada ${w.interval ?? "-"}s${last}${w.duration != null ? ` · ${w.duration}s` : ""}`;
    }
    return `<div class="w"><div class="top"><b>${esc(name)}</b><span class="st ${cls}">${esc(w.state)}</span></div>
      <div class="sub">${sub}</div>
      ${w.error ? `<div class="err">${esc(w.error)}</div>` : ""}</div>`;
  }).join("");
  $("#watches").innerHTML = html || `<div class="w sub">Nenhuma regra. Configure em config.toml.</div>`;
}

function renderLojas(list) {
  LOJAS = Object.fromEntries(list.map(l => [l.chave, l]));
  const html = list.filter(l => l.ativa).map(l => {
    const lim = l.limite, pausa = lim && lim.pausada_ate;
    const [cls, txt] = !l.configurada ? ["sem", "não configurada"]
      : pausa ? ["erro", `pausada até ${hhmm(pausa).slice(0, 5)}`]
      : l.erro ? ["erro", "com erro"] : ["ok", "ok"];
    const det = !l.configurada ? l.motivo : pausa ? lim.motivo : l.erro;
    return `<div class="w"><div class="top"><b>${esc(l.nome)}<span class="tag ${l.oficial ? "of" : "nof"}">${l.oficial ? "oficial" : "não oficial"}</span></b><span class="st ${cls}">${esc(txt)}</span></div>
      ${lim ? `<div class="sub">${lim.ultimo_minuto}/${lim.limite} consultas no último minuto</div>` : ""}
      ${det ? `<div class="err">${esc(det)}</div>` : ""}</div>`;
  }).join("");
  $("#lojas").innerHTML = html || `<div class="w sub">Nenhuma loja ligada. Use [lojas.mercadolivre] ativo = true no config.toml.</div>`;
}
```

No bloco de inicialização (o `(async () => { ... })();` do fim), troque a primeira linha `state.alerts = await api("/api/alerts?limit=200"); render();` por:

```js
  renderLojas(await api("/api/lojas"));
  state.alerts = await api("/api/alerts?limit=200"); render();
```

e, junto dos outros `setInterval`, acrescente:

```js
  setInterval(() => api("/api/lojas").then(renderLojas), 5000);
```

- [ ] **Step 6: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 7: Conferir o painel de verdade**

Run: `.venv\Scripts\python run.py --sem-janela` (em segundo plano) e abra `http://127.0.0.1:8765`.
Confira: o bloco "Lojas" aparece (ou a mensagem "Nenhuma loja ligada…" se o config não tiver loja), o console do navegador não mostra erros de JS e as regras aparecem com o texto certo. Encerre o processo.

- [ ] **Step 8: Commit**

```powershell
git add sniper/engine.py sniper/server.py sniper/web/index.html tests/test_api_lojas.py
git commit -m @'
Mostra lojas, etiqueta oficial e progresso da varredura no painel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 11: Operação 24 horas (suspensão, inicialização, log rotativo)

**Files:**
- Create: `sniper/winsys.py`
- Modify: `run.py`
- Test: `tests/test_winsys.py`

**Interfaces:**
- Consumes: nada.
- Produces: `winsys.impedir_suspensao() -> bool`, `winsys.pasta_inicializar() -> Path`, `winsys.script_atalho(base: Path, lnk: Path) -> str`, `winsys.instalar_inicio(base: Path) -> Path`, `winsys.remover_inicio() -> bool`, `winsys.NOME_ATALHO`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_winsys.py`:

```python
"""Atalho de inicialização do Windows (só a parte que dá para testar sem mexer no sistema)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import winsys  # noqa: E402


class AtalhoTests(unittest.TestCase):
    def test_script_aponta_para_iniciar_bat_sem_janela(self):
        base = Path(r"C:\Users\Fulana\Projeto\sniper")
        s = winsys.script_atalho(base, Path(r"C:\Startup\Sniper de Ofertas.lnk"))
        self.assertIn(r"'C:\Users\Fulana\Projeto\sniper\iniciar.bat'", s)
        self.assertIn("$s.Arguments = '--sem-janela'", s)
        self.assertIn(r"$s.WorkingDirectory = 'C:\Users\Fulana\Projeto\sniper'", s)
        self.assertIn("$s.WindowStyle = 7", s)

    def test_aspas_simples_escapadas(self):
        s = winsys.script_atalho(Path(r"C:\D'Avila"), Path(r"C:\x.lnk"))
        self.assertIn(r"'C:\D''Avila\iniciar.bat'", s)

    def test_nome_do_atalho(self):
        self.assertEqual(winsys.NOME_ATALHO, "Sniper de Ofertas.lnk")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python -m unittest tests.test_winsys -v`
Expected: ERROR `cannot import name 'winsys'`.

- [ ] **Step 3: Implementar `winsys`**

Crie `sniper/winsys.py`:

```python
"""Integração com o Windows para rodar 24 horas: não deixar o PC dormir e abrir junto com o Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
NOME_ATALHO = "Sniper de Ofertas.lnk"


def impedir_suspensao() -> bool:
    """Impede a suspensão enquanto este processo roda (o monitor ainda pode desligar).
    Vale para a thread que chamou; chame da thread principal. Fora do Windows não faz nada."""
    if sys.platform != "win32":
        return False
    import ctypes
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))


def pasta_inicializar() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _ps(texto: str) -> str:
    """String literal do PowerShell (aspas simples, com ' escapada)."""
    return "'" + texto.replace("'", "''") + "'"


def script_atalho(base: Path, lnk: Path) -> str:
    bat = base / "iniciar.bat"
    return (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps(str(lnk))}); "
            f"$s.TargetPath = {_ps(str(bat))}; $s.Arguments = '--sem-janela'; "
            f"$s.WorkingDirectory = {_ps(str(base))}; $s.WindowStyle = 7; $s.Save()")


def instalar_inicio(base: Path) -> Path:
    """Cria o atalho na pasta Inicializar: o Sniper abre minimizado quando o Windows inicia."""
    if sys.platform != "win32":
        raise RuntimeError("Iniciar com o sistema só funciona no Windows")
    lnk = pasta_inicializar() / NOME_ATALHO
    subprocess.run(["powershell", "-NoProfile", "-Command", script_atalho(base, lnk)], check=True)
    return lnk


def remover_inicio() -> bool:
    lnk = pasta_inicializar() / NOME_ATALHO
    if lnk.exists():
        lnk.unlink()
        return True
    return False
```

- [ ] **Step 4: `run.py`**

Imports: acrescente `from logging.handlers import RotatingFileHandler` e troque `from sniper import config` por `from sniper import config, winsys`.

Atualize a docstring do topo acrescentando duas linhas de uso:

```
    python run.py --instalar-inicio   # abre sozinho quando o Windows iniciar
    python run.py --remover-inicio    # desfaz o anterior
```

Em `main()`, depois de `ap.add_argument("--sem-janela", action="store_true")`:

```python
    ap.add_argument("--instalar-inicio", action="store_true")
    ap.add_argument("--remover-inicio", action="store_true")
```

Logo depois de `args = ap.parse_args()`:

```python
    if args.instalar_inicio:
        lnk = winsys.instalar_inicio(BASE)
        print(f"Atalho criado em {lnk}. O Sniper vai abrir sozinho quando o Windows iniciar.")
        return
    if args.remover_inicio:
        print("Atalho de inicialização removido." if winsys.remover_inicio()
              else "Não havia atalho de inicialização.")
        return
```

Troque o `logging.FileHandler(...)` do `basicConfig` por:

```python
                                  RotatingFileHandler(BASE / "data" / "sniper.log", maxBytes=5 * 1024 * 1024,
                                                      backupCount=4, encoding="utf-8")])
```

Logo depois do `logging.basicConfig(...)`:

```python
    if winsys.impedir_suspensao():
        logging.getLogger("sniper").info("Suspensão do Windows bloqueada enquanto o Sniper roda")
```

- [ ] **Step 5: Rodar todos os testes**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS.

- [ ] **Step 6: Verificação manual no Windows**

1. Rode `.venv\Scripts\python run.py --sem-janela` em segundo plano. Em outro terminal **como administrador**, rode `powercfg /requests`. Esperado: `python.exe` listado em `SYSTEM:`. Se não houver terminal de administrador, registre como "verificação pendente" no relatório. Encerre o processo.
2. Rode `.venv\Scripts\python run.py --instalar-inicio`. Confira que `"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Sniper de Ofertas.lnk"` existe (`Test-Path`). Depois rode `.venv\Scripts\python run.py --remover-inicio` e confira que sumiu. **Não deixe o atalho instalado**: quem decide ligar é a usuária.

- [ ] **Step 7: Commit**

```powershell
git add sniper/winsys.py run.py tests/test_winsys.py
git commit -m @'
Prepara para rodar 24 horas: sem suspensão, início com o Windows e log rotativo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

---

### Task 12: Config de exemplo, README e verificação final

**Files:**
- Modify: `config.exemplo.toml`, `README.md`

**Interfaces:**
- Consumes: todas as chaves de config das Tasks 4, 6, 8 e 9.
- Produces: documentação.

- [ ] **Step 1: `config.exemplo.toml`**

Troque o bloco `# ---------- Lojas ----------` (o `[mercadolivre]` inteiro) por:

```toml
# ---------- Lojas ----------
# Cada loja tem um bloco [lojas.<nome>]. ativo = true liga; por_minuto é opcional (limite de consultas).
# No painel, "oficial" = API oficial da loja; "não oficial" = endpoint público que pode mudar sem aviso.
[lojas.mercadolivre]
ativo = true
# por_minuto = 60

[mercadolivre]
# Crie o app em https://developers.mercadolivre.com.br/devcenter
client_id = ""
client_secret = ""
redirect_uri = "https://www.google.com"
```

Em `[telegram]`, depois de `nota_minima = 70`:

```toml
resumo_diario = "09:00"      # resumo das últimas 24 h; "" desliga
avisar_travada_minutos = 30  # avisa se uma loja ficar esse tempo com erro ou bloqueada
```

Depois de `[windows]`, antes de `# ---------- O que vigiar ----------`:

```toml
# ---------- Varredura (caça a bugs em todo o catálogo) ----------
[varredura]
valor_alto = 300             # itens a partir deste preço entram na fila rápida
intervalo_rapido = 120       # segundos entre releituras da fila rápida
max_itens_rapida = 1000      # teto da fila rápida (os mais caros primeiro)

# Cada [[varrer]] percorre o catálogo da loja em rodízio, do mais barato para o mais caro.
# categorias: "todas" ou lista de ids (ex.: ["MLB1000", "MLB5726"])
# ciclo_minutos: tempo desejado para uma volta completa (o limite de consultas pode deixar mais lento)
#
# [[varrer]]
# nome = "ML geral"
# loja = "mercadolivre"
# categorias = "todas"
# ciclo_minutos = 60
# paginas = 1
```

- [ ] **Step 2: `README.md`**

Troque o título `# Sniper de Ofertas — Fase 1` e o parágrafo seguinte por:

```markdown
# Sniper de Ofertas

Caçador de bugs de preço para Windows, pensado para rodar 24 horas. Ele varre o catálogo das lojas, relê os itens caros com frequência, detecta preço fora do normal (erro de vírgula, item de graça, queda brusca) e avisa no painel, com notificação do Windows e no Telegram.

Hoje a loja ligada é o **Mercado Livre** (API oficial). Steam, Epic, Nuuvem, lojas VTEX, Amazon e Shopee vêm nas próximas fases.
```

No passo 4 de "Ligar o Mercado Livre de verdade" (o antigo passo 4 foi apagado na Task 1), acrescente:

```markdown
4. Confira que o `config.toml` tem `[lojas.mercadolivre]` com `ativo = true` (configs antigos, só com `[mercadolivre]` preenchido, já ligam a loja).
```

Depois da seção "Regras de vigilância", acrescente:

```markdown
## Varredura e fila rápida

- **`[[varrer]]`** percorre o catálogo da loja em rodízio (no ML, cada categoria final, do mais barato para o mais caro). Se o PC reiniciar, ele continua de onde parou.
- **Fila rápida:** todo item visto nas últimas 48 h com preço ≥ `valor_alto` é relido a cada `intervalo_rapido` segundos.
- **Limite por loja:** cada loja tem um teto de consultas por minuto. Se a loja bloquear (429/403), só ela pausa por 1, 5, 15 e depois 60 min. O painel mostra o motivo.

## Rodar 24 horas

- Enquanto o Sniper está aberto, o Windows não entra em suspensão (o monitor ainda desliga).
- `iniciar.bat --instalar-inicio` faz o Sniper abrir sozinho, minimizado, quando o Windows iniciar. `iniciar.bat --remover-inicio` desfaz.
- Com o Telegram ligado, chega um aviso se uma loja ficar mais de 30 min com problema e um resumo diário às 9h.
- O log fica em `data/sniper.log` (até 5 arquivos de 5 MB).
```

Na seção "Estrutura", troque o bloco de código por:

```
run.py                 inicia motor + API + janela (--instalar-inicio / --remover-inicio)
auth_ml.py             autorização OAuth do Mercado Livre (uma vez)
sniper/stores.py       registro de lojas (nome, oficial/não oficial, limite)
sniper/engine.py       regras, varredura, fila rápida, saúde das lojas e alertas
sniper/ratelimit.py    limite de consultas por loja e pausa por bloqueio
sniper/detector.py     cálculo da nota
sniper/collectors/     um coletor por loja (mercadolivre)
sniper/db.py           SQLite: itens, histórico, alertas, estado da varredura
sniper/notify.py       Telegram + notificação do Windows
sniper/server.py       API local (127.0.0.1) + transmissão ao vivo
sniper/winsys.py       sem suspensão e início com o Windows
sniper/web/index.html  painel
tests/                 python -m unittest discover tests
```

Troque a seção "Próximas fases" por:

```markdown
## Próximas fases

- **Fase 2:** jogos (Steam, Epic, IsThereAnyDeal com Nuuvem) e comparação de preço entre lojas de jogos.
- **Fase 3:** coletor VTEX genérico (Carrefour, Renner, Leroy Merlin e outras) e comparação por código de barras.
- **Fase 4:** Amazon e Shopee pelas APIs de afiliados.
- Depois: executor assistido de compra e aprendizado de quais lojas cancelam pedido.
```

- [ ] **Step 3: Conferir que o config de exemplo carrega**

Run: `.venv\Scripts\python -c "from sniper import config; s = config.load('config.exemplo.toml'); print(s.lojas, s.valor_alto, s.telegram_resumo, [w.name for w in s.watches])"`
Expected: `{'mercadolivre': LojaConfig(ativo=True, por_minuto=None)} 300.0 09:00 ['iPhones', 'Consoles', 'Notebooks']`

- [ ] **Step 4: Rodar a suíte inteira**

Run: `.venv\Scripts\python -m unittest discover tests -v`
Expected: tudo PASS. Anote o número de testes no relatório.

- [ ] **Step 5: Conferir que não sobrou "demo"**

Run: `git grep -n -i "demo" -- sniper run.py config.exemplo.toml README.md`
Expected: só três ocorrências: o comentário da limpeza em `sniper/db.py` ("O modo demonstração foi removido…"), a linha `DELETE ... store='demo'` e o exemplo `["demonstração", "mostruário"]` de `palavras_teste_extras` no `config.exemplo.toml`.

- [ ] **Step 6: Commit**

```powershell
git add config.exemplo.toml README.md
git commit -m @'
Documenta lojas, varredura, fila rápida e operação 24 horas

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
'@
```

- [ ] **Step 7: Relatório para a usuária**

Inclua: o resultado da Task 0 (OK / PENDENTE sem token / problema), o número de testes passando, as verificações manuais da Task 11 que ficaram pendentes e um lembrete. Sem o Mercado Livre autorizado (`python auth_ml.py`), o Sniper abre sem nenhuma loja rodando, porque o demo foi removido.
