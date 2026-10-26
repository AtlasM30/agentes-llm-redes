#!/usr/bin/env python3
"""Gera pacote .zip limpo para revisao externa de codigo (sem segredos ou gabaritos).

Exclui estritamente:
  - .git/, __pycache__/, .venv/, venv/, dist/
  - .env e quaisquer chaves/certificados (*.pem, *.key)
  - logs/, dados/gabaritos/, dados/desempenho/, avaliacao/, resultados_agente/auditoria/

Uso:
    python3 exportar_pacote_revisao.py
"""
import zipfile
from pathlib import Path


RAIZ = Path(__file__).resolve().parent
SAIDA_PADRAO = RAIZ / "dist" / "agentes-llm-redes-etapa7-revisao.zip"

PASTAS_EXCLUIDAS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    ".vscode",
    "logs",
    "dados",
    "avaliacao",
    "dist",
    "auditoria",
}

ARQUIVOS_EXCLUIDOS = {
    ".env",
    "gabarito_avaliacao.json",
    "causas_reais.json",
}

SUFIXOS_EXCLUIDOS = (".pyc", ".pyo", ".pem", ".key", ".log", ".pid", ".tmp", ".swp")


def deve_incluir(caminho_relativo: Path) -> bool:
    partes = set(caminho_relativo.parts)
    if partes & PASTAS_EXCLUIDAS:
        return False
    nome = caminho_relativo.name
    if nome in ARQUIVOS_EXCLUIDOS:
        return False
    if nome.startswith(".env.") and nome != ".env.example":
        return False
    if nome.endswith(SUFIXOS_EXCLUIDOS):
        return False
    if "gabarito" in nome.lower() or "causas_reais" in nome.lower():
        return False
    return True


def exportar_zip(destino=SAIDA_PADRAO):
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    incluidos = []

    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arquivo in sorted(RAIZ.rglob("*")):
            if not arquivo.is_file():
                continue
            rel = arquivo.relative_to(RAIZ)
            if not deve_incluir(rel):
                continue
            zf.write(arquivo, arcname=str(Path("agentes-llm-redes") / rel))
            incluidos.append(str(rel))

    return destino, incluidos


if __name__ == "__main__":
    arq_zip, lista = exportar_zip()
    print(f"Pacote limpo gerado em: {arq_zip}")
    print(f"Total de arquivos incluidos: {len(lista)}")
    for item in lista:
        print(f"  + {item}")
