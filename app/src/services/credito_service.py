"""Crédito: consulta de limite e ciclo de vida da solicitação de aumento."""
from __future__ import annotations

from src.core.logging import get_logger
from src.core.utils import formatar_brl, formatar_percentual
from src.domain.enums import StatusPedido
from src.domain.models import Cliente, FaixaScore, SolicitacaoAumento
from src.domain.results import ResultadoAumento, ResumoLimite
from src.repositories.base import RepositoryError
from src.repositories.clientes import ClienteRepository
from src.repositories.score_limite import FaixaScoreRepository
from src.repositories.solicitacoes import SolicitacaoRepository

logger = get_logger(__name__)


class CreditoService:
    def __init__(
        self,
        faixa_repo: FaixaScoreRepository | None = None,
        solicitacao_repo: SolicitacaoRepository | None = None,
        cliente_repo: ClienteRepository | None = None,
    ) -> None:
        self.faixas = faixa_repo or FaixaScoreRepository()
        self.solicitacoes = solicitacao_repo or SolicitacaoRepository()
        self.clientes = cliente_repo or ClienteRepository()

    def _faixa_do_cliente(self, cliente: Cliente) -> FaixaScore | None:
        try:
            return self.faixas.faixa_para(cliente.score)
        except RepositoryError as exc:
            logger.error("Política de crédito indisponível: %s", exc)
            return None

    def consultar_limite(self, cliente: Cliente) -> ResumoLimite:
        faixa = self._faixa_do_cliente(cliente)
        if faixa is None:
            return ResumoLimite(
                ok=False,
                limite_atual=cliente.limite_atual,
                score=cliente.score,
                mensagem="não consegui consultar a política de crédito agora",
            )
        return ResumoLimite(
            limite_atual=cliente.limite_atual,
            score=cliente.score,
            limite_maximo=faixa.limite_maximo,
            taxa_juros_mensal=faixa.taxa_juros_mensal,
        )

    def _cliente_atual(self, cliente: Cliente) -> Cliente:
        """Relê o cliente do disco antes de decidir.

        O `cliente` que chega é o snapshot congelado no estado do grafo desde a
        autenticação. Avaliar contra ele aprova pedidos sobre um limite que já mudou.
        """
        try:
            return self.clientes.buscar_por_cpf(cliente.cpf) or cliente
        except RepositoryError:
            return cliente

    def solicitar_aumento(self, cliente: Cliente, novo_limite: float) -> ResultadoAumento:
        cliente = self._cliente_atual(cliente)
        if novo_limite <= cliente.limite_atual:
            return ResultadoAumento(
                status=StatusPedido.INVALIDO,
                mensagem=(
                    f"O novo limite ({formatar_brl(novo_limite)}) precisa ser maior que o "
                    f"limite atual ({formatar_brl(cliente.limite_atual)})."
                ),
            )

        faixa = self._faixa_do_cliente(cliente)
        if faixa is None:
            return ResultadoAumento(
                status=StatusPedido.ERRO,
                mensagem="Não consegui consultar a política de crédito agora.",
            )

        solicitacao = SolicitacaoAumento(
            cpf_cliente=cliente.cpf,
            limite_atual=cliente.limite_atual,
            novo_limite_solicitado=novo_limite,
            status_pedido=StatusPedido.PENDENTE,
        )
        try:
            idx = self.solicitacoes.registrar(solicitacao)
        except RepositoryError as exc:
            logger.error("Falha ao registrar solicitação de aumento: %s", exc)
            return ResultadoAumento(
                status=StatusPedido.ERRO,
                mensagem="Não consegui registrar sua solicitação agora. Tente em instantes.",
            )

        aprovado = novo_limite <= faixa.limite_maximo
        status = StatusPedido.APROVADO if aprovado else StatusPedido.REJEITADO
        decidida = solicitacao.model_copy(update={"status_pedido": status})

        try:
            self.solicitacoes.transicionar(idx, decidida)
        except RepositoryError as exc:
            logger.warning("Falha ao transicionar pedido %d para %s: %s", idx, status, exc)

        if not aprovado:
            return ResultadoAumento(
                status=status,
                mensagem=(
                    f"A solicitação de {formatar_brl(novo_limite)} foi rejeitada: o limite "
                    f"máximo para o score atual ({cliente.score}) é "
                    f"{formatar_brl(faixa.limite_maximo)}."
                ),
                limite_maximo=faixa.limite_maximo,
                taxa_juros_mensal=faixa.taxa_juros_mensal,
                solicitacao=decidida,
                linha_idx=idx,
                score_avaliado=cliente.score,
                cliente_atualizado=cliente,
            )

        return ResultadoAumento(
            status=status,
            mensagem=(
                f"Aumento para {formatar_brl(novo_limite)} aprovado. Teto para o score "
                f"{cliente.score}: {formatar_brl(faixa.limite_maximo)}; taxa de juros "
                f"{formatar_percentual(faixa.taxa_juros_mensal)} ao mês."
            ),
            limite_maximo=faixa.limite_maximo,
            taxa_juros_mensal=faixa.taxa_juros_mensal,
            solicitacao=decidida,
            linha_idx=idx,
            score_avaliado=cliente.score,
            cliente_atualizado=self._persistir_novo_limite(cliente, novo_limite),
        )

    def _persistir_novo_limite(self, cliente: Cliente, novo_limite: float) -> Cliente:
        """Grava o novo limite só se o valor em disco ainda for o que foi avaliado.

        Falhar aqui não invalida o pedido já registrado. Se outra aprovação escreveu
        primeiro, o `compare-and-set` recusa a sobrescrita e o limite vigente prevalece —
        é preferível não aplicar um aumento a apagar outro silenciosamente.
        """
        try:
            aplicado = self.clientes.atualizar_limite_se(
                cliente.cpf, cliente.limite_atual, novo_limite
            )
            if not aplicado:
                logger.warning(
                    "Limite de %s mudou durante a avaliação; aumento para %.2f não aplicado.",
                    cliente.cpf, novo_limite,
                )
                return self._cliente_atual(cliente)
        except RepositoryError as exc:
            logger.error("Aumento aprovado mas não persistido para %s: %s", cliente.cpf, exc)
            return cliente
        return cliente.model_copy(update={"limite_atual": novo_limite})
