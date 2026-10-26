"""Validador Deterministico de Seguranca para acoes propostas pelo Agente LLM.

Implementa os 7 portoes (gates) explicitos previstos na Secao 2.8 e 4.3 da
monografia:
  1. Sintaxe e bloqueio de metacaracteres/injecao de shell
  2. Operacao solicitada e proibicao de comandos destrutivos/alteracao
  3. Permissoes do dispositivo de origem (conforme politica 'padrao'/'restritiva')
  4. Escopo do destino (IPs, sub-redes, portas e dominios do laboratorio)
  5. Parametros e tipos de argumentos
  6. Limites de duracao (timeouts e tempo de sonda)
  7. Limites de quantidade/volume de trafego (pacotes, bytes, fluxos, flood)

A decisao de autorizacao e tomada de forma 100% deterministica, ignorando
qualquer argumento retorico ou tentativa de persuasao na justificativa textual
fornecida pelo LLM (mitigacao de OWASP Excessive Agency / Prompt Injection).
"""
import shlex
from datetime import datetime, timezone

from seguranca.politicas import (
    BINARIOS_ESTRITAMENTE_PROIBIDOS,
    DISPOSITIVOS_AUTORIZADOS,
    DOMINIOS_AUTORIZADOS,
    METACARACTERES_SHELL_PROIBIDOS,
    SERVIDOR_PRINCIPAL_IP,
    URLS_HTTP_AUTORIZADAS,
    ip_no_escopo_laboratorio,
    obter_politica,
)


CODIGOS_DECISAO = (
    "AUTORIZADO",
    "SINTAXE_INVALIDA",
    "INJECAO_SHELL_DETECTADA",
    "COMANDO_DESTRUTIVO_OU_ALTERACAO",
    "OPERACAO_NAO_PERMITIDA",
    "BLOQUEADO_POLITICA_RESTRITIVA",
    "ORIGEM_SEM_PERMISSAO",
    "DESTINO_FORA_DO_ESCOPO",
    "PARAMETRO_INVALIDO",
    "LIMITE_DURACAO_EXCEDIDO",
    "LIMITE_TRAFEGO_EXCEDIDO",
)


def _inteiro_estrito(valor):
    """Converte para int rejeitando bool, float nao inteiro e strings malformadas."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.strip().lstrip("-").isdigit():
        return int(valor.strip())
    return None


class ValidadorDeterministico:
    """Interceptador deterministico de seguranca entre o Agente LLM e a rede."""

    def __init__(self, politica="padrao"):
        self.config_politica = obter_politica(politica)
        self.nome_politica = self.config_politica["nome"]

    def _decisao(
        self,
        autorizado,
        codigo_motivo,
        motivo,
        aspecto_verificado,
        operacao="",
        dispositivo="",
        parametros_normalizados=None,
        comando_canonico=None,
        solicitacao_original=None,
    ):
        return {
            "autorizado": bool(autorizado),
            "codigo_motivo": codigo_motivo,
            "motivo": motivo,
            "aspecto_verificado": aspecto_verificado,
            "politica": self.nome_politica,
            "operacao": operacao or "desconhecida",
            "dispositivo": dispositivo or "indefinido",
            "parametros_normalizados": parametros_normalizados or {},
            "comando_canonico": list(comando_canonico) if comando_canonico else None,
            "justificativa_ignorada_na_decisao": True,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "solicitacao_original": solicitacao_original,
        }

    def _contem_metacaracteres_shell(self, texto):
        if not isinstance(texto, str):
            return None
        for meta in METACARACTERES_SHELL_PROIBIDOS:
            if meta in texto:
                return meta
        return None

    def _inspecionar_strings_recursivo(self, obj):
        if isinstance(obj, str):
            achado = self._contem_metacaracteres_shell(obj)
            if achado is not None:
                return achado
        elif isinstance(obj, dict):
            for k, v in obj.items():
                # A justificativa textual nao entra jamais em comando_canonico,
                # mas todos os campos operacionais e chaves sao inspecionados.
                if k == "justificativa":
                    continue
                achado = self._inspecionar_strings_recursivo(k) or self._inspecionar_strings_recursivo(v)
                if achado is not None:
                    return achado
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                achado = self._inspecionar_strings_recursivo(item)
                if achado is not None:
                    return achado
        return None

    # ------------------------------------------------------------------
    # Validacao de comandos CLI brutos (quando propostos em formato texto)
    # ------------------------------------------------------------------

    def validar_comando_cli(self, dispositivo, comando, justificativa=""):
        """Analisa sintaticamente um comando CLI bruto e aplica os 7 portoes."""
        original = {
            "dispositivo": dispositivo,
            "comando_bruto": comando,
            "justificativa": justificativa,
        }

        if isinstance(comando, str):
            if not comando.strip():
                return self._decisao(
                    False, "SINTAXE_INVALIDA",
                    "Comando CLI vazio ou ausente.",
                    "sintaxe", dispositivo=dispositivo, solicitacao_original=original,
                )
            meta = self._contem_metacaracteres_shell(comando)
            if meta is not None:
                return self._decisao(
                    False, "INJECAO_SHELL_DETECTADA",
                    f"Metacaractere ou operador de shell proibido detectado: {repr(meta)}.",
                    "sintaxe", dispositivo=dispositivo, solicitacao_original=original,
                )
            try:
                tokens = shlex.split(comando)
            except ValueError as exc:
                return self._decisao(
                    False, "SINTAXE_INVALIDA",
                    f"Erro sintatico ao analisar argumentos CLI: {exc}",
                    "sintaxe", dispositivo=dispositivo, solicitacao_original=original,
                )
        elif isinstance(comando, (list, tuple)) and comando and all(isinstance(t, str) for t in comando):
            for tok in comando:
                meta = self._contem_metacaracteres_shell(tok)
                if meta is not None:
                    return self._decisao(
                        False, "INJECAO_SHELL_DETECTADA",
                        f"Metacaractere proibido em argumento CLI: {repr(meta)}.",
                        "sintaxe", dispositivo=dispositivo, solicitacao_original=original,
                    )
            tokens = list(comando)
        else:
            return self._decisao(
                False, "SINTAXE_INVALIDA",
                "Formato de comando CLI invalido.",
                "sintaxe", dispositivo=dispositivo, solicitacao_original=original,
            )

        binario = tokens[0].split("/")[-1]

        # Gate 2A: Binarios administrativos ou destrutivos
        if binario in BINARIOS_ESTRITAMENTE_PROIBIDOS:
            return self._decisao(
                False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                f"Binario '{binario}' proibido: operacoes destrutivas, shells ou alteracao de sistema nao sao permitidas.",
                "operacao", operacao=binario, dispositivo=dispositivo, solicitacao_original=original,
            )

        # Gate 2B: Subcomandos de alteracao nas ferramentas de rede conhecidas
        traducao = self._traduzir_cli_para_estruturado(binario, tokens[1:], dispositivo, original)
        if "autorizado" in traducao:
            return traducao

        return self.validar_solicitacao(traducao)

    def _traduzir_cli_para_estruturado(self, binario, args, dispositivo, original):
        """Converte apenas sintaxes CLI reconhecidas em solicitacoes estruturadas."""
        if binario == "ip":
            if any(sub in args for sub in ("set", "add", "del", "delete", "replace", "change", "flush", "netns", "restore")):
                return self._decisao(
                    False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                    "Subcomando de alteracao do iproute2 bloqueado (apenas leitura de link, addr e route e permitida).",
                    "operacao", operacao="ip_alteracao", dispositivo=dispositivo, solicitacao_original=original,
                )
            if args in (["-br", "link"], ["link", "show"], ["link"]):
                return {"operacao": "consultar_interfaces", "dispositivo": dispositivo,
                        "parametros": {"subcomando": "estado"}, "_original": original}
            if args in (["-br", "addr"], ["addr", "show"], ["addr"], ["address", "show"]):
                return {"operacao": "consultar_interfaces", "dispositivo": dispositivo,
                        "parametros": {"subcomando": "enderecos"}, "_original": original}
            if args == ["-s", "link"]:
                return {"operacao": "consultar_interfaces", "dispositivo": dispositivo,
                        "parametros": {"subcomando": "estatisticas"}, "_original": original}
            if args in (["route", "show"], ["route"], ["route", "list"]):
                return {"operacao": "consultar_rotas", "dispositivo": dispositivo,
                        "parametros": {}, "_original": original}
            if len(args) == 3 and args[:2] == ["route", "get"]:
                return {"operacao": "investigar_caminho", "dispositivo": dispositivo,
                        "parametros": {"destino": args[2], "modo": "ip_route_get"}, "_original": original}
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Argumentos nao homologados para 'ip': {' '.join(args)}",
                "parametros", operacao="ip", dispositivo=dispositivo, solicitacao_original=original,
            )

        if binario == "iptables":
            flags_alteracao = {"-A", "-I", "-D", "-R", "-F", "-Z", "-N", "-X", "-P", "-E",
                               "--append", "--insert", "--delete", "--replace", "--flush", "--policy"}
            if any(a in flags_alteracao for a in args):
                return self._decisao(
                    False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                    "Modificacao de regras iptables (-A/-I/-D/-F/-P) bloqueada: o agente possui permissao apenas de leitura.",
                    "operacao", operacao="iptables_alteracao", dispositivo=dispositivo, solicitacao_original=original,
                )
            if args == ["-S"]:
                return {"operacao": "consultar_acl", "dispositivo": dispositivo,
                        "parametros": {}, "_original": original}
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Apenas 'iptables -S' e permitido para inspecao de ACL.",
                "parametros", operacao="consultar_acl", dispositivo=dispositivo, solicitacao_original=original,
            )

        if binario == "tc":
            if any(sub in args for sub in ("add", "del", "delete", "change", "replace", "link")):
                return self._decisao(
                    False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                    "Alteracao de disciplinas de fila (tc add/del/change/replace) bloqueada.",
                    "operacao", operacao="tc_alteracao", dispositivo=dispositivo, solicitacao_original=original,
                )
            if args in (["-s", "qdisc", "show"], ["qdisc", "show"]):
                return {"operacao": "consultar_tc", "dispositivo": dispositivo,
                        "parametros": {}, "_original": original}
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Apenas 'tc -s qdisc show' e homologado para leitura de filas.",
                "parametros", operacao="consultar_tc", dispositivo=dispositivo, solicitacao_original=original,
            )

        if binario == "ping":
            if "-f" in args:
                return self._decisao(
                    False, "LIMITE_TRAFEGO_EXCEDIDO",
                    "Modo flood ('ping -f') estritamente proibido por risco de sobrecarga.",
                    "quantidade_trafego", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
                )
            pacotes = 3
            timeout_s = 2
            tamanho_bytes = 56
            destino = None
            idx = 0
            while idx < len(args):
                arg = args[idx]
                if arg == "-n":
                    idx += 1
                elif arg in ("-c", "-W", "-s", "-i"):
                    if idx + 1 >= len(args):
                        return self._decisao(
                            False, "SINTAXE_INVALIDA", f"Flag '{arg}' sem valor em ping.",
                            "sintaxe", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
                        )
                    val_str = args[idx + 1]
                    if arg == "-i":
                        try:
                            intervalo = float(val_str)
                        except ValueError:
                            return self._decisao(False, "PARAMETRO_INVALIDO", "Intervalo -i invalido.", "parametros",
                                                 operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original)
                        if intervalo < 0.2:
                            return self._decisao(
                                False, "LIMITE_TRAFEGO_EXCEDIDO",
                                "Intervalo de ping menor que 0.2s bloqueado por controle de taxa de trafego.",
                                "quantidade_trafego", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
                            )
                    elif arg == "-c":
                        pacotes = _inteiro_estrito(val_str)
                    elif arg == "-W":
                        timeout_s = _inteiro_estrito(val_str)
                    elif arg == "-s":
                        tamanho_bytes = _inteiro_estrito(val_str)
                    idx += 2
                elif arg.startswith("-"):
                    return self._decisao(
                        False, "PARAMETRO_INVALIDO", f"Flag nao permitida em ping: '{arg}'.",
                        "parametros", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
                    )
                else:
                    if destino is not None:
                        return self._decisao(
                            False, "PARAMETRO_INVALIDO", "Multiplos destinos nao permitidos em ping.",
                            "parametros", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
                        )
                    destino = arg
                    idx += 1

            return {
                "operacao": "testar_ping",
                "dispositivo": dispositivo,
                "parametros": {
                    "destino": destino,
                    "pacotes": pacotes,
                    "timeout_s": timeout_s,
                    "tamanho_bytes": tamanho_bytes,
                },
                "_original": original,
            }

        if binario == "dig":
            servidor_dns = SERVIDOR_PRINCIPAL_IP
            dominio = None
            tipo_registro = "A"
            timeout_s = 2
            tentativas = 1
            for arg in args:
                if arg.startswith("@"):
                    servidor_dns = arg[1:]
                elif arg.startswith("+time="):
                    timeout_s = _inteiro_estrito(arg.split("=", 1)[1])
                elif arg.startswith("+tries="):
                    tentativas = _inteiro_estrito(arg.split("=", 1)[1])
                elif arg == "+short":
                    continue
                elif arg.upper() in ("A", "AAAA", "AXFR", "IXFR", "ANY", "MX", "TXT", "NS", "PTR"):
                    tipo_registro = arg.upper()
                elif arg.startswith("-") or arg.startswith("+"):
                    return self._decisao(
                        False, "PARAMETRO_INVALIDO", f"Opcao nao permitida em dig: '{arg}'.",
                        "parametros", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
                    )
                else:
                    dominio = arg

            return {
                "operacao": "testar_dns",
                "dispositivo": dispositivo,
                "parametros": {
                    "servidor_dns": servidor_dns,
                    "dominio": dominio,
                    "tipo_registro": tipo_registro,
                    "timeout_s": timeout_s,
                    "tentativas": tentativas,
                },
                "_original": original,
            }

        if binario == "curl":
            flags_proibidas = {"-d", "--data", "--data-raw", "--data-binary", "-F", "--form",
                               "-T", "--upload-file", "-o"}
            metodo = "GET"
            connect_timeout = 3
            max_time = 5
            url = None
            idx = 0
            while idx < len(args):
                arg = args[idx]
                if arg in ("-s", "-S", "-sS", "--silent", "--show-error", "-I", "--head"):
                    if arg in ("-I", "--head"):
                        metodo = "HEAD"
                    idx += 1
                elif arg in ("-X", "--request") and idx + 1 < len(args):
                    metodo = args[idx + 1].upper()
                    idx += 2
                elif arg == "--connect-timeout" and idx + 1 < len(args):
                    connect_timeout = _inteiro_estrito(args[idx + 1])
                    idx += 2
                elif arg in ("-m", "--max-time") and idx + 1 < len(args):
                    max_time = _inteiro_estrito(args[idx + 1])
                    idx += 2
                elif arg in ("--noproxy", "--write-out", "-w") and idx + 1 < len(args):
                    idx += 2
                elif arg in ("--output", "-o") and idx + 1 < len(args):
                    if args[idx + 1] != "/dev/null":
                        return self._decisao(
                            False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                            "Escrita de saida em arquivo local via curl nao e permitida (exceto /dev/null).",
                            "parametros", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
                        )
                    idx += 2
                elif arg in flags_proibidas or arg.startswith("-"):
                    return self._decisao(
                        False, "PARAMETRO_INVALIDO", f"Opcao curl nao permitida: '{arg}'.",
                        "parametros", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
                    )
                else:
                    url = arg
                    idx += 1

            return {
                "operacao": "testar_http",
                "dispositivo": dispositivo,
                "parametros": {
                    "url": url,
                    "metodo": metodo,
                    "connect_timeout_s": connect_timeout,
                    "max_time_s": max_time,
                },
                "_original": original,
            }

        if binario == "iperf3":
            if "-s" in args or "--server" in args:
                return self._decisao(
                    False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                    "Inicializacao de daemon servidor ('iperf3 -s') nao e permitida ao agente.",
                    "operacao", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
                )
            if "-u" in args or "--udp" in args or "-b" in args or "--bitrate" in args:
                return self._decisao(
                    False, "LIMITE_TRAFEGO_EXCEDIDO",
                    "Modo UDP ou injecao de taxa arbitraria em iperf3 bloqueado por controle de trafego.",
                    "quantidade_trafego", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
                )
            destino = None
            porta = 5202
            duracao_s = 3
            fluxos = 1
            idx = 0
            while idx < len(args):
                arg = args[idx]
                if arg in ("-J", "--json"):
                    idx += 1
                elif arg in ("-c", "-p", "-t", "-P") and idx + 1 < len(args):
                    val = args[idx + 1]
                    if arg == "-c":
                        destino = val
                    elif arg == "-p":
                        porta = _inteiro_estrito(val)
                    elif arg == "-t":
                        duracao_s = _inteiro_estrito(val)
                    elif arg == "-P":
                        fluxos = _inteiro_estrito(val)
                    idx += 2
                else:
                    return self._decisao(
                        False, "PARAMETRO_INVALIDO", f"Parametro nao permitido em iperf3: '{arg}'.",
                        "parametros", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
                    )

            return {
                "operacao": "testar_desempenho",
                "dispositivo": dispositivo,
                "parametros": {
                    "destino": destino,
                    "porta": porta,
                    "duracao_s": duracao_s,
                    "fluxos": fluxos,
                },
                "_original": original,
            }

        if binario == "traceroute":
            destino = None
            max_saltos = 4
            timeout_s = 2
            idx = 0
            while idx < len(args):
                arg = args[idx]
                if arg == "-n":
                    idx += 1
                elif arg in ("-m", "-w") and idx + 1 < len(args):
                    if arg == "-m":
                        max_saltos = _inteiro_estrito(args[idx + 1])
                    else:
                        timeout_s = _inteiro_estrito(args[idx + 1])
                    idx += 2
                elif arg.startswith("-"):
                    return self._decisao(
                        False, "PARAMETRO_INVALIDO", f"Flag nao permitida em traceroute: '{arg}'.",
                        "parametros", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
                    )
                else:
                    destino = arg
                    idx += 1
            return {
                "operacao": "investigar_caminho",
                "dispositivo": dispositivo,
                "parametros": {
                    "destino": destino,
                    "modo": "traceroute",
                    "max_saltos": max_saltos,
                    "timeout_s": timeout_s,
                },
                "_original": original,
            }

        return self._decisao(
            False, "OPERACAO_NAO_PERMITIDA",
            f"Utilitario '{binario}' nao pertence ao conjunto de ferramentas diagnosticas autorizadas.",
            "operacao", operacao=binario, dispositivo=dispositivo, solicitacao_original=original,
        )

    # ------------------------------------------------------------------
    # Validacao principal de solicitacoes estruturadas
    # ------------------------------------------------------------------

    def validar_solicitacao(self, solicitacao):
        """Valida uma solicitacao estruturada de teste pelos 7 portoes de seguranca."""
        if not isinstance(solicitacao, dict):
            return self._decisao(
                False, "SINTAXE_INVALIDA",
                "A solicitacao de teste deve ser um objeto estruturado (dict).",
                "sintaxe", solicitacao_original=solicitacao,
            )

        original = solicitacao.get("_original") or {
            k: v for k, v in solicitacao.items() if k != "_original"
        }

        # Se o modelo enviou apenas comando_bruto em vez de operacao estruturada
        if "comando_bruto" in solicitacao and not solicitacao.get("operacao"):
            return self.validar_comando_cli(
                solicitacao.get("dispositivo", ""),
                solicitacao.get("comando_bruto", ""),
                solicitacao.get("justificativa", ""),
            )

        operacao = solicitacao.get("operacao")
        dispositivo = solicitacao.get("dispositivo")
        parametros = solicitacao.get("parametros")

        # Gate 1: Sintaxe e injecao de shell em qualquer campo operacional
        if not isinstance(operacao, str) or not operacao.strip():
            return self._decisao(
                False, "SINTAXE_INVALIDA",
                "Campo 'operacao' ausente ou invalido.",
                "sintaxe", dispositivo=str(dispositivo or ""), solicitacao_original=original,
            )
        if not isinstance(dispositivo, str) or not dispositivo.strip():
            return self._decisao(
                False, "SINTAXE_INVALIDA",
                "Campo 'dispositivo' ausente ou invalido.",
                "sintaxe", operacao=operacao, solicitacao_original=original,
            )
        if parametros is None:
            parametros = {}
        if not isinstance(parametros, dict):
            return self._decisao(
                False, "SINTAXE_INVALIDA",
                "Campo 'parametros' deve ser um dicionario.",
                "sintaxe", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        meta = self._inspecionar_strings_recursivo({
            "operacao": operacao,
            "dispositivo": dispositivo,
            "parametros": parametros,
        })
        if meta is not None:
            return self._decisao(
                False, "INJECAO_SHELL_DETECTADA",
                f"Sequencia proibida de shell detectada nos parametros: {repr(meta)}.",
                "sintaxe", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        operacao = operacao.strip()
        dispositivo = dispositivo.strip()

        # Gate 2: Operacao permitida vs destrutiva vs bloqueada pela politica ativa
        nomes_alteracao = {
            "alterar_interface", "desativar_interface", "ativar_interface",
            "adicionar_rota", "remover_rota", "alterar_rota",
            "alterar_acl", "limpar_firewall", "reiniciar_servico",
            "executar_shell", "aplicar_correcao",
        }
        if operacao in nomes_alteracao or operacao.startswith(("alterar_", "remover_", "deletar_", "reiniciar_", "aplicar_")):
            return self._decisao(
                False, "COMANDO_DESTRUTIVO_OU_ALTERACAO",
                f"Operacao '{operacao}' bloqueada: o agente nao tem permissao para executar correcoes ou alterar configuracoes.",
                "operacao", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        bloqueadas_politica = self.config_politica.get("operacoes_bloqueadas_pela_politica", {})
        if operacao in bloqueadas_politica:
            return self._decisao(
                False, "BLOQUEADO_POLITICA_RESTRITIVA",
                bloqueadas_politica[operacao],
                "operacao", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        regras_operacoes = self.config_politica["operacoes"]
        if operacao not in regras_operacoes:
            return self._decisao(
                False, "OPERACAO_NAO_PERMITIDA",
                f"Operacao '{operacao}' nao reconhecida ou fora do catalogo diagnostico.",
                "operacao", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        regra = regras_operacoes[operacao]

        # Gate 3: Permissoes do dispositivo de origem
        if dispositivo not in DISPOSITIVOS_AUTORIZADOS:
            return self._decisao(
                False, "ORIGEM_SEM_PERMISSAO",
                f"Dispositivo '{dispositivo}' nao existe ou nao e autorizado no laboratorio.",
                "permissoes", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        if dispositivo not in regra["origens_permitidas"]:
            # Diferencia restricao adicional da politica restritiva vs proibicao geral
            politica_padrao_origens = obter_politica("padrao")["operacoes"].get(operacao, {}).get("origens_permitidas", ())
            if self.nome_politica == "restritiva" and dispositivo in politica_padrao_origens:
                return self._decisao(
                    False, "BLOQUEADO_POLITICA_RESTRITIVA",
                    f"A politica restritiva bloqueia '{operacao}' no dispositivo '{dispositivo}'; busque evidencias alternativas nos clientes permitidos.",
                    "permissoes", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
                )
            return self._decisao(
                False, "ORIGEM_SEM_PERMISSAO",
                f"Dispositivo '{dispositivo}' nao possui permissao para executar '{operacao}'. Origens permitidas: {list(regra['origens_permitidas'])}.",
                "permissoes", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )

        # Gates 4, 5, 6 e 7 especificos por operacao
        metodo_validador = getattr(self, f"_validar_{operacao}")
        return metodo_validador(dispositivo, parametros, regra, original)

    def _rejeitar_chaves_extras(self, operacao, dispositivo, parametros, permitidas, original):
        extras = set(parametros.keys()) - set(permitidas)
        if extras:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Parametros nao reconhecidos para '{operacao}': {sorted(extras)}.",
                "parametros", operacao=operacao, dispositivo=dispositivo, solicitacao_original=original,
            )
        return None

    def _validar_consultar_interfaces(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras("consultar_interfaces", dispositivo, parametros, ("subcomando",), original)
        if erro:
            return erro
        sub = parametros.get("subcomando", "estado")
        if sub not in regra["subcomandos_permitidos"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Subcomando '{sub}' invalido. Permitidos: {list(regra['subcomandos_permitidos'])}.",
                "parametros", operacao="consultar_interfaces", dispositivo=dispositivo, solicitacao_original=original,
            )
        mapa_cmd = {
            "estado": ["ip", "-br", "link"],
            "enderecos": ["ip", "-br", "addr"],
            "estatisticas": ["ip", "-s", "link"],
        }
        return self._decisao(
            True, "AUTORIZADO",
            f"Consulta somente leitura de interfaces ({sub}) autorizada em {dispositivo}.",
            "todos", operacao="consultar_interfaces", dispositivo=dispositivo,
            parametros_normalizados={"subcomando": sub},
            comando_canonico=mapa_cmd[sub],
            solicitacao_original=original,
        )

    def _validar_consultar_rotas(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras("consultar_rotas", dispositivo, parametros, (), original)
        if erro:
            return erro
        return self._decisao(
            True, "AUTORIZADO",
            f"Leitura da tabela de roteamento autorizada em {dispositivo}.",
            "todos", operacao="consultar_rotas", dispositivo=dispositivo,
            parametros_normalizados={},
            comando_canonico=["ip", "route", "show"],
            solicitacao_original=original,
        )

    def _validar_consultar_acl(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras("consultar_acl", dispositivo, parametros, (), original)
        if erro:
            return erro
        return self._decisao(
            True, "AUTORIZADO",
            f"Leitura de regras de filtragem (iptables -S) autorizada em {dispositivo}.",
            "todos", operacao="consultar_acl", dispositivo=dispositivo,
            parametros_normalizados={},
            comando_canonico=["iptables", "-S"],
            solicitacao_original=original,
        )

    def _validar_consultar_tc(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras("consultar_tc", dispositivo, parametros, (), original)
        if erro:
            return erro
        return self._decisao(
            True, "AUTORIZADO",
            f"Inspecao somente leitura de filas qdisc autorizada em {dispositivo}.",
            "todos", operacao="consultar_tc", dispositivo=dispositivo,
            parametros_normalizados={},
            comando_canonico=["tc", "-s", "qdisc", "show"],
            solicitacao_original=original,
        )

    def _validar_testar_ping(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras(
            "testar_ping", dispositivo, parametros,
            ("destino", "pacotes", "timeout_s", "tamanho_bytes", "flood"),
            original,
        )
        if erro:
            return erro

        if parametros.get("flood") is True:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                "Parametro flood nao permitido em testar_ping.",
                "quantidade_trafego", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )

        destino = parametros.get("destino", SERVIDOR_PRINCIPAL_IP)
        if not ip_no_escopo_laboratorio(destino):
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"Destino '{destino}' fora das sub-redes autorizadas do laboratorio (192.168.10.0/24 e 192.168.20.0/24).",
                "destino", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )

        pacotes = _inteiro_estrito(parametros.get("pacotes", 3))
        if pacotes is None or pacotes < regra["pacotes_min"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Quantidade de pacotes invalida para testar_ping.",
                "parametros", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )
        if pacotes > regra["pacotes_max"]:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Quantidade de pacotes ({pacotes}) excede o limite maximo da politica ({regra['pacotes_max']}).",
                "quantidade_trafego", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )

        timeout_s = _inteiro_estrito(parametros.get("timeout_s", 2))
        if timeout_s is None or timeout_s < regra["timeout_min_s"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Valor de timeout_s invalido para testar_ping.",
                "parametros", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )
        if timeout_s > regra["timeout_max_s"]:
            return self._decisao(
                False, "LIMITE_DURACAO_EXCEDIDO",
                f"Timeout ({timeout_s}s) excede o limite de duracao permitido ({regra['timeout_max_s']}s).",
                "duracao", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )

        tamanho_bytes = _inteiro_estrito(parametros.get("tamanho_bytes", 56))
        if tamanho_bytes is None or tamanho_bytes < 16:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Tamanho de pacote invalido em testar_ping.",
                "parametros", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )
        if tamanho_bytes > regra["tamanho_max_bytes"]:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Tamanho do pacote ICMP ({tamanho_bytes} bytes) excede o limite permitido ({regra['tamanho_max_bytes']} bytes).",
                "quantidade_trafego", operacao="testar_ping", dispositivo=dispositivo, solicitacao_original=original,
            )

        cmd = ["ping", "-n", "-c", str(pacotes), "-W", str(timeout_s)]
        if tamanho_bytes != 56:
            cmd.extend(["-s", str(tamanho_bytes)])
        cmd.append(destino)

        return self._decisao(
            True, "AUTORIZADO",
            f"Teste ICMP controlado autorizado ({pacotes} pacotes para {destino}).",
            "todos", operacao="testar_ping", dispositivo=dispositivo,
            parametros_normalizados={
                "destino": destino,
                "pacotes": pacotes,
                "timeout_s": timeout_s,
                "tamanho_bytes": tamanho_bytes,
            },
            comando_canonico=cmd,
            solicitacao_original=original,
        )

    def _validar_testar_dns(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras(
            "testar_dns", dispositivo, parametros,
            ("servidor_dns", "dominio", "tipo_registro", "timeout_s", "tentativas", "usar_perfil_cliente"),
            original,
        )
        if erro:
            return erro

        usar_perfil = bool(parametros.get("usar_perfil_cliente", True))
        servidor_dns = parametros.get("servidor_dns", SERVIDOR_PRINCIPAL_IP)
        if not ip_no_escopo_laboratorio(servidor_dns):
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"Servidor DNS '{servidor_dns}' fora do escopo do laboratorio.",
                "destino", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )

        dominio = parametros.get("dominio", "app.lab.local")
        if dominio not in DOMINIOS_AUTORIZADOS:
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"Dominio '{dominio}' nao autorizado. Dominios permitidos: {sorted(DOMINIOS_AUTORIZADOS)}.",
                "destino", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )

        tipo = str(parametros.get("tipo_registro", "A")).upper()
        if tipo in ("AXFR", "IXFR", "ANY"):
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Consulta DNS '{tipo}' proibida (transferencia de zona / amplificacao).",
                "quantidade_trafego", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )
        if tipo not in regra["tipos_registro"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Tipo de registro DNS '{tipo}' nao permitido pela politica atual.",
                "parametros", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )

        timeout_s = _inteiro_estrito(parametros.get("timeout_s", 2))
        if timeout_s is None or timeout_s < regra["timeout_min_s"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO", "Timeout invalido em testar_dns.",
                "parametros", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )
        if timeout_s > regra["timeout_max_s"]:
            return self._decisao(
                False, "LIMITE_DURACAO_EXCEDIDO",
                f"Timeout DNS ({timeout_s}s) excede o maximo permitido ({regra['timeout_max_s']}s).",
                "duracao", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )

        tentativas = _inteiro_estrito(parametros.get("tentativas", 1))
        if tentativas is None or tentativas < 1:
            return self._decisao(
                False, "PARAMETRO_INVALIDO", "Numero de tentativas invalido em testar_dns.",
                "parametros", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )
        if tentativas > regra["tentativas_max"]:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Tentativas DNS ({tentativas}) excedem o limite ({regra['tentativas_max']}).",
                "quantidade_trafego", operacao="testar_dns", dispositivo=dispositivo, solicitacao_original=original,
            )

        cmd = [
            "dig", f"@{servidor_dns}", dominio, tipo,
            f"+time={timeout_s}", f"+tries={tentativas}", "+short",
        ]
        return self._decisao(
            True, "AUTORIZADO",
            f"Consulta DNS controlada autorizada ({dominio} {tipo} em @{servidor_dns}).",
            "todos", operacao="testar_dns", dispositivo=dispositivo,
            parametros_normalizados={
                "servidor_dns": servidor_dns,
                "dominio": dominio,
                "tipo_registro": tipo,
                "timeout_s": timeout_s,
                "tentativas": tentativas,
                "usar_perfil_cliente": usar_perfil,
            },
            comando_canonico=cmd,
            solicitacao_original=original,
        )

    def _validar_testar_http(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras(
            "testar_http", dispositivo, parametros,
            ("url", "metodo", "connect_timeout_s", "max_time_s"),
            original,
        )
        if erro:
            return erro

        url = parametros.get("url", f"http://{SERVIDOR_PRINCIPAL_IP}/")
        if url not in URLS_HTTP_AUTORIZADAS:
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"URL '{url}' fora do escopo autorizado do laboratorio ({sorted(URLS_HTTP_AUTORIZADAS)}).",
                "destino", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
            )

        metodo = str(parametros.get("metodo", "GET")).upper()
        if metodo not in regra["metodos_permitidos"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Metodo HTTP '{metodo}' proibido; apenas {list(regra['metodos_permitidos'])} sao permitidos.",
                "parametros", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
            )

        connect_timeout = _inteiro_estrito(parametros.get("connect_timeout_s", 3))
        max_time = _inteiro_estrito(parametros.get("max_time_s", 5))
        if connect_timeout is None or max_time is None or connect_timeout < 1 or max_time < 1:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                "Timeouts invalidos em testar_http.",
                "parametros", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
            )
        if connect_timeout > regra["connect_timeout_max_s"] or max_time > regra["max_time_s"]:
            return self._decisao(
                False, "LIMITE_DURACAO_EXCEDIDO",
                f"Timeouts HTTP ({connect_timeout}s/{max_time}s) excedem os limites ({regra['connect_timeout_max_s']}s/{regra['max_time_s']}s).",
                "duracao", operacao="testar_http", dispositivo=dispositivo, solicitacao_original=original,
            )

        cmd = [
            "curl", "--noproxy", "*", "--silent", "--show-error",
            "--output", "/dev/null", "--write-out", "%{http_code}",
            "--connect-timeout", str(connect_timeout),
            "--max-time", str(max_time),
        ]
        if metodo == "HEAD":
            cmd.append("--head")
        cmd.append(url)

        return self._decisao(
            True, "AUTORIZADO",
            f"Teste HTTP ({metodo} {url}) autorizado a partir de {dispositivo}.",
            "todos", operacao="testar_http", dispositivo=dispositivo,
            parametros_normalizados={
                "url": url,
                "metodo": metodo,
                "connect_timeout_s": connect_timeout,
                "max_time_s": max_time,
            },
            comando_canonico=cmd,
            solicitacao_original=original,
        )

    def _validar_investigar_caminho(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras(
            "investigar_caminho", dispositivo, parametros,
            ("destino", "modo", "max_saltos", "timeout_s"),
            original,
        )
        if erro:
            return erro

        destino = parametros.get("destino", SERVIDOR_PRINCIPAL_IP)
        if not ip_no_escopo_laboratorio(destino):
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"Destino '{destino}' fora das sub-redes autorizadas para investigacao de caminho.",
                "destino", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
            )

        modo = parametros.get("modo", "ip_route_get")
        if modo not in ("ip_route_get", "traceroute"):
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Modo '{modo}' invalido para investigar_caminho.",
                "parametros", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
            )

        if modo == "ip_route_get":
            return self._decisao(
                True, "AUTORIZADO",
                f"Consulta de decisao de encaminhamento para {destino} autorizada.",
                "todos", operacao="investigar_caminho", dispositivo=dispositivo,
                parametros_normalizados={"destino": destino, "modo": modo},
                comando_canonico=["ip", "route", "get", destino],
                solicitacao_original=original,
            )

        max_saltos = _inteiro_estrito(parametros.get("max_saltos", 4))
        timeout_s = _inteiro_estrito(parametros.get("timeout_s", 2))
        if max_saltos is None or timeout_s is None or max_saltos < 1 or timeout_s < 1:
            return self._decisao(
                False, "PARAMETRO_INVALIDO", "Parametros de saltos/timeout invalidos.",
                "parametros", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
            )
        if max_saltos > regra["max_saltos"]:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"max_saltos ({max_saltos}) excede o limite da topologia ({regra['max_saltos']}).",
                "quantidade_trafego", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
            )
        if timeout_s > regra["timeout_max_s"]:
            return self._decisao(
                False, "LIMITE_DURACAO_EXCEDIDO",
                f"Timeout ({timeout_s}s) excede o limite ({regra['timeout_max_s']}s).",
                "duracao", operacao="investigar_caminho", dispositivo=dispositivo, solicitacao_original=original,
            )

        return self._decisao(
            True, "AUTORIZADO",
            f"Traceroute limitado para {destino} autorizado.",
            "todos", operacao="investigar_caminho", dispositivo=dispositivo,
            parametros_normalizados={
                "destino": destino, "modo": modo,
                "max_saltos": max_saltos, "timeout_s": timeout_s,
            },
            comando_canonico=["traceroute", "-n", "-m", str(max_saltos), "-w", str(timeout_s), destino],
            solicitacao_original=original,
        )

    def _validar_testar_desempenho(self, dispositivo, parametros, regra, original):
        erro = self._rejeitar_chaves_extras(
            "testar_desempenho", dispositivo, parametros,
            ("destino", "porta", "duracao_s", "fluxos", "protocolo"),
            original,
        )
        if erro:
            return erro

        destino = parametros.get("destino", SERVIDOR_PRINCIPAL_IP)
        if destino != SERVIDOR_PRINCIPAL_IP:
            return self._decisao(
                False, "DESTINO_FORA_DO_ESCOPO",
                f"Medicao iperf3 permitida apenas contra o servidor principal ({SERVIDOR_PRINCIPAL_IP}).",
                "destino", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )

        protocolo = str(parametros.get("protocolo", "TCP")).upper()
        if protocolo != "TCP":
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Protocolo '{protocolo}' bloqueado em testar_desempenho; apenas TCP com controle de congestionamento e permitido.",
                "quantidade_trafego", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )

        porta = _inteiro_estrito(parametros.get("porta", 5202))
        if porta not in regra["portas_permitidas"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO",
                f"Porta iperf3 '{porta}' nao autorizada. Permitidas: {sorted(regra['portas_permitidas'])}.",
                "parametros", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )

        duracao_s = _inteiro_estrito(parametros.get("duracao_s", 3))
        if duracao_s is None or duracao_s < regra["duracao_min_s"]:
            return self._decisao(
                False, "PARAMETRO_INVALIDO", "Duracao invalida em testar_desempenho.",
                "parametros", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )
        if duracao_s > regra["duracao_max_s"]:
            return self._decisao(
                False, "LIMITE_DURACAO_EXCEDIDO",
                f"Duracao ({duracao_s}s) excede o limite maximo seguro de sonda ({regra['duracao_max_s']}s).",
                "duracao", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )

        fluxos = _inteiro_estrito(parametros.get("fluxos", 1))
        if fluxos is None or fluxos < 1:
            return self._decisao(
                False, "PARAMETRO_INVALIDO", "Numero de fluxos invalido em testar_desempenho.",
                "parametros", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )
        if fluxos > regra["fluxos_max"]:
            return self._decisao(
                False, "LIMITE_TRAFEGO_EXCEDIDO",
                f"Fluxos paralelos ({fluxos}) excedem o limite ({regra['fluxos_max']}) para sonda diagnostica.",
                "quantidade_trafego", operacao="testar_desempenho", dispositivo=dispositivo, solicitacao_original=original,
            )

        cmd = ["iperf3", "-c", destino, "-p", str(porta), "-t", str(duracao_s), "-J"]
        return self._decisao(
            True, "AUTORIZADO",
            f"Sonda controlada iperf3 TCP ({duracao_s}s, 1 fluxo) autorizada de {dispositivo} para {destino}:{porta}.",
            "todos", operacao="testar_desempenho", dispositivo=dispositivo,
            parametros_normalizados={
                "destino": destino,
                "porta": porta,
                "duracao_s": duracao_s,
                "fluxos": fluxos,
                "protocolo": protocolo,
            },
            comando_canonico=cmd,
            solicitacao_original=original,
        )
