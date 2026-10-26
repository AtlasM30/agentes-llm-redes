"""Modulo do Agente LLM de Diagnostico com RAG, Validacao e Auditoria."""
from agente.auditoria import ConfiguracaoAgente, RegistroAuditoria
from agente.diagnostico_agente import AgenteDiagnosticoRedes
from agente.executor import (
    ExecutorEvidenciasOffline,
    ExecutorMininetAtivo,
    sanitizar_evidencias_brutas,
    verificar_arquivo_evidencia_permitido,
)
from agente.provedores_llm import (
    ClienteGemini,
    ClienteLLMSimulado,
    ClienteOllama,
    ClienteOpenAICompativel,
    criar_cliente_llm,
)

__all__ = [
    "AgenteDiagnosticoRedes",
    "ClienteGemini",
    "ClienteLLMSimulado",
    "ClienteOllama",
    "ClienteOpenAICompativel",
    "ConfiguracaoAgente",
    "ExecutorEvidenciasOffline",
    "ExecutorMininetAtivo",
    "RegistroAuditoria",
    "criar_cliente_llm",
    "sanitizar_evidencias_brutas",
    "verificar_arquivo_evidencia_permitido",
]
