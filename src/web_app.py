"""Minimal web UI for running the admissibility pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4
import os

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from src.config import LLM_PROVIDER, OPENAI_API_KEY, OPENROUTER_API_KEY, OUTPUTS_DIR
from src.pipeline import PipelineAdmissibilidade

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static",
)

UPLOADS_DIR = OUTPUTS_DIR / "web_uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> str:
    """Get active API key based on provider."""
    if LLM_PROVIDER == "openrouter":
        return OPENROUTER_API_KEY
    return OPENAI_API_KEY


def _get_default_model() -> str:
    """Get default model based on provider."""
    if LLM_PROVIDER == "openrouter":
        return "deepseek/deepseek-r1"
    return "gpt-4.1"


def _friendly_error(exc: Exception) -> str:
    """Map known errors to concise messages for UI."""
    msg = str(exc)
    if "api key" in msg.lower() or "API_KEY" in msg:
        return "API Key ausente ou inválida. Configure no .env."
    if "pdf" in msg.lower():
        return f"Falha ao processar PDF: {msg}"
    return msg


@app.get("/")
def index():
    """Render upload page."""
    return render_template(
        "web/index.html",
        result=None,
        error=None,
        default_model=_get_default_model(),
    )


@app.post("/processar")
def processar():
    """Handle upload and execute pipeline."""
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
        pipeline = PipelineAdmissibilidade(
            modelo=modelo,
            formato_saida=formato,
        )
        resultado = pipeline.executar(
            pdfs=[str(recurso_path)] + acordao_paths,
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
        return render_template(
            "web/index.html",
            result=result_payload,
            error=None,
            default_model=modelo,
        )
    except Exception as exc:
        return render_template(
            "web/index.html",
            result=None,
            error=_friendly_error(exc),
            default_model=modelo,
        ), 500


@app.get("/download")
def download():
    """Download generated files from outputs directory."""
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
