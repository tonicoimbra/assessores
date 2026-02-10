# TASKS — Agente de Admissibilidade Recursal (TJPR)

> ✅ Sprint 1 concluída

## SPRINT 1 — Fundação e Infraestrutura

### 1.1 Estrutura do Projeto

- [x] **1.1.1** Criar repositório Git com `.gitignore` (Python, venv, `.env`, `__pycache__`)
- [x] **1.1.2** Criar estrutura de diretórios
- [x] **1.1.3** Criar `requirements.txt` com dependências iniciais
- [x] **1.1.4** Criar `.env.example` com variáveis de ambiente
- [x] **1.1.5** Criar `README.md` com instruções de setup, uso e estrutura

### 1.2 Configuração e Ambiente

- [x] **1.2.1** Implementar `config.py` com carregamento de `.env` via `python-dotenv`
- [x] **1.2.2** Definir constantes: modelo padrão, temperatura, max_tokens, diretório de prompts, diretório de saída
- [x] **1.2.3** Validar presença da `OPENAI_API_KEY` no startup com mensagem clara de erro
- [x] **1.2.4** Implementar logging configurável (nível via env var `LOG_LEVEL`)

### 1.3 Modelos de Dados

- [x] **1.3.1** Criar model `DocumentoEntrada`
- [x] **1.3.2** Criar model `ResultadoEtapa1`
- [x] **1.3.3** Criar model `TemaEtapa2`
- [x] **1.3.4** Criar model `ResultadoEtapa2`
- [x] **1.3.5** Criar model `ResultadoEtapa3`
- [x] **1.3.6** Criar model `EstadoPipeline`

### 1.4 Extração de Texto de PDFs

- [x] **1.4.1** Implementar `pdf_processor.py` com função `extrair_texto()`
- [x] **1.4.2** Implementar fallback com `pdfplumber`
- [x] **1.4.3** Implementar limpeza de texto
- [x] **1.4.4** Implementar detecção de PDF escaneado
- [x] **1.4.5** Implementar concatenação de múltiplos PDFs fracionados
- [x] **1.4.6** Adicionar contagem de páginas e caracteres
- [x] **1.4.7** Tratar exceções: arquivo corrompido, protegido por senha, formato inválido

### 1.5 Testes da Sprint 1

- [x] **1.5.1** Teste: extração de texto de PDF válido
- [x] **1.5.2** Teste: fallback pdfplumber quando PyMuPDF falha
- [x] **1.5.3** Teste: tratamento de PDF corrompido/inválido
- [x] **1.5.4** Teste: validação dos models Pydantic
- [x] **1.5.5** Teste: carregamento de configuração

---

## SPRINT 2 — Classificação de Documentos e Carregamento de Prompt

### 2.1 Carregamento do Prompt Externo

- [ ] **2.1.1** Implementar `prompt_loader.py` com função `carregar_prompt()`
- [ ] **2.1.2** Implementar cache em memória do prompt
- [ ] **2.1.3** Implementar hot-reload via timestamp
- [ ] **2.1.4** Implementar extração de seções por etapa (parsing de headers markdown)
- [ ] **2.1.5** Validar que o prompt tem as 3 seções de etapa
- [ ] **2.1.6** Implementar `montar_mensagem_sistema(etapa)` — regras gerais + específicas

### 2.2 Classificação de Documentos

- [x] **2.2.1** Implementar `classifier.py` com função `classificar_documento()`
- [x] **2.2.2** Classificação por heurísticas textuais (padrões de recurso e acórdão)
- [x] **2.2.3** Classificação por LLM como fallback (confiança < 0.7)
- [x] **2.2.4** Criar prompt curto para classificação via LLM
- [x] **2.2.5** Lógica de agrupamento de PDFs fracionados
- [x] **2.2.6** Validação: pelo menos 1 recurso identificado
- [x] **2.2.7** Logar resultado da classificação com confiança

### 2.3 Integração com OpenAI API

- [x] **2.3.1** Implementar cliente OpenAI reutilizável (`llm_client.py`)
- [x] **2.3.2** Função genérica `chamar_llm()`
- [x] **2.3.3** Retry com backoff exponencial (429/500+)
- [x] **2.3.4** Tracking de uso de tokens
- [x] **2.3.5** Timeout configurável (default: 120s)
- [x] **2.3.6** Tratamento de resposta truncada (`finish_reason != "stop"`)

### 2.4 Testes da Sprint 2

- [x] **2.4.1** Teste: carregamento de prompt válido e extração de seções
- [x] **2.4.2** Teste: detecção de prompt inválido/incompleto
- [x] **2.4.3** Teste: classificação por heurística — padrão de recurso
- [x] **2.4.4** Teste: classificação por heurística — padrão de acórdão
- [x] **2.4.5** Teste: fallback para LLM quando heurística falha
- [x] **2.4.6** Teste de integração: chamada real à OpenAI API (slow test)

---

## SPRINT 3 — Etapa 1: Análise da Petição do Recurso

### 3.1 Lógica da Etapa 1

- [x] **3.1.1** Implementar `etapa1.py` com função `executar_etapa1()`
- [x] **3.1.2** Montar `user_message` com texto do recurso
- [x] **3.1.3** Envio ao LLM com system prompt (regras gerais + Etapa 1)
- [x] **3.1.4** Parsing da resposta para extrair campos estruturados
- [x] **3.1.5** Validação pós-resposta: campos obrigatórios presentes
- [x] **3.1.6** Detecção básica de alucinação

### 3.2 Parsing Estruturado da Saída

- [x] **3.2.1** Parser para número do processo
- [x] **3.2.2** Parser para nome do Recorrente
- [x] **3.2.3** Parser para espécie do recurso e permissivo constitucional
- [x] **3.2.4** Parser para dispositivos violados
- [x] **3.2.5** Parser para justiça gratuita e efeito suspensivo
- [x] **3.2.6** Popular `ResultadoEtapa1` com dados parseados

### 3.3 Gestão de Contexto

- [x] **3.3.1** Verificação de tamanho vs. limite de contexto (128k tokens)
- [x] **3.3.2** Chunking com overlap se exceder 80%
- [x] **3.3.3** Estimativa de tokens com `tiktoken`
- [x] **3.3.4** Log de tokens estimados vs. reais

### 3.4 Armazenamento do Estado

- [x] **3.4.1** Salvar `ResultadoEtapa1` no `EstadoPipeline`
- [x] **3.4.2** Serialização do estado para JSON em disco
- [x] **3.4.3** Função `restaurar_estado()` para retomar de checkpoint

### 3.5 Testes da Sprint 3

- [x] **3.5.1** Teste: parsing do formato de saída da Etapa 1
- [x] **3.5.2** Teste: detecção de campos ausentes
- [x] **3.5.3** Teste: estimativa de tokens com tiktoken
- [x] **3.5.4** Teste: serialização/deserialização do estado
- [x] **3.5.5** Teste de integração: Etapa 1 completa (slow test)

---

## SPRINT 4 — Etapa 2: Análise do Acórdão

### 4.1 Lógica da Etapa 2

- [x] **4.1.1** Implementar `etapa2.py` com função `executar_etapa2()`
- [x] **4.1.2** Montar `user_message` com texto do acórdão + dispositivos da Etapa 1
- [x] **4.1.3** Envio ao LLM com system prompt (regras gerais + Etapa 2)
- [x] **4.1.4** Parsing da resposta para extrair temas estruturados
- [x] **4.1.5** Validação: cada tema com matéria e conclusão preenchidos
- [x] **4.1.6** Extração e armazenamento de trechos literais do acórdão

### 4.2 Parsing dos Temas

- [x] **4.2.1** Parser para separar blocos de tema
- [x] **4.2.2** Parser para campo "Tema:" — matéria controvertida
- [x] **4.2.3** Parser para campo "Conclusão e fundamentos"
- [x] **4.2.4** Parser para campo "Aplicação de Tema/Precedente/Súmula"
- [x] **4.2.5** Parser para campo "Óbices/Súmulas"
- [x] **4.2.6** Popular lista de `TemaEtapa2` no `ResultadoEtapa2`

### 4.3 Validação de Óbices

- [x] **4.3.1** Lista das súmulas válidas STJ/STF como constantes
- [x] **4.3.2** Validar óbices do LLM contra lista permitida
- [x] **4.3.3** Cruzar óbices com texto do acórdão para confirmar lastro

### 4.4 Armazenamento do Estado

- [x] **4.4.1** Salvar `ResultadoEtapa2` no `EstadoPipeline`
- [x] **4.4.2** Atualizar checkpoint JSON em disco
- [x] **4.4.3** Validar: Etapa 2 só executa se Etapa 1 completa

### 4.5 Testes da Sprint 4

- [x] **4.5.1** Teste: parsing do formato de saída da Etapa 2
- [x] **4.5.2** Teste: validação de súmulas contra lista permitida
- [x] **4.5.3** Teste: extração de múltiplos temas
- [x] **4.5.4** Teste: tratamento de tema com campos ausentes
- [x] **4.5.5** Teste de integração: Etapa 2 completa (slow test)

---

## SPRINT 5 — Etapa 3: Geração da Minuta

### 5.1 Lógica da Etapa 3

- [x] **5.1.1** Implementar `etapa3.py` com função `executar_etapa3()`
- [x] **5.1.2** Montar `user_message` com saídas da Etapa 1 + Etapa 2 + texto do acórdão
- [x] **5.1.3** Envio ao LLM com system prompt (regras gerais + Etapa 3)
- [x] **5.1.4** Validação da minuta: presença das seções I, II e III
- [x] **5.1.5** Verificar que seção I reproduz dados da Etapa 1
- [x] **5.1.6** Verificar que seção II contém temas com paráfrase + transcrição
- [x] **5.1.7** Verificar que seção III contém decisão com fundamentação

### 5.2 Validação Cruzada (Anti-Alucinação)

- [x] **5.2.1** Comparar dispositivos da seção I com Etapa 1
- [x] **5.2.2** Comparar temas da seção II com Etapa 2
- [x] **5.2.3** Verificar trechos de transcrição no texto do acórdão
- [x] **5.2.4** Verificar súmulas da seção III contra Etapa 2

### 5.3 Formatação de Saída

- [x] **5.3.1** Implementar `output_formatter.py` com `formatar_minuta()`
- [x] **5.3.2** Negrito nos campos obrigatórios
- [x] **5.3.3** Salvamento em arquivo `.md` no diretório `outputs/`
- [x] **5.3.4** Geração de relatório de auditoria

### 5.4 Armazenamento Final

- [x] **5.4.1** Salvar `ResultadoEtapa3` no `EstadoPipeline`
- [x] **5.4.2** Salvar estado completo final em JSON
- [x] **5.4.3** Limpar checkpoints intermediários após sucesso

### 5.5 Testes da Sprint 5

- [x] **5.5.1** Teste: validação de estrutura I/II/III na minuta
- [x] **5.5.2** Teste: divergência entre Etapa 1 e seção I
- [x] **5.5.3** Teste: transcrição literal presente no acórdão
- [x] **5.5.4** Teste: formatação markdown correta
- [x] **5.5.5** Teste de integração: pipeline completo (slow test)


---

## SPRINT 6 — Orquestrador e CLI

### 6.1 Orquestrador do Pipeline

- [x] **6.1.1** Implementar `pipeline.py` com `PipelineAdmissibilidade`
- [x] **6.1.2** Implementar método `executar()` com fluxo completo
- [x] **6.1.3** Tratamento de fluxo interrompido (checkpoint resume)
- [x] **6.1.4** Callback/progress para atualizar andamento
- [x] **6.1.5** Coleta de métricas: tempo, tokens, custo estimado

### 6.2 Interface CLI

- [x] **6.2.1** Implementar `main.py` com CLI argparse (processar/status/limpar)
- [x] **6.2.2** Flag `--modelo` para selecionar modelo
- [x] **6.2.3** Flag `--temperatura` para ajustar criatividade
- [x] **6.2.4** Flag `--saida` para diretório customizado
- [x] **6.2.5** Flag `--verbose` para logging detalhado
- [x] **6.2.6** Saída formatada com progress bar e painéis
- [x] **6.2.7** Resumo final: decisão, tokens, custo, caminho

### 6.3 Tratamento de Erros Global

- [x] **6.3.1** Handler global que salva estado antes de sair
- [x] **6.3.2** Mensagens amigáveis: API key, quota, timeout, PDF inválido
- [x] **6.3.3** Log de erros em arquivo para diagnóstico

### 6.4 Testes da Sprint 6

- [x] **6.4.1** Teste: pipeline completo com mocks
- [x] **6.4.2** Teste: recuperação de estado após interrupção
- [x] **6.4.3** Teste: CLI com argumentos válidos e inválidos
- [x] **6.4.4** Teste: tratamento de erro quando API key inválida

---

## SPRINT 7 — Refinamento e deploy

- [x] **SPRINT 7** Concluir todas as tarefas da sprint

### 7.1 Refinamento do Prompt

- [x] **7.1** Concluir tarefa 7.1
- [x] **7.1.1** Executar 5+ casos reais e coletar resultados para análise de qualidade
- [x] **7.1.2** Identificar padrões de erro/alucinação recorrentes e ajustar `SYSTEM_PROMPT.md`
- [x] **7.1.3** Ajustar temperatura e max_tokens baseado nos resultados reais
- [x] **7.1.4** Documentar no `SYSTEM_PROMPT.md` o changelog de ajustes (tabela de versionamento)

### 7.2 Exportação DOCX (Opcional)

- [x] **7.2** Concluir tarefa 7.2
- [x] **7.2.1** Implementar conversão Markdown → DOCX usando `python-docx` ou `pandoc`
- [x] **7.2.2** Aplicar formatação compatível com padrão TJPR (fonte, espaçamento, margens)
- [x] **7.2.3** Adicionar flag `--formato docx` na CLI

### 7.3 Documentação

- [x] **7.3** Concluir tarefa 7.3
- [x] **7.3.1** Completar `README.md` com: instalação, configuração, uso, exemplos, troubleshooting
- [x] **7.3.2** Documentar fluxo de ajuste de prompt (como editar o `SYSTEM_PROMPT.md` e testar)
- [x] **7.3.3** Documentar estrutura dos arquivos de saída e do JSON de estado
- [x] **7.3.4** Criar `CONTRIBUTING.md` com guia de contribuição (se for compartilhado)

### 7.4 Preparação para Deploy

- [x] **7.4** Concluir tarefa 7.4
- [x] **7.4.1** Criar `Dockerfile` para containerização
- [x] **7.4.2** Criar `docker-compose.yml` para execução local simplificada
- [x] **7.4.3** Testar execução em container Docker de ponta a ponta
- [x] **7.4.4** Documentar opções de deploy: local, VPS (Contabo), ou integração com n8n via webhook


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
