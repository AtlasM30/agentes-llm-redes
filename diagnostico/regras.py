import re


SERVIDOR_IP = "192.168.20.10"
REDE_CLIENTES = "192.168.10.0/24"


def resultado(hipotese, confianca, evidencias):
    return {
        "hipotese": hipotese,
        "confianca": confianca,
        "evidencias": evidencias,
    }


def extrair_saida(dados, *caminho):
    atual = dados

    for chave in caminho:
        if not isinstance(atual, dict):
            return ""

        atual = atual.get(chave)

    if not isinstance(atual, dict):
        return ""

    if atual.get("sucesso") is not True:
        return ""

    return atual.get("saida", "")


def interface_desativada(cliente, nome):
    saida = extrair_saida(
        cliente, "interfaces", "estado"
    )

    for linha in saida.splitlines():
        campos = linha.split()

        if not campos:
            continue

        interface = campos[0].split("@")[0]

        if interface != f"{nome}-eth0":
            continue

        if len(campos) > 1 and campos[1] == "DOWN":
            return True

        return False

    return None


def rota_padrao_ausente(cliente):
    rotas = cliente.get("rotas", {})

    if rotas.get("sucesso") is not True:
        return None

    saida = rotas.get("saida", "")

    for linha in saida.splitlines():
        if linha.startswith("default "):
            return False

    return True


def bloqueio_http_acl(servidor):
    saida = extrair_saida(servidor, "acl")

    if not saida:
        return False

    for linha in saida.splitlines():
        if not re.search(r"-j\s+(DROP|REJECT)\b", linha):
            continue

        # A regra deve mencionar TCP/porta HTTP.
        if not re.search(r"--dport\s+80\b", linha):
            continue

        if not re.search(r"-p\s+tcp\b", linha):
            continue

        # Bloqueio esperado para o client1
        if not re.search(r"-s\s+192\.168\.10\.2(?:/32)?\b", linha):
            continue

        return True

    return False


def diagnosticar_cliente(
    evidencias,
    nome="client1",
    servidor=None,
    latencia_referencia=None,
):
    ping = evidencias.get("ping", {})
    dns = evidencias.get("dns", {})
    http = evidencias.get("http", {})

    conectividade = ping.get("sucesso")
    resolucao = dns.get("resolucao_correta")
    servico_http = http.get("servico_disponivel")

    # 1. Estado da interface
    estado_interface = interface_desativada(
        evidencias, nome
    )

    if estado_interface is True:
        return resultado(
            "falha_de_interface",
            "alta",
            [
                f"Interface {nome}-eth0 encontra-se DOWN."
            ]
        )

    # 2. Roteamento
    rota_ausente = rota_padrao_ausente(evidencias)

    if rota_ausente is True and conectividade is False:
        return resultado(
            "falha_de_roteamento",
            "alta",
            [
                "Rota padrao ausente.",
                "Ping para o servidor falhou.",
            ]
        )

    # 3. Falta de evidencias
    if any(
        valor is None
        for valor in (
            conectividade,
            resolucao,
            servico_http,
        )
    ):
        return resultado(
            "evidencias_insuficientes",
            "indeterminada",
            ["Resultado de teste ausente."]
        )

    # 4. Falha geral de conectividade
    if conectividade is False:
        return resultado(
            "falha_de_conectividade",
            "limitada",
            [
                "Ping falhou.",
                "Causa nao confirmada pelas evidencias."
            ]
        )

    # 5. DNS
    if resolucao is False:
        return resultado(
            "problema_dns",
            "indicativa",
            [
                "Conectividade IP funcionando.",
                "Teste de resolucao DNS falhou.",
            ]
        )

    # 6. HTTP e ACL
    if servico_http is False:
        if (
            nome == "client1"
            and servidor is not None
            and bloqueio_http_acl(servidor)
        ):
            return resultado(
                "bloqueio_acl",
                "alta",
                [
                    "Ping e DNS funcionando.",
                    "HTTP indisponivel.",
                    "Regra TCP/80 DROP ou REJECT "
                    "encontrada no servidor para client1.",
                ]
            )

        return resultado(
            "problema_http_ou_bloqueio",
            "indicativa",
            [
                "Ping e DNS funcionando.",
                "HTTP indisponivel.",
                "Causa nao confirmada.",
            ]
        )

    # 7. Latencia e possivel congestionamento
    latencia = ping.get("latencia_media_ms")

    if isinstance(latencia, (int, float)):
        if (
            isinstance(latencia_referencia, (int, float))
            and latencia_referencia > 0
            and latencia >= latencia_referencia * 3
            and latencia - latencia_referencia >= 50
        ):
            return resultado(
                "possivel_congestionamento",
                "indicativa",
                [
                    f"Latencia atual: {latencia:.3f} ms.",
                    f"Referencia: {latencia_referencia:.3f} ms.",
                    "Aumento expressivo de latencia.",
                ]
            )

        if latencia > 150:
            return resultado(
                "latencia_elevada",
                "indicativa",
                [
                    f"Latencia observada: {latencia:.3f} ms.",
                    "Investigar possivel congestionamento.",
                ]
            )

    # 8. Funcionamento normal
    return resultado(
        "sem_anomalia_detectada",
        "limitada",
        [
            "Ping, DNS e HTTP funcionando.",
            "Nenhuma anomalia identificada pelos testes."
        ]
    )
