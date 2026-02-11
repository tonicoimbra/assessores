
# Guia de Deploy Anti-Bloqueio 🚀

Este guia descreve como colocar o **Copilot Jurídico** no ar em plataformas que utilizam portas padrão (443/HTTPS) e domínios confiáveis, minimizando a chance de bloqueio em redes corporativas.

## Opção 1: Hugging Face Spaces (Recomendado 🌟)
*Melhor custo-benefício (Grátis), HTTPS padrão, domínio `huggingface.co` geralmente liberado.*

1.  **Crie o Space:**
    *   Acesse [huggingface.co/new-space](https://huggingface.co/new-space).
    *   Nome: `copilot-juridico` (ou similar).
    *   License: `mit`.
    *   SDK: **Docker**.
    *   Template: **Blank**.
    *   Visibility: **Private** (recomendado para dados jurídicos).

2.  **Arquivos:**
    *   Faça upload de todo o conteúdo deste projeto para o repositório do Space (via Git ou Interface Web).
    *   Certifique-se de que o `Dockerfile` está na raiz.

3.  **Configuração (Secrets):**
    *   Vá em **Settings** > **Variables and secrets**.
    *   Adicione as seguintes secrets (copie do seu `.env`):
        *   `OPENAI_API_KEY`
        *   `OPENROUTER_API_KEY`
        *   `GOOGLE_API_KEY`
        *   `LLM_PROVIDER` (ex: `openrouter`)
        *   `OUTPUTS_DIR` (pode ser `/app/outputs` ou `/tmp/outputs` se o disco for efêmero)

4.  **Pronto!**
    *   O Space irá construir a imagem Docker e iniciar.
    *   Acesse via: `https://huggingface.co/spaces/SEU_USUARIO/copilot-juridico`

---

## Opção 2: Google Cloud Run (Profissional 💼)
*Infraestrutura Google, altamente confiável, `*.run.app` raramente bloqueado.*

1.  **Pré-requisitos:**
    *   Conta Google Cloud ativa.
    *   `gcloud` CLI instalado.

2.  **Deploy:**
    Execute no terminal:
    ```bash
    gcloud run deploy copilot-juridico \
      --source . \
      --region us-central1 \
      --allow-unauthenticated \
      --set-env-vars LLM_PROVIDER=openrouter,OUTPUTS_DIR=/tmp/outputs
    ```
    *(Nota: Cloud Run tem sistema de arquivos efêmero, então use `/tmp` para saídas ou configure um bucket GCS se precisar persistir relatórios).*

3.  **Secrets:**
    *   Recomenda-se usar o **Secret Manager** para as chaves de API, ou passar via `--set-env-vars` (menos seguro, mas funciona para teste).

4.  **Acesso:**
    *   Você receberá uma URL terminada em `*.run.app`.

---

## Observações Importantes
*   **Persistência:** Em ambas as opções (camada gratuita), os arquivos gerados (PDFs, Markdown) são apagados quando o container reinicia. Para persistência real, seria necessário integrar com S3 ou Google Drive API (já temos clientes de Drive no projeto, basta ativar).
*   **Porta:** A aplicação foi configurada para ler a variável `PORT` automaticamente, adaptando-se a qualquer ambiente.
