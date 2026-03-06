# Política de Retenção de Cache

## Objetivo

Definir como o cache de respostas LLM (`outputs/.cache/`) expira e é limpo automaticamente, reduzindo retenção indevida de conteúdo processual.

## Configurações

Variáveis relevantes no `.env`:

- `ENABLE_CACHING`: habilita/desabilita o cache de chamadas LLM.
- `CACHE_TTL_SECONDS`: tempo de vida da entrada em cache, em segundos. Default recomendado: `86400` (24h).
- `CACHE_PURGE_ON_START`: quando `true`, remove entradas expiradas no início de cada execução de pipeline.
- `CACHE_ENCRYPTION_KEY`: chave Fernet para criptografia do payload em repouso.

Compatibilidade:

- `CACHE_TTL_HOURS` permanece aceito como legado quando `CACHE_TTL_SECONDS` não estiver definido.
- Se `CACHE_ENCRYPTION_KEY` estiver vazio, o sistema usa `DLQ_ENCRYPTION_KEY`.
- Se ambas estiverem vazias, o cache usa chave efêmera em memória: mantém dados criptografados em disco, porém sem reuso entre reinicializações.

## Regra de expiração

Cada entrada de cache armazena metadados de criação (`created_at`).  
No `get()`:

1. se idade da entrada > `CACHE_TTL_SECONDS`, a entrada é removida;
2. a leitura retorna `None` para forçar nova chamada ao LLM.

## Limpeza automática

Método: `CacheManager.purge_expired()`

- remove entradas expiradas;
- remove entradas corrompidas (JSON inválido);
- remove entradas legadas em texto plano (formato antigo);
- é chamado automaticamente no início do pipeline quando:
  - `ENABLE_CACHING=true`
  - `CACHE_PURGE_ON_START=true`

## Boas práticas operacionais

- Produção judicial: manter `CACHE_TTL_SECONDS` em janelas curtas (24h ou menos).
- Ambientes com alto volume: manter `CACHE_PURGE_ON_START=true`.
- Se necessário, executar limpeza manual via código:

```python
from src.cache_manager import cache_manager
removidas = cache_manager.purge_expired()
print(removidas)
```
