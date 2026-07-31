"""Crédito: consulta de limite e ciclo de vida da solicitação de aumento."""
from __future__ import annotations

from datetime import datetime

from src.core.constants import JANELA_IDEMPOTENCIA
from src.core.logging import get_logger
from src.core.utils import cpf_mascarado, formatar_brl, formatar_percentual
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

    def _faixa_do_cliente(self, cliente: Cliente) -> tuple[FaixaScore | None, str]:
        """Devolve `(faixa, motivo)`.

        Colapsar "política ilegível" e "score fora de todas as faixas" no mesmo `None`
        envenena o diagnóstico: a mensagem culpa a infraestrutura quando o defeito está
        no cadastro do cliente, e alguém vai procurar problema no arquivo errado.
        """
        try:
            faixa = self.faixas.faixa_para(cliente.score)
        except RepositoryError as exc:
            logger.error("Política de crédito indisponível: %s", exc)
            return None, "não consegui consultar a política de crédito agora"

        if faixa is None:
            logger.error(
                "Score %s do cliente %s não corresponde a nenhuma faixa da política.",
                cliente.score, cpf_mascarado(cliente.cpf),
            )
            return None, (
                f"o score cadastrado ({cliente.score}) está fora das faixas da política "
                "de crédito, então não é possível avaliar o limite"
            )
        return faixa, ""

    def _acima_do_teto_global(self, novo_limite: float) -> bool:
        """Nenhum score da política aprova este valor.

        Sem isso o agente oferecia a entrevista financeira para um pedido de R$ 1 bilhão:
        um caminho que nenhum recálculo de score pode fazer dar certo.
        """
        try:
            return novo_limite > self.faixas.teto_maximo()
        except RepositoryError:
            return False

    def consultar_limite(self, cliente: Cliente) -> ResumoLimite:
        faixa, motivo = self._faixa_do_cliente(cliente)
        if faixa is None:
            return ResumoLimite(
                ok=False,
                limite_atual=cliente.limite_atual,
                score=cliente.score,
                mensagem=motivo,
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

    def _pedido_recente_identico(self, cliente: Cliente, novo_limite: float) -> bool:
        """Evita duas linhas idênticas por dois cliques ou dois turnos seguidos.

        A janela é curta de propósito: pedir de novo o mesmo valor depois de um tempo é
        uma intenção legítima do cliente e precisa gerar registro próprio.
        """
        try:
            anteriores = self.solicitacoes.do_cliente(cliente.cpf)
        except RepositoryError:
            return False
        if not anteriores:
            return False

        ultimo = anteriores[-1]
        try:
            valor = float(ultimo.get("novo_limite_solicitado") or 0)
            quando = datetime.fromisoformat(ultimo.get("data_hora_solicitacao", ""))
        except ValueError:
            return False

        idade = (datetime.now() - quando).total_seconds()
        return abs(valor - novo_limite) < 0.005 and idade < JANELA_IDEMPOTENCIA

    def solicitar_aumento(
        self, cliente: Cliente, novo_limite: float, *, reavaliacao: bool = False
    ) -> ResultadoAumento:
        """Registra e avalia um pedido de aumento.

        `reavaliacao=True` dispensa a guarda de idempotência: a reavaliação após a
        entrevista repete o mesmo valor de propósito, sob um score novo — é uma decisão
        diferente, não o mesmo pedido duas vezes.
        """
        cliente = self._cliente_atual(cliente)
        if novo_limite <= cliente.limite_atual:
            return ResultadoAumento(
                status=StatusPedido.INVALIDO,
                mensagem=(
                    f"O novo limite ({formatar_brl(novo_limite)}) precisa ser maior que o "
                    f"limite atual ({formatar_brl(cliente.limite_atual)})."
                ),
            )

        if not reavaliacao and self._pedido_recente_identico(cliente, novo_limite):
            logger.info(
                "Pedido idêntico recente para %s ignorado (idempotência).",
                cpf_mascarado(cliente.cpf),
            )
            return ResultadoAumento(
                status=StatusPedido.INVALIDO,
                mensagem=(
                    f"Já registrei um pedido de {formatar_brl(novo_limite)} há instantes. "
                    "O resultado continua valendo."
                ),
            )

        faixa, motivo = self._faixa_do_cliente(cliente)
        if faixa is None:
            return ResultadoAumento(status=StatusPedido.ERRO, mensagem=f"{motivo.capitalize()}.")

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
                acima_do_teto_global=self._acima_do_teto_global(novo_limite),
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
                    cpf_mascarado(cliente.cpf), novo_limite,
                )
                return self._cliente_atual(cliente)
        except RepositoryError as exc:
            logger.error(
                "Aumento aprovado mas não persistido para %s: %s",
                cpf_mascarado(cliente.cpf), exc,
            )
            return cliente
        return cliente.model_copy(update={"limite_atual": novo_limite})
