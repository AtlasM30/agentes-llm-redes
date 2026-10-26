"""Politicas declarativas para o Validador Deterministico de Seguranca.

Define escopo de dispositivos, enderecamento, dominios, operacoes diagnosticas
permitidas, limites de duracao/volume de trafego e as duas configuracoes de
politica previstas na Secao 4.4 da monografia ('padrao' e 'restritiva').
"""
import ipaddress
import re


DISPOSITIVOS_AUTORIZADOS = ("client1", "client2", "router1", "server")
CLIENTES_AUTORIZADOS = ("client1", "client2")

SUBREDES_LABORATORIO = (
    ipaddress.ip_network("192.168.10.0/24"),
    ipaddress.ip_network("192.168.20.0/24"),
)

IPS_CONHECIDOS_TOPOLOGIA = frozenset({
    "192.168.10.1",   # router1-eth0
    "192.168.10.2",   # client1
    "192.168.10.3",   # client2
    "192.168.20.1",   # router1-eth1
    "192.168.20.10",  # server (HTTP, DNS, iperf3)
    "192.168.20.99",  # endereco de perfil DNS de teste dentro da sub-rede 20.0/24
})

SERVIDOR_PRINCIPAL_IP = "192.168.20.10"
DOMINIOS_AUTORIZADOS = frozenset({"app.lab.local"})
URLS_HTTP_AUTORIZADAS = frozenset({
    "http://192.168.20.10/",
    "http://192.168.20.10",
    "http://app.lab.local/",
    "http://app.lab.local",
})
PORTAS_IPERF3_AUTORIZADAS = frozenset({5201, 5202})

# Metacaracteres de shell e caracteres de controle proibidos
METACARACTERES_SHELL_PROIBIDOS = (
    ";", "&&", "||", "|", "`", "$(", "${", ">", "<",
    "\n", "\r", "\x00", "\x0b", "\x0c", "\x1b", "&",
)

# Binarios administrativos, destrutivos, wrappers de ambiente ou fora de escopo
BINARIOS_ESTRITAMENTE_PROIBIDOS = frozenset({
    "rm", "mv", "cp", "dd", "mkfs", "mount", "umount", "chmod", "chown",
    "kill", "killall", "pkill", "reboot", "shutdown", "poweroff", "halt",
    "sudo", "su", "passwd", "useradd", "usermod", "userdel",
    "sh", "bash", "dash", "zsh", "python", "python3", "perl", "ruby", "lua",
    "nc", "netcat", "ncat", "socat", "nmap", "hping3", "scapy", "arping",
    "sysctl", "systemctl", "service", "ufw", "nft", "ip6tables", "ovs-vsctl", "ovs-ofctl",
    "sed", "awk", "tee", "vi", "vim", "nano", "wget", "ssh", "scp",
    "env", "nohup", "timeout", "watch", "xargs", "find", "tar", "cat", "head", "tail", "grep",
})

POLITICAS_SEGURANCA = {
    "padrao": {
        "nome": "padrao",
        "descricao": (
            "Politica diagnostica padrao: autoriza consultas de estado somente leitura "
            "e sondas ativas nao destrutivas dentro dos limites de escopo, duracao e trafego."
        ),
        "operacoes": {
            "consultar_interfaces": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "subcomandos_permitidos": ("estado", "enderecos", "estatisticas"),
                "timeout_max_s": 5,
            },
            "consultar_rotas": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "consultar_acl": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "consultar_tc": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "testar_ping": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "pacotes_min": 1,
                "pacotes_max": 5,
                "timeout_min_s": 1,
                "timeout_max_s": 5,
                "tamanho_max_bytes": 1472,
            },
            "testar_dns": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "tipos_registro": ("A", "AAAA"),
                "timeout_min_s": 1,
                "timeout_max_s": 3,
                "tentativas_min": 1,
                "tentativas_max": 2,
            },
            "testar_http": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "metodos_permitidos": ("GET", "HEAD"),
                "connect_timeout_max_s": 3,
                "max_time_s": 5,
            },
            "investigar_caminho": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "max_saltos": 5,
                "timeout_max_s": 3,
            },
            "testar_desempenho": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "duracao_min_s": 1,
                "duracao_max_s": 5,
                "fluxos_max": 1,
                "portas_permitidas": PORTAS_IPERF3_AUTORIZADAS,
                "somente_tcp": True,
            },
        },
        "operacoes_bloqueadas_pela_politica": {},
    },
    "restritiva": {
        "nome": "restritiva",
        "descricao": (
            "Politica restritiva para analise de trade-off e resiliencia (Secao 4.4): "
            "bloqueia inspecao administrativa de ACL no servidor/roteador e medicoes "
            "ativas de vazao iperf3, alem de reduzir o limite de pacotes ICMP."
        ),
        "operacoes": {
            "consultar_interfaces": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "subcomandos_permitidos": ("estado", "enderecos", "estatisticas"),
                "timeout_max_s": 5,
            },
            "consultar_rotas": {
                "origens_permitidas": DISPOSITIVOS_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "consultar_acl": {
                # Clientes podem ver apenas seu proprio namespace; server/router1 bloqueados
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "consultar_tc": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "timeout_max_s": 5,
            },
            "testar_ping": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "pacotes_min": 1,
                "pacotes_max": 3,
                "timeout_min_s": 1,
                "timeout_max_s": 3,
                "tamanho_max_bytes": 512,
            },
            "testar_dns": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "tipos_registro": ("A",),
                "timeout_min_s": 1,
                "timeout_max_s": 2,
                "tentativas_min": 1,
                "tentativas_max": 1,
            },
            "testar_http": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "metodos_permitidos": ("GET", "HEAD"),
                "connect_timeout_max_s": 3,
                "max_time_s": 5,
            },
            "investigar_caminho": {
                "origens_permitidas": CLIENTES_AUTORIZADOS,
                "max_saltos": 4,
                "timeout_max_s": 2,
            },
        },
        "operacoes_bloqueadas_pela_politica": {
            "testar_desempenho": (
                "Sondas ativas de vazao (iperf3) estao desabilitadas na politica "
                "restritiva para evitar geracao adicional de carga; utilize metricas "
                "de latencia de ping ou estatisticas locais permitidas."
            ),
        },
    },
}


_PADRAO_IPV4_CANONICO = re.compile(r"^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$")


def ip_no_escopo_laboratorio(endereco_ip):
    """Verifica se um endereco IPv4 canonico pertence as sub-redes do laboratorio."""
    if not isinstance(endereco_ip, str):
        return False
    ip_limpo = endereco_ip.strip()
    if ip_limpo != endereco_ip or not _PADRAO_IPV4_CANONICO.match(ip_limpo):
        return False
    try:
        ip_obj = ipaddress.IPv4Address(ip_limpo)
    except ValueError:
        return False
    return any(ip_obj in rede for rede in SUBREDES_LABORATORIO)


def obter_politica(nome_politica="padrao"):
    if nome_politica not in POLITICAS_SEGURANCA:
        raise ValueError(
            f"Politica desconhecida: '{nome_politica}'. Opcoes: {sorted(POLITICAS_SEGURANCA)}"
        )
    return POLITICAS_SEGURANCA[nome_politica]
