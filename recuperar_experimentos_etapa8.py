from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import json
import subprocess
import sys
import time

RAIZ = Path(__file__).resolve().parent

BATERIA = (
    RAIZ / "experimentos_etapa8"
    / "baterias" / "20261026T061113Z"
)

ENTRADAS = RAIZ / "experimentos_etapa8" / "entradas"
RECUPERACOES = RAIZ / "experimentos_etapa8" / "recuperacoes"

MODELO = "gemini-3.1-flash-lite"


def carregar_pendentes():
    arquivo = BATERIA / "diagnosticos_pendentes.csv"

    with arquivo.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))



def recuperado_anteriormente(item):
    politica = item["politica"]
    repeticao = int(item["repeticao"])
    caso = int(item["caso"])
    cliente = item["cliente"]

    nome = (
        f"auditoria_caso_{caso:02d}_"
        f"{politica}_{cliente}.json"
    )

    for lote in RECUPERACOES.iterdir():
        if not lote.is_dir():
            continue

        pasta = (
            lote
            / politica
            / f"repeticao_{repeticao:02d}"
            / f"caso_{caso:02d}"
            / cliente
        )

        arquivo = pasta / "auditoria" / nome
        status = pasta / "status.json"

        if not arquivo.is_file() or not status.is_file():
            continue

        try:
            dados = json.loads(
                status.read_text(encoding="utf-8")
            )

            if (
                dados.get("concluido") is True
                and dados.get("politica") == politica
                and int(dados.get("repeticao", -1)) == repeticao
                and int(dados.get("caso", -1)) == caso
                and dados.get("cliente") == cliente
            ):
                return True

        except (ValueError, OSError, TypeError):
            continue

    return False



def executar(item, pasta_lote):
    politica = item["politica"]
    repeticao = int(item["repeticao"])
    caso = int(item["caso"])
    cliente = item["cliente"]

    pasta = (
        pasta_lote / politica
        / f"repeticao_{repeticao:02d}"
        / f"caso_{caso:02d}"
        / cliente
    )

    auditoria_dir = pasta / "auditoria"
    auditoria_dir.mkdir(parents=True, exist_ok=False)

    comando = [
        sys.executable,
        str(RAIZ / "executar_agente.py"),
        "--provedor", "gemini",
        "--modelo", MODELO,
        "--temperatura", "0.0",
        "--top-k", "4",
        "--politica", politica,
        "--modo-evidencias", "progressivo",
        "--caso", str(caso),
        "--cliente", cliente,
        "--logs", str(ENTRADAS),
        "--auditoria-dir", str(auditoria_dir),
    ]

    inicio = datetime.now(timezone.utc)
    codigo = 125
    erro = None

    try:
        with (pasta / "terminal.log").open(
            "w", encoding="utf-8"
        ) as log:
            try:
                resultado = subprocess.run(
                    comando,
                    cwd=RAIZ,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=600
                )
                codigo = resultado.returncode

            except subprocess.TimeoutExpired:
                codigo = 124
                erro = "timeout_global_600s"
                log.write("\nTimeout global do orquestrador.\n")

            except Exception as exc:
                erro = f"{type(exc).__name__}: {exc}"
                log.write(f"\nErro do orquestrador: {erro}\n")

    except OSError as exc:
        erro = f"Erro ao gravar log: {exc}"

    auditorias = list(auditoria_dir.glob("*.json"))
    concluido = codigo == 0 and len(auditorias) == 1

    texto = (pasta / "terminal.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (pasta / "terminal.log").exists() else ""

    status = {
        "politica": politica,
        "repeticao": repeticao,
        "caso": caso,
        "cliente": cliente,
        "inicio_utc": inicio.isoformat(),
        "fim_utc": datetime.now(timezone.utc).isoformat(),
        "codigo_saida": codigo,
        "concluido": concluido,
        "erro": erro,
        "auditorias": [a.name for a in auditorias],
        "erro_429": "HTTP 429" in texto,
        "erro_503": "HTTP 503" in texto,
        "conexao_recusada": "Connection refused" in texto,
    }

    (pasta / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-unidades", type=int, default=1)
    parser.add_argument("--pausa", type=int, default=90)
    args = parser.parse_args()

    if args.max_unidades < 1 or args.pausa < 0:
        parser.error("max-unidades deve ser >= 1 e pausa >= 0")

    identificador = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    pasta_lote = RECUPERACOES / identificador
    pasta_lote.mkdir(parents=True, exist_ok=False)

    pendentes = [
        item for item in carregar_pendentes()
        if not recuperado_anteriormente(item)
    ]

    print(f"Pendentes ainda nao recuperados: {len(pendentes)}")

    executados = 0

    for item in pendentes:
        if executados >= args.max_unidades:
            break

        print(
            f"Recuperando {item['politica']} | "
            f"rep {item['repeticao']} | "
            f"caso {item['caso']} | {item['cliente']}",
            flush=True
        )

        status = executar(item, pasta_lote)
        executados += 1

        print(
            f"Concluido: {status['concluido']} | "
            f"Codigo: {status['codigo_saida']}",
            flush=True
        )

        if not status["concluido"]:
            print(
                "Falha registrada. Recuperacao interrompida "
                "para evitar novas chamadas desnecessarias."
            )
            break

        if executados < args.max_unidades:
            time.sleep(args.pausa)

    print(f"Recuperacoes tentadas: {executados}")
    print(f"Resultados: {pasta_lote}")


if __name__ == "__main__":
    main()
