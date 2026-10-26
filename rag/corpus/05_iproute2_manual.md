# Manual Linux iproute2 — ip-link(8), ip-address(8) e ip-route(8)

## Inspecao de Interfaces de Rede com ip-link(8) e ip-address(8)
A suite `iproute2` (versao 6.1.0) fornece os subcomandos `ip link` (camada de enlace) e `ip addr` (enderecamento de rede). Os comandos somente leitura para diagnostico sao:
- `ip -br link`: exibe resumo compacto do estado de cada interface no formato `<nome> <estado> <mac> <flags>`.
  - Exemplo de interface saudavel: `client1-eth0@if48 UP 00:00:00:00:00:01 <BROADCAST,MULTICAST,UP,LOWER_UP>`
  - Exemplo de interface desativada: `client1-eth0@if48 DOWN 00:00:00:00:00:01 <BROADCAST,MULTICAST>`
  - Quando o segundo campo e `DOWN` (ausencia da flag administrativa `UP`), a interface descarta todo envio e recepcao de quadros Ethernet.
- `ip -br addr`: lista os enderecos IPv4/IPv6 atribuidos a cada interface (ex.: `192.168.10.2/24` em `client1-eth0`).
- `ip -s link`: exibe contadores acumulados de pacotes e bytes transmitidos (`TX`) e recebidos (`RX`), incluindo `errors`, `dropped` e `overrun`.

## Inspecao da Tabela de Roteamento com ip-route(8)
O comando somente leitura `ip route show` lista as entradas da tabela principal de encaminhamento IPv4 (`main`):
```text
default via 192.168.10.1 dev client1-eth0
192.168.10.0/24 dev client1-eth0 proto kernel scope link src 192.168.10.2
```
- **Rota diretamente conectada (`scope link`)**: gerada automaticamente pelo kernel quando a interface esta `UP` com endereco IPv4 configurado; permite comunicacao apenas dentro da propria sub-rede local (`192.168.10.0/24`).
- **Rota padrao (`default via 192.168.10.1 dev client1-eth0`)**: indispensavel para encaminhar pacotes destinados a redes remotas (como o servidor `192.168.20.10/24`) atraves do gateway `router1` (`192.168.10.1`).
- O comando `ip route get 192.168.20.10` consulta de forma nao destrutiva qual proximo salto o kernel selecionaria para alcancar o destino; caso nao haja rota aplicavel, o kernel retorna `RTNETLINK answers: Network is unreachable`.

## Precedencia Causal Critica: Interface DOWN vs Rota Padrao Ausente
No kernel Linux, desativar administrativamente uma interface (`ip link set <dev> down`) faz com que o kernel **remova ou invalide automaticamente todas as rotas associadas aquela interface**, incluindo a rota `default via 192.168.10.1`!
Consequentemente, quando `client1-eth0` esta `DOWN`:
1. `ip -br link` mostrara `client1-eth0 ... DOWN`.
2. `ip route show` estara vazio (sem rota `default` e sem rota `192.168.10.0/24`).
3. `ping`, `dig` e `curl` falharao integralmente.
Portanto, na arvore de raciocinio diagnostico, **a verificacao do estado da interface tem precedencia obrigatoria sobre a verificacao da tabela de rotas**:
- Interface `DOWN` → classificar como `falha_de_interface` (a ausencia de rota e mera consequencia da interface desligada).
- Interface `UP` + ausencia de rota `default` (ou rota para `192.168.20.0/24`) + `ping` falho → classificar como `falha_de_roteamento`.

## Separacao entre Consulta Segura e Comandos Administrativos
Somente subcomandos de leitura (`ip -br link`, `ip -br addr`, `ip -s link`, `ip route show`, `ip route get`) sao permitidos ao agente. Subcomandos que alteram o estado da rede — como `ip link set <dev> up/down`, `ip addr add/del/replace/flush` e `ip route add/del/replace/flush` — sao bloqueados pelo validador deterministico e devem constar apenas como recomendacoes textuais para o administrador humano:
- Para `falha_de_interface`: recomendar ao administrador reativar a interface (`ip link set client1-eth0 up`), confirmar o endereco IPv4 (`192.168.10.2/24`) e restaurar a rota padrao (`ip route replace default via 192.168.10.1`).
- Para `falha_de_roteamento`: recomendar ao administrador restaurar a rota padrao no cliente afetado (`ip route replace default via 192.168.10.1`).
