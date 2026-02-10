# Arquitetura Técnica

## Stack

| Componente | Tecnologia | Justificativa |
|------------|------------|---------------|
| Linguagem | Python 3.11+ | Ecossistema maduro para IA e automação |
| LLM | OpenAI API (GPT-4o) | Contexto longo (128k tokens), qualidade de análise |
| Extração de PDF | PyMuPDF (fitz) + pdfplumber | Robustez com PDFs escaneados e fracionados |
| Prompt | Arquivo `.md` separado | Iteração rápida sem alterar código |
| Interface | CLI (fase 1), API (fase 2) | Validação rápida, depois exposição como serviço |
| Armazenamento | JSON em memória/disco | Persistência entre etapas sem banco de dados |
| Exportação | Markdown → DOCX (opcional) | Formato legível + compatível com Word |
| Testes | pytest | Conforme definido no `CLAUDE.md` |

## Fluxo de dados

```
PDFs (upload)
    │
    ▼
Extração de Texto (PyMuPDF / pdfplumber fallback)
    │
    ▼
Classificação (heurística textual → fallback LLM)
    │
    ├── Recurso → Etapa 1 (OpenAI)
    │                │
    │                ▼
    ├── Acórdão → Etapa 2 (OpenAI, com dados da Etapa 1)
    │                │
    │                ▼
    └──────────── Etapa 3 (OpenAI, com dados das Etapas 1+2)
                     │
                     ▼
               Minuta Final (.md / .docx)
```

## Modelos de dados planejados

| Model | Descrição |
|-------|-----------|
| `DocumentoEntrada` | PDF de entrada: filepath, texto extraído, tipo (RECURSO/ACORDAO), páginas |
| `ResultadoEtapa1` | Dados do recurso: nº processo, partes, dispositivos, flags |
| `TemaEtapa2` | Tema individual: matéria, conclusão, base vinculante, óbices |
| `ResultadoEtapa2` | Lista de temas do acórdão |
| `ResultadoEtapa3` | Minuta completa + decisão (ADMITIDO/INADMITIDO) |
| `EstadoPipeline` | Agrupa todos os resultados + metadata (timestamps, tokens) |

## Variáveis de ambiente

| Variável | Descrição | Default |
|----------|-----------|---------|
| `OPENAI_API_KEY` | Chave da API OpenAI | — (obrigatória) |
| `OPENAI_MODEL` | Modelo a usar | `gpt-4o` |
| `MAX_TOKENS` | Limite de tokens por chamada | — |
| `TEMPERATURE` | Temperatura da geração | `0.1` |
| `LOG_LEVEL` | Nível de logging | — |
