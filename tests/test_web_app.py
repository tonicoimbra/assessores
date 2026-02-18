"""Tests for Flask web app routes and guardrails."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.web_app as web_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Flask test client with isolated outputs/uploads directories."""
    outputs_dir = tmp_path / "outputs"
    uploads_dir = outputs_dir / "web_uploads"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(web_app, "OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(web_app, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(web_app, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(web_app, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(web_app, "OPENROUTER_API_KEY", "")

    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


class TestWebAppRoutes:
    """Core web endpoints and upload flow validations."""

    def test_index_returns_200(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert b"Enviar Documentos" in response.data

    def test_processar_requires_api_key(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web_app, "OPENAI_API_KEY", "")
        response = client.post("/processar", data={})
        assert response.status_code == 400
        assert b"Configure OPENAI_API_KEY" in response.data

    def test_processar_requires_files(self, client) -> None:
        response = client.post("/processar", data={})
        assert response.status_code == 400
        assert b"Envie o recurso e pelo menos um arquivo de ac" in response.data

    def test_processar_limits_acordao_files(self, client) -> None:
        pdf = b"%PDF-1.4\n%mock\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
        data = {
            "formato": "md",
            "modelo": "gpt-4o",
            "recurso_pdf": (BytesIO(pdf), "recurso.pdf"),
            "acordao_pdf": [(BytesIO(pdf), f"acordao_{i}.pdf") for i in range(11)],
        }
        response = client.post("/processar", data=data, content_type="multipart/form-data")

        assert response.status_code == 400
        assert b"limite" in response.data

    def test_processar_success_renders_result(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakePipeline:
            def __init__(self, modelo: str, formato_saida: str):
                self.modelo = modelo
                self.formato_saida = formato_saida
                self.metricas: dict[str, Any] = {
                    "tokens_totais": 321,
                    "custo_estimado_usd": 0.12,
                    "tempo_total": 1.23,
                    "arquivo_minuta": "outputs/minuta.md",
                    "arquivo_auditoria": "outputs/auditoria.md",
                }

            def executar(self, pdfs: list[str], processo_id: str, continuar: bool):
                assert len(pdfs) == 2
                assert processo_id.startswith("web_")
                assert continuar is False
                return SimpleNamespace(
                    decisao=SimpleNamespace(value="ADMITIDO"),
                    minuta_completa="Texto da minuta final.",
                )

        monkeypatch.setattr(web_app, "PipelineAdmissibilidade", FakePipeline)

        pdf = b"%PDF-1.4\n%mock\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
        data = {
            "formato": "docx",
            "modelo": "gpt-4o",
            "recurso_pdf": (BytesIO(pdf), "recurso.pdf"),
            "acordao_pdf": [(BytesIO(pdf), "acordao_1.pdf")],
        }
        response = client.post("/processar", data=data, content_type="multipart/form-data")

        assert response.status_code == 200
        assert b"ADMITIDO" in response.data
        assert b"Texto da minuta final." in response.data

    def test_processar_on_pipeline_error_returns_500(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakePipelineError:
            def __init__(self, modelo: str, formato_saida: str):
                self.metricas = {}

            def executar(self, pdfs: list[str], processo_id: str, continuar: bool):
                raise RuntimeError("API_KEY invalid")

        captured: dict[str, Any] = {}

        def _fake_handle_error(exc: Exception, **kwargs):
            captured["error"] = str(exc)
            captured["kwargs"] = kwargs
            return None

        monkeypatch.setattr(web_app, "PipelineAdmissibilidade", FakePipelineError)
        monkeypatch.setattr(web_app, "handle_pipeline_error", _fake_handle_error)

        pdf = b"%PDF-1.4\n%mock\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
        data = {
            "formato": "md",
            "modelo": "gpt-4o",
            "recurso_pdf": (BytesIO(pdf), "recurso.pdf"),
            "acordao_pdf": [(BytesIO(pdf), "acordao_1.pdf")],
        }
        response = client.post("/processar", data=data, content_type="multipart/form-data")

        assert response.status_code == 500
        assert b"API Key ausente ou inv" in response.data
        assert captured["error"] == "API_KEY invalid"
        assert captured["kwargs"]["processo_id"].startswith("web_")
        assert captured["kwargs"]["contexto"]["origem"] == "web"

    def test_download_guards_and_success(self, client, tmp_path: Path) -> None:
        response = client.get("/download")
        assert response.status_code == 400

        response = client.get("/download?path=/etc/passwd")
        assert response.status_code == 403

        missing_inside = (tmp_path / "outputs" / "missing.md").resolve()
        response = client.get(f"/download?path={missing_inside}")
        assert response.status_code == 404

        generated = (tmp_path / "outputs" / "resultado.md").resolve()
        generated.write_text("conteudo", encoding="utf-8")
        response = client.get(f"/download?path={generated}")
        assert response.status_code == 200
        assert response.headers.get("Content-Disposition", "").startswith("attachment;")
