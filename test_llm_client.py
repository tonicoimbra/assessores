import os
from dotenv import load_dotenv

# Load .env explicito
load_dotenv(".env")

from src.llm_client import _get_client
from src.config import MODEL_CLASSIFICATION

print(f"🔍 Testando llm_client com modelo: {MODEL_CLASSIFICATION}")
print(f"🔑 GOOGLE_API_KEY env: '{os.getenv('GOOGLE_API_KEY')}'")
print(f"🔑 OPENROUTER_API_KEY env: '{os.getenv('OPENROUTER_API_KEY')}'")
print(f"⚙️  LLM_PROVIDER: {os.getenv('LLM_PROVIDER')}")

try:
    print("🔄 Obtendo cliente...")
    client = _get_client(model_name=MODEL_CLASSIFICATION)
    print(f"✅ Cliente obtido: {client.base_url}")
    
    print("🔄 Testando chamada simples...")
    response = client.chat.completions.create(
        model=MODEL_CLASSIFICATION.replace("google/", "") if "generativelanguage" in str(client.base_url) else MODEL_CLASSIFICATION,
        messages=[{"role": "user", "content": "Oi"}],
        max_tokens=10
    )
    print(f"✅ Resposta LLM: {response.choices[0].message.content}")

except Exception as e:
    print(f"❌ ERRO FATAL: {e}")
    import traceback
    traceback.print_exc()
