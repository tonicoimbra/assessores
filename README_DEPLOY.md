
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

2.  **Upload via Git (Terminal):**
    *   No terminal do seu projeto:
        ```bash
        # 1. Instale o git (se não tiver) e configure seu usuário
        git config --global user.email "seu@email.com"
        git config --global user.name "Seu Nome"

        # 2. Inicialize o repositório (se ainda não fez)
        git init
        git add .
        git commit -m "Deploy inicial"

        # 3. Adicione o remoto do Hugging Face
        # (Substitua SEU_USUARIO e NOME_DO_SPACE)
        git remote add space https://huggingface.co/spaces/SEU_USUARIO/copilot-juridico

        # 4. Envie o código (vai pedir senha = seu TOKEN DE ACESSO do Hugging Face)
        git push space main
        # (Se der erro de branch, tente: git push space master:main)
        ```
    *   **Importante:** Ao pedir a senha, use um **Access Token** com permissão `WRITE` (crie em [hf.co/settings/tokens](https://huggingface.co/settings/tokens)), não sua senha de login.

3.  **Configuração (Secrets):**
    *   Adicione as seguintes secrets (pode fazer manualmente ou usar o script abaixo):
        *   `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `LLM_PROVIDER`, etc.

### ⚡ Dica: Upload Automático do .env
Se você tiver muitas variáveis no `.env`, pode usar o script que criei para subir tudo de uma vez:

1.  Instale a biblioteca necessária: `pip install huggingface_hub python-dotenv`
2.  Rode o script:
    ```bash
    python upload_secrets.py elvertoni/ar SEU_TOKEN_HF
    ```
    *(Substitua `elvertoni/ar` pelo seu Space e coloque seu Token com permissão WRITE).*

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
