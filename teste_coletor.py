
from mininet.net import Mininet
from mininet.node import Node, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

from coleta.coletor import ColetorEvidencias

import subprocess
import time

class Roteador(Node):
    def config(self, **params):
        super().config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")


def executar_teste():
    net = Mininet(
        topo=None,
        build=False,
        controller=None,
        switch=OVSSwitch,
        link=TCLink
    )

    try:
        # Criacao dos dispositivos
        c1 = net.addHost(
            "client1",
            ip="192.168.10.2/24",
            defaultRoute="via 192.168.10.1"
        )

        c2 = net.addHost(
            "client2",
            ip="192.168.10.3/24",
            defaultRoute="via 192.168.10.1"
        )

        r1 = net.addHost(
            "router1",
            cls=Roteador,
            ip=None
        )

        srv = net.addHost(
            "server",
            ip="192.168.20.10/24",
            defaultRoute="via 192.168.20.1"
        )

        sw = net.addSwitch(
            "switch1",
            failMode="standalone"
        )

        # Enlaces
        net.addLink(c1, sw)
        net.addLink(c2, sw)
        net.addLink(
            sw, r1,
            intfName2="router1-eth0"
        )
        net.addLink(
            r1, srv,
            intfName1="router1-eth1",
            intfName2="server-eth0"
        )

        # Inicializacao
        net.build()
        net.start()

        # Configuracao do roteador
        r1.cmd(
            "ip addr add 192.168.10.1/24 "
            "dev router1-eth0"
        )
        r1.cmd(
            "ip addr add 192.168.20.1/24 "
            "dev router1-eth1"
        )

        r1.cmd("ip link set router1-eth0 up")
        r1.cmd("ip link set router1-eth1 up")

        # Iniciar servidor HTTP no host server
        http_server = srv.popen(
            [
                "python3", "-m", "http.server",
                "80", "--bind", "192.168.20.10"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Iniciar servidor DNS no host server
        dns_server = srv.popen(
            [
                "dnsmasq",
                "--no-daemon",
                "--no-resolv",
                "--no-hosts",
                "--bind-interfaces",
                "--listen-address=192.168.20.10",
                "--address=/app.lab.local/192.168.20.10",
                "--port=53"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        time.sleep(2)

        
        # Criar o coletor
        coletor = ColetorEvidencias(net)

        # =====================================
        # CENARIO 1 - REDE NORMAL
        # =====================================

        print("\nColetando cenario normal...")

        dados_normal = coletor.coletar_rede(
            cenario="normal",
            testes_ativos=True,
            desempenho=False
        )

        coletor.salvar(dados_normal)

        # =====================================
        # CENARIO 2 - FALHA DE ROTEAMENTO
        # =====================================

        print("\nSimulando falha de roteamento...")

        # Remover a rota padrao do cliente 1
        c1.cmd("ip route del default via 192.168.10.1")

        # Coletar evidencias com a falha ativa
        dados_falha = coletor.coletar_rede(
            cenario="falha_rota",
            testes_ativos=True,
            desempenho=False
        )

        coletor.salvar(dados_falha)

        # =====================================
        # RESTAURAR CONFIGURACAO
        # =====================================

        print("\nRestaurando rota do cliente 1...")

        c1.cmd("ip route replace default via 192.168.10.1")

        print("\nTestes finalizados!")


    finally:
        for nome in ("http_server", "dns_server"):
            processo = locals().get(nome)

            if processo is not None and processo.poll() is None:
                processo.terminate()

                try:
                    processo.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    processo.kill()
                    processo.wait()
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    executar_teste()
