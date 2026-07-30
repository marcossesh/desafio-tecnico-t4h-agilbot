"""Utilidades transversais: normalização de texto, formatação e marcação interna."""
from __future__ import annotations

import re
import unicodedata

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


def formatar_brl(valor: float) -> str:
    """Formata em reais no padrão brasileiro (R$ 1.234,56)."""
    inteiro = f"{valor:,.2f}"
    return "R$ " + inteiro.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatar_percentual(taxa: float) -> str:
    """0.0599 -> '5,99%'."""
    return f"{taxa * 100:.2f}".replace(".", ",") + "%"


_MULTIPLICADORES = {
    "k": 1_000, "mil": 1_000, "m": 1_000_000, "mi": 1_000_000,
    "milhao": 1_000_000, "milhoes": 1_000_000,
}
_RE_MULTIPLICADOR = re.compile(
    r"^([\d.,]+)\s*(" + "|".join(sorted(_MULTIPLICADORES, key=len, reverse=True)) + r")\b"
)


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
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"\d+\.\d{3}", texto):
        texto = texto.replace(".", "")

    try:
        return float(texto) * multiplicador
    except ValueError as exc:
        raise ValueError(f"valor monetário inválido: {valor!r}") from exc


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
