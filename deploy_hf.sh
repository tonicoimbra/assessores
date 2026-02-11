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

push_success() {
    if git push space main; then
        echo ""
        echo -e "${GREEN}✅ SUCESSO! Deploy enviado.${NC}"
        echo "Acompanhe o build em: $REMOTE_URL"
        return 0
    fi
    return 1
}

if ! push_success; then
    echo ""
    echo "⚠️ Falha no push inicial. O remoto pode ter alterações (ex: README criado automaticamente)."
    echo "🔄 Tentando sincronizar (git pull --rebase space main)..."
    
    if git pull space main --rebase; then
        echo "✅ Sincronizado com sucesso."
        echo "📤 Tentando enviar novamente..."
        if push_success; then
            exit 0
        fi
    else
        echo -e "${RED}❌ Conflito na sincronização.${NC}"
        echo "Tente resolver manualmente: git pull space main --rebase"
    fi

    echo ""
    echo -e "${RED}❌ FALHA FINAL NO DEPLOY.${NC}"
    echo "Verifique:"
    echo "1. Se voce usou o TOKEN (não a senha)."
    echo "2. Se o Token tem permissão 'WRITE'."
    exit 1
fi
