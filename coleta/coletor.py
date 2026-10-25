
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


class ColetorEvidencias:
    """
    Coleta evidências dos dispositivos do Mininet.

    Os comandos são definidos previamente no código.
    Não permite execução de comandos arbitrários pelo LLM.
    """

    SERVIDOR_IP = "192.168.20.10"
    DOMINIO = "app.lab.local"
    CLIENTES = ("client1", "client2")
    DISPOSITIVOS = ("client1", "client2", "router1", "server")

    def __init__(self, rede):
        self.rede = rede

    def executar(self, dispositivo, comando, timeout=8):
        """
        Executa um teste limitado no host virtual.

        Retorna saída, código de retorno e possíveis erros.
        """
        if dispositivo not in self.DISPOSITIVOS:
            return {
                "sucesso": False,
                "erro": "Dispositivo nao autorizado"
            }

        try:
            host = self.rede.get(dispositivo)

            processo = host.popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL
            )

            try:
                saida, _ = processo.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                processo.kill()
                saida, _ = processo.communicate()

                return {
                    "sucesso": False,
                    "timeout": True,
                    "erro": "Tempo limite excedido",
                    "saida": saida.decode(
                        "utf-8", errors="replace"
                    )[:12000]
                }

            return {
                "sucesso": processo.returncode == 0,
                "codigo_retorno": processo.returncode,
                "saida": saida.decode(
                    "utf-8", errors="replace"
                )[:12000]
            }

        except Exception as erro:
            return {
                "sucesso": False,
                "erro": str(erro)
            }

    # ----------------------------------------
    # 1. Interfaces de rede
    # ----------------------------------------

    def coletar_interfaces(self, dispositivo):
        return {
            "enderecos": self.executar(
                dispositivo, ["ip", "-br", "addr"]
            ),
            "estado": self.executar(
                dispositivo, ["ip", "-br", "link"]
            ),
            "estatisticas": self.executar(
                dispositivo, ["ip", "-s", "link"]
            )
        }

    # ----------------------------------------
    # 2. Tabela de roteamento
    # ----------------------------------------

    def coletar_rotas(self, dispositivo):
        return self.executar(
            dispositivo, ["ip", "route", "show"]
        )

    # ----------------------------------------
    # 3. Regras ACL / Firewall
    # ----------------------------------------

    def coletar_regras_acl(self, dispositivo):
        return self.executar(
            dispositivo, ["iptables", "-S"]
        )

    # ----------------------------------------
    # 4. Conectividade e latencia
    # ----------------------------------------

    def testar_ping(self, dispositivo):
        if dispositivo not in self.CLIENTES:
            return {
                "sucesso": False,
                "erro": "Origem nao autorizada para ping"
            }

        resultado = self.executar(
            dispositivo,
            [
                "ping",
                "-n",
                "-c", "3",
                "-W", "2",
                self.SERVIDOR_IP
            ],
            timeout=10
        )

        saida = resultado.get("saida", "")

        # Extrai perda de pacotes e RTT quando disponíveis.
        import re

        perda = re.search(
            r"([\d.]+)% packet loss", saida
        )

        latencia = re.search(
            r"(?:rtt|round-trip) min/avg/max"
            r"(?:/mdev|/stddev)? = "
            r"([\d.]+)/([\d.]+)/([\d.]+)",
            saida
        )

        resultado["destino"] = self.SERVIDOR_IP
        resultado["pacotes_enviados"] = 3

        resultado["perda_percentual"] = (
            float(perda.group(1)) if perda else None
        )

        resultado["latencia_media_ms"] = (
            float(latencia.group(2)) if latencia else None
        )

        return resultado

    # ----------------------------------------
    # 5. Resolucao DNS
    # ----------------------------------------

    def testar_dns(self, dispositivo):
        if dispositivo not in self.CLIENTES:
            return {
                "sucesso": False,
                "erro": "Origem nao autorizada para DNS"
            }

        resultado = self.executar(
            dispositivo,
            [
                "dig",
                "@" + self.SERVIDOR_IP,
                self.DOMINIO,
                "A",
                "+time=2",
                "+tries=1",
                "+short"
            ],
            timeout=5
        )

        enderecos = [
            linha.strip()
            for linha in resultado.get("saida", "").splitlines()
            if linha.strip()
        ]

        resultado["dominio"] = self.DOMINIO
        resultado["servidor_dns"] = self.SERVIDOR_IP
        resultado["enderecos_resolvidos"] = enderecos

        resultado["resolucao_correta"] = (
            resultado.get("sucesso", False)
            and self.SERVIDOR_IP in enderecos
        )

        return resultado

    # ----------------------------------------
    # 6. Disponibilidade HTTP
    # ----------------------------------------

    def testar_http(self, dispositivo):
        if dispositivo not in self.CLIENTES:
            return {
                "sucesso": False,
                "erro": "Origem nao autorizada para HTTP"
            }

        url = f"http://{self.SERVIDOR_IP}/"

        resultado = self.executar(
            dispositivo,
            [
                "curl",
                "--noproxy", "*",
                "--silent",
                "--show-error",
                "--output", "/dev/null",
                "--write-out", "%{http_code}",
                "--connect-timeout", "3",
                "--max-time", "5",
                url
            ],
            timeout=7
        )

        codigo = resultado.get("saida", "").strip()

        resultado["url"] = url
        resultado["codigo_http"] = (
            int(codigo) if codigo.isdigit() else None
        )
        resultado["servico_disponivel"] = (
            resultado.get("sucesso", False)
            and codigo.isdigit()
            and 200 <= int(codigo) < 400
        )

        return resultado

    # ----------------------------------------
    # 7. Medicao de vazao com iperf3
    # ----------------------------------------

    def testar_desempenho(self, dispositivo, duracao=3):
        """
        Mede vazao TCP por tempo limitado.

        Deve ser chamado apenas nos experimentos
        autorizados pela equipe.
        """
        if dispositivo not in self.CLIENTES:
            return {
                "sucesso": False,
                "erro": "Origem nao autorizada"
            }

        duracao = max(1, min(int(duracao), 3))

        servidor = self.rede.get("server")
        processo_servidor = None

        try:
            processo_servidor = servidor.popen(
                [
                    "iperf3",
                    "-s",
                    "-1",
                    "-B", self.SERVIDOR_IP,
                    "-p", "5201"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )

            time.sleep(1)

            resultado = self.executar(
                dispositivo,
                [
                    "iperf3",
                    "-c", self.SERVIDOR_IP,
                    "-p", "5201",
                    "-t", str(duracao),
                    "-J"
                ],
                timeout=duracao + 8
            )

            resultado["destino"] = self.SERVIDOR_IP
            resultado["duracao_s"] = duracao

            if resultado.get("sucesso"):
                try:
                    dados = json.loads(resultado["saida"])

                    bits_por_segundo = (
                        dados.get("end", {})
                        .get("sum_received", {})
                        .get("bits_per_second")
                    )

                    resultado["vazao_mbps"] = (
                        round(bits_por_segundo / 1_000_000, 3)
                        if bits_por_segundo is not None
                        else None
                    )
                except (ValueError, TypeError):
                    resultado["vazao_mbps"] = None

            return resultado

        except Exception as erro:
            return {
                "sucesso": False,
                "erro": str(erro)
            }

        finally:
            if processo_servidor is not None:
                if processo_servidor.poll() is None:
                    processo_servidor.terminate()
                    try:
                        processo_servidor.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        processo_servidor.kill()
                        processo_servidor.wait()

    # ----------------------------------------
    # 8. Coleta completa de um dispositivo
    # ----------------------------------------

    def coletar_dispositivo(
        self,
        dispositivo,
        testes_ativos=True,
        desempenho=False
    ):
        dados = {
            "interfaces": self.coletar_interfaces(dispositivo),
            "rotas": self.coletar_rotas(dispositivo),
            "acl": self.coletar_regras_acl(dispositivo)
        }

        if testes_ativos and dispositivo in self.CLIENTES:
            dados["ping"] = self.testar_ping(dispositivo)
            dados["dns"] = self.testar_dns(dispositivo)
            dados["http"] = self.testar_http(dispositivo)

            if desempenho:
                dados["desempenho"] = self.testar_desempenho(
                    dispositivo
                )

        return dados

    # ----------------------------------------
    # 9. Coleta da rede
    # ----------------------------------------

    def coletar_rede(
        self,
        dispositivos=None,
        cenario="normal",
        testes_ativos=True,
        desempenho=False
    ):
        if dispositivos is None:
            dispositivos = self.DISPOSITIVOS

        resultado = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "cenario": cenario,
            "servidor": self.SERVIDOR_IP,
            "dominio": self.DOMINIO,
            "dispositivos": {}
        }

        for dispositivo in dispositivos:
            print(f"Coletando: {dispositivo}")

            resultado["dispositivos"][dispositivo] = (
                self.coletar_dispositivo(
                    dispositivo,
                    testes_ativos=testes_ativos,
                    desempenho=desempenho
                )
            )

        return resultado

    # ----------------------------------------
    # 10. Salvar evidencias
    # ----------------------------------------

    def salvar(self, dados, arquivo=None):
        if arquivo is None:
            cenario = dados.get("cenario", "normal")

            nome_seguro = "".join(
                c for c in cenario
                if c.isalnum() or c in ("_", "-")
            )

            raiz = Path(__file__).resolve().parent.parent
            arquivo = (
                raiz / "logs" /
                f"evidencias_{nome_seguro or 'normal'}.json"
            )

        caminho = Path(arquivo)
        caminho.parent.mkdir(parents=True, exist_ok=True)

        with caminho.open("w", encoding="utf-8") as f:
            json.dump(
                dados,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(f"Evidencias salvas em: {caminho}")
