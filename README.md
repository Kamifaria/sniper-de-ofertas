# Sniper de Ofertas

Caçador de bugs de preço para Windows, pensado para rodar 24 horas. Ele varre o catálogo das lojas, relê os itens caros com frequência, detecta preço fora do normal (erro de vírgula, item de graça, queda brusca) e avisa no painel, com notificação do Windows e no Telegram.

Lojas: **Mercado Livre** (API oficial, precisa de `auth_ml.py`; lê pelo **catálogo**: mais vendidos de cada categoria e todos os vendedores de cada produto, porque a busca de anúncios e a leitura direta de anúncios são bloqueadas para apps comuns) e **10 lojas VTEX** pela busca pública, sem login: C&A, Tok&Stok, Cobasi, Pague Menos, Americanas, Telhanorte, Sam's Club, Drogaria São Paulo, Drogarias Pacheco e Atacadão. Nas lojas VTEX, item que já aparece a R$ 0,00/0,01 é tratado como preço simbólico (sem alerta); só alerta quando o preço **cai** para isso. Steam, Epic, Nuuvem, Amazon e Shopee vêm nas próximas fases.

## Como rodar (Windows)

1. Instale o **Python 3.11+** em python.org e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez, ele cria o ambiente e instala as dependências (1–2 min).
   - Ele copia `config.exemplo.toml` para `config.toml`.
3. O painel abre em uma janela própria. Sem loja configurada ele fica vazio: siga "Ligar o Mercado Livre de verdade" abaixo.

Outras formas de abrir: `iniciar.bat --navegador` (abre no Chrome/Edge) ou `iniciar.bat --sem-janela` (painel em http://127.0.0.1:8765).

## Ligar o Mercado Livre de verdade

1. Acesse https://developers.mercadolivre.com.br/devcenter e crie um aplicativo.
   - **Redirect URI:** `https://www.google.com` (ou outra URL https que você controle)
   - Escopos: leitura + `offline_access` (é esse escopo que gera o refresh token)
2. No `config.toml`, preencha `[mercadolivre]` com `client_id`, `client_secret` e `redirect_uri`.
3. Abra um terminal na pasta e rode:
   ```
   .venv\Scripts\activate
   python auth_ml.py
   ```
   Autorize no navegador, copie a URL para onde você foi mandado e cole no terminal. O token fica em `data/ml_token.json` e é renovado automaticamente.
4. Confira que o `config.toml` tem `[lojas.mercadolivre]` com `ativo = true` (configs antigos, só com `[mercadolivre]` preenchido, já ligam a loja).

## Telegram (alerta no celular)

1. Fale com o **@BotFather**, crie um bot e copie o token.
2. Mande qualquer mensagem para o seu bot e pegue o seu id com o **@userinfobot**.
3. Em `[telegram]`: `ativo = true`, `bot_token`, `chat_id`.

## Regras de vigilância

Cada bloco `[[vigiar]]` no `config.toml` é uma regra:

| campo | o que faz |
|---|---|
| `busca` | termo de busca (ex.: `"iphone 15"`) |
| `categoria` | id de categoria do ML (ex.: `MLB1055`) |
| `itens` | anúncios específicos: `["MLB123..."]` |
| `intervalo` | segundos entre coletas (itens caros: 60–90) |
| `piso` | preço abaixo disso já é suspeito |
| `preco_minimo` | ignora itens que normalmente custam menos (capinhas, cabos) |
| `paginas` | páginas de 50 resultados por busca |

## Varredura e fila rápida

- **`[[varrer]]`** percorre o catálogo da loja em rodízio (no ML, cada categoria final, do mais barato para o mais caro). Se o PC reiniciar, ele continua de onde parou.
- **Fila rápida:** todo item visto nas últimas 48 h com preço ≥ `valor_alto` é relido a cada `intervalo_rapido` segundos.
- **Limite por loja:** cada loja tem um teto de consultas por minuto. Se a loja bloquear (429/403), só ela pausa por 1, 5, 15 e depois 60 min. O painel mostra o motivo.

## Rodar 24 horas

- Enquanto o Sniper está aberto, o Windows não entra em suspensão (o monitor ainda desliga).
- `iniciar.bat --instalar-inicio` faz o Sniper abrir sozinho, minimizado, quando o Windows iniciar. `iniciar.bat --remover-inicio` desfaz.
- Com o Telegram ligado, chega um aviso se uma loja ficar mais de 30 min com problema e um resumo diário às 9h.
- O log fica em `data/sniper.log` (até 5 arquivos de 5 MB).

## Como a nota (0–100) é calculada

| sinal | pontos |
|---|---|
| preço ≤ R$ 1,00 | 100 → **GRÁTIS** |
| queda vs mediana de 30 dias (85% / 70% / 55% / 40% / 25%) | 75 / 62 / 50 / 40 / 15 |
| queda brusca vs última coleta (≥50% / ≥30%) | +20 / +10 |
| abaixo do piso da regra | +20 a +30 |
| "de/por" anunciado pela loja (≥80% / 60% / 45%) | +25 / +15 / +8 |
| frete grátis (quando já há queda forte) | +5 |

Níveis: **CRÍTICO** ≥ 90 · **ALTO** ≥ 70 · **MÉDIO** ≥ 50. O padrão é o modo **"só bugs"** (`nota_minima_alerta = 70`): promoção comum de 40-50% não aparece.

Contra falso alerta:
- **GRÁTIS** (preço ≤ R$ 1,00) só conta se o preço normal era pelo menos R$ 10.
- Nas lojas VTEX o mesmo código de barras aparece na unidade e na caixa, então **não** se compara produtos da mesma loja: a comparação é com o **mesmo código de barras em outras lojas** (EAN válido, único em cada loja, pelo menos 2 lojas).
- O mesmo item com o mesmo preço só alerta de novo depois de 24 h (antes, só se cair mais 5%).

## Escolher as lojas e log de bugs

- No painel, bloco **Lojas**: botão **Ligar/Desligar** em cada loja. Vale na hora e fica salvo. Loja ligada ganha uma varredura automática (não precisa de `[[varrer]]`).
- Lista de alertas = log de bugs. Filtre por **Hoje / 24 h / 7 dias** e use **⬇ Exportar CSV** (abre no Excel). Item sem histórico e sem piso fica limitado a 75, porque ainda não dá para confiar.

## Estrutura

```
run.py                 inicia motor + API + janela (--instalar-inicio / --remover-inicio)
auth_ml.py             autorização OAuth do Mercado Livre (uma vez)
sniper/stores.py       registro de lojas (nome, oficial/não oficial, limite)
sniper/engine.py       regras, varredura, fila rápida, saúde das lojas e alertas
sniper/ratelimit.py    limite de consultas por loja e pausa por bloqueio
sniper/detector.py     cálculo da nota
sniper/collectors/     um coletor por plataforma (mercadolivre, vtex)
sniper/db.py           SQLite: itens, histórico, alertas, estado da varredura
sniper/notify.py       Telegram + notificação do Windows
sniper/server.py       API local (127.0.0.1) + transmissão ao vivo
sniper/winsys.py       sem suspensão e início com o Windows
sniper/web/index.html  painel
tests/                 python -m unittest discover tests
```

## Próximas fases

- **Fase 2:** jogos (Steam, Epic, IsThereAnyDeal com Nuuvem) e comparação de preço entre lojas de jogos.
- **Fase 3:** coletor VTEX genérico (Carrefour, Renner, Leroy Merlin e outras) e comparação por código de barras.
- **Fase 4:** Amazon e Shopee pelas APIs de afiliados.
- Depois: executor assistido de compra e aprendizado de quais lojas cancelam pedido.
