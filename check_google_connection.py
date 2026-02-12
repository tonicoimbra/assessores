import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

# Load .env
load_dotenv(".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

print(f"🔑 Google Key: {'OK (Found)' if GOOGLE_API_KEY else '❌ MISSING'}")

if not GOOGLE_API_KEY:
    sys.exit(1)

client = OpenAI(
    api_key=GOOGLE_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

try:
    print("🔄 Testing Google Gemini connection (1.5 Flash Latest)...")
    response = client.chat.completions.create(
        model="gemini-1.5-flash-latest",
        messages=[{"role": "user", "content": "Hello, are you working?"}],
        max_tokens=10
    )
    print(f"✅ Success! Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ Error: {e}")
