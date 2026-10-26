"""Camada de Execucao Controlada e Sanitizacao Anti-Vazamento (Etapa 7).

Garante duas propriedades criticas de seguranca e validade cientifica:
  1. Anti-vazamento: remove metadados de cenario/rotulo das evidencias antes
     de disponibiliza-las ao Agente LLM e proibe leitura de gabaritos.
  2. Execucao condicionada: nenhuma operacao e executada sem um objeto de
     decisao com autorizado == True e comando_canonico emitido pelo
     ValidadorDeterministico (shell=False em todas as chamadas).
"""
import copy
import json
import re
import subprocess
import time
from pathlib import Path

from seguranca.politicas import DISPOSITIVOS_AUTORIZADOS, SERVIDOR_PRINCIPAL_IP


CAMPOS_RAIZ_SENSIVEIS = frozenset({
    "cenario",
    "rotulo",
    "causa_real",
    "gabarito",
    "esperado",
})

PADROES_GABARITO_PROIBIDOS = (
    "gabarito",
    "causas_reais",
    "resultados_avaliacao",
)


def verificar_arquivo_evidencia_permitido(caminho):
    """Impede que o agente carregue arquivos de gabarito como entrada."""
    caminho_str = str(Path(caminho).resolve()).lower().replace("\\", "/")
    for padrao in PADROES_GABARITO_PROIBIDOS:
        if padrao in caminho_str:
            raise PermissionError(
                f"Acesso bloqueado: '{caminho}' pertence ao conjunto restrito de avaliacao/gabarito."
            )


def sanitizar_evidencias_brutas(dados):
    """Remove qualquer metadado que possa revelar o nome do cenario ao agente."""
    if not isinstance(dados, dict):
        raise ValueError("As evidencias devem ser um dicionario JSON.")

    limpo = {}
    for chave, valor in dados.items():
        if chave.lower() in CAMPOS_RAIZ_SENSIVEIS:
            continue
        limpo[chave] = copy.deepcopy(valor)
    return limpo


def extrair_visao_inicial_progressiva(evidencias_sanitizadas, dispositivo_alvo="client1"):
    """Monta a observacao inicial minima para investigacao multi-etapa.

    No modo progressivo, o agente inicia apenas com o contexto da topologia
    (IPs do servidor e dominio experimental) e precisa propor testes validados
    pelo ValidadorDeterministico para coletar estado de interfaces, rotas,
    conectividade, DNS, HTTP, ACL e desempenho.
    """
    return {
        "servidor": evidencias_sanitizadas.get("servidor", SERVIDOR_PRINCIPAL_IP),
        "dominio": evidencias_sanitizadas.get("dominio", "app.lab.local"),
        "enlace_servidor_mbps": evidencias_sanitizadas.get("enlace_servidor_mbps"),
        "dispositivo_sob_investigacao": dispositivo_alvo,
        "observacoes_coletadas": {
            nome: {} for nome in DISPOSITIVOS_AUTORIZADOS
        },
    }


def _exigir_decisao_autorizada(decisao):
    if not isinstance(decisao, dict) or decisao.get("autorizado") is not True:
        motivo = decisao.get("motivo", "Solicitacao nao validada") if isinstance(decisao, dict) else "Decisao ausente"
        raise PermissionError(
            f"Execucao bloqueada pela camada de seguranca: {motivo}"
        )
    cmd = decisao.get("comando_canonico")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
        raise PermissionError(
            "Execucao bloqueada: comando_canonico ausente ou invalido na decisao."
        )


class ExecutorEvidenciasOffline:
    """Executa testes autorizados consultando evidencias ja coletadas do Mininet.

    Permite reproduzir integralmente o ciclo multi-etapa do agente + validador
    sobre logs/evidencias_caso_XX.json sem exigir Mininet ativo no momento da
    analise, mantendo a mesma semantica de autorizacao deterministica.
    """

    def __init__(self, dados_evidencias, dados_desempenho=None):
        self.evidencias = sanitizar_evidencias_brutas(dados_evidencias)
        self.dispositivos = self.evidencias.get("dispositivos", {})
        self.dados_desempenho = copy.deepcopy(dados_desempenho) if dados_desempenho else None

    def executar_decisao(self, decisao):
        """Retorna a evidencia correspondente somente se decisao['autorizado'] == True."""
        _exigir_decisao_autorizada(decisao)

        operacao = decisao["operacao"]
        dispositivo = decisao["dispositivo"]
        params = decisao.get("parametros_normalizados", {})
        dados_disp = self.dispositivos.get(dispositivo, {})

        if operacao == "consultar_interfaces":
            sub = params.get("subcomando", "estado")
            interfaces = dados_disp.get("interfaces", {})
            bloco = interfaces.get(sub) if isinstance(interfaces, dict) else None
            if isinstance(bloco, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "subcomando": sub, "dados": copy.deepcopy(bloco)}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": f"Campo interfaces.{sub} ausente no log coletado."}

        if operacao == "consultar_rotas":
            rotas = dados_disp.get("rotas")
            if isinstance(rotas, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(rotas)}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": "Tabela de rotas ausente no log coletado."}

        if operacao == "consultar_acl":
            acl = dados_disp.get("acl")
            if isinstance(acl, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(acl)}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": f"Regras ACL de {dispositivo} ausentes no log coletado."}

        if operacao == "consultar_tc":
            tc = dados_disp.get("tc")
            if isinstance(tc, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(tc)}
            return {
                "sucesso_execucao": False,
                "operacao": operacao,
                "indisponivel_no_registro_offline": True,
                "aviso": "Coleta offline nao contem saida bruta de 'tc -s qdisc show'; utilize latencia ICMP ou vazao.",
            }

        if operacao == "testar_ping":
            ping = dados_disp.get("ping")
            if isinstance(ping, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(ping)}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": "Resultado de ping ausente no log coletado."}

        if operacao == "testar_dns":
            dns = dados_disp.get("dns")
            if isinstance(dns, dict):
                copia_dns = copy.deepcopy(dns)
                if "perfil_dns" in dados_disp and "dns_configurado_no_perfil" not in copia_dns:
                    copia_dns["dns_configurado_no_perfil"] = dados_disp["perfil_dns"]
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copia_dns}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": "Resultado de DNS ausente no log coletado."}

        if operacao == "testar_http":
            http = dados_disp.get("http")
            if isinstance(http, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(http)}
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": "Resultado de HTTP ausente no log coletado."}

        if operacao == "investigar_caminho":
            rotas = dados_disp.get("rotas", {})
            saida_rotas = rotas.get("saida", "") if isinstance(rotas, dict) else ""
            destino = params.get("destino", SERVIDOR_PRINCIPAL_IP)
            if "default via " in saida_rotas:
                return {
                    "sucesso_execucao": True,
                    "operacao": operacao,
                    "dados": {
                        "sucesso": True,
                        "destino": destino,
                        "saida": f"{destino} via 192.168.10.1 dev {dispositivo}-eth0 src 192.168.10.x",
                    },
                }
            return {
                "sucesso_execucao": True,
                "operacao": operacao,
                "dados": {
                    "sucesso": False,
                    "destino": destino,
                    "saida": "RTNETLINK answers: Network is unreachable",
                },
            }

        if operacao == "testar_desempenho":
            desemp = dados_disp.get("desempenho")
            if isinstance(desemp, dict):
                return {"sucesso_execucao": True, "operacao": operacao, "dados": copy.deepcopy(desemp)}
            return {
                "sucesso_execucao": False,
                "operacao": operacao,
                "indisponivel_no_registro_offline": True,
                "aviso": (
                    "Medicao ativa iperf3 nao consta neste JSON estatico de evidencias; "
                    "avalie congestionamento pela latencia_media_ms do ping frente a referencia."
                ),
            }

        return {"sucesso_execucao": False, "operacao": operacao, "aviso": "Operacao sem mapeamento offline."}


class ExecutorMininetAtivo:
    """Executa comandos canonicos aprovados diretamente nos namespaces Mininet."""

    def __init__(self, rede, dns_clientes=None):
        self.rede = rede
        self.dns_clientes = dns_clientes or {}

    def executar_decisao(self, decisao, timeout_padrao=8):
        _exigir_decisao_autorizada(decisao)

        operacao = decisao["operacao"]
        dispositivo = decisao["dispositivo"]
        params = decisao.get("parametros_normalizados", {})
        comando = list(decisao["comando_canonico"])

        # Respeita perfil DNS experimental do cliente quando usar_perfil_cliente=True
        if operacao == "testar_dns" and params.get("usar_perfil_cliente", True):
            servidor_perfil = self.dns_clientes.get(dispositivo)
            if servidor_perfil:
                comando[1] = f"@{servidor_perfil}"

        host = self.rede.get(dispositivo)
        if host is None:
            return {"sucesso_execucao": False, "operacao": operacao, "aviso": f"Host {dispositivo} nao encontrado no Mininet."}

        timeout = int(params.get("duracao_s", params.get("max_time_s", params.get("timeout_s", timeout_padrao)))) + 5
        inicio = time.monotonic()
        proc = host.popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        try:
            saida_bytes, _ = proc.communicate(timeout=timeout)
            expirado = False
        except subprocess.TimeoutExpired:
            proc.kill()
            saida_bytes, _ = proc.communicate()
            expirado = True

        duracao_ms = round((time.monotonic() - inicio) * 1000, 2)
        saida = saida_bytes.decode("utf-8", errors="replace")[:12000]
        dados = {
            "sucesso": (not expirado) and (proc.returncode == 0),
            "codigo_retorno": proc.returncode,
            "timeout": expirado,
            "duracao_execucao_ms": duracao_ms,
            "saida": saida,
        }

        if operacao == "testar_ping":
            perda = re.search(r"([\d.]+)% packet loss", saida)
            rtt = re.search(
                r"(?:rtt|round-trip) min/avg/max(?:/mdev|/stddev)? = ([\d.]+)/([\d.]+)/([\d.]+)",
                saida,
            )
            dados["destino"] = params.get("destino", SERVIDOR_PRINCIPAL_IP)
            dados["pacotes_enviados"] = params.get("pacotes", 3)
            dados["perda_percentual"] = float(perda.group(1)) if perda else None
            dados["latencia_media_ms"] = float(rtt.group(2)) if rtt else None

        elif operacao == "testar_dns":
            enderecos = [l.strip() for l in saida.splitlines() if l.strip() and not l.startswith(";")]
            srv_usado = comando[1].lstrip("@") if len(comando) > 1 else SERVIDOR_PRINCIPAL_IP
            dados["dominio"] = params.get("dominio", "app.lab.local")
            dados["dns_configurado_no_perfil"] = srv_usado
            dados["enderecos_resolvidos"] = enderecos
            dados["resolucao_correta"] = bool(dados["sucesso"] and SERVIDOR_PRINCIPAL_IP in enderecos)

        elif operacao == "testar_http":
            cod = saida.strip()
            dados["url"] = params.get("url", f"http://{SERVIDOR_PRINCIPAL_IP}/")
            dados["codigo_http"] = int(cod) if cod.isdigit() else None
            dados["servico_disponivel"] = bool(dados["sucesso"] and cod.isdigit() and 200 <= int(cod) < 400)

        elif operacao == "testar_desempenho" and dados["sucesso"]:
            try:
                j = json.loads(saida)
                bps = j.get("end", {}).get("sum_received", {}).get("bits_per_second")
                dados["vazao_mbps"] = round(bps / 1_000_000, 3) if bps is not None else None
            except (ValueError, TypeError):
                dados["vazao_mbps"] = None

        return {"sucesso_execucao": True, "operacao": operacao, "dados": dados}
