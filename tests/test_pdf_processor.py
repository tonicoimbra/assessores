"""Tests for PDF text extraction (Sprint 1.4)."""

import pytest

from src.pdf_processor import (
    ExtractionResult,
    PDFCorruptedError,
    PDFExtractionError,
    _deve_tentar_ocr,
    _limpar_texto,
    _parse_osd_rotation,
    _preprocess_image_for_ocr,
    extrair_multiplos_pdfs,
    extrair_texto,
)


class TestExtrairTexto:
    """Test 1.5.1: extraction from a valid PDF with text."""

    def test_extracts_text_from_valid_pdf(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)

        assert isinstance(resultado, ExtractionResult)
        assert resultado.num_paginas > 0
        assert resultado.num_caracteres > 0
        assert "RECURSO ESPECIAL" in resultado.texto

    def test_returns_page_count(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)
        assert resultado.num_paginas == 1

    def test_returns_character_count(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)
        assert resultado.num_caracteres > 50

    def test_extracts_recorrente_name(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)
        assert "JOÃO DA SILVA" in resultado.texto

    def test_tracks_engine_used(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)
        assert resultado.engine_usada in ("pymupdf", "pdfplumber")

    def test_exposes_quality_and_page_mappings(self, sample_recurso_path: str) -> None:
        resultado = extrair_texto(sample_recurso_path)
        assert 0.0 <= resultado.quality_score <= 1.0
        assert len(resultado.raw_text_by_page) == resultado.num_paginas
        assert len(resultado.clean_text_by_page) == resultado.num_paginas


class TestFallbackPdfplumber:
    """Test 1.5.2: fallback to pdfplumber when PyMuPDF returns too little text."""

    def test_fallback_activates_on_minimal_text(self, sample_minimal_path: str) -> None:
        resultado = extrair_texto(sample_minimal_path)

        # Should still return a result (either engine)
        assert isinstance(resultado, ExtractionResult)
        assert resultado.num_paginas > 0

    def test_ocr_is_used_when_enabled_and_improves_text(self, sample_minimal_path: str, monkeypatch) -> None:
        monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)

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
                texto="",
                num_paginas=1,
                num_caracteres=0,
                engine_usada="pdfplumber",
                raw_text_by_page=[""],
            ),
        )
        monkeypatch.setattr(
            "src.pdf_processor._extrair_com_ocr",
            lambda _path: ExtractionResult(
                texto="Texto extraído por OCR com conteúdo útil",
                num_paginas=1,
                num_caracteres=39,
                engine_usada="ocr",
                raw_text_by_page=["Texto extraído por OCR com conteúdo útil"],
                pages_with_ocr=[1],
                ocr_aplicado=True,
            ),
        )

        resultado = extrair_texto(sample_minimal_path)
        assert resultado.engine_usada == "ocr"
        assert resultado.ocr_aplicado is True
        assert resultado.pages_with_ocr == [1]
        assert "OCR" in resultado.texto

    def test_ocr_failure_keeps_previous_engine(self, sample_minimal_path: str, monkeypatch) -> None:
        monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)

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
                texto="abc",
                num_paginas=1,
                num_caracteres=3,
                engine_usada="pdfplumber",
                raw_text_by_page=["abc"],
            ),
        )

        def _raise_ocr(_path: str) -> ExtractionResult:
            raise RuntimeError("OCR unavailable")

        monkeypatch.setattr("src.pdf_processor._extrair_com_ocr", _raise_ocr)

        resultado = extrair_texto(sample_minimal_path)
        assert resultado.engine_usada == "pdfplumber"

    def test_ocr_trigger_by_average_chars_per_page(self, monkeypatch) -> None:
        monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", True)
        monkeypatch.setattr("src.pdf_processor.MIN_TEXT_THRESHOLD", 100)
        monkeypatch.setattr("src.pdf_processor.OCR_TRIGGER_MIN_CHARS_PER_PAGE", 20)

        resultado = ExtractionResult(
            texto="x" * 200,
            num_paginas=20,
            num_caracteres=200,
            engine_usada="pdfplumber",
        )
        assert _deve_tentar_ocr(resultado) is True

    def test_ocr_trigger_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr("src.pdf_processor.ENABLE_OCR_FALLBACK", False)
        resultado = ExtractionResult(
            texto="x" * 10,
            num_paginas=1,
            num_caracteres=10,
            engine_usada="pdfplumber",
        )
        assert _deve_tentar_ocr(resultado) is False

    def test_parse_osd_rotation(self) -> None:
        assert _parse_osd_rotation("Page number: 0\nRotate: 90\n") == 90
        assert _parse_osd_rotation("Rotate: 180") == 180
        assert _parse_osd_rotation("Rotate: 33") == 0
        assert _parse_osd_rotation("") == 0

    def test_preprocess_image_for_ocr_applies_steps(self, monkeypatch) -> None:
        from PIL import Image

        class FakePytesseract:
            @staticmethod
            def image_to_osd(_image) -> str:
                return "Rotate: 90"

        monkeypatch.setattr("src.pdf_processor.OCR_DENOISE_ENABLED", True)
        monkeypatch.setattr("src.pdf_processor.OCR_BINARIZATION_ENABLED", True)
        monkeypatch.setattr("src.pdf_processor.OCR_DESKEW_ENABLED", True)
        monkeypatch.setattr("src.pdf_processor.OCR_DENOISE_MEDIAN_SIZE", 4)
        monkeypatch.setattr("src.pdf_processor.OCR_BINARIZATION_THRESHOLD", 170)

        image = Image.new("RGB", (16, 16), color="white")
        processed, steps = _preprocess_image_for_ocr(
            image,
            pytesseract_module=FakePytesseract(),
        )

        assert processed.mode == "L"
        assert "grayscale" in steps
        assert "denoise_median_5" in steps
        assert "binarize_threshold_170" in steps
        assert "deskew_rotate_90" in steps


class TestPDFErrors:
    """Test 1.5.3: handling of corrupted, missing, and invalid PDFs."""

    def test_raises_on_nonexistent_file(self, nonexistent_path: str) -> None:
        with pytest.raises(PDFExtractionError, match="Arquivo não encontrado"):
            extrair_texto(nonexistent_path)

    def test_raises_on_invalid_format(self, not_a_pdf_path: str) -> None:
        with pytest.raises(PDFExtractionError, match="Formato inválido"):
            extrair_texto(not_a_pdf_path)

    def test_raises_on_corrupted_pdf(self, corrupted_pdf_path: str) -> None:
        with pytest.raises((PDFCorruptedError, PDFExtractionError)):
            extrair_texto(corrupted_pdf_path)


class TestLimpezaTexto:
    """Test text cleaning utility."""

    def test_removes_excessive_blank_lines(self) -> None:
        resultado = _limpar_texto("A\n\n\n\n\nB")
        assert resultado == "A\n\nB"

    def test_normalizes_multiple_spaces(self) -> None:
        resultado = _limpar_texto("many    spaces    here")
        assert "    " not in resultado

    def test_removes_standalone_page_numbers(self) -> None:
        resultado = _limpar_texto("text\n  42  \nmore text")
        assert "42" not in resultado

    def test_strips_result(self) -> None:
        resultado = _limpar_texto("  text  ")
        assert resultado == "text"


class TestExtrairMultiplosPdfs:
    """Test multi-PDF extraction."""

    def test_extracts_from_multiple_files(self, sample_recurso_path: str) -> None:
        docs = extrair_multiplos_pdfs([sample_recurso_path])
        assert len(docs) == 1
        assert docs[0].texto_extraido
        assert docs[0].num_paginas > 0

    def test_raises_on_invalid_file_in_list(self, nonexistent_path: str) -> None:
        with pytest.raises(PDFExtractionError):
            extrair_multiplos_pdfs([nonexistent_path])
