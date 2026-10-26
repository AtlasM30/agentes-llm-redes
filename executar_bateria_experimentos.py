
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import json
import hashlib
import sys
import os

RAIZ = Path(__file__).resolve().parent
ENTRADAS = RAIZ / "experimentos_etapa8" / "entradas"
BASE = RAIZ / "experimentos_etapa8" / "baterias"

MODELO = "gemini-3.1-flash-lite"
REPETICOES = 3
POLITICAS = ["padrao", "restritiva"]
CASOS = range(6)


def sha256(arquivo):
    h = hashlib.sha256()
    with arquivo.open("rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def versao_git():
    resultado = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=RAIZ,
        capture_output=True,
        text=True
    )
    return resultado.stdout.strip()


def executar():
    arquivos = [
        ENTRADAS / f"evidencias_caso_{i:02d}.json"
        for i in CASOS
    ]

    ausentes = [str(a) for a in arquivos if not a.is_file()]

    if ausentes:
        print("ERRO: evidencias ausentes:")
        for nome in ausentes:
            print(nome)
        sys.exit(1)

    identificador = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    pasta_bateria = BASE / identificador
    pasta_bateria.mkdir(parents=True, exist_ok=False)

    manifesto = {
        "identificador": identificador,
        "modelo": MODELO,
        "provedor": "gemini",
        "temperatura": 0.0,
        "rag_top_k": 4,
        "repeticoes": REPETICOES,
        "politicas": POLITICAS,
        "modo_evidencias": "progressivo",
        "git_commit": versao_git(),
        "entradas": {
            a.name: sha256(a) for a in arquivos
        }
    }

    (pasta_bateria / "manifesto.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    registros = []

    for politica in POLITICAS:
        for repeticao in range(1, REPETICOES + 1):
            for caso in CASOS:
                pasta = (
                    pasta_bateria
                    / politica
                    / f"repeticao_{repeticao:02d}"
                    / f"caso_{caso:02d}"
                )

                auditoria = pasta / "auditoria"
                auditoria.mkdir(parents=True, exist_ok=False)

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
                    "--logs", str(ENTRADAS),
                    "--auditoria-dir", str(auditoria)
                ]

                print(
                    f"\nExecutando: {politica} | "
                    f"repeticao {repeticao} | caso {caso}",
                    flush=True
                )

                inicio = datetime.now(timezone.utc)
                erro = None

                with (pasta / "terminal.log").open(
                    "w", encoding="utf-8"
                ) as log:
                    try:
                        processo = subprocess.run(
                            comando,
                            cwd=RAIZ,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=900
                        )
                        codigo = processo.returncode

                    except subprocess.TimeoutExpired:
                        codigo = 124
                        erro = "timeout_global_900s"
                        log.write(
                            "\n[ORQUESTRADOR] "
                            "Timeout global de 900s.\n"
                        )

                    except Exception as exc:
                        codigo = 125
                        erro = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        log.write(
                            f"\n[ORQUESTRADOR] {erro}\n"
                        )

                fim = datetime.now(timezone.utc)

                auditorias = sorted(
                    p.name for p in auditoria.glob("*.json")
                )

                registro = {
                    "politica": politica,
                    "repeticao": repeticao,
                    "caso": caso,
                    "inicio_utc": inicio.isoformat(),
                    "fim_utc": fim.isoformat(),
                    "duracao_total_s": (
                        fim - inicio
                    ).total_seconds(),
                    "codigo_saida": codigo,
                    "erro_orquestrador": erro,
                    "auditorias": auditorias,
                    "quantidade_auditorias": len(auditorias),
                    "completo": (
                        codigo == 0
                        and len(auditorias) == 2
                    ),
                    "pasta": str(pasta.relative_to(RAIZ))
                }

                (pasta / "status.json").write_text(
                    json.dumps(
                        registro,
                        indent=2,
                        ensure_ascii=False
                    ),
                    encoding="utf-8"
                )

                registros.append(registro)

                (pasta_bateria / "indice_execucoes.json").write_text(
                    json.dumps(
                        registros,
                        indent=2,
                        ensure_ascii=False
                    ),
                    encoding="utf-8"
                )

                print(
                    f"Codigo: {codigo} | "
                    f"Auditorias: {len(auditorias)}/2",
                    flush=True
                )

    completas = sum(r["completo"] for r in registros)

    print("\nBateria encerrada.")
    print(f"Execucoes completas: {completas}/{len(registros)}")
    print(f"Resultados: {pasta_bateria}")


if __name__ == "__main__":
    executar()
