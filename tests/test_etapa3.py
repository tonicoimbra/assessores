"""Tests for Sprint 5: Etapa 3 validation, cross-checking, and output formatting."""

import shutil
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

import pytest

from src.etapa3 import (
    Etapa3Error,
    _extrair_decisao,
    _validar_cruzada_dispositivos,
    _validar_cruzada_temas,
    _validar_secao_i,
    _validar_secao_ii,
    _validar_secao_iii,
    _validar_secoes,
    _validar_sumulas_secao_iii,
    _validar_transcricoes,
)
from src.models import (
    Decisao,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TemaEtapa2,
)
from src.output_formatter import (
    formatar_minuta,
    gerar_relatorio_auditoria,
    salvar_minuta,
    salvar_minuta_docx,
)

HAS_PYTHON_DOCX = find_spec("docx") is not None


MINUTA_COMPLETA = """
Seção I – Relatório
Processo nº 0001234-56.2024.8.16.0001
Recorrente: EMPRESA ABC LTDA
Recorrido: CONSUMIDOR XYZ
Espécie: RECURSO ESPECIAL
Dispositivos violados: art. 927 do CC

Seção II – Análise Temática
Tema: Responsabilidade civil
O tribunal entendeu que não há dano moral comprovado.
"Não restou demonstrada a ocorrência do dano alegado pelo recorrente."

Seção III – Decisão
Ante o exposto, INADMITO o recurso especial interposto.
Fundamento: Súmula 7 do STJ.
"""


# --- 5.5.1: Structure I/II/III validation ---


class TestValidacaoEstrutura:
    """Test validation of draft sections I, II, III."""

    def test_valid_structure_no_alerts(self) -> None:
        alertas = _validar_secoes(MINUTA_COMPLETA)
        assert len(alertas) == 0

    def test_missing_section_i(self) -> None:
        sem_i = MINUTA_COMPLETA.replace("Seção I", "Parte X")
        alertas = _validar_secoes(sem_i)
        assert any("I" in a for a in alertas)

    def test_missing_section_iii(self) -> None:
        sem_iii = MINUTA_COMPLETA.replace("Seção III", "Conclusão")
        alertas = _validar_secoes(sem_iii)
        assert any("III" in a for a in alertas)

    def test_detects_admito(self) -> None:
        assert _extrair_decisao("ADMITO o recurso") == Decisao.ADMITIDO

    def test_detects_inadmito(self) -> None:
        assert _extrair_decisao(MINUTA_COMPLETA) == Decisao.INADMITIDO


# --- 5.5.2: Divergence Etapa 1 x Seção I ---


class TestDivergenciaEtapa1:
    """Test cross-check between Stage 1 and section I."""

    def test_no_divergence(self) -> None:
        r1 = ResultadoEtapa1(
            numero_processo="0001234-56.2024.8.16.0001",
            recorrente="EMPRESA ABC LTDA",
            especie_recurso="RECURSO ESPECIAL",
        )
        alertas = _validar_secao_i(MINUTA_COMPLETA, r1)
        assert len(alertas) == 0

    def test_missing_process_number(self) -> None:
        r1 = ResultadoEtapa1(numero_processo="9999999-99.9999.9.99.9999")
        alertas = _validar_secao_i(MINUTA_COMPLETA, r1)
        assert any("número" in a for a in alertas)

    def test_missing_recorrente(self) -> None:
        r1 = ResultadoEtapa1(recorrente="PESSOA INEXISTENTE")
        alertas = _validar_secao_i(MINUTA_COMPLETA, r1)
        assert any("recorrente" in a.lower() for a in alertas)

    def test_cross_validate_devices(self) -> None:
        r1 = ResultadoEtapa1(dispositivos_violados=["art. 927 do CC"])
        alertas = _validar_cruzada_dispositivos(MINUTA_COMPLETA, r1)
        assert len(alertas) == 0

    def test_cross_validate_missing_device(self) -> None:
        r1 = ResultadoEtapa1(dispositivos_violados=["art. 999 do CPC"])
        alertas = _validar_cruzada_dispositivos(MINUTA_COMPLETA, r1)
        assert any("999" in a for a in alertas)


# --- 5.5.3: Transcription in ruling ---


class TestTranscricaoLiteral:
    """Test that transcription excerpts exist in ruling text."""

    def test_valid_transcription(self) -> None:
        acordao = "Não restou demonstrada a ocorrência do dano alegado pelo recorrente."
        alertas = _validar_transcricoes(MINUTA_COMPLETA, acordao)
        assert len(alertas) == 0

    def test_missing_transcription(self) -> None:
        alertas = _validar_transcricoes(MINUTA_COMPLETA, "Texto completamente diferente.")
        assert any("Transcrição" in a for a in alertas)

    def test_sumula_consistency(self) -> None:
        r2 = ResultadoEtapa2(temas=[TemaEtapa2(obices_sumulas=["Súmula 7"])])
        alertas = _validar_sumulas_secao_iii(MINUTA_COMPLETA, r2)
        assert len(alertas) == 0

    def test_sumula_new_in_draft(self) -> None:
        r2 = ResultadoEtapa2(temas=[])
        alertas = _validar_sumulas_secao_iii(MINUTA_COMPLETA, r2)
        assert any("7" in a for a in alertas)


# --- 5.5.4: Markdown formatting ---


class TestFormatacaoMarkdown:
    """Test markdown formatting of the draft."""

    def test_bold_recorrente(self) -> None:
        r3 = ResultadoEtapa3(minuta_completa="Recorrente: FULANO de TAL")
        r1 = ResultadoEtapa1(recorrente="FULANO de TAL")
        estado = EstadoPipeline(resultado_etapa1=r1)
        fmt = formatar_minuta(r3, estado)
        assert "**FULANO de TAL**" in fmt

    def test_bold_decisao(self) -> None:
        r3 = ResultadoEtapa3(minuta_completa="INADMITO o recurso.")
        fmt = formatar_minuta(r3)
        assert "**INADMITO**" in fmt

    def test_no_double_bold(self) -> None:
        r3 = ResultadoEtapa3(minuta_completa="**ADMITO** o recurso.")
        fmt = formatar_minuta(r3)
        assert "****" not in fmt

    def test_save_minuta_creates_file(self, tmp_path: Path) -> None:
        with patch("src.output_formatter.OUTPUTS_DIR", tmp_path):
            path = salvar_minuta("# Minuta\nConteúdo.", "123")
            assert path.exists()
            assert "minuta_123" in path.name
            assert path.read_text(encoding="utf-8").startswith("# Minuta")

    def test_audit_report(self, tmp_path: Path) -> None:
        with patch("src.output_formatter.OUTPUTS_DIR", tmp_path):
            estado = EstadoPipeline(
                resultado_etapa1=ResultadoEtapa1(numero_processo="123"),
                resultado_etapa2=ResultadoEtapa2(temas=[TemaEtapa2()]),
                resultado_etapa3=ResultadoEtapa3(decisao=Decisao.INADMITIDO),
                metadata=MetadadosPipeline(total_tokens=5000, modelo_usado="gpt-4o"),
            )
            path = gerar_relatorio_auditoria(estado, ["teste"], "123")
            content = path.read_text(encoding="utf-8")
            assert "5000" in content
            assert "teste" in content
            assert "gpt-4o" in content

    @pytest.mark.skipif(not HAS_PYTHON_DOCX, reason="python-docx não instalado")
    def test_save_minuta_docx_creates_file(self, tmp_path: Path) -> None:
        from docx import Document

        with patch("src.output_formatter.OUTPUTS_DIR", tmp_path):
            path = salvar_minuta_docx("# Minuta\nTexto com **destaque**.", "123")
            assert path.exists()
            assert path.suffix == ".docx"
            doc = Document(path)
            assert any("Minuta" in p.text for p in doc.paragraphs)
            assert any(run.bold for p in doc.paragraphs for run in p.runs)

    @pytest.mark.skipif(not HAS_PYTHON_DOCX, reason="python-docx não instalado")
    def test_docx_tjpr_formatting(self, tmp_path: Path) -> None:
        from docx import Document

        with patch("src.output_formatter.OUTPUTS_DIR", tmp_path):
            path = salvar_minuta_docx("Seção I\nParágrafo de teste.", "123")
            doc = Document(path)
            section = doc.sections[0]
            normal = doc.styles["Normal"]

            assert round(section.left_margin.cm, 1) == 3.0
            assert round(section.right_margin.cm, 1) == 2.0
            assert round(section.top_margin.cm, 1) == 3.0
            assert round(section.bottom_margin.cm, 1) == 2.0
            assert normal.font.name == "Times New Roman"
            assert int(normal.font.size.pt) == 12


# --- 5.5.5: Integration (slow) ---


@pytest.mark.slow
class TestPipelineIntegration:
    """Integration test: full pipeline Etapa 1→2→3. Run with: pytest -m slow"""

    def test_full_pipeline(self) -> None:
        from src.config import OPENAI_API_KEY

        if not OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY not set")

        from src.etapa1 import executar_etapa1
        from src.etapa2 import executar_etapa2
        from src.etapa3 import executar_etapa3

        texto_recurso = "RECURSO ESPECIAL. Recorrente: TESTE. Processo 123."
        texto_acordao = "ACÓRDÃO. Vistos. EMENTA: Dano moral."

        r1 = executar_etapa1(texto_recurso, "Extraia dados do recurso.")
        r2 = executar_etapa2(texto_acordao, r1, "Analise temas do acórdão.")
        r3 = executar_etapa3(r1, r2, texto_acordao, "Gere a minuta.")

        assert isinstance(r3, ResultadoEtapa3)
        assert len(r3.minuta_completa) > 0
