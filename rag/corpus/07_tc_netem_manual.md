# Manual Linux tc(8) — Controle de Trafego, Filas, Latencia e Congestionamento

## Disciplinas de Fila (qdisc) e Modelagem de Enlace no Linux
O utilitario `tc` (*Traffic Control*, pacote `iproute2-6.1.0`) consulta e gerencia disciplinas de enfileiramento (`qdisc`), classes e filtros no subsistema de rede do kernel Linux. Em enlaces emulados com `TCLink` (por exemplo, `router1-eth1` ↔ `server-eth0` configurado com `bw=10` Mbps e `delay=10ms`), o Linux combina duas estruturas na arvore `qdisc`:
1. **HTB (`Hierarchical Token Bucket`) ou TBF (`Token Bucket Filter`)**: regula a taxa maxima de saida para 10 Mbps, retendo pacotes excedentes em fila ate o limite do buffer.
2. **NetEm (`Network Emulator`)**: adiciona atraso deterministico de propagacao (`delay 10.0ms` em cada direcao, perfazendo no minimo 20 ms de RTT base) e possui fila interna finita (`limit`).

## Inspecao Somente Leitura com tc -s qdisc show
Para inspecionar estatisticas de enfileiramento sem modificar a rede, utiliza-se exclusivamente o subcomando de leitura:
```text
tc -s qdisc show
```
Os contadores exibidos incluem:
- `Sent <bytes> bytes <pkt> pkt`: total transmitido pela interface.
- `dropped <n>, overlimits <m>, requeues <k>`: pacotes descartados por estouro de fila e eventos em que o modelador de banda precisou atrasar envios (`overlimits`) por atingir o teto de 10 Mbps.
- `backlog <bytes>b <pkt>p`: ocupacao instantanea da fila no momento da coleta (um `backlog` elevado comprova fila acumulada em tempo real).

## Diagnostico de Congestionamento por Latencia (RTT), Perda e Vazao
Quando fluxos intensivos (ex.: multiplos fluxos TCP concorrentes gerados na rede) saturam o enlace compartilhado de 10 Mbps entre `router1` e `server`:
- **Conectividade funcional preservada**: diferentemente das falhas de interface, rota, DNS ou ACL, nos cenarios de congestionamento moderado a severo os testes funcionais basicos (`ping`, `dig` e `curl`) frequentemente continuam retornando sucesso (`True`) em **ambos** os clientes (`client1` e `client2`), pois o gargalo situa-se no enlace compartilhado `router1`↔`server`.
- **Elevacao expressiva de RTT (Bufferbloat)**: os pacotes ICMP Echo aguardam atras dos segmentos TCP na fila do enlace de 10 Mbps. Como criterio quantitativo de referencia adotado no laboratorio:
  - Quando a `latencia_media_ms` atual e simultaneamente **$\ge 3\times$ a latencia de referencia (linha de base normal)** e apresenta **aumento absoluto $\ge 50\text{ ms}$** (por exemplo, saltando da faixa basal de 20–37 ms para ~200–400 ms ou mais), configura-se forte indicio de `possivel_congestionamento`.
  - Caso nao haja linha de base disponivel mas a latencia absoluta supere `150 ms`, observa-se `latencia_elevada`, devendo-se investigar congestionamento por meio de estatisticas `tc -s qdisc show` ou medicao controlada de vazao `iperf3` (se permitida pela politica).
- **Queda acentuada de vazao disponivel**: uma sonda curta `iperf3` observa queda severa em relacao aos ~9,4 Mbps nominais do enlace de 10 Mbps (frequentemente abaixo de 1–2 Mbps ou sofrendo timeout).

## Limites Interpretativos e Recomendacoes Administrativas
A latencia elevada no `ping` constitui forte evidencia indicativa de fila/congestionamento no caminho compartilhado, especialmente quando afeta simultaneamente `client1` e `client2`. As operacoes `tc qdisc add/change/replace/delete` sao estritamente proibidas ao agente. Como acao corretiva para o administrador humano, recomenda-se identificar e limitar ou encerrar os fluxos geradores de sobrecarga no enlace `router1`↔`server`, revisar politicas de QoS/filas (`tc`) ou redimensionar a capacidade do enlace conforme a demanda do servico.
