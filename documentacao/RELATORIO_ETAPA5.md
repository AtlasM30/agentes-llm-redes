# Etapa 5 — Dados e ambiente (versão de integração)

**Projeto:** Agentes Baseados em Modelos de Linguagem para Diagnóstico de Redes com Validação Determinística de Segurança  
**Estado:** seis cenários validados no laboratório independente; integração refatorada disponível para teste na VM. A nova `topology.py` **ainda não foi testada na VM**.

## 1. Objetivo e escopo

Construir um laboratório virtual reproduzível com coleta de evidências de falhas de DNS, rota, interface, ACL e congestionamento. O agente LLM, quando integrado, deverá realizar diagnóstico e recomendações: não tem permissão para aplicar correções automaticamente. Testes solicitados pelo agente deverão passar por validador determinístico separado, ainda não implementado nesta etapa.

## 2. Ambiente

- Hospedeiro: Windows com VirtualBox; VM `Ubuntu-Mininet2`, Ubuntu Server 24.04.5 LTS (minimized), 1.536 MB RAM e 2 vCPU, conforme configuração reportada. Revisar esses dados antes da entrega.
- Acesso: VS Code Remote-SSH; arquivos em `/home/arthur/agentes-llm-redes`.
- Software: Python 3, Mininet, Open vSwitch, dnsmasq, iptables, iperf3, iproute2, curl, dnsutils; inserir versões do Ubuntu executando `mn --version`, `ovs-vsctl --version`, `iperf3 --version`, `python3 --version`, `lsb_release -a`.
- Não executar simultaneamente outra rede Mininet.

## 3. Topologia e endereçamento

```text
client1 (192.168.10.2/24) ---\
                              switch1 --- router1 --- server (192.168.20.10/24)
client2 (192.168.10.3/24) ---/                |            DNS, HTTP, iperf3
                                   192.168.10.1 / 192.168.20.1
```

Rotas padrão dos clientes: `via 192.168.10.1`; rota padrão do servidor: `via 192.168.20.1`. Roteador com forwarding IPv4. Switch OVS sem controlador, modo `standalone`. Enlace `router1`↔`server`: **10 Mbps com 10 ms configurados no TCLink**, nos testes de desempenho; o código compartilhado originalmente pelo colega havia previsto **100 Mbps**. Essa diferença é **intencional para demonstrar congestionamento**; manter ambas as configurações identificadas, sem dizer que os resultados a 10 Mbps foram obtidos a 100 Mbps.

Serviços no server: `dnsmasq` em `192.168.20.10:53`, registro A `app.lab.local` → `192.168.20.10`; `python3 -m http.server` em TCP/80; `iperf3` em TCP/5201. Sonda de desempenho usa TCP/5202.

## 4. Ajustes na topologia para integração

1. `topology.py` centraliza a construção e a inicialização dos serviços, reutilizadas por `executar_experimentos.py` e `validar_desempenho.py`.
2. Eliminada a tentativa de bind-mount de `/etc/resolv.conf`: no Mininet padrão, os hosts compartilham o namespace de montagem do Ubuntu, embora tenham namespaces de rede distintos. A modificação de `/etc/resolv.conf` poderia alterar a VM.
3. Eliminado `killall python3 dnsmasq`: cada serviço iniciado tem seu `Popen`, com `terminate`, `wait` e `kill` apenas para seu próprio processo.
4. OVS em modo `standalone` sem controlador remoto; serviços com logs e verificação de que continuam ativos.
5. Restauração de interface recompõe endereço IP e rota padrão. ACL bloqueia apenas HTTP do `client1`, para manter o `client2` como controle.
6. Gerador de carga usa 2 fluxos TCP; o programa de desempenho inclui 15 segundos de recuperação e timeout de sonda de 35 segundos.

**Limitação de procedência:** o código integral e atual da versão do colega não estava disponível como arquivo nesta revisão; a topologia incluída é uma **implementação integrada compatível com a arquitetura e endereçamento informados**, não um diff revisado linha a linha do arquivo original. Confrontar com a versão do repositório da equipe.

## 5. Cenários de falha e critérios

| ID | Cenário | Falha controlada | Evidência esperada |
|---|---|---|---|
| caso_00 | normal | nenhuma | ping/DNS/HTTP em ambos os clientes |
| caso_01 | DNS | consulta a DNS incorreto apenas no perfil de diagnóstico do client1 | ping e HTTP por IP OK; DNS client1 falha |
| caso_02 | rota | remove rota padrão do client1 | ping/DNS/HTTP client1 falham |
| caso_03 | interface | desativa client1-eth0 | perda de conectividade de client1 |
| caso_04 | ACL | iptables bloqueia TCP/80 do client1 para o servidor | ping/DNS client1 OK, HTTP client1 falha; client2 OK |
| caso_05 | congestionamento | 2 fluxos concorrentes em enlace de 10 Mbps | aumento de latência e/ou perda; possível queda de vazão |

**Atenção ao DNS:** o caso 01 ainda usa **perfil experimental de servidor DNS no coletor** (`dig @IP`), e não um resolvedor configurado no cliente Linux. Não é correto declarar que a configuração real do cliente foi adulterada. Uma implementação futura deverá usar namespaces de montagem isolados ou outra técnica segura, com validação dedicada.

## 6. Evidências já obtidas (execuções anteriores; antes da refatoração)

### 6.1 Seis cenários — execução com restaurações corrigidas

| Caso | client1 Ping/DNS/HTTP | client2 Ping/DNS/HTTP | Latência média client1 / client2 |
|---|---|---|---|
| 00 | sim/sim/sim | sim/sim/sim | 36,796 / 21,962 ms |
| 01 | sim/não/sim | sim/sim/sim | 20,779 / 20,688 ms |
| 02 | não/não/não | sim/sim/sim | indisponível / 21,026 ms |
| 03 | não/não/não | sim/sim/sim | indisponível / 20,528 ms |
| 04 | sim/sim/não | sim/sim/sim | 21,029 / 20,531 ms |
| 05 | sim/sim/sim | sim/sim/sim | 213,749 / 378,625 ms |

### 6.2 Desempenho — três repetições (2 fluxos, recuperação de 15 s)

| Condição | Client1 latência mediana | Client2 latência mediana | Client1 vazão mediana válida | Client2 vazão |
|---|---:|---:|---:|---|
| Normal | 22,118 ms | 20,927 ms | 9,377 Mbps | 9,380 Mbps |
| Congestionamento | 199,154 ms | 1.564,286 ms | 0,716 Mbps | 0,000 Mbps em 1 medição válida; outras 2 timeouts |

Em três repetições, os pings reportaram perda de 0%, embora com latência muito maior sob carga. A vazão disponível da sonda de `client1` caiu ~92,4%. Os dois `None` do `client2` são **timeouts, não vazão zero**. Três repetições representam teste de viabilidade, não estimativa estatística robusta. Fluxos de ping e de vazão são executados sequencialmente, não concomitantemente.

## 7. Dados, procedimentos e reprodutibilidade

Diretório de evidências: `logs/evidencias_caso_XX.json`, onde os IDs neutros devem evitar expor o tipo de falha ao agente. Gabarito de causas: `dados/gabaritos/causas_reais.json` — **não incluí-lo no corpus RAG do agente**. Séries de desempenho: `dados/desempenho/medicoes.csv` e `resumo_desempenho.json`.

```bash
cd ~/agentes-llm-redes
sudo apt update
sudo apt install -y mininet openvswitch-switch python3 dnsmasq dnsutils curl iperf3 iptables iproute2
sudo mn -c                  # SOMENTE com outros laboratórios Mininet encerrados
sudo python3 topology.py   # teste de fumaça
sudo python3 executar_experimentos.py
sudo python3 validar_desempenho.py --repeticoes 3
```

Os scripts devem ser executados isoladamente. Revisar `logs/servicos/` em caso de falha na inicialização. Ao instalar os arquivos, fazer backup dos scripts anteriores, pois esta entrega contém revisões das versões de integração.

## 8. Limites e próximos passos

- Confirmar, na VM, a nova topologia integrada e reproduzir ao menos uma execução dos seis cenários após a troca de scripts.
- Confrontar o módulo `topology.py` com o arquivo mais recente do colega e decidir documentadamente entre enlace 100 Mbps (topologia original) e 10 Mbps (ensaio controlado de congestionamento).
- Melhorar a configuração DNS por cliente para realizar falha efetiva do resolvedor, sem impactar o Ubuntu.
- Registrar versões reais, data/hora, parâmetros e sementes/condições, onde aplicável.
- Completar o validador determinístico antes de qualquer integração com executor de comandos propostos pelo LLM.

## 9. Corpus técnico para RAG (preparação)

Ver `FONTES_RAG.md`. Documentar fontes e licenças, selecionar trechos pertinentes e distinguir documentação de referência dos gabaritos experimentais; não indexar resultados rotulados por causa real no corpus acessível ao agente.
