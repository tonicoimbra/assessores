#!/usr/bin/env python3
"""Atualiza pricing.json a partir da API pública de modelos da OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OUTPUT_PATH = "pricing.json"


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_existing_models(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    models = payload.get("models")
    if not isinstance(models, dict):
        return {}

    parsed: dict[str, dict[str, float]] = {}
    for model_name, prices in models.items():
        if not isinstance(model_name, str) or not isinstance(prices, dict):
            continue
        parsed[model_name] = {
            "input_per_1m": _to_float(prices.get("input_per_1m")),
            "output_per_1m": _to_float(prices.get("output_per_1m")),
        }
    return parsed


def _fetch_openrouter_payload(api_url: str, timeout: int) -> dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "assessor-ai-pricing-updater/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(api_url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8")
    return json.loads(content)


def _extract_models_from_openrouter(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Resposta inválida da OpenRouter: campo 'data' ausente ou inválido.")

    models: dict[str, dict[str, float]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        pricing = item.get("pricing")
        if not isinstance(model_id, str) or not isinstance(pricing, dict):
            continue

        # OpenRouter retorna preços por token; convertemos para preço por 1M tokens.
        prompt_per_token = _to_float(pricing.get("prompt"))
        completion_per_token = _to_float(pricing.get("completion"))

        if prompt_per_token < 0 or completion_per_token < 0:
            continue

        models[model_id] = {
            "input_per_1m": round(prompt_per_token * 1_000_000, 6),
            "output_per_1m": round(completion_per_token * 1_000_000, 6),
        }

    if not models:
        raise ValueError("Nenhum modelo com pricing válido encontrado na resposta da OpenRouter.")

    return models


def _write_pricing_file(
    output_path: Path,
    version: str,
    models: dict[str, dict[str, float]],
    source_url: str,
) -> None:
    payload = {
        "version": version,
        "source": source_url,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": dict(sorted(models.items())),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atualiza pricing.json a partir de https://openrouter.ai/api/v1/models"
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="Endpoint da API de modelos (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        help="Arquivo de saída JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--version",
        default=datetime.now(timezone.utc).strftime("%Y-%m"),
        help="Versão a gravar no pricing.json (default: ano-mes UTC)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout da requisição em segundos (default: %(default)s)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Substitui totalmente o arquivo, sem preservar modelos já existentes.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    try:
        payload = _fetch_openrouter_payload(api_url=args.api_url, timeout=args.timeout)
        fetched_models = _extract_models_from_openrouter(payload)
    except HTTPError as exc:
        print(f"Erro HTTP ao consultar OpenRouter: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Erro de rede ao consultar OpenRouter: {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Falha ao obter pricing da OpenRouter: {exc}", file=sys.stderr)
        return 1

    if args.replace:
        merged_models = fetched_models
    else:
        existing_models = _load_existing_models(output_path)
        merged_models = {**existing_models, **fetched_models}

    try:
        _write_pricing_file(
            output_path=output_path,
            version=args.version,
            models=merged_models,
            source_url=args.api_url,
        )
    except Exception as exc:
        print(f"Falha ao gravar {output_path}: {exc}", file=sys.stderr)
        return 1

    print(
        f"pricing atualizado em {output_path} com {len(merged_models)} modelos "
        f"(capturados: {len(fetched_models)})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
