"""Minimal web UI for running the admissibility pipeline."""

from __future__ import annotations

import logging
import os
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

from src.auth import generate_jwt_token, verify_jwt_token, verify_login_password
from src.config import (
    ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL,
    JOB_TTL_HOURS,
    LLM_PROVIDER,
    MAX_UPLOAD_SIZE_MB,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    OUTPUTS_DIR,
    UPLOAD_RATE_LIMIT_PER_MINUTE,
    WEB_AUTH_ENABLED,
    WEB_DOWNLOAD_TOKEN_TTL_SECONDS,
    validate_environment_settings,
)
from src.operational_dashboard import obter_metricas_operacionais
from src.pipeline import PipelineAdmissibilidade, handle_pipeline_error
from src.retention_manager import aplicar_politica_retencao

logger = logging.getLogger("assessor_ai")

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static",
)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# Limit upload size to prevent DoS
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_MB * 1024 * 1024

UPLOADS_DIR = OUTPUTS_DIR / "web_uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_DOWNLOAD_TOKENS: dict[str, dict[str, Any]] = {}
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_SUPPORTED_UPLOAD_EXTENSIONS: set[str] = {".pdf", ".docx"}


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
    if "pdf" in msg.lower() or "docx" in msg.lower() or "document" in msg.lower():
        return f"Falha ao processar documento: {msg}"
    return msg


def _get_client_ip() -> str:
    """Resolve remote client IP, honoring reverse-proxy forwarding."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _log_unauthorized(reason: str) -> None:
    """Log unauthorized access attempts with ip and timestamp."""
    logger.warning(
        "WEB_AUTH unauthorized access | ip=%s | method=%s | path=%s | reason=%s | ts=%s",
        _get_client_ip(),
        request.method,
        request.path,
        reason,
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def _extract_bearer_token() -> str:
    """Extract bearer token from Authorization header."""
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return ""
    if not auth_header.lower().startswith("bearer "):
        return ""
    return auth_header[7:].strip()


def _is_authenticated() -> bool:
    """Validate auth token when web auth is enabled."""
    if not WEB_AUTH_ENABLED:
        return True

    bearer_token = _extract_bearer_token()
    cookie_token = (request.cookies.get("assessor_auth") or "").strip()
    token = bearer_token or cookie_token
    if not token:
        return False
    return verify_jwt_token(token) is not None


def require_auth(view: Callable[..., Response | str]) -> Callable[..., Response | str]:
    """Decorator to protect routes when WEB_AUTH_ENABLED=true."""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Response | str:
        if _is_authenticated():
            return view(*args, **kwargs)

        _log_unauthorized("missing_or_invalid_token")

        if (
            request.path.startswith("/status/")
            or request.path.startswith("/api/")
            or request.path == "/metrics"
        ):
            return jsonify({"error": "Unauthorized"}), 401

        accept_header = (request.headers.get("Accept") or "").lower()
        wants_html = "text/html" in accept_header or request.method == "GET"
        if wants_html:
            return redirect("/login")
        return jsonify({"error": "Unauthorized"}), 401

    return wrapper


def _purge_expired_download_tokens() -> None:
    """Drop expired download tokens from in-memory store."""
    now = time.time()
    expired = [
        token
        for token, meta in _DOWNLOAD_TOKENS.items()
        if float(meta.get("expires_at", 0)) <= now
    ]
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
    """Remove completed/failed jobs older than JOB_TTL_HOURS."""
    cutoff = time.time() - (JOB_TTL_HOURS * 3600)
    with _JOBS_LOCK:
        expired = [
            jid
            for jid, j in _JOBS.items()
            if j.get("finished_at") and j["finished_at"] < cutoff
        ]
        for jid in expired:
            _JOBS.pop(jid, None)


def _is_supported_upload(filename: str) -> bool:
    """Return True when uploaded filename has a supported extension."""
    suffix = Path(str(filename or "").strip()).suffix.lower()
    return suffix in _SUPPORTED_UPLOAD_EXTENSIONS


def _run_pipeline_job(
    job_id: str,
    modelo: str,
    formato: str,
    recurso_path: str,
    acordao_paths: list[str],
    req_id: str,
    upload_dir: str,
) -> None:
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


@app.after_request
def _apply_security_headers(response: Response) -> Response:
    """Apply baseline security headers to all responses."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self' 'unsafe-inline'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        ),
    )
    return response


@app.get("/login")
def login_page() -> Response | str:
    """Render login page when web auth is enabled."""
    if not WEB_AUTH_ENABLED:
        return redirect("/")
    return render_template("web/login.html", error=None)


@app.post("/login")
@limiter.limit("10/minute")
def login_submit() -> Response | str:
    """Validate credential and issue JWT token."""
    if not WEB_AUTH_ENABLED:
        return redirect("/")

    password = ""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        password = str(payload.get("password") or "")
    else:
        password = str(request.form.get("password") or "")

    if not verify_login_password(password):
        _log_unauthorized("invalid_login_token")
        if request.is_json:
            return jsonify({"error": "Credencial inválida."}), 401
        return render_template("web/login.html", error="Token inválido."), 401

    token = generate_jwt_token(expires_hours=12)

    if request.is_json:
        return jsonify(
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in_hours": 12,
            }
        )

    response = make_response(redirect("/"))
    response.set_cookie(
        "assessor_auth",
        token,
        httponly=True,
        secure=False,
        samesite="Strict",
        max_age=12 * 3600,
    )
    return response


@app.post("/logout")
def logout() -> Response:
    """Clear auth cookie and redirect to login."""
    response = make_response(redirect("/login"))
    response.delete_cookie("assessor_auth")
    return response


@app.get("/")
@require_auth
def index() -> str:
    """Render upload page."""
    return render_template(
        "web/index.html",
        result=None,
        error=None,
        default_model=_get_default_model(),
    )


@app.get("/healthz")
def healthz() -> tuple[dict[str, str], int]:
    """Lightweight health endpoint for orchestrators/load balancers."""
    return {"status": "ok"}, 200


@app.get("/metrics")
@require_auth
def metrics() -> tuple[Response, int] | Response:
    """Return operational metrics from recent snapshots as JSON."""
    raw_days = str(request.args.get("days", "30") or "30").strip()
    try:
        days = int(raw_days)
    except ValueError:
        return jsonify({"error": "Parâmetro 'days' inválido. Use inteiro entre 1 e 365."}), 400

    if days < 1 or days > 365:
        return jsonify({"error": "Parâmetro 'days' fora do intervalo permitido (1..365)."}), 400

    try:
        payload = obter_metricas_operacionais(
            snapshot_dir=OUTPUTS_DIR,
            period_days=days,
        )
        return jsonify(payload), 200
    except Exception as exc:
        logger.exception("Falha ao gerar métricas operacionais: %s", exc)
        return jsonify({"error": "Falha ao gerar métricas operacionais."}), 500


@app.post("/processar")
@require_auth
@limiter.limit(lambda: f"{UPLOAD_RATE_LIMIT_PER_MINUTE}/minute")
def processar() -> tuple[str, int] | str:
    """Handle upload and start pipeline in background."""
    erros_env = validate_environment_settings()
    if erros_env:
        return (
            render_template(
                "web/index.html",
                result=None,
                error="Configuração de ambiente inválida. Revise o .env.",
                default_model=request.form.get("modelo", _get_default_model()),
            ),
            400,
        )

    if not _get_api_key():
        provider_name = (
            "OPENROUTER_API_KEY" if LLM_PROVIDER == "openrouter" else "OPENAI_API_KEY"
        )
        return (
            render_template(
                "web/index.html",
                result=None,
                error=f"Configure {provider_name} no arquivo .env antes de processar.",
                default_model=request.form.get("modelo", _get_default_model()),
            ),
            400,
        )

    recurso = request.files.get("recurso_pdf")
    acordaos = request.files.getlist("acordao_pdf")
    formato = request.form.get("formato", "md")
    modelo = request.form.get("modelo", _get_default_model())

    if not recurso or not acordaos:
        return (
            render_template(
                "web/index.html",
                result=None,
                error="Envie o recurso e pelo menos um arquivo de acórdão.",
                default_model=modelo,
            ),
            400,
        )

    if len(acordaos) > 10:
        return (
            render_template(
                "web/index.html",
                result=None,
                error="O limite é de 10 arquivos para o Acórdão.",
                default_model=modelo,
            ),
            400,
        )

    if not _is_supported_upload(recurso.filename or ""):
        return (
            render_template(
                "web/index.html",
                result=None,
                error="Formato inválido no recurso. Envie arquivo .pdf ou .docx.",
                default_model=modelo,
            ),
            400,
        )
    invalid_acordaos = [
        secure_filename(file.filename or "")
        for file in acordaos
        if not _is_supported_upload(file.filename or "")
    ]
    if invalid_acordaos:
        return (
            render_template(
                "web/index.html",
                result=None,
                error=(
                    "Formato inválido em acórdão: "
                    + ", ".join(invalid_acordaos)
                    + ". Envie apenas .pdf ou .docx."
                ),
                default_model=modelo,
            ),
            400,
        )

    if formato not in {"md", "docx"}:
        formato = "md"

    req_id = f"{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    upload_dir = UPLOADS_DIR / req_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    recurso_name = secure_filename(recurso.filename or "recurso.pdf")
    recurso_path = upload_dir / recurso_name
    recurso.save(recurso_path)

    acordao_paths: list[str] = []
    for i, file in enumerate(acordaos):
        name = secure_filename(file.filename or f"acordao_{i}.pdf")
        path = upload_dir / name
        file.save(path)
        acordao_paths.append(str(path))

    try:
        aplicar_politica_retencao()
    except Exception:
        pass

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
        args=(
            job_id,
            modelo,
            formato,
            str(recurso_path),
            acordao_paths,
            req_id,
            str(upload_dir),
        ),
        daemon=True,
    )
    thread.start()

    return render_template(
        "web/processing.html",
        job_id=job_id,
        default_model=modelo,
    )


@app.get("/status/<job_id>")
@require_auth
def job_status(job_id: str) -> tuple[Response, int] | Response:
    """AJAX endpoint to poll job status."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    return jsonify(
        {
            "status": job["status"],
            "result": job.get("result"),
            "error": job.get("error"),
            "elapsed": round(time.time() - job["started_at"], 1),
        }
    )


@app.get("/resultado/<job_id>")
@require_auth
def resultado(job_id: str) -> tuple[str, int] | str:
    """Show result page when job is done."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)

    if not job:
        return (
            render_template(
                "web/index.html",
                result=None,
                error="Job não encontrado.",
                default_model=_get_default_model(),
            ),
            404,
        )

    if job["status"] == "error":
        return render_template(
            "web/index.html",
            result=None,
            error=job["error"],
            default_model=job.get("modelo", _get_default_model()),
        )

    if job["status"] != "done":
        return render_template(
            "web/processing.html",
            job_id=job_id,
            default_model=job.get("modelo", _get_default_model()),
        )

    result_with_urls = dict(job["result"])
    result_with_urls["download_minuta_url"] = _build_download_url(
        result_with_urls.get("arquivo_minuta", "")
    )
    result_with_urls["download_auditoria_url"] = _build_download_url(
        result_with_urls.get("arquivo_auditoria", "")
    )
    return render_template(
        "web/index.html",
        result=result_with_urls,
        error=None,
        default_model=job.get("modelo", _get_default_model()),
    )


@app.get("/download")
@require_auth
def download() -> tuple[str, int] | Response:
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
        _log_unauthorized("invalid_download_path")
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
