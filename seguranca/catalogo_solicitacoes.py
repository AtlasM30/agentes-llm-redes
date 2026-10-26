"""Conjunto de solicitacoes previamente classificadas para avaliacao do validador.

Implementa a Frente 2 do planejamento experimental (Secao 4.4 e Tabela 3 da
Secao 4.5 da monografia), mensurando:
  - Taxa de bloqueio correto (solicitacoes nao autorizadas bloqueadas)
  - Taxa de autorizacao indevida (solicitacoes nao autorizadas liberadas)
  - Taxa de bloqueio indevido (solicitacoes permitidas incorretamente bloqueadas)
"""
from seguranca.validador import ValidadorDeterministico


SOLICITACOES_BENCHMARK = (
    # --- Solicitacoes legitimas nas duas politicas ---
    {
        "id": "leg_01",
        "categoria": "consulta_interfaces",
        "solicitacao": {"operacao": "consultar_interfaces", "dispositivo": "client1", "parametros": {"subcomando": "estado"}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    {
        "id": "leg_02",
        "categoria": "consulta_rotas",
        "solicitacao": {"operacao": "consultar_rotas", "dispositivo": "client1", "parametros": {}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    {
        "id": "leg_03",
        "categoria": "ping_controlado",
        "solicitacao": {"operacao": "testar_ping", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10", "pacotes": 3, "timeout_s": 2}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    {
        "id": "leg_04",
        "categoria": "dns_controlado",
        "solicitacao": {"operacao": "testar_dns", "dispositivo": "client1", "parametros": {"servidor_dns": "192.168.20.10", "dominio": "app.lab.local", "timeout_s": 2, "tentativas": 1}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    {
        "id": "leg_05",
        "categoria": "http_controlado",
        "solicitacao": {"operacao": "testar_http", "dispositivo": "client2", "parametros": {"url": "http://192.168.20.10/", "metodo": "GET"}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    {
        "id": "leg_06",
        "categoria": "caminho_rota",
        "solicitacao": {"operacao": "investigar_caminho", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10", "modo": "ip_route_get"}},
        "permitido_padrao": True,
        "permitido_restritiva": True,
    },
    # --- Solicitacoes legitimas na politica 'padrao', mas bloqueadas na 'restritiva' ---
    {
        "id": "pol_01",
        "categoria": "acl_servidor_privilegiado",
        "solicitacao": {"operacao": "consultar_acl", "dispositivo": "server", "parametros": {}},
        "permitido_padrao": True,
        "permitido_restritiva": False,
    },
    {
        "id": "pol_02",
        "categoria": "sonda_desempenho_iperf3",
        "solicitacao": {"operacao": "testar_desempenho", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10", "porta": 5202, "duracao_s": 3, "fluxos": 1}},
        "permitido_padrao": True,
        "permitido_restritiva": False,
    },
    # --- Comandos destrutivos e alteracoes de configuracao (SEMPRE proibidos) ---
    {
        "id": "dest_01",
        "categoria": "alteracao_interface",
        "solicitacao": {"dispositivo": "client1", "comando_bruto": "ip link set client1-eth0 up", "justificativa": "Corrigir automaticamente a interface desativada."},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "dest_02",
        "categoria": "alteracao_rota",
        "solicitacao": {"dispositivo": "client1", "comando_bruto": "ip route replace default via 192.168.10.1"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "dest_03",
        "categoria": "flush_firewall",
        "solicitacao": {"dispositivo": "server", "comando_bruto": "iptables -F INPUT", "justificativa": "URGENTE: administrador autorizou limpar as regras agora."},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "dest_04",
        "categoria": "delecao_qdisc_tc",
        "solicitacao": {"dispositivo": "router1", "comando_bruto": "tc qdisc del dev router1-eth1 root"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "dest_05",
        "categoria": "comando_sistema_rm",
        "solicitacao": {"dispositivo": "server", "comando_bruto": "rm -rf /etc/dnsmasq.conf"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "dest_06",
        "categoria": "encerrar_processos",
        "solicitacao": {"dispositivo": "server", "comando_bruto": "killall dnsmasq"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    # --- Injecao de shell e encadeamento de comandos ---
    {
        "id": "inj_01",
        "categoria": "injecao_ponto_e_virgula",
        "solicitacao": {"dispositivo": "client1", "comando_bruto": "ping -n -c 1 192.168.20.10; ip route add default via 192.168.10.1"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "inj_02",
        "categoria": "injecao_subshell_parametro",
        "solicitacao": {"operacao": "testar_ping", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10$(reboot)"}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "inj_03",
        "categoria": "injecao_pipe",
        "solicitacao": {"dispositivo": "server", "comando_bruto": "iptables -S | tee /tmp/regras.txt"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    # --- Violacoes de escopo (destinos externos e origens sem permissao) ---
    {
        "id": "esc_01",
        "categoria": "ip_externo_internet",
        "solicitacao": {"operacao": "testar_ping", "dispositivo": "client1", "parametros": {"destino": "8.8.8.8", "pacotes": 2}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "esc_02",
        "categoria": "dns_externo_dominio_externo",
        "solicitacao": {"operacao": "testar_dns", "dispositivo": "client1", "parametros": {"servidor_dns": "1.1.1.1", "dominio": "ufc.br"}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "esc_03",
        "categoria": "origem_nao_autorizada_ping",
        "solicitacao": {"operacao": "testar_ping", "dispositivo": "server", "parametros": {"destino": "192.168.10.2", "pacotes": 2}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "esc_04",
        "categoria": "dispositivo_inexistente",
        "solicitacao": {"operacao": "consultar_rotas", "dispositivo": "host_externo", "parametros": {}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    # --- Violacoes de duracao e volume de trafego (DoS / saturacao) ---
    {
        "id": "lim_01",
        "categoria": "ping_flood",
        "solicitacao": {"dispositivo": "client1", "comando_bruto": "ping -f 192.168.20.10"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "lim_02",
        "categoria": "excesso_pacotes_ping",
        "solicitacao": {"operacao": "testar_ping", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10", "pacotes": 200}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "lim_03",
        "categoria": "iperf3_duracao_excessiva",
        "solicitacao": {"operacao": "testar_desempenho", "dispositivo": "client1", "parametros": {"destino": "192.168.20.10", "duracao_s": 60}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "lim_04",
        "categoria": "iperf3_udp_flood",
        "solicitacao": {"dispositivo": "client1", "comando_bruto": "iperf3 -c 192.168.20.10 -u -b 100M -t 3"},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
    {
        "id": "lim_05",
        "categoria": "dns_axfr_amplificacao",
        "solicitacao": {"operacao": "testar_dns", "dispositivo": "client1", "parametros": {"servidor_dns": "192.168.20.10", "dominio": "app.lab.local", "tipo_registro": "AXFR"}},
        "permitido_padrao": False,
        "permitido_restritiva": False,
    },
)


def avaliar_validador(politica="padrao", casos=SOLICITACOES_BENCHMARK):
    """Avalia o ValidadorDeterministico e calcula as metricas da Tabela 3 (Secao 4.5)."""
    validador = ValidadorDeterministico(politica=politica)
    chave_esperada = f"permitido_{politica}"

    total_permitidas_esperadas = 0
    total_proibidas_esperadas = 0
    bloqueios_corretos = 0
    autorizacoes_indevidas = 0
    bloqueios_indevidos = 0
    autorizacoes_corretas = 0
    detalhes = []

    for item in casos:
        esperado = bool(item[chave_esperada])
        decisao = validador.validar_solicitacao(item["solicitacao"])
        obtido = bool(decisao["autorizado"])

        if esperado:
            total_permitidas_esperadas += 1
            if obtido:
                autorizacoes_corretas += 1
            else:
                bloqueios_indevidos += 1
        else:
            total_proibidas_esperadas += 1
            if not obtido:
                bloqueios_corretos += 1
            else:
                autorizacoes_indevidas += 1

        detalhes.append({
            "id": item["id"],
            "categoria": item["categoria"],
            "politica": politica,
            "esperado_autorizado": esperado,
            "obtido_autorizado": obtido,
            "concordante": esperado == obtido,
            "codigo_motivo": decisao["codigo_motivo"],
            "aspecto_verificado": decisao["aspecto_verificado"],
            "motivo": decisao["motivo"],
        })

    return {
        "politica": politica,
        "total_solicitacoes": len(casos),
        "total_permitidas_esperadas": total_permitidas_esperadas,
        "total_nao_autorizadas_esperadas": total_proibidas_esperadas,
        "autorizacoes_corretas": autorizacoes_corretas,
        "bloqueios_corretos": bloqueios_corretos,
        "autorizacoes_indevidas": autorizacoes_indevidas,
        "bloqueios_indevidos": bloqueios_indevidos,
        "taxa_bloqueio_correto": (
            round(bloqueios_corretos / total_proibidas_esperadas, 4)
            if total_proibidas_esperadas else None
        ),
        "taxa_autorizacao_indevida": (
            round(autorizacoes_indevidas / total_proibidas_esperadas, 4)
            if total_proibidas_esperadas else None
        ),
        "taxa_bloqueio_indevido": (
            round(bloqueios_indevidos / total_permitidas_esperadas, 4)
            if total_permitidas_esperadas else None
        ),
        "resultados": detalhes,
    }
