"""PDF text extraction with PyMuPDF (primary) and pdfplumber (fallback)."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

from src.config import MIN_TEXT_THRESHOLD
from src.models import DocumentoEntrada, TipoDocumento

logger = logging.getLogger("assessor_ai")


class PDFExtractionError(Exception):
    """Raised when PDF text extraction fails."""


class PDFPasswordProtectedError(PDFExtractionError):
    """Raised when PDF is password-protected."""


class PDFCorruptedError(PDFExtractionError):
    """Raised when PDF file is corrupted or invalid."""


@dataclass
class ExtractionResult:
    """Result of text extraction from a single PDF."""

    texto: str
    num_paginas: int
    num_caracteres: int
    engine_usada: str  # "pymupdf" or "pdfplumber"


def _extrair_com_pymupdf(filepath: str) -> ExtractionResult:
    """Extract text using PyMuPDF (fitz) as primary engine."""
    doc = fitz.open(filepath)

    if doc.is_encrypted:
        doc.close()
        raise PDFPasswordProtectedError(
            f"PDF protegido por senha: {filepath}"
        )

    pages_text: list[str] = []
    for page in doc:
        pages_text.append(page.get_text())

    doc.close()

    texto = "\n".join(pages_text)
    return ExtractionResult(
        texto=texto,
        num_paginas=len(pages_text),
        num_caracteres=len(texto),
        engine_usada="pymupdf",
    )


def _extrair_com_pdfplumber(filepath: str) -> ExtractionResult:
    """Extract text using pdfplumber as fallback engine."""
    pages_text: list[str] = []

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    texto = "\n".join(pages_text)
    return ExtractionResult(
        texto=texto,
        num_paginas=len(pages_text),
        num_caracteres=len(texto),
        engine_usada="pdfplumber",
    )


def _limpar_texto(texto: str) -> str:
    """Clean extracted text: normalize whitespace, remove repeated headers/footers."""
    # Normalize line endings
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive blank lines (3+ consecutive → 2)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    # Normalize multiple spaces (but preserve indentation)
    texto = re.sub(r"[^\S\n]{2,}", " ", texto)

    # Remove common repeated headers/footers (page numbers, repeated lines)
    lines = texto.split("\n")
    if len(lines) > 10:
        # Count line frequency to detect headers/footers
        line_counts: dict[str, int] = {}
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) < 100:
                line_counts[stripped] = line_counts.get(stripped, 0) + 1

        # Remove lines that appear more than 3 times (likely headers/footers)
        threshold = max(3, len(lines) // 20)
        repeated = {line for line, count in line_counts.items() if count > threshold}
        if repeated:
            logger.debug("Removendo %d padrões repetidos (headers/footers)", len(repeated))
            lines = [line for line in lines if line.strip() not in repeated]
            texto = "\n".join(lines)

    # Remove standalone page numbers
    texto = re.sub(r"\n\s*\d{1,4}\s*\n", "\n", texto)

    return texto.strip()


def _detectar_pdf_escaneado(resultado: ExtractionResult, filepath: str) -> bool:
    """Detect if PDF is scanned (image-only, no extractable text)."""
    if resultado.num_caracteres < MIN_TEXT_THRESHOLD and resultado.num_paginas > 0:
        logger.warning(
            "⚠️  PDF possivelmente escaneado (sem texto extraível): %s "
            "(%d páginas, %d caracteres extraídos). "
            "Considere usar OCR (Tesseract) para melhor resultado.",
            filepath,
            resultado.num_paginas,
            resultado.num_caracteres,
        )
        return True
    return False


def extrair_texto(filepath: str) -> ExtractionResult:
    """
    Extract text from a single PDF file.

    Uses PyMuPDF as primary engine. Falls back to pdfplumber if
    PyMuPDF returns less than MIN_TEXT_THRESHOLD characters.

    Args:
        filepath: Path to the PDF file.

    Returns:
        ExtractionResult with cleaned text, page count, and char count.

    Raises:
        PDFCorruptedError: If the file is corrupted or not a valid PDF.
        PDFPasswordProtectedError: If the file is password-protected.
        PDFExtractionError: For other extraction failures.
    """
    path = Path(filepath)

    if not path.exists():
        raise PDFExtractionError(f"Arquivo não encontrado: {filepath}")

    if not path.suffix.lower() == ".pdf":
        raise PDFExtractionError(
            f"Formato inválido (esperado .pdf): {path.suffix}"
        )

    # Try PyMuPDF first
    try:
        resultado = _extrair_com_pymupdf(filepath)
        logger.info(
            "PyMuPDF: %d páginas, %d caracteres — %s",
            resultado.num_paginas,
            resultado.num_caracteres,
            path.name,
        )
    except PDFPasswordProtectedError:
        raise
    except Exception as e:
        logger.warning("PyMuPDF falhou para %s: %s", path.name, e)
        resultado = ExtractionResult(
            texto="", num_paginas=0, num_caracteres=0, engine_usada="pymupdf"
        )

    # Fallback to pdfplumber if PyMuPDF got too little text
    if resultado.num_caracteres < MIN_TEXT_THRESHOLD:
        logger.info("Fallback para pdfplumber: %s", path.name)
        try:
            resultado = _extrair_com_pdfplumber(filepath)
            logger.info(
                "pdfplumber: %d páginas, %d caracteres — %s",
                resultado.num_paginas,
                resultado.num_caracteres,
                path.name,
            )
        except Exception as e:
            raise PDFCorruptedError(
                f"Não foi possível extrair texto de {path.name}: {e}"
            ) from e

    # Detect scanned PDFs
    _detectar_pdf_escaneado(resultado, filepath)

    # Clean the extracted text
    resultado.texto = _limpar_texto(resultado.texto)
    resultado.num_caracteres = len(resultado.texto)

    return resultado


def extrair_multiplos_pdfs(filepaths: list[str]) -> list[DocumentoEntrada]:
    """
    Extract text from multiple PDF files (possibly fractioned).

    Concatenates text from all PDFs into DocumentoEntrada objects.

    Args:
        filepaths: List of paths to PDF files.

    Returns:
        List of DocumentoEntrada, one per file, with extracted text.
    """
    documentos: list[DocumentoEntrada] = []

    for filepath in filepaths:
        try:
            resultado = extrair_texto(filepath)
            doc = DocumentoEntrada(
                filepath=filepath,
                texto_extraido=resultado.texto,
                tipo=TipoDocumento.DESCONHECIDO,
                num_paginas=resultado.num_paginas,
                num_caracteres=resultado.num_caracteres,
            )
            documentos.append(doc)
        except PDFExtractionError as e:
            logger.error("❌ Erro ao processar %s: %s", filepath, e)
            raise

    total_chars = sum(d.num_caracteres for d in documentos)
    total_pages = sum(d.num_paginas for d in documentos)
    logger.info(
        "Extração concluída: %d arquivo(s), %d páginas, %d caracteres",
        len(documentos),
        total_pages,
        total_chars,
    )

    return documentos


def concatenar_textos(documentos: list[DocumentoEntrada]) -> str:
    """
    Concatenate text from multiple fractioned documents into a single string.

    Args:
        documentos: List of DocumentoEntrada to concatenate.

    Returns:
        Single string with all texts joined by separator.
    """
    textos = [doc.texto_extraido for doc in documentos if doc.texto_extraido]
    return "\n\n---\n\n".join(textos)
