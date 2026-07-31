# AgilBot — Agente Bancário Inteligente

Atendimento ao cliente do **Banco Ágil** conduzido por **quatro agentes de IA
especializados**, orquestrados com **LangGraph**. Para o cliente existe **um único
atendente** com várias habilidades: as trocas de contexto entre agentes acontecem dentro
do mesmo turno e são invisíveis.

A interface é **Streamlit** e invoca o grafo **no mesmo processo** — não há camada HTTP
intermediária. O estado de cada atendimento vive no **checkpointer do LangGraph**,
persistido em **PostgreSQL**, que também hospeda os vetores da base de conhecimento
(**pgvector**).

**311 testes, 88% de cobertura, sem nenhuma chamada externa.**

> Decisões de projeto em detalhe, e mais 16 problemas enfrentados durante a implementação,
> estão em [`docs/DECISOES.md`](docs/DECISOES.md).

---

## Sumário

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Funcionalidades](#funcionalidades)
- [Desafios enfrentados e como foram resolvidos](#desafios-enfrentados-e-como-foram-resolvidos)
- [Escolhas técnicas e justificativas](#escolhas-técnicas-e-justificativas)
- [Tutorial de execução e testes](#tutorial-de-execução-e-testes)
- [Rastreabilidade dos requisitos](#rastreabilidade-dos-requisitos)

---

## Visão Geral

O atendimento começa na **Triagem**, que autentica o cliente com CPF e data de nascimento
contra `clientes.csv` e só depois direciona ao contexto adequado.

| Agente | Responsabilidade |
| --- | --- |
| **Triagem** | Saudação, validação de CPF, autenticação (até 3 tentativas) e roteamento. |
| **Crédito** | Consulta de limite e solicitação de aumento, com registro formal e análise por score. |
| **Entrevista de Crédito** | Entrevista financeira que recalcula e persiste o score. |
| **Câmbio** | Cotação de moedas em tempo real (AwesomeAPI). |

Os agentes de crédito e câmbio também consultam uma **base de conhecimento (RAG)** com as
políticas oficiais do banco, quando ela está disponível.

---

## Arquitetura

```
Streamlit (UI)  ──invoke(thread_id)──▶  LangGraph
                                          │
                    ┌─────────────────────┼─────────────────────┐
                 agents/              services/             providers/
            triagem·credito·        auth·credito·        llm (Gemini→Groq)
            entrevista·cambio       entrevista·cambio·   embeddings
                                    knowledge·scoring    vectorstore·checkpointer
                                          │                      │
                                   repositories/ ──▶ CSVs   PostgreSQL + pgvector
                                                          (checkpoints e vetores)
```

As dependências correm em uma direção só — `agents → services → repositories → domain` —
com `core` transversal e `providers` isolando todo o mundo externo. Nenhuma regra de
negócio conhece o LLM, e nenhum agente conhece o formato dos CSVs.

```
app/
  ui/            Streamlit: entrypoint, sessão, tela e ponte com o grafo
  src/
    core/          config, constants, logging, utils        (infra transversal)
    domain/        models, enums, results (Pydantic)        (puro, sem I/O)
    repositories/  acesso aos CSVs, com lock e escrita atômica
    services/      regras de negócio: auth, credito, entrevista, cambio, knowledge, scoring
    providers/     adaptadores externos: llm, embeddings, vectorstore, checkpointer
    rag/           documentos .md, loader e ingestão idempotente
    agents/        os 4 agentes: prompts, ferramentas, handlers e o motor de turno
    orchestration/ estado, grafo e container de injeção de dependência
  data/          CSVs (fonte de dados e artefatos gerados em runtime)
tests/           suíte completa, sem nenhuma chamada externa
infra/           Dockerfile, docker-compose, init do pgvector
```

### O grafo

Um nó por agente e uma **entrada condicional** que retoma sempre o `current_agent` — ou
desvia para o nó `encerrado` quando o atendimento já terminou. As arestas entre agentes
não são escritas à mão: cada nó devolve `Command(goto=...)` e a anotação de retorno
`Command[Literal[...]]` declara os destinos, de onde o LangGraph infere o grafo. Este
diagrama é gerado por `build_graph().get_graph().draw_mermaid()`.

```mermaid
graph TD;
	__start__([__start__]):::first
	triagem(triagem)
	credito(credito)
	entrevista(entrevista)
	cambio(cambio)
	encerrado(encerrado)
	__end__([__end__]):::last
	__start__ -.-> triagem;
	__start__ -.-> credito;
	__start__ -.-> entrevista;
	__start__ -.-> cambio;
	__start__ -.-> encerrado;
	triagem -.-> credito;
	triagem -.-> cambio;
	triagem -.-> __end__;
	credito -.-> entrevista;
	credito -.-> cambio;
	credito -.-> __end__;
	entrevista -.-> credito;
	cambio -.-> credito;
	cambio -.-> __end__;
	encerrado --> __end__;
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

O nó **`encerrado`** é a barreira de encerramento no domínio: responde sem chamar o LLM e
vai direto para `END`. Sem ele, `finished` seria apenas o `disabled` do campo de chat, e
qualquer caminho fora da UI — refresh, outra aba, sessão retomada do Postgres — executaria
operações normalmente sobre um atendimento já encerrado.

### O ciclo de um turno

O princípio que sustenta o desenho é **o estado é a memória; as mensagens são a
conversa**.

1. O motor monta o prompt do agente e anexa um **bloco de contexto renderizado a partir
   do estado** (CPF informado, cliente autenticado, limite, score, tentativas restantes,
   último pedido).
2. O histórico enviado ao LLM é **sanitizado**: só sobrevivem as mensagens do cliente e as
   falas do atendente. `tool_calls` e `ToolMessage` de turnos anteriores são descartados.
3. O modelo escolhe ferramentas; cada uma é executada por um **handler** determinístico
   sobre `services/`, que devolve texto ao modelo **e** efeitos no estado.
4. Se houve **handoff**, o turno termina ali e o texto do agente de origem é descartado —
   quem fala com o cliente é sempre o agente de destino.
5. Se o turno terminaria sem resposta, o motor **força uma redação final** sem ferramentas,
   ainda com os resultados das ferramentas à vista.

Antes de devolver, o motor passa a resposta por duas guardas de runtime: uma acusa menção
a transferência de atendimento, outra acusa números que nenhuma ferramenta produziu. As
duas acendem o painel de diagnóstico em vez de derrubar a resposta.

### Manipulação de dados

| Arquivo | Papel |
| --- | --- |
| `app/data/clientes.csv` | Base de autenticação. O `score` é reescrito após a entrevista e o `limite_atual` após um aumento aprovado. |
| `app/data/score_limite.csv` | Política de crédito por faixa: `score_min, score_max, limite_maximo, taxa_juros_mensal`. |
| `app/data/solicitacoes_aumento_limite.csv` | Gerado em runtime, com **exatamente as 5 colunas do enunciado**. |
| `app/data/historico_score.csv` | Gerado em runtime. Trilha de auditoria das mudanças de score. |
| PostgreSQL | Checkpoints das sessões (LangGraph) e vetores da base de conhecimento (pgvector). |

**Ciclo de vida de uma solicitação.** O pedido é gravado como `pendente` **antes** de
qualquer julgamento; o score é conferido contra a política e a **mesma linha** transiciona
para `aprovado` ou `rejeitado`. Uma reavaliação após a entrevista **não** reescreve o
pedido rejeitado: gera uma linha nova. Mutar `rejeitado → aprovado` apagaria justamente a
história que o arquivo existe para registrar — o avaliador lê o percurso inteiro com um
`cat`. Como o arquivo tem só as 5 colunas exigidas, não há chave primária: a identidade de
um pedido é o **índice da linha devolvido no append**, e o timestamp ISO 8601 carrega
microssegundos.

**Escrita.** Todo CSV é reescrito de forma atômica (temporário no mesmo diretório +
`fsync` + `os.replace`), preservando a permissão original. A serialização entre threads
depende de duas condições fixadas em teste: **um repositório por arquivo** (o lock vive no
objeto) e o **ciclo read-modify-write inteiro sob o lock**. Aprovações usam ainda um
**compare-and-set** sobre o limite. É sincronização **intraprocesso** — basta para o
Streamlit, que roda em processo único, e está declarado como limite do desenho.

### Degradação controlada

As falhas previsíveis são contidas na camada onde ocorrem e viram mensagem ao cliente, não
exceção — inclusive uma exceção inesperada dentro de um handler, capturada pelo motor de
turno.

| Componente | Situação | Comportamento |
| --- | --- | --- |
| LLM | Cota do Gemini esgotada | Fallback automático para o Groq |
| LLM | Nenhum provedor disponível | Mensagem de instabilidade, atendimento segue de pé |
| Sessões | Sem `POSTGRES_URL` ou banco fora | `MemorySaver` (sessão dura o processo) |
| RAG | Sem `GOOGLE_API_KEY` ou sem Postgres | Ferramenta não é registrada no `bind_tools` |
| Câmbio | API fora do ar ou timeout | Informa indisponibilidade; nunca inventa cotação |
| CSVs | Arquivo ausente ou linha corrompida | Erro controlado; linhas válidas seguem utilizáveis |

---

## Funcionalidades

- **Validação de CPF por dígitos verificadores** antes de pedir a data — um erro de
  digitação **não consome tentativa de autenticação**.
- **Autenticação** com CPF normalizado, **datas em formato livre** (`14/05/1990`,
  `14 de maio de 1990`, `14051990`) e checagem de conta ativa. **Até 3 tentativas**, com
  encerramento cordial na terceira — guarda imposta no handler, não no prompt.
- **Autenticação sem oráculo de enumeração**: falha de credencial tem mensagem única (o
  motivo fica no log), e o status da conta só é revelado depois de a data conferir.
- **Consulta de limite** com score, teto da faixa e taxa de juros aplicável.
- **Solicitação de aumento**: pedido registrado como `pendente`, avaliado contra a política
  e transicionado para `aprovado`/`rejeitado`; aprovação persiste o novo limite.
- **Oferta de entrevista** quando o pedido é rejeitado e **reavaliação automática** depois
  que o score muda — decidida no nó, sem depender do modelo.
- **Entrevista de crédito** com os 5 dados do enunciado, validados por Pydantic: um campo
  incompreensível volta ao modelo pelo nome, e só ele é reperguntado.
- **Valores como o cliente fala**: `4200`, `R$ 4.200`, `4.200,50`, `10 mil`, `10k`,
  `1,5 milhão` — conversão determinística no código, nunca no prompt.
- **Vocabulário real**: `aposentado`, `pensionista`, `faço bicos` mapeiam para as três
  categorias do enunciado; `estou sem dívidas`, `zero`, `nunca tive` são negativa.
- **Cadastro tolerante**: um campo secundário malformado gera aviso e default, nunca faz o
  cliente desaparecer da base.
- **Cotação de 10 moedas** (USD, EUR, GBP, ARS, JPY, CHF, CAD, AUD, CNY, BTC), declaradas
  como `Literal` no schema da ferramenta.
- **Base de conhecimento (RAG)** sobre políticas, tarifas, câmbio e segurança/LGPD.
- **Handoffs invisíveis**, com guarda de vazamento em runtime e no CI.
- **Guarda de procedência numérica**: um score, limite ou taxa que o modelo não recebeu de
  uma ferramenta é registrado no log e acende o painel de diagnóstico.
- **Encerramento por ferramenta** a qualquer momento, com barreira **no grafo**.
- **Logs correlacionados por sessão**, com CPF mascarado.

---

## Desafios enfrentados e como foram resolvidos

Os cinco que mais mudaram o desenho. Outros dezesseis estão em
[`docs/DECISOES.md`](docs/DECISOES.md).

| # | Desafio | Solução em uma linha |
| --- | --- | --- |
| [1](#1-a-fórmula-de-score-do-enunciado-não-alcança-01000) | A fórmula do enunciado não alcança 0–1000 — a faixa real é ~0–700 | Faixas e scores semeados calibrados na escala real, com teste de regressão sobre o fluxo-vitrine |
| [2](#2-sanitizar-o-histórico-apagaria-a-memória-entre-turnos) | Tool calls atravessando handoffs quebram o agente de destino — mas sanitizar apaga o CPF entre turnos | Sanitização do histórico **mais** reinjeção de contexto derivado do estado; os dois só funcionam juntos |
| [3](#3-o-lock-existia-a-serialização-não) | `clientes.csv` perdia 30 de 30 atualizações com duas threads, com o lock no lugar | Uma instância por arquivo, read-modify-write inteiro sob o lock, compare-and-set na gravação |
| [4](#4-o-modelo-anunciou-um-score-que-não-existia) | A ferramenta gravou 467 e o cliente leu "seu novo score é 780" | Retorno de ferramenta imperativo com um só número, mais guarda de procedência numérica no motor de turno |
| [5](#5-a-entrevista-respondia-sozinha-a-pergunta-que-não-fez) | A entrevista pulou "possui dívidas?" e preencheu `não` sozinha — 200 pontos de score | Verificação lexical na janela da entrevista; o handler recusa e manda perguntar o que falta |

### 1. A fórmula de score do enunciado não alcança 0–1000

Os pesos fora o termo de renda somam no máximo **500** (formal 300 + 0 dependentes 100 +
sem dívidas 100). O termo `(renda / (despesas + 1)) × 30` só passa a dominar quando a renda
é cerca de **17× as despesas** — quando já satura o teto. Na prática, a faixa alcançável é
~0–700, concentrada entre 450 e 600 para qualquer cliente empregado.

Isso quebraria a demonstração central: semear scores em escala FICO (720, 850) faria a
entrevista **derrubar** o score de todo cliente, e o fluxo `rejeitado → entrevista →
aprovado` nunca fecharia.

**Solução:** as faixas de `score_limite.csv` e os scores semeados foram calibrados contra a
escala real da fórmula, e um **teste de regressão** assevera que o cliente do fluxo-vitrine
sobe de score **e** muda de faixa. Um ajuste distraído em qualquer dos dois CSVs quebra o
teste, não a demo.

### 2. Sanitizar o histórico apagaria a memória entre turnos

Quando a triagem passa o atendimento ao crédito, o nó de destino recebe o mesmo `messages`,
com `tool_calls` de ferramentas que **não estão no `bind_tools`** do destino. Provedores
com function calling são estritos quanto a nomes não declarados e `tool_call_id` órfãos — e
Gemini e Groq divergem nessa validação, então um thread que cai no fallback no meio precisa
produzir mensagens que **ambos** aceitem. A saída é sanitizar o histórico enviado ao LLM,
deixando só a conversa em linguagem natural.

Só que isso cria o problema oposto: o CPF coletado no turno 1 vivia num `ToolMessage`, que
passa a ser descartado. O agente pediria o CPF de novo logo depois de o cliente informar a
data. **Os dois problemas têm que ser resolvidos pelo mesmo desenho, ou um quebra o outro.**

**Solução:** os pares de ferramenta permanecem apenas dentro do turno corrente, onde o loop
ReAct precisa deles, e `agents/contexto.py` reinjeta a cada turno um bloco derivado **do
estado** dentro do system prompt. O estado ganhou `cpf_informado` (pré-autenticação)
separado de `cpf` (pós), e o payload de handoff viaja em `Command(update=...)` em vez das
mensagens. Um teste dedicado fixa o caso "CPF num turno, data no seguinte".

### 3. O lock existia; a serialização, não

Um passe adversarial mostrou que `clientes.csv` perdia atualizações em **30 de 30**
execuções com duas threads. O `threading.Lock` estava lá e estava correto — o que faltava
eram as duas condições para ele valer: o container criava um `ClienteRepository` por
serviço (três locks para o mesmo arquivo, que não serializam nada entre si) e o
`read-modify-write` lia fora do lock.

**Solução:** uma instância compartilhada no container, `CsvRepository.mutate()` com o ciclo
inteiro sob o lock, e **compare-and-set** na gravação do limite aprovado. Depois disso, 0
de 30. Coberto por `tests/test_concorrencia.py` — a classe de cenário que cobertura de
linha não alcança, porque o defeito está no interleaving, não numa linha não executada.

### 4. O modelo anunciou um score que não existia

Numa sessão contra o Gemini real, a ferramenta devolveu `540 -> 467`, gravou 467 no CSV — e
o cliente leu **"seu novo score calculado é 780"**. Questionado depois, o modelo chamou o
score novo de "anterior". É a pior classe de falha em contexto financeiro: número
plausível, errado, com aparência de resposta normal. Nenhum teste com LLM falso pega isso,
porque o defeito está no que o modelo escreve por conta própria.

**Solução em duas camadas.** O retorno da ferramenta virou imperativo e cita um único
número (`use EXATAMENTE 467`), em vez de soltar os dois lados da transição. E o motor de
turno ganhou uma **guarda de procedência numérica**, complemento direto da sanitização:
tudo que o modelo pôde legitimamente ver — system prompt, histórico sanitizado, retorno das
ferramentas *deste* turno — é autorizado; qualquer outro número vai para o log e acende o
painel. É diagnóstico, não bloqueio: derrubar a resposta por um falso positivo sairia mais
caro que registrá-lo.

### 5. A entrevista respondia sozinha a pergunta que não fez

Na mesma sessão, o agente perguntou renda, emprego, despesas e dependentes — pulou "possui
dívidas ativas?" e chamou a ferramenta com `tem_dividas="não"`. O handler validava o
*formato* dos 5 campos, nunca a *procedência* deles. São **200 pontos** de score e uma
mudança de faixa (teto de R$ 1.000 contra R$ 15.000) decididos por um dado que o cliente
nunca deu.

**Solução:** uma verificação lexical na janela da entrevista — delimitada por
`entrevista_inicio`, que exclui de propósito o "sim" que aceitou a oferta. O assunto de
cada um dos 5 campos precisa ter aparecido; se não apareceu, o handler recusa e devolve ao
modelo a instrução de fazer a pergunta que falta.

A primeira versão olhava só para as perguntas do *atendente*, e **a suíte reprovou**: o
cliente que responde tudo de uma vez ("4200, autônomo, 1200 de despesas, sem dependentes e
sem dívidas") é legítimo e teria sido bloqueado. A janela passou a valer para os dois lados
da conversa — o que se barra é o campo que **ninguém** mencionou.

---

## Escolhas técnicas e justificativas

**LangGraph para orquestração.** O problema é, na essência, *fluxo de estado entre
agentes*: cada agente é um nó, o estado compartilhado é cidadão de primeira classe e o
checkpointer dá persistência de sessão sem código extra. O handoff invisível no mesmo turno
cai naturalmente em `Command(goto=...)`. CrewAI e AutoGen abstraem demais o controle de
fluxo por turno; agentes ReAct do LangChain dão menos controle determinístico sobre as
transições.

**Ferramenta (schema) + handler (execução).** O `@tool` declara só o que o LLM enxerga; a
execução é determinística, isolada em `services/` e **testada sem chamar LLM**. O modelo
orquestra linguagem e escolhe ferramentas; ele nunca decide uma regra de negócio.

**Gemini primário → Groq como fallback.** Ambos com free tier, `max_retries=1` no primário
para cair rápido. O modelo que atendeu cada turno aparece no painel de diagnóstico, porque
os modelos Llama são bem mais fracos em roteamento multi-ferramenta e a queda de qualidade
seria invisível.

**`gemini-3.5-flash-lite`, escolhido por sondagem.** A documentação da Google não publica
mais os limites por modelo, e os modelos citados na maioria dos tutoriais já não são
acessíveis a chaves novas — `gemini-2.5-flash-lite` responde **404, "no longer available to
new users"**. A escolha foi feita testando a API com a chave em mãos, uma requisição por
modelo, exercitando uma tool call real. A linha *flash-lite* é a de maior cota diária no
free tier e a mais rápida entre as testadas (0,78 s). A versão é **fixada de propósito**:
`gemini-flash-lite-latest` é um alias móvel e mudaria o comportamento sem alteração no
código. Tabela completa da sondagem em [`docs/DECISOES.md`](docs/DECISOES.md).

**Streamlit invocando o grafo no mesmo processo.** O enunciado pede "uma UI simples para
testes". Uma API HTTP entre a UI e o grafo acrescentaria uma camada de serialização, um
serviço a subir e uma fonte de erro, sem entregar nada ao avaliador. O grafo *é* a API.

**Um único Postgres para sessões e vetores.** Os checkpoints precisam de um banco; o RAG
precisa de um índice vetorial. Postgres com pgvector atende os dois e deixa o compose com
**dois serviços** em vez de quatro.

**Domínio em Pydantic.** A normalização de linguagem natural (`"PJ"` → autônomo,
`"não tenho"` → `False`, `"R$ 4.200"` → `4200.0`) vive em validadores testáveis, **nunca no
prompt** — do contrário o comportamento dependeria do modelo da vez.

**RAG como diferencial, não como requisito.** Não é pedido pelo enunciado. Está
implementado, mas atrás de uma flag que age no `bind_tools`: sem Postgres ou sem chave de
embeddings, o modelo sequer enxerga a ferramenta, em vez de chamá-la e receber vazio.

**Testes sem rede.** A suíte inteira roda com um LLM falso e a API de câmbio mockada.
Nenhuma chave é necessária no CI, e nenhum teste fica intermitente por causa de cota.

---

## Tutorial de execução e testes

Requer **Docker** (opção A) ou **Python 3.12** (opção B). As chaves ficam num `.env`:

```bash
cp .env.example .env      # preencha GOOGLE_API_KEY e/ou GROQ_API_KEY
```

Uma chave já é suficiente. **Sem nenhuma chave a aplicação sobe**, mas o atendente responde
com a mensagem de instabilidade.

### Opção A — Docker (recomendada)

```bash
make docker
# APP_UID=$(id -u) APP_GID=$(id -g) docker compose -f infra/docker-compose.yml up --build
```

Interface em **http://localhost:8501**. `APP_UID`/`APP_GID` fazem os CSVs escritos no bind
mount pertencerem ao seu usuário. Se a porta 5432 estiver ocupada, use
`POSTGRES_PORT=5433 make docker`.

Para indexar a base de conhecimento (opcional, exige `GOOGLE_API_KEY`):

```bash
docker compose -f infra/docker-compose.yml exec app python -m src.rag.ingest
```

### Opção B — Local, com uv

```bash
make install     # instala o Python 3.12 gerenciado e as dependências
make run         # http://localhost:8501
```

Sem `POSTGRES_URL`, as sessões ficam em memória e o RAG fica desligado — o restante do
atendimento funciona normalmente.

### Testes

```bash
make test    # 311 testes com cobertura (88%)
make lint    # ruff
```

A suíte cobre as regras determinísticas (CPF, datas, score, crédito, câmbio mockado,
repositórios) **e a orquestração completa** — grafo, handoffs, memória entre turnos e
sessões — com um LLM falso, **sem nenhuma chamada externa**. O mesmo conjunto roda no CI
(`.github/workflows/ci.yml`).

### Clientes de teste

| Cliente | CPF | Nascimento | Score | Limite | Demonstra |
| --- | --- | --- | --- | --- | --- |
| Ana Souza | 111.444.777-35 | 14/05/1990 | 540 | R$ 5.000 | Fluxo feliz: aumento aprovado |
| **Diego Rocha** | **222.555.888-46** | **19/07/1995** | **380** | **R$ 800** | **Rejeição → entrevista → aprovação** |
| Carla Mendes | 333.666.999-57 | 27/03/1978 | 655 | R$ 15.000 | Faixa de topo |
| Bruno Lima | 123.456.789-09 | 02/11/1985 | 280 | R$ 500 | Score baixo |
| Felipe Nunes | 987.654.321-00 | 08/09/1988 | 520 | R$ 10.000 | Conta bloqueada |

**Roteiro do fluxo-vitrine** (Diego): peça um aumento para **R$ 10.000** → é rejeitado
(teto de R$ 5.000 para score 380) e a entrevista é oferecida → aceite e responda renda
**4.200**, **autônomo**, despesas **1.200**, **0** dependentes, **sem** dívidas → o score
vai a **505**, o pedido é reavaliado sozinho e **aprovado**.

A história faz sentido porque o cadastro de Diego traz `renda_declarada` de R$ 2.600: a
entrevista revela que os dados estavam desatualizados, que é o propósito desse agente. No
painel lateral, o campo `agente atual` percorre `triagem → credito → entrevista → credito`
enquanto o cliente conversa com **um** atendente.

Depois, confira os artefatos no host:

```bash
cat app/data/solicitacoes_aumento_limite.csv   # rejeitado e, em nova linha, aprovado
cat app/data/historico_score.csv               # 380 -> 505, entre os dois pedidos
grep Diego app/data/clientes.csv               # score 505 e limite 10000
```

> **Cota de free tier.** Um atendimento completo custa cerca de **21 requisições ao LLM**
> (1,8 por turno). O limite que aperta primeiro é o de **requisições por minuto**. Ao
> esgotar, a aplicação cai para o Groq; se ambos atingirem o limite, o atendente responde
> com a mensagem de instabilidade — erro tratado, sem quebrar a aplicação.

---

## Rastreabilidade dos requisitos

| Requisito do enunciado | Onde está | Teste |
| --- | --- | --- |
| Saudação, coleta de CPF e data | `agents/triagem.py`, `agents/prompts.py` | `test_graph.py::TestAutenticacao` |
| Autenticação contra `clientes.csv` | `services/auth_service.py` | `test_auth.py::TestAuthService` |
| Até 3 tentativas, encerramento cordial | `agents/triagem.py::_handler_autenticar` | `test_graph.py::test_tres_falhas_encerram_com_cordialidade` |
| Roteamento só após autenticar | `agents/triagem.py::_somente_autenticado` | `test_graph.py::test_direcionamento_bloqueado_sem_autenticacao` |
| Consulta de limite | `services/credito_service.py::consultar_limite` | `test_credito.py::TestConsultaDeLimite` |
| Pedido formal em CSV (5 colunas) | `repositories/solicitacoes.py`, `domain/models.py` | `test_credito.py::test_csv_tem_exatamente_as_cinco_colunas_do_enunciado` |
| Checagem contra `score_limite.csv` | `services/credito_service.py::solicitar_aumento` | `test_credito.py::TestSolicitacaoDeAumento` |
| Oferta de entrevista ao rejeitar | `agents/credito.py::_handler_solicitar_aumento` | `test_graph.py::TestFluxoVitrineNoGrafo` |
| Entrevista com os 5 dados | `agents/entrevista.py`, `domain/models.py::DadosEntrevista` | `test_credito.py::TestEntrevista` |
| Fórmula ponderada, score 0–1000 | `services/scoring.py` | `test_score.py::TestFormula`, `TestClamp` |
| Atualização do score em `clientes.csv` | `services/entrevista_service.py` | `test_credito.py::test_recalcula_e_persiste_o_score` |
| Trilha de auditoria do score (extra) | `repositories/historico_score.py` | `test_credito.py::TestHistoricoDeScore` |
| Retorno ao crédito para nova análise | `agents/credito.py::_reavaliacao_automatica` | `test_graph.py::test_rejeitado_entrevista_reavaliacao_aprovada` |
| Cotação por API externa | `services/cambio_service.py` | `test_cambio.py` |
| Ferramenta de encerramento | `agents/common.py::handler_encerrar` | `test_graph.py::test_encerramento_marca_a_sessao` |
| Nenhum agente fora do escopo | ferramentas por agente; RAG fora da triagem | `test_conhecimento.py::TestFerramentaCondicional` |
| Redirecionamentos implícitos | `agents/base.py` (handoff silencia a origem) | `test_motor.py::TestHandoff`, `test_graph.py::test_cliente_nunca_ve_mencao_a_transferencia` |
| Uso de ferramentas para CSV, API e cálculo | `repositories/`, `services/` | suíte inteira |
| Tratamento de erros e exceções | `RepositoryError`, matriz de degradação | `test_motor.py::TestRedesDeSeguranca`, `test_ui.py::TestErros` |
| Integridade sob escrita concorrente | `CsvRepository.mutate`, `atualizar_limite_se` | `test_concorrencia.py` |
| Procedência de números e respostas | `agents/base.py`, `agents/entrevista.py` | `test_procedencia.py` |
| Encerramento efetivo do atendimento | `orchestration/graph.py` (nó `encerrado`) | `test_graph.py::TestCicloDeVida` |
| Registro de erro para análise posterior | `core/logging.py` (correlação por sessão) | — |
| UI simples para testes | `app/ui/` | `test_ui.py` |
