# Dose Certa API

API FastAPI do Dose Certa (agenda de remedios, leitura de bulas com IA, Jardim da Saude e recados da familia).
Banco relacional em 3FN (SQLite por padrao, Postgres via `DATABASE_URL`). Dados de demonstracao sao criados sozinhos
na primeira execucao (Dona Maria, id 1, e Ana, a filha, id 2).

## Rodar no computador

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra http://127.0.0.1:8000/docs para testar todos os endpoints.

## Publicar no Render (gratis)

1. Suba esta pasta para um repositorio no GitHub (o `.gitignore` ja evita subir `.env` e o banco).
2. Em render.com: **New > Blueprint** (usa o `render.yaml`) ou **New > Web Service** com:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Em **Environment**, adicione `GEMINI_API_KEY` (opcional; sem ela a leitura de bula devolve uma explicacao de exemplo).
4. Quando o deploy terminar, abra `https://SEU-SERVICO.onrender.com/docs`.

Cuidados: no plano gratis a API "dorme" e a primeira chamada demora cerca de 1 minuto (abra o `/docs` antes de gravar o video).
O SQLite e apagado a cada deploy, mas o seed recria os dados de demonstracao sozinho.

## Ligar o app (Snack)

No topo do `App.js`:

```js
const BASE_URL = 'https://SEU-SERVICO.onrender.com/api';
const USE_MOCK = false;
```

O app ja chama `POST /doses/{id}/confirmar` com `{ "horarioConfirmacao": "HH:MM" }`. Para a integracao completa, o app tambem deve chamar
`GET /idosos/1/agenda` ao abrir (os ids das doses vem dessa resposta), `GET /gamificacao/1` na aba Jardim e `POST /documentos/ler` na aba Ler.

## Endpoints (prefixo /api)

| Metodo e caminho | Para que serve |
| --- | --- |
| GET /saude | Verifica se a API esta no ar |
| POST /auth/entrar | Entrada so com apelido; devolve o id do usuario |
| POST /consentimento | Registra o consentimento LGPD |
| GET /idosos/{id}/agenda | Remedios de hoje, com status (tomada, atrasada, pendente) |
| POST /doses/{id}/confirmar | Botao TOMEI (idempotente; devolve pontos e conquistas novas) |
| POST /prescricoes | Cadastra remedio na agenda |
| PUT /prescricoes/{id}/pausar | Pausa um remedio (mantem o historico) |
| GET /idosos/{id}/adesao | Resumo para o painel do cuidador |
| POST /documentos/ler | Foto da bula/receita (multipart: id_idoso, tipo, imagem); explicacao simples |
| GET /gamificacao/{id} | Pontos, estagio do jardim, sequencia, semana e conquistas |
| POST /vinculos | Idoso autoriza um cuidador |
| PUT /vinculos/{id}/revogar | Pausa do compartilhamento (LGPD) |
| POST /mensagens | Recado de carinho (ate 140 caracteres; exige vinculo ativo) |
| GET /mensagens/{id} | Recados recebidos |
| POST /mensagens/{id}/lida | Marca como lido |
| GET /usuarios/{id}/dados | Direito de acesso (LGPD) |
| DELETE /usuarios/{id}/dados | Direito de exclusao (LGPD) |

## Regras do jardim

Dose no horario (ate 60 min de tolerancia): +10. Dose com atraso: +6. Bula lida: +5. Conquistas somam seus pontos.
Os pontos nunca diminuem. Estagios: Semente 0, Broto 30, Planta 80, Flor 160, Jardim Florido 300.

## Limitacoes (MVP)

- Sem login com senha: o app entra so com apelido e os endpoints do cuidador nao sao autenticados. Para producao, adicione JWT.
- A foto da bula nunca e guardada; so o resumo.
- Uma dose por dia por remedio (horario unico).
