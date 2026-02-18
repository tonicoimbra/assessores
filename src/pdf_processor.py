"""PDF text extraction with PyMuPDF (primary) and pdfplumber (fallback)."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber

from src.config import (
    ENABLE_OCR_PREPROCESSING,
    ENABLE_OCR_FALLBACK,
    MIN_TEXT_THRESHOLD,
    OCR_BINARIZATION_ENABLED,
    OCR_BINARIZATION_THRESHOLD,
    OCR_DENOISE_ENABLED,
    OCR_DENOISE_MEDIAN_SIZE,
    OCR_DESKEW_ENABLED,
    OCR_LANGUAGES,
    OCR_TRIGGER_MIN_CHARS_PER_PAGE,
)
from src.models import DocumentoEntrada, TipoDocumento

logger = logging.getLogger("assessor_ai")

_NOISE_PATTERNS = [
    re.compile(r"^\s*p[áa]gina\s+\d+(\s+de\s+\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*documento\s+assinado\s+digitalmente.*$", re.IGNORECASE),
    re.compile(r"^\s*assinado\s+eletronicamente.*$", re.IGNORECASE),
    re.compile(r"^\s*c[óo]digo\s+verificador.*$", re.IGNORECASE),
    re.compile(r"^\s*c[óo]digo\s+de\s+autentica[çc][ãa]o.*$", re.IGNORECASE),
    re.compile(r"^\s*consulte\s+autenticidade.*$", re.IGNORECASE),
    re.compile(r"^\s*http[s]?://\S+\s*$", re.IGNORECASE),
    re.compile(r"^\s*[-_=*~]{4,}\s*$"),
]


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
    raw_text_by_page: list[str] = field(default_factory=list)
    clean_text_by_page: list[str] = field(default_factory=list)
    pages_with_ocr: list[int] = field(default_factory=list)
    ocr_aplicado: bool = False
    ocr_fallback_successful: bool = False
    ocr_preprocess_aplicado: bool = False
    ocr_preprocess_steps: list[str] = field(default_factory=list)
    quality_score: float = 0.0


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
        raw_text_by_page=pages_text,
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
        raw_text_by_page=pages_text,
    )


def _parse_osd_rotation(osd_text: str) -> int:
    """Extract rotation angle from pytesseract OSD text."""
    match = re.search(r"Rotate:\s*(\d+)", str(osd_text or ""), re.IGNORECASE)
    if not match:
        return 0
    angle = int(match.group(1))
    return angle if angle in {0, 90, 180, 270} else 0


def _preprocess_image_for_ocr(
    image: Any,
    *,
    pytesseract_module: Any | None = None,
) -> tuple[Any, list[str]]:
    """Apply OCR preprocessing: deskew, denoise, and binarization."""
    steps: list[str] = []
    processed = image

    try:
        from PIL import ImageFilter, ImageOps
    except ImportError:
        return processed, steps

    if getattr(processed, "mode", "") != "L":
        processed = processed.convert("L")
        steps.append("grayscale")

    if OCR_DENOISE_ENABLED:
        size = max(3, int(OCR_DENOISE_MEDIAN_SIZE))
        if size % 2 == 0:
            size += 1
        processed = processed.filter(ImageFilter.MedianFilter(size=size))
        steps.append(f"denoise_median_{size}")

    if OCR_BINARIZATION_ENABLED:
        threshold = max(0, min(255, int(OCR_BINARIZATION_THRESHOLD)))
        processed = ImageOps.autocontrast(processed)
        processed = processed.point(lambda px: 255 if px >= threshold else 0).convert("L")
        steps.append(f"binarize_threshold_{threshold}")

    if OCR_DESKEW_ENABLED and pytesseract_module is not None:
        try:
            osd_text = pytesseract_module.image_to_osd(processed)
            rotate = _parse_osd_rotation(osd_text)
            if rotate in {90, 180, 270}:
                processed = processed.rotate(-rotate, expand=True)
                steps.append(f"deskew_rotate_{rotate}")
        except Exception:
            logger.debug("OSD rotation unavailable for OCR preprocessing.", exc_info=True)

    return processed, steps


def _extrair_com_ocr(filepath: str) -> ExtractionResult:
    """Extract text with OCR page-by-page using PyMuPDF rasterization + pytesseract."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError as e:
        raise PDFExtractionError(
            "OCR indisponível: instale pytesseract e garanta o binário Tesseract no sistema."
        ) from e

    doc = fitz.open(filepath)
    if doc.is_encrypted:
        doc.close()
        raise PDFPasswordProtectedError(f"PDF protegido por senha: {filepath}")

    pages_text: list[str] = []
    pages_with_ocr: list[int] = []
    preprocess_steps: list[str] = []
    preprocess_aplicado = False

    for idx, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        if pix.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)

        mode = "RGB" if pix.n == 3 else "L"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if ENABLE_OCR_PREPROCESSING:
            image, page_steps = _preprocess_image_for_ocr(
                image,
                pytesseract_module=pytesseract,
            )
            if page_steps:
                preprocess_aplicado = True
                for step in page_steps:
                    if step not in preprocess_steps:
                        preprocess_steps.append(step)
        page_text = pytesseract.image_to_string(image, lang=OCR_LANGUAGES) or ""
        if page_text.strip():
            pages_with_ocr.append(idx + 1)
        pages_text.append(page_text)

    doc.close()

    texto = "\n".join(pages_text)
    return ExtractionResult(
        texto=texto,
        num_paginas=len(pages_text),
        num_caracteres=len(texto),
        engine_usada="ocr",
        raw_text_by_page=pages_text,
        pages_with_ocr=pages_with_ocr,
        ocr_aplicado=True,
        ocr_fallback_successful=bool(texto.strip()),
        ocr_preprocess_aplicado=preprocess_aplicado,
        ocr_preprocess_steps=preprocess_steps,
    )


def _is_noise_line(line: str) -> bool:
    """Return True if line matches known extraction noise patterns."""
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.match(stripped) for pattern in _NOISE_PATTERNS)


def _limpar_texto(texto: str) -> str:
    """Clean extracted text deterministically while preserving useful legal content."""
    # Normalize line endings
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize multiple spaces (keep line boundaries)
    texto = re.sub(r"[^\S\n]{2,}", " ", texto)

    lines = texto.split("\n")
    if not lines:
        return ""

    # Frequency map for short lines (headers/footers often repeat a lot)
    freq: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 140:
            freq[stripped] = freq.get(stripped, 0) + 1

    repeated_threshold = max(8, len(lines) // 15)
    repeated_lines = {
        line for line, count in freq.items()
        if count >= repeated_threshold
    }

    filtered_lines: list[str] = []
    last_kept = ""
    duplicate_run = 0

    for raw_line in lines:
        line = raw_line.strip()

        if _is_noise_line(line):
            continue

        # Remove globally repeated header/footer lines
        if line in repeated_lines:
            continue

        # Remove long duplicate runs (same line repeated many times consecutively)
        if line and line == last_kept:
            duplicate_run += 1
            if duplicate_run >= 2:
                continue
        else:
            duplicate_run = 0

        filtered_lines.append(line)
        if line:
            last_kept = line

    # Remove standalone page numbers
    texto = "\n".join(filtered_lines)
    texto = re.sub(r"\n\s*\d{1,4}\s*\n", "\n", texto)

    # Collapse blank lines: 3+ -> 2
    texto = re.sub(r"\n{3,}", "\n\n", texto)

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


def _calcular_score_qualidade(texto: str) -> float:
    """Estimate extraction quality score in [0, 1]."""
    if not texto.strip():
        return 0.0

    total_chars = len(texto)
    alnum_ratio = sum(c.isalnum() for c in texto) / max(total_chars, 1)
    lines = [line.strip() for line in texto.splitlines() if line.strip()]
    if not lines:
        return round(alnum_ratio, 3)

    useful_lines = sum(1 for line in lines if len(line) >= 20 and not _is_noise_line(line))
    useful_ratio = useful_lines / len(lines)
    unique_ratio = len(set(lines)) / len(lines)
    score = (0.45 * alnum_ratio) + (0.4 * useful_ratio) + (0.15 * unique_ratio)
    return round(max(0.0, min(1.0, score)), 3)


def _deve_tentar_ocr(resultado: ExtractionResult) -> bool:
    """Decide whether OCR fallback should be attempted for a low-text extraction."""
    if not ENABLE_OCR_FALLBACK:
        return False

    if resultado.num_caracteres < MIN_TEXT_THRESHOLD:
        return True

    media_chars_por_pagina = resultado.num_caracteres / max(resultado.num_paginas, 1)
    return media_chars_por_pagina < OCR_TRIGGER_MIN_CHARS_PER_PAGE


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

    # Optional OCR pass for low-text/scanned PDFs
    if _deve_tentar_ocr(resultado):
        logger.info("Tentando OCR automático: %s", path.name)
        try:
            resultado_ocr = _extrair_com_ocr(filepath)
            if resultado_ocr.num_caracteres > resultado.num_caracteres:
                logger.info(
                    "OCR melhorou extração: %d -> %d caracteres (%s)",
                    resultado.num_caracteres,
                    resultado_ocr.num_caracteres,
                    path.name,
                )
                resultado = resultado_ocr
            else:
                logger.info(
                    "OCR não trouxe ganho de extração (%d chars, mantendo engine=%s).",
                    resultado_ocr.num_caracteres,
                    resultado.engine_usada,
                )
        except Exception as e:
            logger.warning("OCR falhou para %s: %s", path.name, e)

    # Detect scanned PDFs
    _detectar_pdf_escaneado(resultado, filepath)

    # Clean the extracted text and log reduction
    if not resultado.raw_text_by_page:
        resultado.raw_text_by_page = [resultado.texto] if resultado.texto else []

    chars_before = len(resultado.texto)
    resultado.texto = _limpar_texto(resultado.texto)
    resultado.num_caracteres = len(resultado.texto)
    resultado.clean_text_by_page = [
        _limpar_texto(page_text) for page_text in resultado.raw_text_by_page
    ]
    resultado.quality_score = _calcular_score_qualidade(resultado.texto)
    chars_after = resultado.num_caracteres
    reduction = (chars_before - chars_after) / chars_before * 100 if chars_before > 0 else 0.0
    logger.info(
        "🧹 Limpeza de texto (%s): %d -> %d chars (redução %.1f%%, quality=%.3f)",
        path.name,
        chars_before,
        chars_after,
        reduction,
        resultado.quality_score,
    )

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
