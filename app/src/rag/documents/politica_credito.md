# Política de Crédito — Banco Ágil

## Faixas de score e limite máximo

O limite máximo aprovável depende da faixa de score do cliente:

| Faixa de score | Limite máximo | Taxa de juros mensal |
| --- | --- | --- |
| 0 a 300 | R$ 1.000,00 | 8,99% a.m. |
| 301 a 450 | R$ 5.000,00 | 7,49% a.m. |
| 451 a 600 | R$ 15.000,00 | 5,99% a.m. |
| 601 a 1000 | R$ 50.000,00 | 4,49% a.m. |

A faixa de 601 a 1000 é reservada a perfis com vínculo formal, sem dependentes, sem
dívidas ativas e com renda substancialmente superior às despesas fixas.

## Solicitação de aumento de limite

Todo pedido de aumento é registrado formalmente antes de qualquer análise, com status
inicial `pendente`. Em seguida o score do cliente é conferido contra a tabela acima:

- se o valor pedido couber no limite máximo da faixa, o pedido passa a `aprovado` e o
  novo limite é aplicado imediatamente;
- caso contrário, o pedido passa a `rejeitado`.

O cliente pode solicitar um novo aumento a qualquer momento. Pedidos anteriores não são
apagados: cada solicitação fica registrada com data e hora, para consulta posterior.

Não é possível solicitar um limite igual ou menor que o limite atual.

## Recálculo de score

Um pedido rejeitado pode ser reavaliado depois que o cliente atualiza seus dados
financeiros por meio da entrevista de crédito. Se o novo score mudar de faixa, um novo
pedido é registrado e analisado sob a política vigente.

O score varia de 0 a 1000 e considera renda mensal, tipo de vínculo empregatício,
despesas fixas, número de dependentes e existência de dívidas ativas.

## Prazos

A análise é automática e instantânea. Não há período de carência entre solicitações.
