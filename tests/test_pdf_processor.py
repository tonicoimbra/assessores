"""Tests for PDF text extraction (Sprint 1.4)."""

import pytest

from src.pdf_processor import (
    ExtractionResult,
    PDFCorruptedError,
    PDFExtractionError,
    _limpar_texto,
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


class TestFallbackPdfplumber:
    """Test 1.5.2: fallback to pdfplumber when PyMuPDF returns too little text."""

    def test_fallback_activates_on_minimal_text(self, sample_minimal_path: str) -> None:
        resultado = extrair_texto(sample_minimal_path)

        # Should still return a result (either engine)
        assert isinstance(resultado, ExtractionResult)
        assert resultado.num_paginas > 0


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
