"""Coleta opcional de trechos das manpages instaladas no sistema Linux.

Permite verificar a disponibilidade local dos manuais catalogados em
documentacao/FONTES_RAG.md (ip-link, ip-route, ip-address, iptables,
dnsmasq, dig e tc) e extrair secoes NAME/SYNOPSIS/DESCRIPTION sem
depender de acesso externo a Internet durante os experimentos na VM.
"""
import os
import re
import subprocess
from datetime import date
from pathlib import Path


MANPAGES_PADRAO = (
    ("iproute2_man", "ip-link", "roteamento_e_interfaces"),
    ("iproute2_man", "ip-route", "roteamento_e_interfaces"),
    ("iproute2_man", "ip-address", "roteamento_e_interfaces"),
    ("iptables_man", "iptables", "regras_acl_firewall"),
    ("dnsmasq_man", "dnsmasq", "servico_dns"),
    ("bind9_dig", "dig", "resolucao_dns"),
    ("tc_man", "tc", "controle_trafego_congestionamento"),
)


def limpar_formatacao_man(texto):
    """Remove sequencias de backspace (overstrike) e ANSI de saidas do man."""
    sem_overstrike = re.sub(r".\x08", "", texto)
    sem_ansi = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", sem_overstrike)
    return sem_ansi


def extrair_manpage_sistema(pagina, max_linhas=90):
    """Extrai o cabecalho e a sinopse de uma manpage local, se instalada."""
    ambiente = {**os.environ, "MANWIDTH": "100", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["man", pagina],
            capture_output=True,
            text=True,
            timeout=6,
            env=ambiente,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    limpo = limpar_formatacao_man(proc.stdout)
    linhas = [linha.rstrip() for linha in limpo.splitlines()[:max_linhas]]
    return "\n".join(linhas).strip()


def coletar_manpages_locais(destino_dir=None):
    """Coleta sinopses das manpages instaladas e grava resumo opcional."""
    coletadas = []
    hoje = date.today().isoformat()

    for fonte_id, pagina, tema in MANPAGES_PADRAO:
        conteudo = extrair_manpage_sistema(pagina)
        if not conteudo:
            continue
        coletadas.append({
            "fonte_id": f"{fonte_id}_{pagina.replace('-', '_')}",
            "pagina": pagina,
            "tema": tema,
            "data_acesso": hoje,
            "trecho": conteudo,
        })

    if destino_dir is not None and coletadas:
        pasta = Path(destino_dir)
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / "08_manpages_sistema_local.md"
        blocos = ["# Sinopses Extraidas das Manpages Locais do Sistema Linux\n"]
        for item in coletadas:
            blocos.append(f"## Manpage {item['pagina']} ({item['tema']})")
            blocos.append("```text")
            blocos.append(item["trecho"])
            blocos.append("```\n")
        caminho.write_text("\n".join(blocos), encoding="utf-8")

    return coletadas
