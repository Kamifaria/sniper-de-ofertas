# Sniper de Ofertas — Fase 1

Monitor de preços em tempo real para Windows. Ele vigia o Mercado Livre pela API oficial, detecta preço fora do normal (erro de vírgula, item de graça, queda brusca) e avisa no painel, com notificação do Windows e no Telegram.

## Como rodar (Windows)

1. Instale o **Python 3.11+** em python.org e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez, ele cria o ambiente e instala as dependências (1–2 min).
   - Ele copia `config.exemplo.toml` para `config.toml`.
3. O painel abre em uma janela própria. Vem com o **modo demonstração** ligado: uma loja simulada que gera "bugs" de vez em quando, para você ver tudo funcionando.

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
4. Em `[demo]`, mude para `ativo = false` e reinicie.

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

## Como a nota (0–100) é calculada

| sinal | pontos |
|---|---|
| preço ≤ R$ 1,00 | 100 → **GRÁTIS** |
| queda vs mediana de 30 dias (85% / 70% / 55% / 40% / 25%) | 75 / 62 / 50 / 40 / 15 |
| queda brusca vs última coleta (≥50% / ≥30%) | +20 / +10 |
| abaixo do piso da regra | +20 a +30 |
| "de/por" anunciado pela loja (≥80% / 60% / 45%) | +25 / +15 / +8 |
| frete grátis (quando já há queda forte) | +5 |

Níveis: **CRÍTICO** ≥ 90 · **ALTO** ≥ 70 · **MÉDIO** ≥ 50. Item sem histórico e sem piso fica limitado a 75, porque ainda não dá para confiar.

## Estrutura

```
run.py                 inicia motor + API + janela
auth_ml.py             autorização OAuth do Mercado Livre (uma vez)
sniper/engine.py       agenda as regras, avalia e dispara alertas
sniper/detector.py     cálculo da nota
sniper/collectors/     um coletor por loja (mercadolivre, demo)
sniper/db.py           SQLite: itens, histórico, alertas
sniper/notify.py       Telegram + notificação do Windows
sniper/server.py       API local (127.0.0.1) + transmissão ao vivo
sniper/web/index.html  painel
tests/                 python -m unittest discover tests
```

## Próximas fases

- **Fase 2:** executor assistido (abre no seu Chrome logado, põe no carrinho, aplica cupom e para no botão de pagar) + travas de valor e limite por dia.
- **Fase 3:** Shopee (API de afiliados), monitor de grupos do Telegram e Pelando/Promobit, motor de cupons e cashback.
- **Fase 4:** arbitragem (lucro de revenda estimado) e aprendizado de quais lojas cancelam pedido.
