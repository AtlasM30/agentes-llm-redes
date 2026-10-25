"""Avalia previsoes usando gabarito EXCLUSIVAMENTE no avaliador.

Uso: python3 avaliar_diagnostico.py
     python3 avaliar_diagnostico.py --gabarito avaliacao/gabarito_avaliacao.json
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from diagnostico.pipeline import carregar_evidencias
from diagnostico.regras import diagnosticar_cliente


def latencia(dados, nome):
    return dados['dispositivos'][nome].get('ping', {}).get('latencia_media_ms')


def avaliar(pasta_logs, arquivo_gabarito):
    with arquivo_gabarito.open(encoding='utf-8') as arquivo:
        gabarito = json.load(arquivo)
    if not isinstance(gabarito, dict) or not isinstance(gabarito.get('casos'), dict):
        raise ValueError("O gabarito deve conter um objeto 'casos'.")

    # Baseline obtida somente do JSON de evidencias, sem ler rotulos do gabarito.
    normal = carregar_evidencias(pasta_logs / 'evidencias_caso_00.json')
    referencias = {nome: latencia(normal, nome) for nome in ('client1', 'client2')}
    resultados = []
    erros = []

    for identificador, rotulos in sorted(gabarito['casos'].items()):
        arquivo_caso = pasta_logs / f'evidencias_{identificador}.json'
        if not arquivo_caso.is_file():
            erros.append(f'Evidencia ausente: {arquivo_caso}')
            continue
        try:
            dados = carregar_evidencias(arquivo_caso)
            servidor = dados['dispositivos']['server']
            for nome in ('client1', 'client2'):
                esperado = rotulos.get(nome)
                if not isinstance(esperado, str):
                    erros.append(f'Rotulo ausente: {identificador}/{nome}')
                    continue
                resposta = diagnosticar_cliente(
                    dados['dispositivos'][nome],
                    nome=nome,
                    servidor=servidor,
                    latencia_referencia=referencias[nome],
                )
                previsto = resposta.get('hipotese', 'sem_resultado')
                resultados.append({
                    'caso': identificador,
                    'dispositivo': nome,
                    'esperado': esperado,
                    'previsto': previsto,
                    'acerto': previsto == esperado,
                    'confianca': resposta.get('confianca', ''),
                    'evidencias_utilizadas': resposta.get('evidencias', []),
                })
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            erros.append(f'{identificador}: {type(exc).__name__}: {exc}')

    total = len(resultados)
    acertos = sum(r['acerto'] for r in resultados)
    inconclusivos = sum(r['previsto'] in {'evidencias_insuficientes', 'falha_de_conectividade', 'problema_http_ou_bloqueio'} for r in resultados)
    matriz = Counter((r['esperado'], r['previsto']) for r in resultados)
    return {
        'gerado_em_utc': datetime.now(timezone.utc).isoformat(),
        'total_avaliado': total,
        'acertos': acertos,
        'erros_classificacao': total - acertos,
        'taxa_acerto': (acertos / total if total else None),
        'hipoteses_inconclusivas_ou_genericas': inconclusivos,
        'matriz_confusao': [
            {'esperado': esperado, 'previsto': previsto, 'quantidade': quantidade}
            for (esperado, previsto), quantidade in sorted(matriz.items())
        ],
        'resultados': resultados,
        'problemas_leitura': erros,
        'nota': ('Avaliacao restrita aos cenarios controlados; rotulos servem apenas '
                 'para pontuacao. O gabarito nao e utilizado pelo diagnostico.'),
    }


def main():
    parser = argparse.ArgumentParser(description='Avaliacao offline do diagnostico por regras')
    parser.add_argument('--logs', type=Path, default=Path('logs'))
    parser.add_argument('--gabarito', type=Path, default=Path('avaliacao/gabarito_avaliacao.json'))
    parser.add_argument('--saida', type=Path, default=Path('resultados_avaliacao'))
    args = parser.parse_args()
    relatorio = avaliar(args.logs, args.gabarito)
    args.saida.mkdir(parents=True, exist_ok=True)
    arquivo_json = args.saida / 'avaliacao_diagnostico.json'
    arquivo_csv = args.saida / 'avaliacao_diagnostico.csv'
    arquivo_json.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with arquivo_csv.open('w', newline='', encoding='utf-8') as arq:
        writer = csv.DictWriter(arq, fieldnames=['caso', 'dispositivo', 'esperado', 'previsto', 'acerto', 'confianca', 'evidencias_utilizadas'])
        writer.writeheader()
        for item in relatorio['resultados']:
            writer.writerow({**item, 'evidencias_utilizadas': ' | '.join(map(str, item['evidencias_utilizadas']))})
    print(f"\nAvaliados: {relatorio['total_avaliado']} | Acertos: {relatorio['acertos']} | Erros: {relatorio['erros_classificacao']}")
    if relatorio['taxa_acerto'] is not None:
        print(f"Taxa de acerto nos cenarios controlados: {relatorio['taxa_acerto'] * 100:.1f}%")
    for r in relatorio['resultados']:
        marca = 'OK' if r['acerto'] else 'DIVERGENTE'
        print(f"{r['caso']} {r['dispositivo']}: {r['previsto']} (esperado: {r['esperado']}) [{marca}]")
    for erro in relatorio['problemas_leitura']:
        print('AVISO:', erro)
    print('JSON:', arquivo_json)
    print('CSV: ', arquivo_csv)
    if relatorio['problemas_leitura']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
