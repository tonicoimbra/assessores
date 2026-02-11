#!/bin/bash

# CORES
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Copilot Jurídico -> Hugging Face Deploy Auto${NC}"
echo "--------------------------------------------------------"

if [ -z "$1" ]; then
    echo -e "${RED}❌ ERRO: Faltou o ID do Space!${NC}"
    echo "Uso correto: ./deploy_hf.sh SEU_USUARIO/NOME_DO_SPACE"
    echo "Exemplo:     ./deploy_hf.sh tonicoimbra/copilot-juridico"
    echo ""
    exit 1
fi

SPACE_ID=$1
REMOTE_URL="https://huggingface.co/spaces/$SPACE_ID"

echo -e "📦 Configurando repositório para: ${GREEN}$SPACE_ID${NC}"

# 1. GIT INIT
if [ ! -d ".git" ]; then
    echo "⚙️ Inicializando repositório Git..."
    git init
    # Tenta definir branch main se não padrão
    git checkout -b main 2>/dev/null || true
else
    echo "✅ Git já inicializado."
fi

# 2. GIT REMOTE
if git remote | grep -q "^space$"; then
    echo "⚙️ Atualizando remote 'space'..."
    git remote set-url space "$REMOTE_URL"
else
    echo "⚙️ Adicionando remote 'space'..."
    git remote add space "$REMOTE_URL"
fi
echo "✅ Remote configurado: $REMOTE_URL"

# 3. GIT ADD & COMMIT
echo "📄 Adicionando arquivos..."
git add .

echo "💾 Commitando mudanças..."
git commit -m "Deploy automático $(date +'%Y-%m-%d %H:%M')" || echo "⚠️ Nada novo para commitar."

# 4. AVISO DE CREDENCIAIS
echo ""
echo "--------------------------------------------------------"
echo "🔑 ATENÇÃO: O Git vai pedir suas credenciais do Hugging Face!"
echo "   Username: Seu nome de usuário"
echo "   Password: Seu TOKEN DE ACESSO (Permissão WRITE)"
echo "   Crie o token aqui: https://huggingface.co/settings/tokens"
echo "--------------------------------------------------------"
echo ""

read -p "Pressione ENTER para continuar o upload..."
echo ""

# 5. GIT PUSH
echo "📤 Enviando para Hugging Face..."
if git push space main; then
    echo ""
    echo -e "${GREEN}✅ SUCESSO! Deploy enviado.${NC}"
    echo "Acompanhe o build em: $REMOTE_URL"
else
    echo ""
    echo "⚠️ Falha no push para 'main'. Tentando 'master:main'..."
    if git push space master:main; then
        echo -e "${GREEN}✅ SUCESSO! Deploy enviado.${NC}"
        echo "Acompanhe o build em: $REMOTE_URL"
    else
        echo -e "${RED}❌ FALHA NO DEPLOY.${NC}"
        echo "Verifique suas credenciais (TOKEN) e permissões."
    fi
fi
