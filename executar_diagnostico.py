
from pathlib import Path

from diagnostico.pipeline import carregar_evidencias
from diagnostico.regras import diagnosticar_cliente


PASTA = Path("logs")


def carregar_caso(numero):
    caminho = PASTA / f"evidencias_caso_{numero:02d}.json"
    return carregar_evidencias(caminho)


def obter_latencia(evidencias):
    return evidencias.get("ping", {}).get(
        "latencia_media_ms"
    )


def executar():
    # Caso normal serve como linha de base.
    # Nao utilizamos o gabarito de causas.
    normal = carregar_caso(0)

    referencias = {
        nome: obter_latencia(
            normal["dispositivos"][nome]
        )
        for nome in ("client1", "client2")
    }

    for numero in range(6):
        dados = carregar_caso(numero)

        servidor = dados["dispositivos"]["server"]

        print(f"\n{'=' * 48}")
        print(f"ARQUIVO {numero:02d}")
        print("=" * 48)

        for nome in ("client1", "client2"):
            cliente = dados["dispositivos"][nome]

            diagnostico = diagnosticar_cliente(
                evidencias=cliente,
                nome=nome,
                servidor=servidor,
                latencia_referencia=referencias[nome],
            )

            print(f"\n{nome}")
            print(
                " Hipotese:",
                diagnostico["hipotese"]
            )
            print(
                " Confianca:",
                diagnostico["confianca"]
            )

            for evidencia in diagnostico["evidencias"]:
                print(" -", evidencia)


if __name__ == "__main__":
    executar()
