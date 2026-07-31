"""Utilidades transversais: normalização de texto, formatação e marcação interna."""
from __future__ import annotations

import math
import re
import unicodedata

TETO_VALOR_MONETARIO = 1_000_000_000.0

_MARCADOR_INTERNO = "[interno]"


def sem_acentos(texto: str) -> str:
    """Remove acentuação, preservando o resto. `autônomo` -> `autonomo`."""
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Forma canônica para comparação: sem acentos, minúsculo e sem espaços nas pontas."""
    return sem_acentos(str(texto)).strip().lower()


def apenas_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto))


def formatar_cpf(cpf: str) -> str:
    """Formata 11 dígitos como 000.000.000-00; devolve a entrada se não for possível."""
    d = apenas_digitos(cpf)
    if len(d) != 11:
        return cpf
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def cpf_mascarado(cpf: str) -> str:
    """`***.***.777-35` — para log e telemetria.

    CPF é dado pessoal e o log é persistido em `app/logs/`, montado no host. Nenhuma
    mensagem de log deve carregar o número completo.
    """
    d = apenas_digitos(cpf)
    return f"***.***.{d[6:9]}-{d[9:]}" if len(d) == 11 else "***"


def formatar_brl(valor: float) -> str:
    """Formata em reais no padrão brasileiro: `R$ 1.234,56`, `-R$ 1.234,56`."""
    sinal = "-" if valor < 0 else ""
    inteiro = f"{abs(valor):,.2f}"
    corpo = inteiro.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{sinal}R$ {corpo}"


def formatar_percentual(taxa: float) -> str:
    """0.0599 -> '5,99%'."""
    return f"{taxa * 100:.2f}".replace(".", ",") + "%"


_MULTIPLICADORES = {
    "k": 1_000, "mil": 1_000, "m": 1_000_000, "mi": 1_000_000,
    "milhao": 1_000_000, "milhoes": 1_000_000,
}
# Ancorado no fim: "10 mil mil" precisa falhar, não virar 10.000 ignorando o excedente.
_RE_MULTIPLICADOR = re.compile(
    r"^([\d.,]+)\s*(" + "|".join(sorted(_MULTIPLICADORES, key=len, reverse=True)) + r")$"
)
# Formas aceitas: "4200", "4200.50", "4.200", "1.234.567,89", "4200,50".
# Milhar só é milhar quando todos os grupos têm 3 dígitos — "1.2.3" não é número.
_RE_NUMERO = re.compile(r"^(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$|^\d+(\.\d+)?$")


def parse_valor_monetario(valor: str | float | int) -> float:
    """Interpreta um valor em reais escrito como o cliente falaria."""
    if isinstance(valor, int | float):
        return float(valor)

    texto = normalizar(valor)
    for prefixo in ("r$", "rs", "reais", "real"):
        texto = texto.replace(prefixo, " ")
    texto = texto.strip()

    multiplicador = 1
    if achado := _RE_MULTIPLICADOR.match(texto):
        texto = achado.group(1)
        multiplicador = _MULTIPLICADORES[achado.group(2)]

    texto = texto.replace(" ", "")

    # Valida a forma ANTES de reinterpretar os separadores. Depois da normalização,
    # "1.2.3" já teria virado "123" e passaria como número plausível.
    if not _RE_NUMERO.fullmatch(texto):
        raise ValueError(f"valor monetário inválido: {valor!r}")

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"\d+\.\d{3}", texto):
        texto = texto.replace(".", "")

    try:
        resultado = float(texto) * multiplicador
    except ValueError as exc:
        raise ValueError(f"valor monetário inválido: {valor!r}") from exc

    # `float()` aceita "inf", "-inf" e "1e999". Um infinito passa pelo `ge=0` do modelo
    # (inf >= 0 é verdadeiro) e só estoura lá na frente, no `int()` do cálculo de score.
    # Barrar aqui, na fronteira, mantém o erro como mensagem de campo ao invés de exceção.
    if not math.isfinite(resultado):
        raise ValueError(f"valor monetário fora de faixa: {valor!r}")
    if abs(resultado) > TETO_VALOR_MONETARIO:
        raise ValueError(f"valor monetário implausível: {valor!r}")
    return resultado


_RE_TOKEN_NUMERICO = re.compile(r"\d[\d.,]*")


def _leituras(token: str) -> set[float]:
    """Todas as leituras plausíveis de um token numérico.

    `15.000` é milhar em português e decimal em inglês. Como esta função alimenta uma
    guarda de diagnóstico, a ambiguidade se resolve devolvendo as DUAS leituras: perder
    sensibilidade é barato, acusar um número legítimo custa a confiança na guarda.
    """
    limpo = token.rstrip(".,")
    if not limpo:
        return set()

    candidatos = {limpo}
    if "," in limpo:
        candidatos.add(limpo.replace(".", "").replace(",", "."))
    elif limpo.count(".") > 1 or re.fullmatch(r"\d+\.\d{3}", limpo):
        candidatos.add(limpo.replace(".", ""))

    valores: set[float] = set()
    for candidato in candidatos:
        try:
            valor = float(candidato)
        except ValueError:
            continue
        if math.isfinite(valor):
            valores.add(round(valor, 2))
    return valores


def numeros_do_texto(texto: str) -> set[float]:
    """Valores numéricos citados num texto, em forma canônica.

    Serve para confrontar o que o atendente escreveu com o que ele tinha autorização
    para saber — score, limite, taxa e cotação nunca podem ser estimados.
    """
    numeros: set[float] = set()
    for token in _RE_TOKEN_NUMERICO.findall(texto or ""):
        numeros |= _leituras(token)
    return numeros


def texto_da_mensagem(content: object) -> str:
    """Extrai o texto de um `content` de mensagem."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict) and bloco.get("type") == "text":
                partes.append(str(bloco.get("text", "")))
        return "".join(partes)
    return "" if content is None else str(content)


def interno(texto: str) -> str:
    """Marca um retorno de ferramenta como conteúdo interno."""
    return f"{_MARCADOR_INTERNO} {texto}"
