# Pacote de integração — Etapa 5

**O pacote contém substituições para `topology.py`, `cenarios.py`, `executar_experimentos.py` e `validar_desempenho.py`** e documentação. NÃO contém `coleta/coletor.py`: preserve o seu arquivo já validado.

## Instalação no VS Code Remote-SSH

1. Abra `/home/arthur/agentes-llm-redes`.
2. Faça uma cópia dos quatro arquivos anteriores (principalmente `topology.py` do colega) antes de substituir.
3. Copie os quatro `.py` e a pasta `documentacao/` para a raiz.
4. Confirme que `coleta/coletor.py` continua no lugar.
5. Execute separadamente, sem outras redes Mininet ativas:

```bash
cd ~/agentes-llm-redes
python3 -m py_compile topology.py cenarios.py executar_experimentos.py validar_desempenho.py
sudo mn -c
sudo python3 topology.py
sudo python3 executar_experimentos.py
sudo python3 validar_desempenho.py --repeticoes 3
```

Para confirmar os casos, reutilize seu script de leitura de `logs/evidencias_caso_XX.json`. A nova integração ainda precisa ser validada no Ubuntu, pois aqui apenas se verificou a sintaxe Python e a estrutura dos módulos.

## O que mudou

- `topology.py`: centraliza a rede e os serviços; evita bind-mount de `/etc/resolv.conf` e `killall python3`.
- `cenarios.py`: restaura rota/endereço após interface, ACL seletiva, 2 fluxos de congestionamento.
- `executar_experimentos.py`: importa a mesma topologia para os seis casos; exporta evidências com gabaritos separados.
- `validar_desempenho.py`: reutiliza a mesma topologia, tempo máximo de 35 s para sondas e 15 s de recuperação entre rodadas.
- `documentacao/`: relatório da etapa e catálogo inicial de fontes RAG.

**Atenção**: `topology.py` é uma versão integrada compatível com a arquitetura informada, não uma edição linha a linha do arquivo original do colega, cuja versão completa e atual não estava presente nesta entrega.
