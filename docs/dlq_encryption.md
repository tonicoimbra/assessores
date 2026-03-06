# Criptografia da Dead Letter Queue (DLQ)

O sistema usa **Fernet** (AES-128-CBC + HMAC-SHA256) para criptografar snapshots da DLQ em repouso, garantindo compliance com LGPD e política interna do TJPR.

- Arquivos criptografados: extensão `.dlq`
- Arquivos legados (`.json`) permanecem apenas para leitura/migração.
- Sem `DLQ_ENCRYPTION_KEY`, **novos snapshots não são persistidos** (bloqueio anti-texto-plano).

---

## Gerando a Chave Inicial

Execute **uma única vez** e guarde o resultado com segurança (ex.: secret manager, cofre de senhas):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Adicione ao `.env`:

```
DLQ_ENCRYPTION_KEY=<chave gerada>
```

---

## Lendo um Arquivo DLQ para Debugging

Use a função `ler_dead_letter()` — ela detecta automaticamente se o arquivo é `.dlq` ou `.json`:

```python
from src.dead_letter_queue import ler_dead_letter
data = ler_dead_letter("outputs/dead_letter/dlq_proc123_20250304_120000.dlq")
print(data["processo_id"], data["erro"]["tipo"])
```

Ou via terminal:

```bash
python -c "
from src.dead_letter_queue import ler_dead_letter
import sys, json
data = ler_dead_letter(sys.argv[1])
print(json.dumps(data, indent=2, ensure_ascii=False))
" outputs/dead_letter/dlq_proc123_....dlq
```

---

## Rotação de Chave

Quando precisar trocar a `DLQ_ENCRYPTION_KEY` (periodicidade recomendada: a cada 90 dias):

### 1. Gerar nova chave

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Re-encriptar arquivos existentes

```bash
python scripts/reencript_dlq.py \
  --old-key "CHAVE_ANTIGA" \
  --new-key "CHAVE_NOVA" \
  --dlq-dir outputs/dead_letter/
```

> O script `scripts/reencript_dlq.py` lê cada `.dlq` com a chave antiga e regrava com a nova, mantendo o conteúdo.

### 3. Atualizar o `.env`

Substitua `DLQ_ENCRYPTION_KEY` pelo novo valor.

### 4. Verificar

```bash
python -c "
from src.dead_letter_queue import ler_dead_letter
import pathlib
for f in pathlib.Path('outputs/dead_letter').glob('*.dlq'):
    data = ler_dead_letter(f)
    print(f.name, '→', data.get('processo_id'))
"
```

---

## Arquivos Legados (.json)

Arquivos `.json` criados antes da habilitação da criptografia continuam acessíveis via `ler_dead_letter()` sem nenhuma mudança. Não há migração obrigatória, mas recomendamos apagar arquivos legados após o período de retenção (`RETENTION_DEAD_LETTER_DAYS`).
