# PRD — Agente de Admissibilidade Recursal (TJPR)

> **Projeto:** Assessor.AI — Exame de Admissibilidade de Recurso Especial e Extraordinário
> **Versão:** 1.0.0
> **Data:** 2025-02-10
> **Stack:** Python + OpenAI API + PDF Processing
> **Prompt Principal:** [`SYSTEM_PROMPT.md`](./SYSTEM_PROMPT.md) (arquivo separado para iteração independente)

---

## Visão Geral

Sistema de análise automatizada de recursos jurídicos (Recurso Especial e Extraordinário) do TJPR, composto por um pipeline sequencial de 3 etapas:

1. **Etapa 1** — Extração de dados da petição do recurso
2. **Etapa 2** — Análise do acórdão recorrido
3. **Etapa 3** — Geração da minuta de decisão de admissibilidade

O agente recebe PDFs fracionados, classifica automaticamente cada documento (recurso vs. acórdão), executa as 3 etapas em sequência e produz a minuta final formatada.

---

## Arquitetura de Alto Nível

```
PDFs (upload) → Extração de Texto → Classificação → Pipeline 3 Etapas (OpenAI) → Minuta Final
     │                │                    │                    │                      │
     ▼                ▼                    ▼                    ▼                      ▼
  Validação      PyMuPDF/          Prompt de              Etapa 1 → 2 → 3        Markdown +
  de entrada     pdfplumber        classificação          (chat completions)      Exportação
```

---

## Decisões Técnicas

| Componente         | Tecnologia                | Justificativa                                      |
|--------------------|---------------------------|----------------------------------------------------|
| Linguagem          | Python 3.11+              | Ecossistema maduro para IA e automação             |
| LLM                | OpenAI API (GPT-4o)       | Capacidade de contexto longo, qualidade de análise  |
| Extração de PDF    | PyMuPDF (fitz) + pdfplumber | Robustez com PDFs escaneados e fracionados       |
| Prompt             | Arquivo `.md` separado    | Iteração rápida sem alterar código                 |
| Interface          | CLI primeiro, API depois  | Validação rápida, depois exposição como serviço    |
| Armazenamento      | JSON em memória/disco     | Persistência entre etapas sem banco de dados       |
| Exportação         | Markdown → DOCX (opcional)| Formato legível + compatível com Word              |

---

## Sprints e Tarefas

---

### SPRINT 1 — Fundação e Infraestrutura

> **Objetivo:** Estrutura do projeto, configuração do ambiente, e leitura de PDFs funcional.

#### 1.1 Estrutura do Projeto

- [ ] **1.1.1** Criar repositório Git com `.gitignore` (Python, venv, `.env`, `__pycache__`)
- [ ] **1.1.2** Criar estrutura de diretórios:
  ```
  copilot-juridico/
  ├── src/
  │   ├── __init__.py
  │   ├── main.py              # Ponto de entrada CLI
  │   ├── config.py            # Configurações e variáveis de ambiente
  │   ├── pdf_processor.py     # Extração de texto de PDFs
  │   ├── classifier.py        # Classificação de documentos
  │   ├── pipeline.py          # Orquestrador das 3 etapas
  │   ├── etapa1.py            # Lógica da Etapa 1
  │   ├── etapa2.py            # Lógica da Etapa 2
  │   ├── etapa3.py            # Lógica da Etapa 3
  │   ├── prompt_loader.py     # Carregamento do prompt externo
  │   ├── output_formatter.py  # Formatação da saída final
  │   └── models.py            # Dataclasses/Pydantic models
  ├── prompts/
  │   └── SYSTEM_PROMPT.md     # Prompt principal (arquivo separado)
  ├── tests/
  │   ├── __init__.py
  │   ├── test_pdf_processor.py
  │   ├── test_classifier.py
  │   ├── test_etapa1.py
  │   ├── test_etapa2.py
  │   ├── test_etapa3.py
  │   └── fixtures/            # PDFs de teste
  ├── outputs/                 # Minutas geradas
  ├── .env.example
  ├── requirements.txt
  └── README.md
  ```
- [ ] **1.1.3** Criar `requirements.txt` com dependências iniciais: `openai`, `pymupdf`, `pdfplumber`, `python-dotenv`, `pydantic`, `rich` (para CLI)
- [ ] **1.1.4** Criar `.env.example` com variáveis: `OPENAI_API_KEY`, `OPENAI_MODEL` (default: `gpt-4o`), `MAX_TOKENS`, `TEMPERATURE` (default: `0.1`)
- [ ] **1.1.5** Criar `README.md` com instruções de setup, uso e estrutura

#### 1.2 Configuração e Ambiente

- [ ] **1.2.1** Implementar `config.py` com carregamento de `.env` via `python-dotenv`
- [ ] **1.2.2** Definir constantes: modelo padrão, temperatura, max_tokens, diretório de prompts, diretório de saída
- [ ] **1.2.3** Validar presença da `OPENAI_API_KEY` no startup com mensagem clara de erro
- [ ] **1.2.4** Implementar logging configurável (nível via env var `LOG_LEVEL`)

#### 1.3 Modelos de Dados

- [ ] **1.3.1** Criar dataclass/Pydantic model `DocumentoEntrada` com campos: `filepath`, `texto_extraido`, `tipo` (enum: `RECURSO`, `ACORDAO`, `DESCONHECIDO`), `num_paginas`
- [ ] **1.3.2** Criar model `ResultadoEtapa1` com campos: `numero_processo`, `recorrente`, `recorrido`, `especie_recurso`, `permissivo_constitucional`, `camara_civel`, `dispositivos_violados` (lista), `justica_gratuita` (bool), `efeito_suspensivo` (bool), `texto_formatado` (saída final)
- [ ] **1.3.3** Criar model `TemaEtapa2` com campos: `materia_controvertida`, `conclusao_fundamentos`, `base_vinculante`, `obices_sumulas`, `trecho_transcricao`
- [ ] **1.3.4** Criar model `ResultadoEtapa2` com campo: `temas` (lista de `TemaEtapa2`), `texto_formatado`
- [ ] **1.3.5** Criar model `ResultadoEtapa3` com campo: `minuta_completa` (texto final), `decisao` (enum: `ADMITIDO`, `INADMITIDO`)
- [ ] **1.3.6** Criar model `EstadoPipeline` que agrupa: `documentos_entrada`, `resultado_etapa1`, `resultado_etapa2`, `resultado_etapa3`, `metadata` (timestamps, modelo usado, tokens consumidos)

#### 1.4 Extração de Texto de PDFs

- [ ] **1.4.1** Implementar `pdf_processor.py` com função `extrair_texto(filepath: str) -> str` usando PyMuPDF como engine principal
- [ ] **1.4.2** Implementar fallback com `pdfplumber` caso PyMuPDF retorne texto vazio ou menor que threshold (100 caracteres)
- [ ] **1.4.3** Implementar limpeza de texto: remover quebras de página excessivas, normalizar espaços, remover headers/footers repetidos
- [ ] **1.4.4** Implementar detecção de PDF escaneado (sem texto extraível) com log de aviso ao usuário
- [ ] **1.4.5** Implementar concatenação de múltiplos PDFs fracionados em texto único por documento lógico
- [ ] **1.4.6** Adicionar contagem de páginas e caracteres no retorno para controle de contexto
- [ ] **1.4.7** Tratar exceções: arquivo corrompido, protegido por senha, formato inválido — com mensagens claras

#### 1.5 Testes da Sprint 1

- [ ] **1.5.1** Teste unitário: extração de texto de PDF válido com texto
- [ ] **1.5.2** Teste unitário: fallback pdfplumber quando PyMuPDF falha
- [ ] **1.5.3** Teste unitário: tratamento de PDF corrompido/inválido
- [ ] **1.5.4** Teste unitário: validação dos models Pydantic com dados válidos e inválidos
- [ ] **1.5.5** Teste unitário: carregamento de configuração com e sem `.env`

---

### SPRINT 2 — Classificação de Documentos e Carregamento de Prompt

> **Objetivo:** Classificar automaticamente PDFs (recurso vs. acórdão) e carregar o prompt externo.

#### 2.1 Carregamento do Prompt Externo

- [ ] **2.1.1** Implementar `prompt_loader.py` com função `carregar_prompt(caminho: str) -> str` que lê o arquivo `SYSTEM_PROMPT.md`
- [ ] **2.1.2** Implementar cache em memória do prompt (carregar uma vez, reutilizar)
- [ ] **2.1.3** Implementar hot-reload: detectar se o arquivo `.md` mudou (via timestamp) e recarregar automaticamente
- [ ] **2.1.4** Implementar extração de seções específicas do prompt por etapa (Etapa 1, 2, 3) usando parsing de headers markdown
- [ ] **2.1.5** Validar que o prompt não está vazio e tem as 3 seções de etapa; emitir erro claro se faltar alguma seção
- [ ] **2.1.6** Implementar função `montar_mensagem_sistema(etapa: int) -> str` que combina regras gerais + regras específicas da etapa

#### 2.2 Classificação de Documentos

- [ ] **2.2.1** Implementar `classifier.py` com função `classificar_documento(texto: str) -> TipoDocumento`
- [ ] **2.2.2** Implementar classificação por heurísticas textuais (primeira tentativa, sem LLM):
  - Detectar padrões de recurso: "PROJUDI - Recurso:", "Recurso Especial", "Recurso Extraordinário", "razões recursais", "art. 105, III" ou "art. 102, III"
  - Detectar padrões de acórdão: "ACÓRDÃO", "Vistos, relatados e discutidos", "Câmara Cível", "EMENTA", "ACORDAM"
- [ ] **2.2.3** Implementar classificação por LLM como fallback quando heurísticas forem inconclusivas (score de confiança < 0.7)
- [ ] **2.2.4** Criar prompt curto e específico para classificação via LLM: recebe os primeiros 2000 caracteres do texto e retorna JSON `{"tipo": "RECURSO"|"ACORDAO", "confianca": 0.0-1.0}`
- [ ] **2.2.5** Implementar lógica de agrupamento: quando múltiplos PDFs fracionados pertencem ao mesmo documento, agrupá-los antes de classificar
- [ ] **2.2.6** Implementar validação: garantir que pelo menos 1 recurso foi identificado; emitir aviso se nenhum acórdão foi encontrado
- [ ] **2.2.7** Logar resultado da classificação com confiança para auditoria

#### 2.3 Integração com OpenAI API

- [ ] **2.3.1** Implementar cliente OpenAI reutilizável em `config.py` ou módulo `llm_client.py`
- [ ] **2.3.2** Implementar função genérica `chamar_llm(system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> str`
- [ ] **2.3.3** Implementar retry com backoff exponencial para erros 429 (rate limit) e 500+ (server error) — máximo 3 tentativas
- [ ] **2.3.4** Implementar tracking de uso de tokens: registrar `prompt_tokens`, `completion_tokens`, `total_tokens` por chamada
- [ ] **2.3.5** Implementar timeout configurável (default: 120s) para chamadas longas
- [ ] **2.3.6** Implementar tratamento de resposta truncada: detectar se `finish_reason != "stop"` e logar aviso

#### 2.4 Testes da Sprint 2

- [ ] **2.4.1** Teste unitário: carregamento de prompt válido e extração de seções
- [ ] **2.4.2** Teste unitário: detecção de prompt inválido/incompleto
- [ ] **2.4.3** Teste unitário: classificação por heurística de texto com padrão de recurso
- [ ] **2.4.4** Teste unitário: classificação por heurística de texto com padrão de acórdão
- [ ] **2.4.5** Teste unitário: fallback para LLM quando heurística falha
- [ ] **2.4.6** Teste de integração: chamada real à OpenAI API com prompt de teste (marcado como slow test)

---

### SPRINT 3 — Etapa 1: Análise da Petição do Recurso

> **Objetivo:** Implementar a Etapa 1 completa — extração de dados do recurso com saída formatada.

#### 3.1 Lógica da Etapa 1

- [ ] **3.1.1** Implementar `etapa1.py` com função principal `executar_etapa1(texto_recurso: str, prompt_sistema: str) -> ResultadoEtapa1`
- [ ] **3.1.2** Montar o `user_message` com o texto completo do recurso, precedido de instrução: `"Analise o documento de recurso a seguir e execute a Etapa 1 conforme instruções."`
- [ ] **3.1.3** Implementar envio ao LLM com o system prompt contendo regras gerais + regras da Etapa 1
- [ ] **3.1.4** Implementar parsing da resposta do LLM para extrair campos estruturados (número processo, recorrente, etc.) do texto formatado
- [ ] **3.1.5** Implementar validação pós-resposta: verificar se campos obrigatórios estão presentes; marcar campos ausentes como `[NÃO CONSTA NO DOCUMENTO]`
- [ ] **3.1.6** Implementar detecção de alucinação básica: se a resposta contém informações que não aparecem no texto de entrada (ex.: números de artigos não presentes), logar alerta

#### 3.2 Parsing Estruturado da Saída

- [ ] **3.2.1** Implementar parser regex/string para extrair: número do processo do header `[RECURSO ESPECIAL CÍVEL] Nº xxx`
- [ ] **3.2.2** Implementar parser para extrair nome do Recorrente (texto em negrito após "I –")
- [ ] **3.2.3** Implementar parser para extrair espécie do recurso e permissivo constitucional
- [ ] **3.2.4** Implementar parser para extrair lista de dispositivos violados (itens a, b, c...)
- [ ] **3.2.5** Implementar parser para extrair flags de justiça gratuita e efeito suspensivo (Sim/Não)
- [ ] **3.2.6** Popular o model `ResultadoEtapa1` com dados parseados + texto formatado original

#### 3.3 Gestão de Contexto

- [ ] **3.3.1** Implementar verificação de tamanho do texto do recurso vs. limite de contexto do modelo (128k tokens para GPT-4o)
- [ ] **3.3.2** Se o texto exceder 80% do limite, implementar estratégia de chunking: dividir em partes com overlap e processar sequencialmente
- [ ] **3.3.3** Implementar estimativa de tokens usando `tiktoken` antes de enviar ao LLM
- [ ] **3.3.4** Logar tokens estimados vs. tokens reais consumidos para calibrar estimativas

#### 3.4 Armazenamento do Estado

- [ ] **3.4.1** Salvar `ResultadoEtapa1` no `EstadoPipeline` em memória
- [ ] **3.4.2** Implementar serialização do estado para JSON em disco (arquivo temporário) para recuperação em caso de falha
- [ ] **3.4.3** Implementar função `restaurar_estado(filepath: str) -> EstadoPipeline` para retomar de checkpoint

#### 3.5 Testes da Sprint 3

- [ ] **3.5.1** Teste unitário: parsing do formato de saída da Etapa 1 com resposta modelo
- [ ] **3.5.2** Teste unitário: detecção de campos ausentes no parsing
- [ ] **3.5.3** Teste unitário: estimativa de tokens com tiktoken
- [ ] **3.5.4** Teste unitário: serialização/deserialização do estado para JSON
- [ ] **3.5.5** Teste de integração: Etapa 1 completa com PDF real de recurso (marcado como slow test)

---

### SPRINT 4 — Etapa 2: Análise do Acórdão

> **Objetivo:** Implementar a Etapa 2 completa — análise temática do acórdão com óbices.

#### 4.1 Lógica da Etapa 2

- [ ] **4.1.1** Implementar `etapa2.py` com função principal `executar_etapa2(texto_acordao: str, resultado_etapa1: ResultadoEtapa1, prompt_sistema: str) -> ResultadoEtapa2`
- [ ] **4.1.2** Montar `user_message` incluindo: texto do acórdão + resumo dos dispositivos violados identificados na Etapa 1 (para direcionar a análise temática)
- [ ] **4.1.3** Implementar envio ao LLM com system prompt contendo regras gerais + regras da Etapa 2
- [ ] **4.1.4** Implementar parsing da resposta para extrair temas estruturados (matéria, conclusão, base vinculante, óbices)
- [ ] **4.1.5** Implementar validação: cada tema deve ter pelo menos matéria e conclusão preenchidos
- [ ] **4.1.6** Implementar extração e armazenamento de trechos literais do acórdão para transcrição na Etapa 3

#### 4.2 Parsing dos Temas

- [ ] **4.2.1** Implementar parser para separar blocos de tema (por parágrafo/seção)
- [ ] **4.2.2** Implementar parser para campo "Tema:" — extrair matéria controvertida
- [ ] **4.2.3** Implementar parser para campo "Conclusão e fundamentos" — extrair paráfrase
- [ ] **4.2.4** Implementar parser para campo "Aplicação de Tema/Precedente/Súmula" — extrair Sim/Não + qual
- [ ] **4.2.5** Implementar parser para campo "Óbices/Súmulas" — extrair lista de súmulas ou registro de impossibilidade
- [ ] **4.2.6** Popular lista de `TemaEtapa2` no model `ResultadoEtapa2`

#### 4.3 Validação de Óbices

- [ ] **4.3.1** Implementar lista das súmulas válidas do STJ (5, 7, 13, 83, 126, 211, 518) e STF (279, 280, 281, 282, 283, 284, 356, 735) como constantes
- [ ] **4.3.2** Validar que os óbices indicados pelo LLM estão na lista permitida; logar alerta se aparecer súmula não prevista
- [ ] **4.3.3** Verificar que o LLM não inventou óbices: cruzar com texto do acórdão para confirmar lastro

#### 4.4 Armazenamento do Estado

- [ ] **4.4.1** Salvar `ResultadoEtapa2` no `EstadoPipeline`
- [ ] **4.4.2** Atualizar checkpoint JSON em disco
- [ ] **4.4.3** Validar integridade: Etapa 2 só executa se Etapa 1 estiver completa no estado

#### 4.5 Testes da Sprint 4

- [ ] **4.5.1** Teste unitário: parsing do formato de saída da Etapa 2 com resposta modelo
- [ ] **4.5.2** Teste unitário: validação de súmulas contra lista permitida
- [ ] **4.5.3** Teste unitário: extração de múltiplos temas de resposta
- [ ] **4.5.4** Teste unitário: tratamento de tema com campos ausentes
- [ ] **4.5.5** Teste de integração: Etapa 2 completa com acórdão real (marcado como slow test)

---

### SPRINT 5 — Etapa 3: Geração da Minuta

> **Objetivo:** Implementar a Etapa 3 completa — montagem da minuta de admissibilidade.

#### 5.1 Lógica da Etapa 3

- [ ] **5.1.1** Implementar `etapa3.py` com função principal `executar_etapa3(resultado_etapa1: ResultadoEtapa1, resultado_etapa2: ResultadoEtapa2, texto_acordao: str, prompt_sistema: str) -> ResultadoEtapa3`
- [ ] **5.1.2** Montar `user_message` com: saída formatada da Etapa 1 + saída formatada da Etapa 2 + texto do acórdão (para transcrição literal)
- [ ] **5.1.3** Implementar envio ao LLM com system prompt contendo regras gerais + regras da Etapa 3
- [ ] **5.1.4** Implementar validação da minuta: verificar presença das seções I, II e III
- [ ] **5.1.5** Verificar que a seção I reproduz dados da Etapa 1 sem alteração
- [ ] **5.1.6** Verificar que a seção II contém pelo menos 1 tema com paráfrase + transcrição
- [ ] **5.1.7** Verificar que a seção III contém decisão (admito/inadmito) com fundamentação

#### 5.2 Validação Cruzada (Anti-Alucinação)

- [ ] **5.2.1** Comparar dispositivos listados na seção I da minuta com os da Etapa 1 — alertar se houver divergência
- [ ] **5.2.2** Comparar temas da seção II com os da Etapa 2 — alertar se houver tema novo ou ausente
- [ ] **5.2.3** Verificar que os trechos de transcrição literal existem no texto do acórdão (busca por substring) — alertar se não encontrado
- [ ] **5.2.4** Verificar que as súmulas citadas na seção III estão presentes na Etapa 2 — alertar se houver súmula nova

#### 5.3 Formatação de Saída

- [ ] **5.3.1** Implementar `output_formatter.py` com função `formatar_minuta(resultado: ResultadoEtapa3) -> str` que garante formatação markdown correta
- [ ] **5.3.2** Implementar negrito correto nos campos obrigatórios (nomes, tipo recurso, admito/inadmito)
- [ ] **5.3.3** Implementar salvamento da minuta em arquivo `.md` no diretório `outputs/` com nome: `minuta_{numero_processo}_{timestamp}.md`
- [ ] **5.3.4** Implementar geração de relatório de auditoria junto à minuta: tokens usados, alertas de validação, timestamps

#### 5.4 Armazenamento Final

- [ ] **5.4.1** Salvar `ResultadoEtapa3` no `EstadoPipeline`
- [ ] **5.4.2** Salvar estado completo final em JSON para referência futura
- [ ] **5.4.3** Limpar checkpoints intermediários após sucesso

#### 5.5 Testes da Sprint 5

- [ ] **5.5.1** Teste unitário: validação de estrutura I/II/III na minuta
- [ ] **5.5.2** Teste unitário: detecção de divergência entre Etapa 1 e seção I da minuta
- [ ] **5.5.3** Teste unitário: verificação de transcrição literal presente no acórdão
- [ ] **5.5.4** Teste unitário: formatação markdown correta
- [ ] **5.5.5** Teste de integração: pipeline Etapa 1 → 2 → 3 completo (marcado como slow test)

---

### SPRINT 6 — Orquestrador e CLI

> **Objetivo:** Implementar o pipeline completo (orquestrador) e a interface de linha de comando.

#### 6.1 Orquestrador do Pipeline

- [ ] **6.1.1** Implementar `pipeline.py` com classe `PipelineAdmissibilidade` que orquestra o fluxo completo
- [ ] **6.1.2** Implementar método `executar(pdfs: list[str]) -> ResultadoEtapa3`:
  1. Extrair texto de todos os PDFs
  2. Classificar documentos
  3. Executar Etapa 1 (recurso)
  4. Executar Etapa 2 (acórdão)
  5. Executar Etapa 3 (minuta)
  6. Retornar resultado
- [ ] **6.1.3** Implementar tratamento de fluxo interrompido: detectar estado salvo e perguntar ao usuário se quer continuar ou reiniciar
- [ ] **6.1.4** Implementar callback/progress para atualizar o usuário sobre o andamento (ex.: "Etapa 1 concluída... iniciando Etapa 2...")
- [ ] **6.1.5** Implementar coleta de métricas: tempo total, tempo por etapa, tokens totais, custo estimado (baseado em pricing da OpenAI)

#### 6.2 Interface CLI

- [ ] **6.2.1** Implementar `main.py` com CLI usando `argparse` ou `typer`:
  ```
  python -m src.main processar documento1.pdf documento2.pdf [documento3.pdf ...]
  python -m src.main status                  # mostra estado do último processamento
  python -m src.main limpar                  # limpa checkpoints
  ```
- [ ] **6.2.2** Implementar flag `--modelo` para selecionar modelo OpenAI (default: gpt-4o)
- [ ] **6.2.3** Implementar flag `--temperatura` para ajustar criatividade (default: 0.1)
- [ ] **6.2.4** Implementar flag `--saida` para diretório de saída customizado
- [ ] **6.2.5** Implementar flag `--verbose` para logging detalhado
- [ ] **6.2.6** Implementar saída formatada com `rich`: progress bars, painéis de status, cores para alertas
- [ ] **6.2.7** Implementar resumo final no terminal: número do processo, decisão, tokens usados, custo estimado, caminho do arquivo gerado

#### 6.3 Tratamento de Erros Global

- [ ] **6.3.1** Implementar handler global de exceções que salva o estado antes de sair
- [ ] **6.3.2** Implementar mensagens de erro amigáveis: API key inválida, quota excedida, timeout, PDF inválido
- [ ] **6.3.3** Implementar log de erros em arquivo para diagnóstico

#### 6.4 Testes da Sprint 6

- [ ] **6.4.1** Teste de integração: pipeline completo com PDFs reais de recurso + acórdão
- [ ] **6.4.2** Teste: recuperação de estado após interrupção simulada
- [ ] **6.4.3** Teste: CLI com argumentos válidos e inválidos
- [ ] **6.4.4** Teste: tratamento de erro quando API key é inválida

---

### SPRINT 7 — Refinamento, Documentação e Deploy

> **Objetivo:** Polimento, documentação completa, e preparação para uso em produção.

#### 7.1 Refinamento do Prompt

- [ ] **7.1.1** Executar 5+ casos reais e coletar resultados para análise de qualidade
- [ ] **7.1.2** Identificar padrões de erro/alucinação recorrentes e ajustar `SYSTEM_PROMPT.md`
- [ ] **7.1.3** Ajustar temperatura e max_tokens baseado nos resultados reais
- [ ] **7.1.4** Documentar no `SYSTEM_PROMPT.md` o changelog de ajustes (tabela de versionamento)

#### 7.2 Exportação DOCX (Opcional)

- [ ] **7.2.1** Implementar conversão Markdown → DOCX usando `python-docx` ou `pandoc`
- [ ] **7.2.2** Aplicar formatação compatível com padrão TJPR (fonte, espaçamento, margens)
- [ ] **7.2.3** Adicionar flag `--formato docx` na CLI

#### 7.3 Documentação

- [ ] **7.3.1** Completar `README.md` com: instalação, configuração, uso, exemplos, troubleshooting
- [ ] **7.3.2** Documentar fluxo de ajuste de prompt (como editar o `SYSTEM_PROMPT.md` e testar)
- [ ] **7.3.3** Documentar estrutura dos arquivos de saída e do JSON de estado
- [ ] **7.3.4** Criar `CONTRIBUTING.md` com guia de contribuição (se for compartilhado)

#### 7.4 Preparação para Deploy

- [ ] **7.4.1** Criar `Dockerfile` para containerização
- [ ] **7.4.2** Criar `docker-compose.yml` para execução local simplificada
- [ ] **7.4.3** Testar execução em container Docker de ponta a ponta
- [ ] **7.4.4** Documentar opções de deploy: local, VPS (Contabo), ou integração com n8n via webhook

#### 7.5 Integração com n8n (Opcional)

- [ ] **7.5.1** Criar endpoint HTTP (FastAPI ou Flask) que recebe PDFs e retorna minuta
- [ ] **7.5.2** Documentar webhook para integração com n8n
- [ ] **7.5.3** Testar fluxo n8n → API → minuta → notificação

---

## Resumo de Métricas

| Sprint | Tarefas | Subtarefas | Foco                              |
|--------|---------|------------|-----------------------------------|
| 1      | 5       | 22         | Fundação, PDFs, models            |
| 2      | 4       | 19         | Classificação, prompt, OpenAI API |
| 3      | 5       | 17         | Etapa 1 — Recurso                 |
| 4      | 5       | 15         | Etapa 2 — Acórdão                 |
| 5      | 5       | 17         | Etapa 3 — Minuta                  |
| 6      | 4       | 15         | Orquestrador e CLI                |
| 7      | 5       | 15         | Refinamento e deploy              |
| **Total** | **33** | **120** | —                              |

---

## Riscos e Mitigações

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Alucinação do LLM | Alto | Validação cruzada entre etapas; temperatura baixa (0.1); checagem de substring |
| PDFs escaneados sem OCR | Médio | Fallback com pdfplumber; aviso ao usuário; futuramente integrar Tesseract |
| Limite de contexto excedido | Médio | Estimativa prévia com tiktoken; chunking com overlap |
| Custo de API alto | Baixo | Tracking de tokens; relatório de custo; possível troca para modelo mais barato em classificação |
| Formato de saída inconsistente | Médio | Parser robusto; validação estrutural; retry se formato inválido |

---

## Critérios de Aceite (Definition of Done)

Uma tarefa é considerada concluída quando:

1. O código implementa exatamente o escopo descrito na subtarefa
2. Testes unitários passam (quando aplicável)
3. Sem erros de linting (`ruff` ou `flake8`)
4. Funcionalidade verificada manualmente com pelo menos 1 caso real
5. Checklist marcado com `[x]`
