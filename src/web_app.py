"""Minimal web UI for running the admissibility pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from src.config import OPENAI_API_KEY, OUTPUTS_DIR
from src.pipeline import PipelineAdmissibilidade

app = Flask(__name__, template_folder="../templates")

UPLOADS_DIR = OUTPUTS_DIR / "web_uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _friendly_error(exc: Exception) -> str:
    """Map known errors to concise messages for UI."""
    msg = str(exc)
    if "OPENAI_API_KEY" in msg or "api key" in msg.lower():
        return "OPENAI_API_KEY ausente ou inválida."
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
        default_model="gpt-4o",
    )


@app.post("/processar")
def processar():
    """Handle upload and execute pipeline."""
    if not OPENAI_API_KEY:
        return render_template(
            "web/index.html",
            result=None,
            error="Configure OPENAI_API_KEY no arquivo .env antes de processar.",
            default_model=request.form.get("modelo", "gpt-4o"),
        ), 400

    recurso = request.files.get("recurso_pdf")
    acordao = request.files.get("acordao_pdf")
    formato = request.form.get("formato", "md")
    modelo = request.form.get("modelo", "gpt-4o")

    if not recurso or not acordao:
        return render_template(
            "web/index.html",
            result=None,
            error="Envie os dois arquivos: recurso e acórdão.",
            default_model=modelo,
        ), 400

    if formato not in {"md", "docx"}:
        formato = "md"

    req_id = f"{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    upload_dir = UPLOADS_DIR / req_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    recurso_name = secure_filename(recurso.filename or "recurso.pdf")
    acordao_name = secure_filename(acordao.filename or "acordao.pdf")
    recurso_path = upload_dir / recurso_name
    acordao_path = upload_dir / acordao_name
    recurso.save(recurso_path)
    acordao.save(acordao_path)

    try:
        pipeline = PipelineAdmissibilidade(
            modelo=modelo,
            formato_saida=formato,
        )
        resultado = pipeline.executar(
            pdfs=[str(recurso_path), str(acordao_path)],
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
    app.run(host="0.0.0.0", port=7860, debug=False)


if __name__ == "__main__":
    run()
