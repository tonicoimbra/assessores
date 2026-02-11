import os
from dotenv import dotenv_values
from huggingface_hub import HfApi
import sys

def upload_secrets(repo_id, token):
    if not os.path.exists(".env"):
        print("❌ Arquivo .env não encontrado!")
        return

    # Carregar todas as variáveis do .env
    config = dotenv_values(".env")
    api = HfApi(token=token)

    print(f"🚀 Iniciando upload de {len(config)} variáveis para {repo_id}...")

    success_count = 0
    for key, value in config.items():
        if not value:
            continue
        try:
            # Usar o método correto da HfApi para Spaces
            api.add_space_secret(
                repo_id=repo_id,
                key=key,
                value=value
            )
            print(f"✅ {key} enviado.")
            success_count += 1
        except Exception as e:
            print(f"❌ Erro ao enviar {key}: {e}")

    print(f"\n✨ Finalizado! {success_count} variáveis foram configuradas no Space.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python upload_secrets.py USUARIO/NOME_DO_SPACE SEU_TOKEN_HF")
        sys.exit(1)

    repo = sys.argv[1]
    hf_token = sys.argv[2]
    upload_secrets(repo, hf_token)
