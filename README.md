# AgilBot: Agente Bancário Inteligente

Atendimento do **Banco Ágil** conduzido por **quatro agentes de IA especializados**,
orquestrados com **LangGraph**. Para o cliente existe **um único atendente**: as trocas de
contexto acontecem dentro do mesmo turno e são invisíveis.

A interface é **Streamlit** e invoca o grafo **no mesmo processo**. O estado de cada
atendimento vive no checkpointer do LangGraph, em **PostgreSQL**, que também hospeda os
vetores da base de conhecimento (**pgvector**).

**328 testes · 88% de cobertura · nenhuma chamada de rede na suíte.**

> Decisões em detalhe e mais dezesseis problemas enfrentados:
> [`docs/DECISOES.md`](docs/DECISOES.md).

---

## Sumário

- [Visão Geral](#visão-geral) · [Arquitetura](#arquitetura) · [Funcionalidades](#funcionalidades)
- [Desafios enfrentados e como foram resolvidos](#desafios-enfrentados-e-como-foram-resolvidos)
- [Escolhas técnicas e justificativas](#escolhas-técnicas-e-justificativas)
- [Tutorial de execução e testes](#tutorial-de-execução-e-testes) · [Rastreabilidade dos requisitos](#rastreabilidade-dos-requisitos)

---

## Visão Geral

O atendimento começa na **Triagem**, que autentica o cliente contra `clientes.csv` e só
depois direciona ao contexto adequado.

| Agente | Responsabilidade |
| --- | --- |
| **Triagem** | Saudação, validação de CPF, autenticação (até 3 tentativas) e roteamento. |
| **Crédito** | Consulta de limite e solicitação de aumento, com registro formal e análise por score. |
| **Entrevista de Crédito** | Entrevista financeira que recalcula e persiste o score. |
| **Câmbio** | Cotação de moedas em tempo real (AwesomeAPI). |

Crédito e câmbio também consultam uma **base de conhecimento (RAG)** com as políticas do
banco, quando disponível.

**A ideia central.** O sistema separa duas responsabilidades que nunca se misturam: **o LLM
cuida de linguagem** (interpreta a intenção e escolhe a ferramenta) e **o código cuida de
regra** (teto por faixa, 3 tentativas, cálculo de score, gravação). A costura é o par
`@tool` + handler: o `@tool` declara só o formulário que o modelo enxerga e tem corpo
vazio; quem executa é um handler Python que devolve o texto ao modelo **e** os efeitos no
estado. Disso decorre a propriedade que mais importa: **o modelo nunca decide se um aumento
é aprovado**. Ele pede a operação; a política decide.

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
```

Dependências em uma direção só (`agents → services → repositories → domain`), com `core`
transversal e `providers` isolando o mundo externo. Nenhuma regra de negócio conhece o LLM;
nenhum agente conhece o formato dos CSVs.

```
app/
  ui/            Streamlit: entrypoint, sessão, tela e ponte com o grafo
  src/
    core/          config, constants, logging, utils        (infra transversal)
    domain/        models, enums, results (Pydantic)        (puro, sem I/O)
    repositories/  acesso aos CSVs, com lock e escrita atômica
    services/      auth, credito, entrevista, cambio, knowledge, scoring
    providers/     llm, embeddings, vectorstore, checkpointer
    rag/           documentos .md, loader e ingestão idempotente
    agents/        os 4 agentes: prompts, ferramentas, handlers e o motor de turno
    orchestration/ estado, grafo e container de injeção de dependência
  data/          CSVs (fonte de dados e artefatos gerados em runtime)
tests/  infra/   suíte sem chamadas externas · Dockerfile, compose, entrypoint, init do pgvector
```

### O grafo

Um nó por agente, mais o nó `encerrado`. **Não há `add_edge` entre agentes:** cada nó
devolve `Command(goto=..., update=...)` e a anotação de retorno declara os destinos, de onde
o LangGraph infere o grafo. O diagrama abaixo é gerado por
`build_graph().get_graph().draw_mermaid()`.

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

A entrada é condicional e retoma o `current_agent` restaurado do checkpointer. Sem isso,
toda mensagem recomeçaria na triagem.

O nó **`encerrado`** é a barreira de encerramento no domínio: responde sem chamar o LLM.
Sem ele, `finished` seria apenas o `disabled` do campo de chat, e qualquer caminho fora da
UI (refresh, outra aba, sessão retomada do Postgres) executaria operações sobre um
atendimento já encerrado.

### O ciclo de um turno

Um **turno** é o intervalo entre a mensagem do cliente e a resposta. Os quatro agentes
compartilham o mesmo motor (`agents/base.py::run_agent_turn`); muda só o prompt, as
ferramentas e os handlers. O princípio: **o estado é a memória; as mensagens são a
conversa.**

1. O motor monta o prompt e anexa um **bloco de contexto derivado do estado** (CPF
   informado, autenticação, limite, score, tentativas restantes, último pedido).
2. O histórico enviado ao LLM é **sanitizado**: só sobrevivem as falas do cliente e do
   atendente. `tool_calls` e `ToolMessage` de turnos anteriores são descartados.
3. O modelo escolhe ferramentas; cada uma executa um **handler** determinístico sobre
   `services/`, que devolve texto ao modelo **e** efeitos no estado.
4. Havendo **handoff**, o texto do agente de origem é descartado: quem fala é o destino.
5. Se o turno terminaria sem resposta, o motor **força uma redação final** sem ferramentas,
   ainda com os resultados à vista.
6. Duas **guardas de runtime** conferem a saída: uma acusa menção a transferência de
   atendimento, outra acusa números que nenhuma ferramenta produziu. Acendem o painel de
   diagnóstico em vez de derrubar a resposta.

**Um turno concreto.** Cliente autenticado digita *"quero aumentar meu limite para 10 mil"*:

```
prompt do agente + "Diego · autenticado · limite R$ 800 · score 380"
histórico enviado ao LLM: só as falas, nenhuma tool call de turnos anteriores
  → o modelo chama  atender_credito           handoff; o texto da triagem é descartado
  → o nó `credito` assume no MESMO turno
  → o modelo chama  solicitar_aumento(10000)  grava `pendente`, avalia contra a faixa
                                              301–450 (teto R$ 5.000), vira `rejeitado`
  → o modelo redige a recusa e oferece a entrevista
```

O cliente enviou **uma** mensagem e recebeu **uma** resposta, embora dois agentes tenham
trabalhado.

### Manipulação de dados

| Arquivo | Papel |
| --- | --- |
| `clientes.csv` | Base de autenticação. `score` reescrito após a entrevista; `limite_atual` após aumento aprovado. |
| `score_limite.csv` | Política por faixa: `score_min, score_max, limite_maximo, taxa_juros_mensal`. |
| `solicitacoes_aumento_limite.csv` | Runtime, com **exatamente as 5 colunas do enunciado**. |
| `historico_score.csv` | Runtime. Trilha de auditoria das mudanças de score. |
| PostgreSQL | Checkpoints das sessões e vetores do RAG. |

**Ciclo de vida de uma solicitação.** O pedido nasce `pendente` **antes** de qualquer
julgamento. Duas transições, deliberadamente diferentes: na avaliação inicial a **mesma
linha** vira `aprovado`/`rejeitado`; na reavaliação pós-entrevista é criada uma **linha
nova**. Mutar `rejeitado → aprovado` apagaria a história que o arquivo existe para
registrar. Sem chave primária (são só 5 colunas), a identidade é o índice devolvido no
`append`, com timestamp ISO 8601 em microssegundos.

**Escrita segura.** Todo CSV é reescrito de forma atômica: temporário no mesmo diretório,
`fsync`, `os.replace`, preservando a permissão. `open("w")` truncaria o arquivo antes de
gravar. A serialização entre threads depende de duas condições fixadas em teste: **um
repositório por arquivo** (o lock vive no objeto) e o **ciclo read-modify-write inteiro sob
o lock**. Aprovações usam ainda **compare-and-set** sobre o limite.

> **Limite declarado:** é sincronização **intraprocesso**. Basta para o Streamlit, que roda
> em processo único; múltiplos workers exigiriam sair do CSV para um banco relacional.

### Degradação controlada

Falhas previsíveis são contidas na camada onde ocorrem e viram mensagem ao cliente, não
exceção, inclusive uma exceção inesperada dentro de um handler, capturada pelo motor.

| Componente | Situação | Comportamento |
| --- | --- | --- |
| LLM | Cota do Gemini esgotada | Fallback automático para o Groq |
| LLM | Nenhum provedor disponível | Mensagem de instabilidade; conversa de pé |
| LLM | Falha **depois** de a ferramenta gravar | Cliente recebe o resultado já apurado, não "tente novamente" |
| Sessões | Sem `POSTGRES_URL` ou banco fora | `MemorySaver` |
| RAG | Sem chave ou sem Postgres | Ferramenta não é registrada no `bind_tools` |
| RAG | Indexação do start falha | Container sobe; agente diz que não tem a informação |
| Câmbio | API fora ou timeout | Informa; nunca inventa cotação |
| CSVs | Arquivo ausente ou linha corrompida | Erro controlado; linhas válidas seguem usáveis |

---

## Funcionalidades

- **Autenticação** com CPF validado por dígitos verificadores **antes** de pedir a data
  (erro de digitação não consome tentativa), datas em formato livre (`14/05/1990`,
  `14 de maio de 1990`, `14051990`) e **até 3 tentativas**, com guarda no handler.
- **Sem oráculo de enumeração**: mensagem única para falha de credencial, status da conta
  revelado só após a data conferir, CPF mascarado nos logs.
- **Consulta de limite** com score, teto da faixa e taxa de juros.
- **Solicitação de aumento** registrada como `pendente`, avaliada contra a política e
  transicionada; aprovação persiste o novo limite.
- **Oferta de entrevista** ao rejeitar e **reavaliação automática** quando o score sobe,
  decidida no nó, sem depender do modelo.
- **Entrevista** com os 5 dados validados por Pydantic: campo incompreensível volta pelo
  nome, e só ele é reperguntado.
- **Linguagem do cliente**, convertida no código e nunca no prompt: `10 mil`, `10k`,
  `1,5 milhão`, `aposentado`, `faço bicos`, `nunca tive`.
- **Cadastro tolerante**: campo secundário malformado gera aviso e default, nunca faz o
  cliente desaparecer da base.
- **Cotação de 10 moedas** declaradas como `Literal` no schema da ferramenta.
- **Handoffs invisíveis** e **guarda de procedência numérica**, ambas verificadas em runtime
  e no CI.
- **Encerramento por ferramenta** com barreira no grafo. **Logs correlacionados por sessão.**

---

## Desafios enfrentados e como foram resolvidos

Os cinco que mais mudaram o desenho. Outros dezesseis em [`docs/DECISOES.md`](docs/DECISOES.md).

### 1. A fórmula de score do enunciado não alcança 0–1000

Os pesos fixos somam no máximo **500** (formal 300 + 0 dependentes 100 + sem dívidas 100). O
resto vem de `(renda / (despesas + 1)) × 30`, e a conta é dura: **601** exige renda ≈ 3,4× as
despesas; **801** exige 10×; **1000** exige 16,7×. A faixa exercida é ~0–700.

A consequência é sobre a **calibração dos dados**: se as faixas e os scores semeados não
viverem nessa escala, a faixa de topo vira letra morta e um cliente com score alto sai
**rebaixado** de uma entrevista honesta.

**Solução.** O enunciado especifica fórmula e pesos, mas **não fornece o conteúdo de
`score_limite.csv` nem de `clientes.csv`**: as duas tabelas tinham de ser escritas do zero.
Escrevi-as contra a escala real: a faixa de topo começa em **601**, não em 801. Os pesos
ficaram idênticos aos sugeridos, porque eles vêm com números concretos que o avaliador usa para
conferir o cálculo; a tabela de faixas não vem. Mexi onde eu era o autor.

Dois testes protegem isso: um assevera que **nenhuma faixa é inalcançável**, outro que o
cliente do fluxo-vitrine sobe de score **e** muda de faixa.

### 2. Sanitizar o histórico apagaria a memória entre turnos

No handoff, o nó de destino recebe o mesmo `messages`, com `tool_calls` de ferramentas que
**não estão no seu `bind_tools`**. Provedores com function calling são estritos quanto a
nomes não declarados e `tool_call_id` órfãos, e Gemini e Groq divergem, então um thread que
caia no fallback precisa produzir mensagens que **ambos** aceitem. A saída é sanitizar.

Só que isso cria o problema oposto: o CPF coletado no turno 1 vivia num `ToolMessage` e
some. **Os dois têm de ser resolvidos pelo mesmo desenho, ou um quebra o outro.**

**Solução.** Os pares de ferramenta permanecem apenas dentro do turno corrente, onde o loop
ReAct precisa deles, e `agents/contexto.py` reinjeta a cada turno um bloco derivado **do
estado** no system prompt. O estado ganhou `cpf_informado` separado de `cpf`, e o payload de
handoff viaja em `Command(update=...)`. Um teste fixa o caso "CPF num turno, data no
seguinte".

### 3. O lock existia; a serialização, não

Um passe adversarial mostrou `clientes.csv` perdendo atualizações em **30 de 30** execuções
com duas threads. O `threading.Lock` estava correto; faltavam as duas condições: o
container criava um `ClienteRepository` por serviço (três locks para o mesmo arquivo) e o
read-modify-write lia fora do lock.

**Solução.** Instância compartilhada, `CsvRepository.mutate()` com o ciclo inteiro sob o
lock, e compare-and-set na gravação. Depois disso, **0 de 30**. Coberto por
`tests/test_concorrencia.py`, a classe de cenário que cobertura de linha não alcança,
porque o defeito está no interleaving.

### 4. O modelo anunciou um score que não existia

Numa sessão contra o Gemini real, a ferramenta devolveu `540 → 467`, gravou 467, e o
cliente leu **"seu novo score calculado é 780"**. Questionado depois, o modelo chamou o score
novo de "anterior". É a pior classe de falha em contexto financeiro: número plausível,
errado, com aparência de resposta normal. Nenhum teste com LLM falso pega isso.

**Solução em duas camadas.** O retorno da ferramenta virou imperativo e cita um único número
(`use EXATAMENTE 467`). E o motor ganhou uma **guarda de procedência numérica**, complemento
da sanitização: tudo que o modelo pôde legitimamente ver (system prompt, histórico
sanitizado, ferramentas *deste* turno) é autorizado; o resto vai para o log e acende o
painel. Diagnóstico, não bloqueio: derrubar a resposta por um falso positivo sairia mais
caro.

### 5. A entrevista respondia sozinha a pergunta que não fez

O agente perguntou renda, emprego, despesas e dependentes, pulou "possui dívidas ativas?" e
chamou a ferramenta com `tem_dividas="não"`. São **200 pontos** de score e uma mudança de
faixa (teto de R$ 1.000 contra R$ 15.000) decididos por um dado que o cliente nunca deu.

**Solução.** Verificação lexical na janela da entrevista, delimitada por `entrevista_inicio`,
que exclui de propósito o "sim" que aceitou a oferta. Se o assunto de um campo não apareceu,
o handler recusa e manda perguntar.

A primeira versão olhava só para as perguntas do *atendente*, e **a suíte reprovou**: o
cliente que responde tudo de uma vez é legítimo e teria sido bloqueado. Corrigi a regra, não
o teste.

---

## Escolhas técnicas e justificativas

**LangGraph para orquestração.** O problema é *fluxo de estado entre agentes*: cada agente é
um nó, o estado é cidadão de primeira classe, o checkpointer dá sessão sem código extra, e o
handoff invisível no mesmo turno cai em `Command(goto=...)`. Por que não os outros quatro
frameworks sugeridos:

| Alternativa | Por que não |
| --- | --- |
| **CrewAI** | Modela times com papéis e delegação; abstrai o controle de fluxo por turno, que aqui precisa ser explícito. |
| **LangChain** (ReAct) | Dá o loop ferramenta↔modelo, mas não o estado tipado nem transições determinísticas; eu construiria por fora o que o `StateGraph` já dá. |
| **LlamaIndex** | Excelente em recuperação, que aqui é acessória (o RAG). Não é orquestrador de agentes com estado. |
| **Google ADK** | Encaixaria com o Gemini, mas amarraria ao ecossistema Google, e o desenho prevê fallback para o Groq, então a orquestração precisa ser neutra quanto ao provedor. |

**Ferramenta (schema) + handler (execução).** O `@tool` declara só o que o LLM enxerga; a
execução é determinística, isolada em `services/` e testada sem LLM. Consequência:
**acrescentar um quinto agente é criar um módulo no mesmo formato e registrar um nó**. O
motor não muda.

**Gemini primário → Groq como fallback**, ambos com free tier. `MAX_RETRIES_LLM = 3` absorve
429 esporádico e soluço de rede; cota esgotada não é caso de retry, porque o 429 do Gemini pede ~57s
de espera, e prender o cliente por isso é pior que degradar. Para cota, quem resolve é o segundo
provedor. O modelo que atendeu cada turno aparece no painel, porque os modelos Llama são mais
fracos em roteamento multi-ferramenta e a queda seria invisível.

**`gemini-3.5-flash-lite`, escolhido por sondagem.** A Google não publica mais os limites por
modelo, e `gemini-2.5-flash-lite` responde **404, "no longer available to new users"**.
Testei a API com a chave em mãos, uma requisição por modelo, exercitando uma tool call real.
A versão é fixada de propósito: `gemini-flash-lite-latest` é alias móvel. Tabela da sondagem
em [`docs/DECISOES.md`](docs/DECISOES.md).

**Streamlit invocando o grafo no mesmo processo.** O enunciado pede "uma UI simples para
testes". Uma API HTTP acrescentaria serialização, um serviço a subir e uma fonte de erro sem
entregar nada ao avaliador. O grafo *é* a interface e o checkpointer *é* a sessão.

**Um único Postgres para sessões e vetores**, deixando o compose com dois serviços em vez de
quatro. **Domínio em Pydantic**, com a normalização de linguagem natural em validadores
testáveis, **nunca no prompt**. **Testes sem rede**: nenhuma chave é necessária no CI e
nenhum teste fica intermitente por cota.

---

## Tutorial de execução e testes

Requer **Docker** (opção A) ou **Python 3.12** (opção B).

```bash
cp .env.example .env      # preencha GOOGLE_API_KEY e/ou GROQ_API_KEY
```

Uma chave já basta. **Sem nenhuma chave a aplicação sobe**, mas o atendente responde com a
mensagem de instabilidade.

```bash
# A) Docker (recomendada). Interface em http://localhost:8501
make docker
# APP_UID/APP_GID fazem os CSVs do bind mount pertencerem ao seu usuário.
# Porta 5432 ocupada? POSTGRES_PORT=5433 make docker
# A base de conhecimento é indexada no start do container (exige GOOGLE_API_KEY).
# Para reindexar à força depois de editar os .md:
docker compose -f infra/docker-compose.yml exec app python -m src.rag.ingest --forcar

# B) Local, com uv. Sem POSTGRES_URL: sessões em memória e RAG desligado.
make install && make run

# Testes
make test    # 328 testes com cobertura (88%)
make lint    # ruff
```

A suíte cobre as regras determinísticas **e a orquestração completa** (grafo, handoffs,
memória entre turnos e sessões) com um LLM falso, **sem nenhuma chamada externa**. O mesmo
conjunto roda no CI.

### Clientes de teste

| Cliente | CPF | Nascimento | Score | Limite | Demonstra |
| --- | --- | --- | --- | --- | --- |
| Ana Souza | 111.444.777-35 | 14/05/1990 | 540 | R$ 5.000 | Fluxo feliz: aumento aprovado |
| **Diego Rocha** | **222.555.888-46** | **19/07/1995** | **380** | **R$ 800** | **Rejeição → entrevista → aprovação** |
| Carla Mendes | 333.666.999-57 | 27/03/1978 | 655 | R$ 15.000 | Faixa de topo |
| Bruno Lima | 123.456.789-09 | 02/11/1985 | 280 | R$ 500 | Score baixo |
| Felipe Nunes | 987.654.321-00 | 08/09/1988 | 520 | R$ 10.000 | Conta bloqueada |

**Fluxo-vitrine (Diego):** peça aumento para **R$ 10.000** → rejeitado (teto de R$ 5.000
para score 380), entrevista oferecida → responda **4.200**, **autônomo**, **1.200**, **0**,
**não** → score vai a **505**, o pedido é reavaliado sozinho e **aprovado**. O cadastro do
Diego traz `renda_declarada` de R$ 2.600: a entrevista revela dados desatualizados, que é o
propósito desse agente. No painel lateral, `agente atual` percorre
`triagem → credito → entrevista → credito`. Os artefatos ficam em `app/data/`.

> **Cota do free tier.** Um atendimento custa ~21 requisições (1,8 por turno) e o limite que
> aperta primeiro é o de **minuto**. Ao esgotar, cai para o Groq; se ambos atingirem o
> limite, o atendente responde com a mensagem de instabilidade.

---

## Rastreabilidade dos requisitos

| Requisito do enunciado | Onde está | Teste |
| --- | --- | --- |
| Saudação, coleta de CPF e data | `agents/triagem.py` | `test_graph.py::TestAutenticacao` |
| Autenticação contra `clientes.csv` | `services/auth_service.py` | `test_auth.py::TestAuthService` |
| Até 3 tentativas, encerramento cordial | `agents/triagem.py::_handler_autenticar` | `test_graph.py::test_tres_falhas_encerram_com_cordialidade` |
| Roteamento só após autenticar | `agents/triagem.py::_somente_autenticado` | `test_graph.py::test_direcionamento_bloqueado_sem_autenticacao` |
| Consulta de limite | `services/credito_service.py::consultar_limite` | `test_credito.py::TestConsultaDeLimite` |
| Pedido formal em CSV (5 colunas) | `repositories/solicitacoes.py` | `test_credito.py::test_csv_tem_exatamente_as_cinco_colunas_do_enunciado` |
| Checagem contra `score_limite.csv` | `services/credito_service.py::solicitar_aumento` | `test_credito.py::TestSolicitacaoDeAumento` |
| Oferta de entrevista ao rejeitar | `agents/credito.py::_handler_solicitar_aumento` | `test_graph.py::TestFluxoVitrineNoGrafo` |
| Entrevista com os 5 dados | `agents/entrevista.py`, `domain/models.py` | `test_credito.py::TestEntrevista` |
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
| Registro de erro para análise posterior | `core/logging.py` (correlação por sessão) | n/a |
| UI simples para testes | `app/ui/` | `test_ui.py` |
