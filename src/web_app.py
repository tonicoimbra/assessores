"""Minimal web UI for running the admissibility pipeline."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from uuid import uuid4
import os
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from src.config import (
    LLM_PROVIDER,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    OUTPUTS_DIR,
    ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL,
    WEB_DOWNLOAD_TOKEN_TTL_SECONDS,
    validate_environment_settings,
)
from src.pipeline import PipelineAdmissibilidade, handle_pipeline_error
from src.retention_manager import aplicar_politica_retencao

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static",
)

UPLOADS_DIR = OUTPUTS_DIR / "web_uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
_DOWNLOAD_TOKENS: dict[str, dict[str, Any]] = {}

# In-memory job store for async processing
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _get_api_key() -> str:
    """Get active API key based on provider."""
    if LLM_PROVIDER == "openrouter":
        return OPENROUTER_API_KEY
    return OPENAI_API_KEY


def _get_default_model() -> str:
    """Get default model based on provider."""
    if LLM_PROVIDER == "openrouter":
        return "qwen/qwen3-235b-a22b-2507"
    return "gpt-4.1"


def _friendly_error(exc: Exception) -> str:
    """Map known errors to concise messages for UI."""
    msg = str(exc)
    if "api key" in msg.lower() or "API_KEY" in msg:
        return "API Key ausente ou inválida. Configure no .env."
    if "pdf" in msg.lower():
        return f"Falha ao processar PDF: {msg}"
    return msg


def _purge_expired_download_tokens() -> None:
    """Drop expired download tokens from in-memory store."""
    now = time.time()
    expired = [token for token, meta in _DOWNLOAD_TOKENS.items() if float(meta.get("expires_at", 0)) <= now]
    for token in expired:
        _DOWNLOAD_TOKENS.pop(token, None)


def _build_download_url(path: str) -> str:
    """Build protected download URL for generated artifact."""
    normalized = str(path or "").strip()
    if not normalized:
        return ""
    if not ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL:
        return f"/download?path={normalized}"

    _purge_expired_download_tokens()
    token = uuid4().hex
    _DOWNLOAD_TOKENS[token] = {
        "path": normalized,
        "expires_at": time.time() + max(60, int(WEB_DOWNLOAD_TOKEN_TTL_SECONDS)),
    }
    return f"/download?token={token}"


def _purge_old_jobs() -> None:
    """Remove completed jobs older than 30 minutes."""
    cutoff = time.time() - 1800
    with _JOBS_LOCK:
        expired = [jid for jid, j in _JOBS.items() if j.get("finished_at", 0) and j["finished_at"] < cutoff]
        for jid in expired:
            _JOBS.pop(jid, None)


def _run_pipeline_job(job_id: str, modelo: str, formato: str, recurso_path: str, acordao_paths: list[str], req_id: str, upload_dir: str) -> None:
    """Execute pipeline in background thread and store result in _JOBS."""
    try:
        pipeline = PipelineAdmissibilidade(
            modelo=modelo,
            formato_saida=formato,
        )
        resultado = pipeline.executar(
            pdfs=[recurso_path] + acordao_paths,
            processo_id=f"web_{req_id}",
            continuar=False,
        )
        metricas = pipeline.metricas

        result_payload = {
            "decisao": resultado.decisao.value if resultado.decisao else "N/A",
            "tokens": metricas.get("tokens_totais", 0),
            "custo": metricas.get("custo_estimado_usd", 0.0),
            "tempo": metricas.get("tempo_total", 0.0),
            "arquivo_minuta": metricas.get("arquivo_minuta", ""),
            "arquivo_auditoria": metricas.get("arquivo_auditoria", ""),
            "preview": resultado.minuta_completa[:2500],
        }
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["result"] = result_payload
            _JOBS[job_id]["finished_at"] = time.time()
    except Exception as exc:
        pipeline_obj = locals().get("pipeline")
        try:
            handle_pipeline_error(
                exc,
                estado=getattr(pipeline_obj, "estado_atual", None),
                processo_id=f"web_{req_id}",
                metricas=getattr(pipeline_obj, "metricas", {}),
                contexto={
                    "origem": "web",
                    "modelo": modelo,
                    "formato_saida": formato,
                    "output_dir": str(OUTPUTS_DIR),
                    "upload_dir": upload_dir,
                    "total_arquivos": 1 + len(acordao_paths),
                },
            )
        except Exception:
            pass
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = _friendly_error(exc)
            _JOBS[job_id]["finished_at"] = time.time()


@app.get("/")
def index():
    """Render upload page."""
    return render_template(
        "web/index.html",
        result=None,
        error=None,
        default_model=_get_default_model(),
    )


@app.get("/healthz")
def healthz():
    """Lightweight health endpoint for orchestrators/load balancers."""
    return {"status": "ok"}, 200


@app.post("/processar")
def processar():
    """Handle upload and start pipeline in background."""
    erros_env = validate_environment_settings()
    if erros_env:
        return render_template(
            "web/index.html",
            result=None,
            error="Configuração de ambiente inválida. Revise o .env.",
            default_model=request.form.get("modelo", _get_default_model()),
        ), 400

    if not _get_api_key():
        provider_name = "OPENROUTER_API_KEY" if LLM_PROVIDER == "openrouter" else "OPENAI_API_KEY"
        return render_template(
            "web/index.html",
            result=None,
            error=f"Configure {provider_name} no arquivo .env antes de processar.",
            default_model=request.form.get("modelo", _get_default_model()),
        ), 400

    recurso = request.files.get("recurso_pdf")
    acordaos = request.files.getlist("acordao_pdf")
    formato = request.form.get("formato", "md")
    modelo = request.form.get("modelo", _get_default_model())

    if not recurso or not acordaos:
        return render_template(
            "web/index.html",
            result=None,
            error="Envie o recurso e pelo menos um arquivo de acórdão.",
            default_model=modelo,
        ), 400

    if len(acordaos) > 10:
        return render_template(
            "web/index.html",
            result=None,
            error="O limite é de 10 arquivos para o Acórdão.",
            default_model=modelo,
        ), 400

    if formato not in {"md", "docx"}:
        formato = "md"

    req_id = f"{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    upload_dir = UPLOADS_DIR / req_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    recurso_name = secure_filename(recurso.filename or "recurso.pdf")
    recurso_path = upload_dir / recurso_name
    recurso.save(recurso_path)

    acordao_paths = []
    for i, file in enumerate(acordaos):
        name = secure_filename(file.filename or f"acordao_{i}.pdf")
        path = upload_dir / name
        file.save(path)
        acordao_paths.append(str(path))

    try:
        aplicar_politica_retencao()
    except Exception:
        pass

    # Create job and start background processing
    _purge_old_jobs()
    job_id = uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "processing",
            "started_at": time.time(),
            "result": None,
            "error": None,
            "finished_at": None,
            "modelo": modelo,
        }

    thread = threading.Thread(
        target=_run_pipeline_job,
        args=(job_id, modelo, formato, str(recurso_path), acordao_paths, req_id, str(upload_dir)),
        daemon=True,
    )
    thread.start()

    # Return processing page immediately (no Cloudflare timeout)
    return render_template(
        "web/processing.html",
        job_id=job_id,
        default_model=modelo,
    )


@app.get("/status/<job_id>")
def job_status(job_id: str):
    """AJAX endpoint to poll job status."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    return jsonify({
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
        "elapsed": round(time.time() - job["started_at"], 1),
    })


@app.get("/resultado/<job_id>")
def resultado(job_id: str):
    """Show result page when job is done."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return render_template("web/index.html", result=None, error="Job não encontrado.", default_model=_get_default_model()), 404
    if job["status"] == "error":
        return render_template("web/index.html", result=None, error=job["error"], default_model=job.get("modelo", _get_default_model()))
    if job["status"] != "done":
        return render_template("web/processing.html", job_id=job_id, default_model=job.get("modelo", _get_default_model()))
    # Generate fresh download tokens at request-time (not in background thread)
    # This ensures the token exists in the same worker process handling the download
    result_with_urls = dict(job["result"])
    result_with_urls["download_minuta_url"] = _build_download_url(result_with_urls.get("arquivo_minuta", ""))
    result_with_urls["download_auditoria_url"] = _build_download_url(result_with_urls.get("arquivo_auditoria", ""))
    return render_template("web/index.html", result=result_with_urls, error=None, default_model=job.get("modelo", _get_default_model()))


@app.get("/download")
def download():
    """Download generated files from outputs directory."""
    raw_path = ""
    if ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL:
        _purge_expired_download_tokens()
        token = str(request.args.get("token", "") or "").strip()
        if not token:
            return "Token de download ausente.", 403
        token_payload = _DOWNLOAD_TOKENS.pop(token, None)
        if not token_payload:
            return "Token de download inválido ou expirado.", 403
        raw_path = str(token_payload.get("path") or "")
    else:
        raw_path = request.args.get("path", "")
        if not raw_path:
            return "Parâmetro 'path' ausente.", 400

    requested = Path(raw_path).expanduser().resolve()
    outputs_root = OUTPUTS_DIR.resolve()

    if not str(requested).startswith(str(outputs_root)):
        return "Caminho inválido.", 403
    if not requested.exists() or not requested.is_file():
        return "Arquivo não encontrado.", 404

    return send_file(requested, as_attachment=True)


def run() -> None:
    """Run local development web server."""
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    run()
