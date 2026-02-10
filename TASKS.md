# TASKS — Agente de Admissibilidade Recursal (TJPR)

## SPRINT 1 — Fundação e Infraestrutura

### 1.1 Estrutura do Projeto

- [x] **1.1.1** Criar repositório Git com `.gitignore` (Python, venv, `.env`, `__pycache__`)
- [x] **1.1.2** Criar estrutura de diretórios
- [x] **1.1.3** Criar `requirements.txt` com dependências iniciais
- [x] **1.1.4** Criar `.env.example` com variáveis de ambiente
- [x] **1.1.5** Criar `README.md` com instruções de setup, uso e estrutura

### 1.2 Configuração e Ambiente

- [ ] **1.2.1** Implementar `config.py` com carregamento de `.env` via `python-dotenv`
- [ ] **1.2.2** Definir constantes: modelo padrão, temperatura, max_tokens, diretório de prompts, diretório de saída
- [ ] **1.2.3** Validar presença da `OPENAI_API_KEY` no startup com mensagem clara de erro
- [ ] **1.2.4** Implementar logging configurável (nível via env var `LOG_LEVEL`)

### 1.3 Modelos de Dados

- [ ] **1.3.1** Criar model `DocumentoEntrada`
- [ ] **1.3.2** Criar model `ResultadoEtapa1`
- [ ] **1.3.3** Criar model `TemaEtapa2`
- [ ] **1.3.4** Criar model `ResultadoEtapa2`
- [ ] **1.3.5** Criar model `ResultadoEtapa3`
- [ ] **1.3.6** Criar model `EstadoPipeline`

### 1.4 Extração de Texto de PDFs

- [ ] **1.4.1** Implementar `pdf_processor.py` com função `extrair_texto()`
- [ ] **1.4.2** Implementar fallback com `pdfplumber`
- [ ] **1.4.3** Implementar limpeza de texto
- [ ] **1.4.4** Implementar detecção de PDF escaneado
- [ ] **1.4.5** Implementar concatenação de múltiplos PDFs fracionados
- [ ] **1.4.6** Adicionar contagem de páginas e caracteres
- [ ] **1.4.7** Tratar exceções: arquivo corrompido, protegido por senha, formato inválido

### 1.5 Testes da Sprint 1

- [ ] **1.5.1** Teste: extração de texto de PDF válido
- [ ] **1.5.2** Teste: fallback pdfplumber quando PyMuPDF falha
- [ ] **1.5.3** Teste: tratamento de PDF corrompido/inválido
- [ ] **1.5.4** Teste: validação dos models Pydantic
- [ ] **1.5.5** Teste: carregamento de configuração
