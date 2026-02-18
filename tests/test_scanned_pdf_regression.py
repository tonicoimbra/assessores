"""Regression tests for scanned/image-only PDF extraction flow."""

from __future__ import annotations

from pathlib import Path

import fitz

from src.pdf_processor import ExtractionResult, extrair_multiplos_pdfs, extrair_texto


def _build_scanned_like_pdf(tmp_path: Path, *, name: str, text: str) -> Path:
    """
    Create a realistic scanned-like PDF (image-only, without text layer).

    Strategy:
    1) generate a normal PDF with text;
    2) rasterize the page to image (pixmap);
    3) embed that image into a new PDF page.
    """
    source_pdf = tmp_path / f"{name}_source.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=595, height=842)  # A4-ish
    page.insert_text(
        (72, 96),
        text,
        fontsize=14,
    )
    source_doc.save(source_pdf)
    source_doc.close()

    source_loaded = fitz.open(source_pdf)
    pix = source_loaded[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    source_loaded.close()

    scanned_pdf = tmp_path / f"{name}_scanned.pdf"
    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=pix.width, height=pix.height)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    scanned_doc.save(scanned_pdf)
    scanned_doc.close()

    return scanned_pdf


def test_scanned_pdf_without_ocr_keeps_low_text_signal(tmp_path: Path, monkeypatch) -> None:
    scanned_pdf = _build_scanned_like_pdf(
        tmp_path,
        name="case_no_ocr",
        text="RECURSO ESPECIAL. Recorrente: EMPRESA TESTE LTDA.",
    )

    monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", False)
    monkeypatch.setattr("src.pdf_processor.MIN_TEXT_THRESHOLD", 100)

    resultado = extrair_texto(str(scanned_pdf))

    assert resultado.engine_usada == "pdfplumber"
    assert resultado.num_paginas == 1
    assert resultado.num_caracteres == 0
    assert resultado.quality_score == 0.0
    assert resultado.noise_ratio == 1.0
    assert len(resultado.raw_text_by_page) == 1
    assert len(resultado.clean_text_by_page) == 1
    assert len(resultado.raw_page_hashes) == 1
    assert len(resultado.clean_page_hashes) == 1
    assert len(resultado.noise_ratio_by_page) == 1
    assert len(resultado.ocr_confidence_by_page) == 1


def test_scanned_pdf_with_ocr_gain_promotes_ocr_result(tmp_path: Path, monkeypatch) -> None:
    scanned_pdf = _build_scanned_like_pdf(
        tmp_path,
        name="case_with_ocr",
        text="ACÓRDÃO. Incidência da Súmula 7/STJ em Recurso Especial.",
    )

    monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)
    monkeypatch.setattr("src.pdf_processor.MIN_TEXT_THRESHOLD", 100)

    ocr_text = "ACÓRDÃO OCR. Incidência da Súmula 7/STJ confirmada."
    monkeypatch.setattr(
        "src.pdf_processor._extrair_com_ocr",
        lambda _path: ExtractionResult(
            texto=ocr_text,
            num_paginas=1,
            num_caracteres=len(ocr_text),
            engine_usada="ocr",
            raw_text_by_page=[ocr_text],
            pages_with_ocr=[1],
            ocr_aplicado=True,
            ocr_fallback_successful=True,
        ),
    )

    resultado = extrair_texto(str(scanned_pdf))

    assert resultado.engine_usada == "ocr"
    assert resultado.ocr_aplicado is True
    assert resultado.pages_with_ocr == [1]
    assert "Súmula 7/STJ" in resultado.texto
    assert resultado.num_caracteres > 20
    assert resultado.quality_score > 0.0
    assert 0.0 <= resultado.noise_ratio <= 1.0
    assert resultado.ocr_confidence == 0.0
    assert len(resultado.raw_page_hashes) == 1
    assert len(resultado.clean_page_hashes) == 1


def test_scanned_pdf_batch_regression_with_mocked_ocr(tmp_path: Path, monkeypatch) -> None:
    scanned_a = _build_scanned_like_pdf(
        tmp_path,
        name="batch_a",
        text="RECURSO ESPECIAL. Processo 0001111-11.2024.8.16.0001.",
    )
    scanned_b = _build_scanned_like_pdf(
        tmp_path,
        name="batch_b",
        text="ACÓRDÃO. Reexame de provas vedado. Súmula 7/STJ.",
    )

    monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)
    monkeypatch.setattr("src.pdf_processor.MIN_TEXT_THRESHOLD", 100)

    def _fake_ocr(path: str) -> ExtractionResult:
        filename = Path(path).name
        text = f"OCR extraído de {filename}"
        return ExtractionResult(
            texto=text,
            num_paginas=1,
            num_caracteres=len(text),
            engine_usada="ocr",
            raw_text_by_page=[text],
            pages_with_ocr=[1],
            ocr_aplicado=True,
            ocr_fallback_successful=True,
        )

    monkeypatch.setattr("src.pdf_processor._extrair_com_ocr", _fake_ocr)

    documentos = extrair_multiplos_pdfs([str(scanned_a), str(scanned_b)])

    assert len(documentos) == 2
    assert all(doc.num_paginas == 1 for doc in documentos)
    assert all(doc.num_caracteres > 0 for doc in documentos)
    assert any("batch_a_scanned.pdf" in doc.texto_extraido for doc in documentos)
    assert any("batch_b_scanned.pdf" in doc.texto_extraido for doc in documentos)
