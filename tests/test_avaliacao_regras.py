import unittest

from diagnostico.regras import diagnosticar_cliente


class TestRobustezDiagnostico(unittest.TestCase):
    def test_sem_campos_retorna_inconclusivo(self):
        self.assertEqual(diagnosticar_cliente({})['hipotese'], 'evidencias_insuficientes')

    def test_http_indisponivel_sem_acl_nao_inventa_bloqueio(self):
        d = {'ping': {'sucesso': True}, 'dns': {'resolucao_correta': True},
             'http': {'servico_disponivel': False}}
        self.assertEqual(diagnosticar_cliente(d, servidor={'acl': {'sucesso': True, 'saida': '-P INPUT ACCEPT'}})['hipotese'],
                         'problema_http_ou_bloqueio')

    def test_ping_falha_sem_rotas_validas_eh_generico(self):
        d = {'ping': {'sucesso': False}, 'dns': {'resolucao_correta': False},
             'http': {'servico_disponivel': False}, 'rotas': {'sucesso': False, 'saida': ''}}
        self.assertEqual(diagnosticar_cliente(d)['hipotese'], 'falha_de_conectividade')

    def test_congestionamento_com_referencia(self):
        d = {'ping': {'sucesso': True, 'latencia_media_ms': 250},
             'dns': {'resolucao_correta': True}, 'http': {'servico_disponivel': True}}
        self.assertEqual(diagnosticar_cliente(d, latencia_referencia=20)['hipotese'], 'possivel_congestionamento')

    def test_latencia_sem_base_nao_prova_congestionamento(self):
        d = {'ping': {'sucesso': True, 'latencia_media_ms': 250},
             'dns': {'resolucao_correta': True}, 'http': {'servico_disponivel': True}}
        self.assertEqual(diagnosticar_cliente(d)['hipotese'], 'latencia_elevada')


if __name__ == '__main__':
    unittest.main()
