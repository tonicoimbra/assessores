"""Operational dashboard aggregation from execution snapshots."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from src.config import OUTPUTS_DIR
from src.pipeline import _estimar_custo

logger = logging.getLogger("assessor_ai")

CRITICAL_FIELDS_ETAPA1: tuple[str, ...] = ("numero_processo", "recorrente", "especie_recurso")
ESSENTIAL_FIELDS_ETAPA2: tuple[str, ...] = (
    "materia_controvertida",
    "conclusao_fundamentos",
    "obices_sumulas",
    "trecho_transcricao",
)


def _listar_snapshots(snapshot_dir: Path) -> list[Path]:
    """Return execution snapshot files sorted by path."""
    return sorted(p for p in snapshot_dir.rglob("snapshot_execucao_*.json") if p.is_file())


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse ISO datetime string safely."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calc_duration_seconds(metadata: dict[str, Any]) -> float:
    """Estimate execution duration using metadata start/end timestamps."""
    inicio = _parse_iso_datetime(metadata.get("inicio"))
    fim = _parse_iso_datetime(metadata.get("fim"))
    if inicio is None or fim is None:
        return 0.0
    return max(0.0, (fim - inicio).total_seconds())


def _extrair_decisao(snapshot: dict[str, Any]) -> str:
    """Extract stage 3 decision from snapshot."""
    stages = snapshot.get("stages", {})
    etapa3 = stages.get("etapa3", {})
    resultado = etapa3.get("resultado") or {}
    decisao = str(resultado.get("decisao") or "").strip().upper()
    return decisao


def _resolve_build_info() -> dict[str, str]:
    """Resolve CI/local build identifiers for dashboard traceability."""
    provider = "local"
    build_id = ""
    for key, provider_name in (
        ("GITHUB_RUN_ID", "github"),
        ("CI_PIPELINE_ID", "gitlab"),
        ("BUILD_ID", "generic"),
    ):
        value = str(os.getenv(key, "")).strip()
        if value:
            build_id = value
            provider = provider_name
            break

    commit_sha = (
        str(os.getenv("GITHUB_SHA", "")).strip()
        or str(os.getenv("CI_COMMIT_SHA", "")).strip()
        or str(os.getenv("COMMIT_SHA", "")).strip()
    )
    branch = (
        str(os.getenv("GITHUB_REF_NAME", "")).strip()
        or str(os.getenv("CI_COMMIT_REF_NAME", "")).strip()
        or str(os.getenv("BRANCH_NAME", "")).strip()
    )
    return {
        "provider": provider,
        "build_id": build_id,
        "commit_sha": commit_sha,
        "branch": branch,
    }


def _tem_valor_em_campo(payload: dict[str, Any], campo: str) -> bool:
    """Check whether a domain field contains useful value for evidence scoring."""
    if campo == "obices_sumulas":
        valor = payload.get(campo)
        if not isinstance(valor, list):
            return False
        return any(str(item).strip() for item in valor)
    return bool(str(payload.get(campo) or "").strip())


def _evidencia_completa(raw: Any) -> bool:
    """Validate required evidence attributes (citation, page and anchor)."""
    if not isinstance(raw, dict):
        return False
    citacao = str(raw.get("citacao_literal") or "").strip()
    ancora = str(raw.get("ancora") or "").strip()
    pagina = raw.get("pagina")
    return bool(citacao and ancora and isinstance(pagina, int) and pagina >= 1)


def _calc_evidence_coverage(snapshot: dict[str, Any]) -> tuple[int, int]:
    """Return (covered_fields, eligible_fields) evidence coverage for a snapshot."""
    covered = 0
    total = 0

    stages = snapshot.get("stages", {})
    etapa1_result = (stages.get("etapa1", {}) or {}).get("resultado") or {}
    if isinstance(etapa1_result, dict):
        evidencias = etapa1_result.get("evidencias_campos")
        evidencias_map = evidencias if isinstance(evidencias, dict) else {}
        for campo in CRITICAL_FIELDS_ETAPA1:
            if not _tem_valor_em_campo(etapa1_result, campo):
                continue
            total += 1
            if _evidencia_completa(evidencias_map.get(campo)):
                covered += 1

    etapa2_result = (stages.get("etapa2", {}) or {}).get("resultado") or {}
    temas = etapa2_result.get("temas") if isinstance(etapa2_result, dict) else []
    if isinstance(temas, list):
        for tema in temas:
            if not isinstance(tema, dict):
                continue
            evidencias = tema.get("evidencias_campos")
            evidencias_map = evidencias if isinstance(evidencias, dict) else {}
            for campo in ESSENTIAL_FIELDS_ETAPA2:
                if not _tem_valor_em_campo(tema, campo):
                    continue
                total += 1
                if _evidencia_completa(evidencias_map.get(campo)):
                    covered += 1

    return covered, total


def _build_dashboard_payload(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate operational metrics from snapshot payloads."""
    total_exec = len(snapshots)

    durations: list[float] = []
    token_totals: list[int] = []
    costs: list[float] = []
    decisions: list[str] = []
    stage_errors = {"etapa1": 0, "etapa2": 0, "etapa3": 0}
    llm_total_calls = 0
    llm_total_truncadas = 0
    llm_latencias: list[float] = []
    evidence_covered_fields = 0
    evidence_total_fields = 0

    for snapshot in snapshots:
        metadata = snapshot.get("metadata", {})
        prompt_tokens = int(metadata.get("prompt_tokens", 0) or 0)
        completion_tokens = int(metadata.get("completion_tokens", 0) or 0)
        total_tokens = int(metadata.get("total_tokens", 0) or 0)
        modelo = str(metadata.get("modelo_usado") or "gpt-4o")

        duration_s = _calc_duration_seconds(metadata)
        durations.append(duration_s)
        token_totals.append(total_tokens)
        costs.append(_estimar_custo(prompt_tokens, completion_tokens, modelo))

        decisao = _extrair_decisao(snapshot)
        if decisao:
            decisions.append(decisao)

        stages = snapshot.get("stages", {})
        for etapa in ("etapa1", "etapa2", "etapa3"):
            erros = stages.get(etapa, {}).get("validacao_erros", [])
            if isinstance(erros, list) and erros:
                stage_errors[etapa] += 1

        llm_stats = metadata.get("llm_stats", {})
        llm_total_calls += int(llm_stats.get("total_calls", 0) or 0)
        llm_total_truncadas += int(llm_stats.get("calls_truncadas", 0) or 0)
        llm_latencias.append(float(llm_stats.get("latencia_media_ms", 0.0) or 0.0))

        covered, total = _calc_evidence_coverage(snapshot)
        evidence_covered_fields += covered
        evidence_total_fields += total

    inconclusivos = sum(1 for d in decisions if d == "INCONCLUSIVO")
    decisoes_conclusivas = len(decisions)

    dashboard = {
        "gerado_em": datetime.now().isoformat(),
        "build": _resolve_build_info(),
        "execucoes": {
            "total": total_exec,
            "com_decisao": decisoes_conclusivas,
        },
        "latencia": {
            "media_s": round(mean(durations), 3) if durations else 0.0,
            "max_s": round(max(durations), 3) if durations else 0.0,
            "min_s": round(min(durations), 3) if durations else 0.0,
        },
        "tokens": {
            "total": int(sum(token_totals)),
            "media_por_execucao": round(mean(token_totals), 2) if token_totals else 0.0,
        },
        "custo_estimado_usd": {
            "total": round(sum(costs), 6),
            "media_por_execucao": round(mean(costs), 6) if costs else 0.0,
        },
        "qualidade": {
            "taxa_inconclusivo": round((inconclusivos / total_exec), 3) if total_exec else 0.0,
            "erro_por_etapa": {
                "etapa1": round(stage_errors["etapa1"] / total_exec, 3) if total_exec else 0.0,
                "etapa2": round(stage_errors["etapa2"] / total_exec, 3) if total_exec else 0.0,
                "etapa3": round(stage_errors["etapa3"] / total_exec, 3) if total_exec else 0.0,
            },
            "retrabalho_retry": {
                "llm_calls_truncadas_total": llm_total_truncadas,
                "taxa_por_call": round(llm_total_truncadas / llm_total_calls, 3) if llm_total_calls else 0.0,
            },
            "cobertura_evidencia": {
                "campos_cobertos": evidence_covered_fields,
                "campos_avaliados": evidence_total_fields,
                "taxa": (
                    round(evidence_covered_fields / evidence_total_fields, 3)
                    if evidence_total_fields
                    else 0.0
                ),
            },
        },
        "llm": {
            "calls_total": llm_total_calls,
            "calls_truncadas_total": llm_total_truncadas,
            "latencia_media_ms": round(mean(llm_latencias), 2) if llm_latencias else 0.0,
        },
    }
    return dashboard


def _to_markdown(payload: dict[str, Any]) -> str:
    """Render markdown summary for operational dashboard."""
    build = payload["build"]
    execucoes = payload["execucoes"]
    latencia = payload["latencia"]
    tokens = payload["tokens"]
    custo = payload["custo_estimado_usd"]
    qualidade = payload["qualidade"]
    llm = payload["llm"]
    erro_etapa = qualidade["erro_por_etapa"]

    lines = [
        "# Dashboard Operacional",
        "",
        f"- Gerado em: {payload['gerado_em']}",
        f"- Build: {build['build_id'] or 'local'} ({build['provider']})",
        f"- Commit: {build['commit_sha'] or 'n/d'}",
        f"- Branch: {build['branch'] or 'n/d'}",
        f"- Execuções analisadas: {execucoes['total']}",
        f"- Execuções com decisão: {execucoes['com_decisao']}",
        "",
        "## Latência",
        "",
        f"- Média: {latencia['media_s']:.3f}s",
        f"- Mínima: {latencia['min_s']:.3f}s",
        f"- Máxima: {latencia['max_s']:.3f}s",
        "",
        "## Tokens",
        "",
        f"- Total: {tokens['total']}",
        f"- Média por execução: {tokens['media_por_execucao']}",
        "",
        "## Custo Estimado (USD)",
        "",
        f"- Total: ${custo['total']:.6f}",
        f"- Média por execução: ${custo['media_por_execucao']:.6f}",
        "",
        "## Qualidade",
        "",
        f"- Taxa de INCONCLUSIVO: {qualidade['taxa_inconclusivo']:.3f}",
        f"- Taxa de erro Etapa 1: {erro_etapa['etapa1']:.3f}",
        f"- Taxa de erro Etapa 2: {erro_etapa['etapa2']:.3f}",
        f"- Taxa de erro Etapa 3: {erro_etapa['etapa3']:.3f}",
        (
            "- Retry/retrabalho (proxy LLM truncada): "
            f"{qualidade['retrabalho_retry']['taxa_por_call']:.3f}"
        ),
        (
            "- Cobertura de evidência: "
            f"{qualidade['cobertura_evidencia']['taxa']:.3f} "
            f"({qualidade['cobertura_evidencia']['campos_cobertos']}/"
            f"{qualidade['cobertura_evidencia']['campos_avaliados']})"
        ),
        "",
        "## LLM",
        "",
        f"- Calls totais: {llm['calls_total']}",
        f"- Calls truncadas: {llm['calls_truncadas_total']}",
        f"- Latência média: {llm['latencia_media_ms']:.2f} ms",
        "",
    ]
    return "\n".join(lines)


def gerar_dashboard_operacional(
    *,
    snapshot_dir: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """
    Generate operational dashboard (JSON + Markdown) from execution snapshots.

    Returns:
        Tuple (dashboard_json_path, dashboard_markdown_path, payload)
    """
    source_dir = snapshot_dir or OUTPUTS_DIR
    target_dir = output_dir or OUTPUTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    snapshot_paths = _listar_snapshots(source_dir)
    snapshots: list[dict[str, Any]] = []
    for path in snapshot_paths:
        try:
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("Snapshot inválido ignorado no dashboard: %s", path)

    payload = _build_dashboard_payload(snapshots)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dashboard_json = target_dir / f"dashboard_operacional_{timestamp}.json"
    dashboard_md = target_dir / f"dashboard_operacional_{timestamp}.md"

    dashboard_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    dashboard_md.write_text(_to_markdown(payload), encoding="utf-8")

    logger.info(
        "📈 Dashboard operacional gerado: snapshots=%d json=%s md=%s",
        len(snapshot_paths),
        dashboard_json,
        dashboard_md,
    )
    return dashboard_json, dashboard_md, payload
