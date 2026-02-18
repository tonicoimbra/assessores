"""Adversarial regression suite for fail-closed behavior."""

from unittest.mock import patch

import pytest

from src.classifier import (
    ClassificationResult,
    DocumentClassificationError,
    classificar_documentos,
)
from src.models import DocumentoEntrada, TipoDocumento
from src.pdf_processor import (
    ExtractionResult,
    PDFCorruptedError,
    extrair_multiplos_pdfs,
    extrair_texto,
)


@pytest.mark.adversarial
def test_adversarial_corrupted_pdf_aborts_batch_extraction(
    sample_recurso_path: str,
    corrupted_pdf_path: str,
) -> None:
    """Fail closed when any file in batch is a corrupted PDF."""
    with pytest.raises(PDFCorruptedError):
        extrair_multiplos_pdfs([sample_recurso_path, corrupted_pdf_path])


@pytest.mark.adversarial
def test_adversarial_scanned_bad_ocr_without_gain_keeps_previous_engine(
    sample_minimal_path: str,
    monkeypatch,
) -> None:
    """If OCR does not improve extraction, keep previous engine and low quality signal."""
    monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)
    monkeypatch.setattr("src.pdf_processor.MIN_TEXT_THRESHOLD", 100)
    monkeypatch.setattr(
        "src.pdf_processor._extrair_com_pymupdf",
        lambda _path: ExtractionResult(
            texto="",
            num_paginas=1,
            num_caracteres=0,
            engine_usada="pymupdf",
            raw_text_by_page=[""],
        ),
    )
    monkeypatch.setattr(
        "src.pdf_processor._extrair_com_pdfplumber",
        lambda _path: ExtractionResult(
            texto="Página 1 de 1\nDocumento assinado digitalmente\nhttp://tjpr.jus.br",
            num_paginas=1,
            num_caracteres=64,
            engine_usada="pdfplumber",
            raw_text_by_page=[
                "Página 1 de 1\nDocumento assinado digitalmente\nhttp://tjpr.jus.br"
            ],
        ),
    )
    monkeypatch.setattr(
        "src.pdf_processor._extrair_com_ocr",
        lambda _path: ExtractionResult(
            texto="",
            num_paginas=1,
            num_caracteres=0,
            engine_usada="ocr",
            raw_text_by_page=[""],
            pages_with_ocr=[],
            ocr_aplicado=True,
            ocr_fallback_successful=False,
        ),
    )

    resultado = extrair_texto(sample_minimal_path)

    assert resultado.engine_usada == "pdfplumber"
    assert resultado.num_paginas == 1
    assert resultado.quality_score <= 0.2
    assert resultado.num_caracteres <= 5


@pytest.mark.adversarial
def test_adversarial_ambiguous_classification_strict_mode_fails_closed() -> None:
    """Ambiguous documents with uncertain LLM must fail strict invariants."""
    docs = [
        DocumentoEntrada(
            filepath="doc_amb_1.pdf",
            texto_extraido="Peça processual genérica sem elementos de recurso ou acórdão.",
        ),
        DocumentoEntrada(
            filepath="doc_amb_2.pdf",
            texto_extraido="Despacho de movimentação sem ementa, sem razões recursais.",
        ),
    ]

    with patch(
        "src.classifier._classificar_por_llm",
        return_value=ClassificationResult(
            tipo=TipoDocumento.DESCONHECIDO,
            confianca=0.12,
            metodo="llm",
        ),
    ):
        with pytest.raises(DocumentClassificationError) as exc_info:
            classificar_documentos(docs, strict=True)

    msg = str(exc_info.value)
    assert "Nenhum RECURSO identificado" in msg
    assert "Foram identificados 0 ACÓRDÃOS" in msg
