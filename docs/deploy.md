# Deploy e Operação

Este documento descreve opções práticas de execução em produção e homologação.

## 1) Deploy local (desenvolvimento e operação simples)

### Sem Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main processar /caminho/recurso.pdf /caminho/acordao.pdf
```

### Com Docker Compose

```bash
docker compose build
docker compose run --rm app --help
docker compose run --rm app status
docker compose run --rm app limpar
docker compose run --rm app processar /workspace/tests/fixtures/sample_recurso.pdf /workspace/tests/fixtures/sample_minimal.pdf
```

Arquivos de saída ficam em `./outputs` (volume mapeado para `/app/outputs`).

## 2) Deploy em VPS (Contabo)

Fluxo recomendado para Ubuntu 22.04+:
1. Provisionar VPS e habilitar firewall (`ufw allow OpenSSH`).
2. Instalar Docker + Docker Compose Plugin.
3. Clonar o repositório no servidor.
4. Configurar variáveis de ambiente com chave real da OpenAI:
   - `export OPENAI_API_KEY=...`
5. Build e execução:
   - `docker compose build`
   - `docker compose run --rm app status`
   - `docker compose run --rm app processar <pdf1> <pdf2>`
6. Opcional: criar `systemd` timer/cron para jobs recorrentes.

Boas práticas:
- manter `outputs/` em disco persistente
- restringir acesso SSH por chave
- não versionar `.env` no servidor

## 3) Integração com n8n via webhook

Status atual:
- o projeto expõe CLI (não API HTTP dedicada nesta sprint)
- integração HTTP direta será tratada em `7.5`

Opção imediata no n8n:
1. Receber arquivos no workflow (Webhook/Form Trigger).
2. Salvar temporariamente os PDFs em disco.
3. Usar node **Execute Command** chamando:
   - `docker compose run --rm app processar <pdf_recurso> <pdf_acordao> --formato docx`
4. Ler saída em `outputs/` e enviar notificação (email/Slack/Drive).

Quando a API HTTP da tarefa 7.5 estiver pronta, substituir o `Execute Command` por chamada direta de webhook.

## Validação executada (Sprint 7.4.3)

Comandos validados neste repositório:

```bash
docker build -t copilot-juridico:local .
docker run --rm copilot-juridico:local --help
docker compose run --rm app status
docker compose run --rm app limpar
docker run --rm --entrypoint python copilot-juridico:local -m pytest -q
```

Resultado: imagem construída com sucesso, CLI funcionando no container e suíte de testes passando dentro do container.
