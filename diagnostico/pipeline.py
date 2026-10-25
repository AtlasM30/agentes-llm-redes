import json
from pathlib import Path


DISPOSITIVOS = ("client1", "client2", "router1", "server")


def carregar_evidencias(caminho):
    """Carrega e valida a estrutura basica das evidencias."""

    caminho = Path(caminho)

    if not caminho.is_file():
        raise FileNotFoundError(
            f"Arquivo nao encontrado: {caminho}"
        )

    with caminho.open("r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    if not isinstance(dados, dict):
        raise ValueError("O JSON deve conter um objeto.")

    dispositivos = dados.get("dispositivos")

    if not isinstance(dispositivos, dict):
        raise ValueError(
            "Campo 'dispositivos' ausente ou invalido."
        )

    for nome in DISPOSITIVOS:
        if nome not in dispositivos:
            raise ValueError(
                f"Dispositivo ausente: {nome}"
            )

        if not isinstance(dispositivos[nome], dict):
            raise ValueError(
                f"Evidencias invalidas para {nome}"
            )

    return dados
