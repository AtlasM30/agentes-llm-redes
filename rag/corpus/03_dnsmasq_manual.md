# Manual Tecnico dnsmasq(8) — Servidor DNS Leve para Ambientes Locais

## Papel do dnsmasq na Resolucao de Nomes Local
O `dnsmasq` (versao 2.91) e um servidor leve de DNS e encaminhamento projetado para redes locais e ambientes controlados de teste. No servico DNS experimental, o `dnsmasq` pode responder autoritativamente por dominios internos de laboratorio (como `app.lab.local`) sem consultar servidores recursivos externos da Internet.

## Parametros de Inicializacao Segura em Laboratorio
Conforme o manual `dnsmasq(8)`, a execucao isolada em um namespace de servidor utiliza tipicamente os seguintes argumentos:
- `--no-daemon` (`-k`): mantem o processo em primeiro plano sob controle direto do gerenciador do experimento, facilitando coleta de logs e encerramento limpo.
- `--no-resolv` (`-R`): instrui o `dnsmasq` a nao ler `/etc/resolv.conf`, impedindo encaminhamento acidental de consultas para fora do laboratorio.
- `--no-hosts` (`-h`): ignora `/etc/hosts` da maquina hospedeira, garantindo que apenas os registros declarados explicitamente sejam servidos.
- `--bind-interfaces` e `--listen-address=192.168.20.10`: vinculam o socket UDP/TCP de porta 53 exclusivamente ao endereco IP do servidor virtual, evitando conflitos com `systemd-resolved` do sistema hospedeiro.
- `--address=/app.lab.local/192.168.20.10`: mapeia estaticamente o nome `app.lab.local` (e subdominios) para o registro IPv4 `A` `192.168.20.10`.
- `--port=53`: define a porta padrao do protocolo DNS.

## Diagnostico de Falhas Relacionadas ao Servico ou Configuracao DNS
Uma falha de resolucao DNS observada a partir de um cliente pode ter duas origens distintas que precisam ser diferenciadas pelas evidencias:
1. **Configuracao incorreta de servidor DNS no cliente**: o cliente envia consultas para um endereco IP onde nao ha servico DNS ativo (ex.: `192.168.20.99`), enquanto o servidor real (`192.168.20.10`) permanece saudavel. Nesse cenario:
   - O `ping` por endereco IP para `192.168.20.10` funciona normalmente no cliente afetado.
   - O acesso HTTP direto por IP (`http://192.168.20.10/`) funciona normalmente.
   - Outro cliente da mesma sub-rede (`client2`) configurado com `192.168.20.10` resolve `app.lab.local` com sucesso, comprovando que o processo `dnsmasq` no servidor esta operacional.
2. **Indisponibilidade global ou bloqueio do servico DNS**: se a consulta direta `dig @192.168.20.10 app.lab.local` falhar para todos os clientes apesar de conectividade IP (`ping`) normal, deve-se investigar regras de firewall na porta UDP/TCP 53 ou inatividade do processo `dnsmasq` no servidor.

## Recomendacoes de Correcao (Acao Humana)
Quando confirmada configuracao incorreta do servidor DNS utilizado pelo cliente (com conectividade IP integra e `dnsmasq` funcional em `192.168.20.10`), a recomendacao administrativa consiste em corrigir o parametro de servidor DNS do cliente afetado para apontar para `192.168.20.10` e revalidar a consulta `A` para `app.lab.local`. A alteracao nao deve ser executada automaticamente pelo agente.
