# Decisões e problemas enfrentados

Complemento do [README](../README.md), que traz os cinco desafios que mais mudaram o
desenho. Aqui estão os outros dezesseis, mais o detalhe de duas decisões que no README
aparecem resumidas.

---

## Problemas encontrados durante a implementação

### O estado inicial sobrescrevia o checkpoint a cada turno

A UI enviava `{**estado_inicial(), "messages": [...]}` em toda invocação. O checkpointer
restaurava a sessão corretamente e a entrada logo em seguida **zerava tudo** — o CPF do
turno anterior inclusive. Os testes do grafo não pegavam isso, porque ali o estado é
encadeado à mão.

**Solução:** enviar apenas o delta (`{"messages": [...]}`) e deixar o LangGraph fundi-lo ao
estado restaurado. Coberto por um teste que atravessa dois turnos pela camada de sessão.

### `os.replace` falharia no bind mount do Docker

A escrita atômica criava o arquivo temporário em `/tmp`, que no container vive no
overlayfs, enquanto `app/data` é um bind mount — outro filesystem. `os.replace` entre
filesystems levanta `OSError: [Errno 18] Invalid cross-device link`. Toda escrita de CSV
falharia **apenas dentro do Docker**, passando limpo em todos os testes locais.

**Solução:** o temporário nasce no **mesmo diretório do alvo**, com `fsync` antes da troca
e retry curto para a semântica de lock do Docker Desktop no Windows. Um teste fixa o
invariante do diretório.

### Propriedade e permissão dos arquivos no host

Rodar o container como root deixaria os CSVs pertencendo ao root na máquina do avaliador;
fixar um UID arbitrário quebraria em máquinas com UID diferente. Além disso, `mkstemp` cria
arquivos com permissão `0600`, então a primeira escrita mudava silenciosamente a permissão
do CSV.

**Solução:** o UID/GID de quem sobe o compose é repassado como build arg, e a escrita
atômica preserva a permissão original. Detalhe que só aparece na prática: **`UID` é
readonly no bash**, então a variável se chama `APP_UID` — `UID=$(id -u) docker compose ...`
falharia na linha de comando.

### Reavaliação pós-entrevista não podia depender do modelo

Se o retorno ao crédito dependesse de o LLM lembrar de chamar `solicitar_aumento` de novo,
o desfecho do fluxo principal seria não-determinístico.

**Solução:** a reavaliação acontece **no nó**, antes da chamada ao LLM, com gatilho
explícito: o último pedido está `rejeitado` **e** o score do cliente **subiu** em relação ao
`score_avaliado` guardado no estado. A condição é "melhorou", não "mudou" — com `!=`, uma
entrevista que derruba o score faria o sistema registrar, por conta própria, um pedido de
aumento que o cliente nunca fez, e ainda rejeitá-lo. Pedido sem origem numa intenção do
cliente é problema de conformidade na trilha formal.

### O modelo padrão tinha sido aposentado — e a resposta não era mais texto

O primeiro spike contra a API real falhou inteiro: `gemini-2.5-flash-lite` responde **404,
"no longer available to new users"**. Chaves criadas recentemente não alcançam o modelo,
embora ele ainda apareça na documentação. A degradação funcionou (todo turno devolveu a
mensagem de instabilidade em vez de quebrar), mas o atendimento não existia.

Trocado o modelo, apareceu um segundo problema, mais sutil: o Gemini 3.x **não devolve
`content` como string**, e sim como lista de blocos tipados —
`[{"type": "text", "text": "Olá!", "extras": {...}}]`. Como o código tratava `content` como
texto, o cliente veria o `repr` de uma lista de dicionários na tela.

**Solução:** sondagem de modelos com a chave em mãos (tabela abaixo) e uma função única,
`core/utils.py::texto_da_mensagem`, que normaliza qualquer formato de `content` para texto
— usada pelo sanitizador, pelas guardas de runtime e pela UI.

### O pool do Postgres bloqueava em vez de degradar

Com um `POSTGRES_URL` apontando para um banco inalcançável — ou para o Postgres de outro
projeto na mesma porta —, o `ConnectionPool` ficava tentando conectar indefinidamente. A
degradação para `MemorySaver`, que é justamente o ponto do provider, nunca acontecia: a
aplicação travava ao subir.

**Solução:** `timeout` no pool e `connect_timeout` na conexão. O provider falha em 5
segundos e cai para memória, como projetado.

### Três formas de derrubar a conversa que a suíte não via

Um valor de renda `inf` passava pelo `Field(ge=0)` (`inf >= 0` é verdadeiro) e estourava em
`OverflowError` no `int()` do score; uma vírgula sobrando em `clientes.csv` fazia o
`DictReader` criar a chave `None` e `Cliente(**linha)` levantar `TypeError`, derrubando a
autenticação de **todos**; e qualquer exceção não prevista dentro de um handler subia até o
grafo.

Os três tinham a mesma forma: exceção de um tipo que o `except` da camada não previa.
**Solução:** rejeitar não-finitos na fronteira (`parse_valor_monetario`), nomear o
`restkey` do `DictReader` para que o excedente nunca vire a chave `None`, ampliar os
`except` para o que de fato pode ocorrer, e envolver a chamada de handler no motor de turno
— o ponto de extensão mais provável do sistema.

### Entrada do cliente: rejeitar não é tratar

Um passe adversarial mostrou um padrão comum a seis defeitos: o sistema recusava entradas
legítimas em vez de interpretá-las, e a recusa acontecia no pior lugar — no meio da
entrevista, onde o prompt manda repreguntar só aquele campo, e o cliente repete a mesma
formulação.

`TipoEmprego` não reconhecia "aposentado", "pensionista" nem "sou empregado";
`tem_dividas` não entendia "estou sem dívidas", "zero" ou "nunca tive"; e `parse_data`
devolvia **2010** para "14 de maio de 1990 às 10h" — data errada e plausível, que consumia
uma tentativa de autenticação sem o cliente entender por quê.

**Solução:** vocabulário ampliado a partir de como o cliente fala, ano exigido com 4
dígitos no ramo textual, e um filtro de intervalo `[1900, hoje]` que elimina de uma vez
datas futuras e o pivô arbitrário de anos com dois dígitos. Aposentadoria e pensão foram
mapeadas para `formal` — decisão de produto, registrada no código.

### Dado ruim no cadastro apagava o cliente

Uma linha de `clientes.csv` com `tipo_emprego=aposentado` fazia o cliente **deixar de
existir**: o validador levantava, o repositório descartava a linha e a autenticação
respondia "não encontrei um cadastro com esse CPF". Dado inválido reportado como dado
inexistente — e o mesmo valia para score fora da escala.

**Solução:** campos secundários passaram a normalizar com aviso em vez de invalidar. A
tentação era `Field(ge=…, le=…)` no score, e seria o remédio errado: trocaria um cliente
sem crédito por um cliente sem cadastro. Também separei "política ilegível" de "score fora
de todas as faixas", que antes davam a mesma mensagem e mandavam quem investiga para o
arquivo errado.

### O atendimento era um oráculo de enumeração

"Não encontrei um cadastro com esse CPF" e "a data de nascimento não confere" são mensagens
distintas — e juntas permitem descobrir quem é cliente do banco variando o CPF. Pior: o
limite de 3 tentativas vivia no estado da conversa, e "Novo atendimento" zerava o contador.

**Solução:** mensagem única para falha de credencial, com o motivo exato apenas no log; o
status da conta só é revelado **depois** de a data conferir; e um contador por CPF com
janela deslizante, que é a dimensão que o cliente não controla. O CPF também deixou de
aparecer em claro nos logs, que são persistidos em `app/logs/` e montados no host.

### Dois artefatos corretos, incompatíveis juntos

A guarda de vazamento proibia a palavra "transferência" — e `tarifas.md` tem uma seção
`## Transferências` com o TED a R$ 8,50. O prompt empurrava o modelo a evitar o termo certo
ao responder sobre tarifas, e o painel de diagnóstico acusava vazamento em resposta
perfeitamente legítima.

**Solução:** o padrão passou a ser contextual — o vazamento é sobre transferir *o
atendimento*, não sobre movimentar dinheiro. Há um teste que confronta o detector com o
corpus RAG inteiro; é o tipo de verificação que só aparece quando se olha dois artefatos
juntos.

### Idempotência quebrou o fluxo-vitrine

Uma janela curta impede que dois cliques ou dois turnos seguidos gerem duas linhas
idênticas em `solicitacoes_aumento_limite.csv`. Só que a reavaliação após a entrevista
repete **de propósito** o mesmo valor, dentro da mesma janela — e passou a ser bloqueada,
quebrando exatamente a demonstração central.

**Solução:** `solicitar_aumento(..., reavaliacao=True)` dispensa a guarda. É uma decisão
diferente sob um score novo, não o mesmo pedido duas vezes. O conflito só apareceu porque
as duas proteções foram escritas em momentos distintos.

### Entrevista oferecida para um pedido impossível

Um pedido de R$ 1 bilhão era rejeitado corretamente e seguido da oferta de entrevista
financeira. Só que o teto da melhor faixa da política é R$ 50.000: nenhum recálculo de
score poderia aprovar aquele valor.

**Solução:** `FaixaScoreRepository.teto_maximo()` dá o maior limite concedido em qualquer
faixa, e `ResultadoAumento.acima_do_teto_global` distingue *"seu score não alcança"* de
*"esse valor não existe neste banco"*. No segundo caso a entrevista não é oferecida.

### O agente afirmava ter feito o que não fez

Um cliente informou renda e tipo de emprego **fora** da entrevista e ouviu "Compreendi sua
renda" — sem que nada tivesse sido registrado, porque o agente de crédito não tem
ferramenta para isso. Em outro momento, "ganho 15000" virou um pedido de aumento de
R$ 15.000 que o cliente nunca fez.

**Solução:** regra explícita nos prompts — nunca afirmar que registrou, anotou ou atualizou
um dado sem ter chamado a ferramenta correspondente, e não deduzir intenção a partir de um
número solto. Como prompt não é executável, um teste assevera a parte que é: só o agente de
entrevista tem ferramenta de escrita financeira, e o caminho honesto
(`iniciar_entrevista`) existe. No dia em que alguém adicionar a ferramenta ao crédito e
esquecer do prompt, o teste avisa.

### Dois drivers para o mesmo Postgres

O checkpointer do LangGraph fala **psycopg** (`postgresql://`) e o `PGEngine` do pgvector é
SQLAlchemy async, exigindo `postgresql+asyncpg://`. Manter duas variáveis de ambiente seria
um convite a configurá-las de forma inconsistente. A conversão acontece em um único ponto
(`providers/vectorstore.py`), e existe uma só `POSTGRES_URL`.

### Inconsistência do enunciado (`rejeitado` × `reprovado`)

O enunciado define a coluna com `rejeitado` e, mais adiante, fala em `reprovado` para o
mesmo estado. Padronizado no enum `StatusPedido`, usando o termo da definição das colunas.

---

## Decisões detalhadas

### Sondagem de modelos do Gemini

A escolha do modelo foi feita testando a API com a chave em mãos, uma requisição por
modelo, exercitando uma tool call real:

| Modelo | Disponível | Tool calling | Latência |
| --- | --- | --- | --- |
| `gemini-2.5-flash-lite` | ✗ 404 (aposentado para chaves novas) | — | — |
| **`gemini-3.5-flash-lite`** | **✓** | **correta** | **0,78 s** |
| `gemini-3.1-flash-lite` | ✓ | correta | 0,79 s |
| `gemini-flash-lite-latest` | ✓ | correta | 0,65 s |
| `gemini-3.6-flash` | ✓ | correta | 1,56 s |
| `gemini-2.0-flash`, `2.0-flash-lite` | ✗ 429 | — | — |

Adotado `gemini-3.5-flash-lite`: a linha *flash-lite* é a de maior cota diária no free tier
e a mais rápida entre as testadas com tool calling correto. A versão é fixada de propósito
— `gemini-flash-lite-latest` é um alias móvel.

**Consumo.** Um turno do cliente custa **mais de uma requisição**: cada rodada do loop
ferramenta↔modelo é uma chamada, e a redação final pode ser outra. Um atendimento completo
de 12 turnos, atravessando os quatro agentes, custou **21 requisições** (média 1,8 por
turno, máximo 3). O limite que aperta primeiro no free tier é o **de minuto**, não o
diário: em uma conversa fluida é fácil passar de 10 requisições por minuto.

### Por que existe um `historico_score.csv`

Manter as 5 colunas do enunciado tem um custo: nenhuma delas é score. Como `clientes.csv`
guarda apenas o score vigente e é sobrescrito a cada entrevista, o score **sob o qual cada
decisão de crédito foi tomada** não sobreviveria em nenhum dado consultável.

O arquivo de histórico fecha isso sem tocar no CSV que o enunciado especifica: os dois usam
ISO 8601 com microssegundos, então cruzar por timestamp reconstrói a decisão inteira —
pedido rejeitado sob score 380, recálculo para 505, pedido idêntico aprovado. Há um teste
que assevera essa reconstrução.

Gravar a trilha nunca invalida a operação que ela documenta: uma falha ao escrever o
histórico vira `warning` no log e o score permanece atualizado.
