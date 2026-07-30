"""Repositório CSV base: leitura e escrita atômica, com erros controlados."""
from __future__ import annotations

import csv
import os
import tempfile
import threading
import time
from pathlib import Path

from src.core.logging import get_logger

logger = get_logger(__name__)

_TENTATIVAS_REPLACE = 3
_ESPERA_RETRY = 0.1


class RepositoryError(Exception):
    """Erro esperado de acesso a dados (arquivo ausente, corrompido, I/O)."""


class CsvRepository:
    """Acesso genérico a um arquivo CSV."""

    def __init__(self, path: Path, header: list[str]):
        self.path = Path(path)
        self.header = header
        self._lock = threading.Lock()


    def read_dicts(self) -> list[dict[str, str]]:
        try:
            with self.path.open(newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except FileNotFoundError as exc:
            raise RepositoryError(f"Arquivo não encontrado: {self.path.name}") from exc
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            raise RepositoryError(f"Falha ao ler {self.path.name}: {exc}") from exc


    def write_dicts(self, rows: list[dict], fieldnames: list[str] | None = None) -> None:
        """Reescreve o arquivo inteiro de forma atômica."""
        campos = fieldnames or self.header
        with self._lock:
            self._escrever_atomico(rows, campos)

    def append_dict(self, row: dict) -> int:
        """Acrescenta uma linha e devolve o índice dela (0-based, sem contar o cabeçalho)."""
        with self._lock:
            existentes = self._ler_sem_lock()
            existentes.append({c: row.get(c, "") for c in self.header})
            self._escrever_atomico(existentes, self.header)
            return len(existentes) - 1

    def update_row(self, idx: int, row: dict) -> None:
        """Substitui a linha de índice `idx`."""
        with self._lock:
            linhas = self._ler_sem_lock()
            if not 0 <= idx < len(linhas):
                raise RepositoryError(
                    f"Linha {idx} inexistente em {self.path.name} ({len(linhas)} linhas)."
                )
            linhas[idx] = {c: row.get(c, "") for c in self.header}
            self._escrever_atomico(linhas, self.header)


    def _ler_sem_lock(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        return self.read_dicts()

    def _modo_do_alvo(self) -> int:
        """Permissão a aplicar no arquivo novo."""
        try:
            return self.path.stat().st_mode & 0o777
        except OSError:
            return 0o644

    def _escrever_atomico(self, rows: list[dict], fieldnames: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            modo = self._modo_do_alvo()
            fd, tmp_nome = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp_nome, modo)
                self._replace_com_retry(tmp_nome)
            except BaseException:
                Path(tmp_nome).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise RepositoryError(f"Falha ao gravar {self.path.name}: {exc}") from exc

    def _replace_com_retry(self, origem: str) -> None:
        """Substitui o arquivo alvo, com retry curto em caso de lock temporário."""
        for tentativa in range(_TENTATIVAS_REPLACE):
            try:
                os.replace(origem, self.path)
                return
            except OSError as exc:
                if tentativa == _TENTATIVAS_REPLACE - 1:
                    raise
                logger.warning(
                    "Retry de escrita em %s (tentativa %d): %s",
                    self.path.name, tentativa + 1, exc,
                )
                time.sleep(_ESPERA_RETRY)
