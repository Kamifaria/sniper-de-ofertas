# Fase 1 — Base multi-loja e modo varredura

Data: 2026-09-23
Status: aprovado no brainstorming, aguardando revisão da spec

## Contexto e objetivo geral

O Sniper de Ofertas deve achar **bugs de preço** (erro de vírgula, preço regional errado, queda absurda) nos sites mais famosos do Brasil, incluindo lojas de jogos. Não é caça a jogos grátis nem a promoções comuns.

Decisões tomadas no brainstorming:

- **Lojas aceitas:** oficiais (API com cadastro) **e** não oficiais (endpoints públicos sem chave). Cada loja tem uma etiqueta `oficial`/`não oficial` e é ligada ou desligada no config.
- **Onde roda:** no PC da usuária com Windows, ligado 24 horas.
- **Abordagem de coleta (C, híbrida):** um coletor direto por loja para detectar rápido. Agregadores (IsThereAnyDeal) entram só como referência de preço para jogos.
- **Lojas de teste:** o modo demonstração (loja simulada) sai do sistema. Os filtros contra vendedores e anúncios de teste do Mercado Livre continuam.

### Fases

| Fase | Conteúdo |
|---|---|
| **1 (esta spec)** | Remover o demo, registro de lojas com etiqueta, limite de consultas por loja, modo varredura, fila rápida, operação 24 horas |
| 2 | Jogos: Steam, Epic, IsThereAnyDeal (inclui Nuuvem), comparação entre lojas de jogos |
| 3 | Coletor VTEX genérico (antes, um teste rápido para confirmar quais lojas da lista são VTEX) e comparação por EAN |
| 4 | Afiliados: Amazon e Shopee (dependem de contas aprovadas) |

Cada fase tem sua própria spec, plano e implementação. A fase 1 entrega a infraestrutura usando só o Mercado Livre.

## 1. Remoção do modo demonstração

- Apagar `sniper/collectors/demo.py`.
- Tirar `DemoCollector` de `sniper/collectors/__init__.py` e de `sniper/engine.py`.
- Tirar `demo_on` e a leitura de `[demo]` de `sniper/config.py`. Um `[demo]` que sobrar em config antigo é ignorado em silêncio.
- Tirar o bloco `[demo]` de `config.toml` e `config.exemplo.toml`, e as menções no `README.md`.
- Tirar `demo: "Demo"` de `sniper/web/index.html`.
- Tirar `"demo"` do comentário de `Offer.store` em `sniper/models.py`.
- **Limpeza do banco:** em `Database.__init__`, apagar as linhas com `store='demo'` das tabelas `prices`, `items`, `alerts`, `discards` e `sellers`. A operação é idempotente e barata, então roda a cada inicialização sem precisar de flag.
- Continuam intactos: `filters.check_listing` (palavras de teste), `filters.check_seller` (vendedor novo ou sem vendas) e o bloqueio automático de vendedores.

## 2. Registro de lojas — `sniper/stores.py`

```python
@dataclass
class LojaInfo:
    chave: str                 # "mercadolivre"
    nome: str                  # "Mercado Livre"
    oficial: bool
    criar: Callable[[Settings, RateLimiter], Collector | None]  # None = falta credencial
    por_minuto: int            # limite padrão de consultas
    motivo_sem_config: str     # texto mostrado no painel quando criar() devolve None

LOJAS: dict[str, LojaInfo]
```

- O `Engine.__init__` percorre `LOJAS`. Para cada loja **ativa** no config, cria um `RateLimiter` e chama `criar`. Os `if` fixos por loja saem do engine.
- Config por loja:
  ```toml
  [lojas.mercadolivre]
  ativo = true
  por_minuto = 60        # opcional
  ```
- **Compatibilidade:** se `[lojas.mercadolivre]` não existir e `[mercadolivre].client_id` estiver preenchido, a loja conta como ativa. As credenciais continuam em `[mercadolivre]`.
- `Settings` ganha `lojas: dict[str, LojaConfig]` (`ativo`, `por_minuto`).

## 3. Limite de consultas — `sniper/ratelimit.py`

- `RateLimiter(por_minuto)`: balde de fichas assíncrono. `await acquire()` espera até haver ficha. É compartilhado por todas as regras e filas da mesma loja.
- Contador de consultas do último minuto, para o painel.
- **Pausa por bloqueio:** `limiter.penalize()` é chamado pelo coletor ao receber 429 ou 403 persistente (depois das novas tentativas que já existem). A loja fica pausada por 1, 5, 15 e depois 60 minutos (degraus crescentes). `acquire()` espera o fim da pausa. Uma consulta bem-sucedida zera o degrau.
- `limiter.estado()` retorna `{"pausada_ate": ts | None, "degrau": int, "ultimo_minuto": int, "limite": int}`.
- Cota por fila: `acquire(fila="rapida")` respeita um teto de 50% do `por_minuto` para a fila rápida. As outras filas usam o restante sem teto próprio.

`MercadoLivreCollector` recebe o limiter no construtor e chama `acquire()` antes de cada `GET`, dentro de `_get`.

## 4. Modo varredura

### Config

```toml
[[varrer]]
nome = "ML geral"
loja = "mercadolivre"
categorias = "todas"     # ou lista de ids
ciclo_minutos = 60
paginas = 1
```

`Watch` ganha `kind: str = "vigiar"` (`"vigiar"` ou `"varrer"`), `sweep_categories: list[str] | None` (None = todas) e `cycle_min: int`.

### Interface do coletor (métodos opcionais em `Collector`)

```python
supports_sweep: bool = False
async def sweep_units(self, watch: Watch) -> list[str]          # ex.: categorias finais
async def sweep(self, unit: str, watch: Watch) -> list[Offer]   # lê uma unidade
supports_refresh: bool = False
async def refresh(self, item_ids: list[str]) -> list[Offer]     # relê itens em lote
```

### Motor

- Loop de varredura por regra `[[varrer]]`: carrega as unidades (cache de 24 h), lê o cursor salvo e processa uma unidade por vez. O intervalo entre unidades é `ciclo_minutos*60 / n_unidades`, e o limiter segura a velocidade se a loja não aguentar.
- Cada lote de ofertas passa pelo **mesmo pipeline** de `run_watch` (filtro, detector, vendedor, reconfirmação, alerta). O pipeline é extraído para `Engine._process(watch, collector, offers)` e reaproveitado por `vigiar`, `varrer` e fila rápida.
- Tabela nova `sweep_state(watch TEXT PRIMARY KEY, units TEXT, units_ts REAL, cursor INTEGER, cycle_started REAL)`. O cursor é salvo depois de cada unidade, e a varredura retoma de onde parou depois de reiniciar.
- Uma unidade com erro é registrada no log e pulada. Uma loja sem `supports_sweep` deixa a regra no estado `"loja não suporta varredura"`.
- Estado no painel: `unidade atual/total` e estimativa de fim da volta.

### Mercado Livre

- `sweep_units`: raízes de `/sites/MLB/categories` (ou as de `categorias`) descendo até as folhas (`children_categories` vazio), com cache em `sweep_state`. A árvore vem de uma chamada só ao dump `/sites/MLB/categories/all`. Se o dump falhar, cada nó é lido em `/categories/{id}`, o que dá milhares de chamadas na primeira carga.
- `sweep(unit)`: `/sites/MLB/search?category={unit}&sort=price_asc&limit=50`, com `paginas` páginas. A ordem do mais barato primeiro põe os bugs no topo.
- `refresh(ids)`: `/items?ids=` em lotes de 20 (reaproveita o `items()` atual).
- **Risco a verificar no início da implementação:** confirmar que o app do ML tem acesso a `/sites/MLB/search` com `sort=price_asc` por categoria e ao endpoint de categorias. Se não tiver, parar e reavaliar antes de seguir.

## 5. Fila rápida

- Config:
  ```toml
  [varredura]
  valor_alto = 300
  intervalo_rapido = 120
  max_itens_rapida = 1000
  ```
- A cada `intervalo_rapido` segundos, para cada loja com `supports_refresh`: seleciona de `items` os itens com `last_price >= valor_alto` e `last_seen` nas últimas 48 h, do mais caro para o mais barato, até `max_itens_rapida`. Depois chama `refresh` e passa o resultado por `_process` com uma `Watch` sintética de nome `"Fila rápida"`.
- Usa `acquire(fila="rapida")`, com teto de 50% da cota da loja.
- Estado no painel: nº de itens e horário da última volta.

## 6. Crescimento do banco

`prices` ganha a coluna `reads INTEGER DEFAULT 1`. `Database.save_offer` só insere uma linha nova em `prices` se o preço (ou `original_price`) mudou em relação à última linha do item **ou** se a última linha tem mais de 6 horas. Nos outros casos, soma 1 em `reads` da última linha. `items` é atualizado sempre (`last_price`, `last_seen`).

`Database.history` expande cada linha em `reads` leituras, respeitando o `limit`. Assim, o detector vê exatamente as mesmas leituras de antes: a mediana e o `historico_minimo` não mudam, e o banco guarda uma linha por mudança de preço. `stats()["leituras_24h"]` passa a somar `reads`.

> Ajuste feito ao escrever o plano: a regra "só insere se mudou" sozinha faria um item estável levar 18 h para juntar 3 leituras e piorava a detecção. O contador resolve isso.

## 7. Operação 24 horas

- **Sem suspensão:** em `run.py`, no Windows, `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` via `ctypes` enquanto o processo roda. O monitor ainda pode desligar. Em outros sistemas não faz nada.
- **Iniciar com o Windows:** `run.py --instalar-inicio` cria `Sniper de Ofertas.lnk` na pasta Inicializar do usuário, apontando para `iniciar.bat --sem-janela`. `--remover-inicio` apaga o atalho. O `iniciar.bat` repassa os argumentos.
- **Supervisor:** cada loop (vigiar, varrer, fila rápida) roda dentro de `Engine._supervise(nome, coro_factory)`. Uma exceção inesperada é registrada no log, e o loop é recriado 30 s depois.
- **Log:** `RotatingFileHandler` com 5 MB × 5 arquivos.
- **Telegram:**
  - `avisar_travada_minutos = 30`: se uma loja ficar em erro ou pausada por mais tempo que isso, envia uma mensagem (uma vez por episódio) e outra quando voltar.
  - `resumo_diario = "09:00"`: resumo com leituras, alertas, descartes e lojas com problema nas últimas 24 h. `""` desliga.

## 8. Painel e API

- `GET /api/lojas`: lista de `{chave, nome, oficial, ativa, configurada, motivo, estado do limiter, erro}`.
- Bloco **Lojas** no painel: um cartão por loja, com a etiqueta "não oficial" em amarelo, o estado, as consultas no último minuto sobre o limite e a pausa até HH:MM.
- Regras `varrer` aparecem na lista de regras com o progresso da volta. A fila rápida aparece como uma linha própria.
- O mapa fixo `STORE` sai do HTML. Os nomes vêm de `/api/lojas`.
- Cada alerta mostra a origem pelo campo `watch` (nome da regra, da regra de varredura ou "Fila rápida"). A nota e os níveis não mudam.

## 9. Erros

| Situação | Comportamento |
|---|---|
| 429/403 persistente | `penalize()` pausa só aquela loja em degraus. Painel mostra o motivo. Telegram avisa depois de `avisar_travada_minutos`. |
| Sem internet | A regra fica em "erro" e tenta no próximo ciclo. A varredura mantém o cursor. |
| Exceção inesperada no loop | O supervisor recria o loop em 30 s. |
| Loja ativa sem credencial | Estado "não configurada" com `motivo_sem_config`. As demais lojas seguem. |
| Categoria some | Unidade pulada. A lista é recarregada a cada 24 h. |

## 10. Testes (`unittest`, no padrão de `tests/test_sniper.py`)

- `RateLimiter`: respeita N/minuto (com relógio injetável), pausa em degraus, zera o degrau com sucesso e aplica o teto de 50% da fila rápida.
- Registro de lojas: cria só as ativas, aceita config novo e antigo, e `/api/lojas` traz a etiqueta.
- Varredura com `FakeCollector`: percorre todas as unidades, retoma do cursor depois de recriar o `Engine` sobre o mesmo banco, pula unidade com erro e marca a loja sem suporte.
- Fila rápida: seleção por `valor_alto`, janela de 48 h, teto e ordem.
- `save_offer`: preço igual não insere, preço mudado insere, mais de 6 h insere.
- Limpeza do demo: remove `store='demo'` e preserva as outras lojas.
- Mercado Livre (respostas falsas): categorias até as folhas, busca com `sort=price_asc` e `refresh` em lotes de 20.
- Os testes existentes continuam passando.
- **Verificação manual:** o PC não suspende com o app aberto, e o atalho de inicialização funciona.

## Fora do escopo desta fase

Lojas novas (Steam, Epic, VTEX, Amazon, Shopee), comparação entre lojas e casamento por EAN ou título ficam para as fases 2 a 4. Executor de compra e aprendizado de cancelamentos continuam no roadmap do README.
