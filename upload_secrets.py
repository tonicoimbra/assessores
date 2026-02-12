import os
import sys
import requests

def load_env(env_path=".env"):
    """Carrega variáveis do arquivo .env manualmente."""
    env_vars = {}
    if not os.path.exists(env_path):
        print(f"❌ Arquivo {env_path} não encontrado!")
        return env_vars
    
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip("'").strip('"')
    return env_vars

def upload_secrets(repo_id, token):
    if not repo_id or not token:
        print("❌ Repo ID e Token são obrigatórios.")
        return

    config = load_env()
    if not config:
        print("⚠️ Nenhuma variável encontrada no .env para upload.")
        return

    print(f"🚀 Iniciando upload de {len(config)} variáveis para {repo_id}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"https://huggingface.co/api/spaces/{repo_id}/secrets"
    
    success_count = 0
    for key, value in config.items():
        if not value:
            continue
            
        try:
            # Hugging Face API para secrets: POST /api/spaces/{repo_id}/secrets
            # Body: {"key": "KEY", "value": "VALUE"}
            response = requests.post(
                base_url,
                json={"key": key, "value": value},
                headers=headers
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ {key} enviado.")
                success_count += 1
            else:
                print(f"❌ Erro ao enviar {key}: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Erro ao enviar {key}: {e}")

    print(f"\n✨ Finalizado! {success_count} variáveis processadas.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 upload_secrets.py USUARIO/NOME_DO_SPACE SEU_TOKEN_HF")
        print("Exemplo: python3 upload_secrets.py my-user/my-space hf_abc123...")
        sys.exit(1)

    repo = sys.argv[1]
    hf_token = sys.argv[2]
    upload_secrets(repo, hf_token)
