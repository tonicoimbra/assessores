"""PDF text extraction with PyMuPDF (primary) and pdfplumber (fallback)."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha256
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Callable

import fitz  # PyMuPDF
import pdfplumber

from src.config import (
    ENABLE_OCR_PREPROCESSING,
    ENABLE_OCR_FALLBACK,
    MIN_TEXT_THRESHOLD,
    OCR_MAX_WORKERS,
    OCR_BINARIZATION_ENABLED,
    OCR_BINARIZATION_THRESHOLD,
    OCR_DENOISE_ENABLED,
    OCR_DENOISE_MEDIAN_SIZE,
    OCR_DESKEW_ENABLED,
    OCR_LANGUAGES,
    OCR_TRIGGER_MIN_CHARS_PER_PAGE,
)
from src.models import DocumentoEntrada

logger = logging.getLogger("assessor_ai")
_OCR_PAGE_TIMEOUT_SECONDS = 25.0

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
_LEGAL_CONTENT_PATTERN = re.compile(
    r"\b("
    r"art\.?|artigo|lei|cpc|cc|cf|constitui[çc][ãa]o|s[úu]mula|sumula|"
    r"resp|recurso|ac[óo]rd[ãa]o|processo|apel[aã]o|agravo|tema"
    r")\b",
    re.IGNORECASE,
)


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
    engine_usada: str  # "pymupdf", "pdfplumber", "ocr", or "<engine>+ocr"
    raw_text_by_page: list[str] = field(default_factory=list)
    clean_text_by_page: list[str] = field(default_factory=list)
    raw_page_hashes: list[str] = field(default_factory=list)
    clean_page_hashes: list[str] = field(default_factory=list)
    quality_score_by_page: list[float] = field(default_factory=list)
    noise_ratio_by_page: list[float] = field(default_factory=list)
    pages_with_ocr: list[int] = field(default_factory=list)
    ocr_aplicado: bool = False
    ocr_fallback_successful: bool = False
    ocr_preprocess_aplicado: bool = False
    ocr_preprocess_steps: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    noise_ratio: float = 0.0
    ocr_confidence_by_page: list[float] = field(default_factory=list)
    ocr_confidence: float = 0.0
    ocr_processing_time_ms: int = 0


@dataclass
class _OCRPageData:
    """Per-page OCR extraction output."""

    page_index: int
    text: str = ""
    confidence: float = 0.0
    preprocess_steps: list[str] = field(default_factory=list)


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
        raw_page_hashes=[sha256((page or "").encode("utf-8")).hexdigest() for page in pages_text],
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
        raw_page_hashes=[sha256((page or "").encode("utf-8")).hexdigest() for page in pages_text],
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


def _extrair_ocr_por_pagina(
    filepath: str,
    page_index: int,
    *,
    pytesseract_module: Any,
    image_module: Any,
    page_timeout_seconds: float,
) -> _OCRPageData:
    """Run OCR for a single page using its own fitz.Document instance."""
    preprocess_steps: list[str] = []
    page_text = ""
    page_confidence = 0.0
    page_number = page_index + 1
    filename = Path(filepath).name

    doc = fitz.open(filepath)
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        if pix.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)

        mode = "RGB" if pix.n == 3 else "L"
        image = image_module.frombytes(mode, [pix.width, pix.height], pix.samples)
        if ENABLE_OCR_PREPROCESSING:
            image, preprocess_steps = _preprocess_image_for_ocr(
                image,
                pytesseract_module=pytesseract_module,
            )

        ocr_kwargs: dict[str, Any] = {"lang": OCR_LANGUAGES}
        if page_timeout_seconds > 0:
            ocr_kwargs["timeout"] = page_timeout_seconds

        try:
            page_text = pytesseract_module.image_to_string(image, **ocr_kwargs) or ""
        except RuntimeError as exc:
            logger.warning(
                "OCR timeout/falha na página %d (%s): %s",
                page_number,
                filename,
                exc,
            )
            return _OCRPageData(
                page_index=page_index,
                text="",
                confidence=0.0,
                preprocess_steps=preprocess_steps,
            )

        try:
            output_type = getattr(getattr(pytesseract_module, "Output", None), "DICT", None)
            if output_type is not None:
                data_kwargs: dict[str, Any] = {
                    "lang": OCR_LANGUAGES,
                    "output_type": output_type,
                }
                if page_timeout_seconds > 0:
                    data_kwargs["timeout"] = page_timeout_seconds
                data = pytesseract_module.image_to_data(image, **data_kwargs)
                conf_values: list[float] = []
                for raw_conf in data.get("conf", []):
                    try:
                        conf = float(str(raw_conf).strip())
                    except (TypeError, ValueError):
                        continue
                    if conf >= 0:
                        conf_values.append(conf)
                if conf_values:
                    page_confidence = round(
                        max(0.0, min(1.0, mean(conf_values) / 100.0)),
                        3,
                    )
        except RuntimeError as exc:
            logger.warning(
                "Timeout/falha ao calcular confiança OCR na página %d (%s): %s",
                page_number,
                filename,
                exc,
            )
        except Exception:
            logger.debug(
                "Falha ao calcular confiança OCR por página (%d).",
                page_number,
                exc_info=True,
            )
    finally:
        doc.close()

    return _OCRPageData(
        page_index=page_index,
        text=page_text,
        confidence=page_confidence,
        preprocess_steps=preprocess_steps,
    )


def _executar_ocr_paralelo(
    filepath: str,
    page_indices: list[int],
    *,
    worker_fn: Callable[[str, int], _OCRPageData],
    max_workers: int,
) -> dict[int, _OCRPageData]:
    """Execute per-page OCR in parallel and keep per-page outputs."""
    workers = max(1, int(max_workers))
    results: dict[int, _OCRPageData] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_page = {
            executor.submit(worker_fn, filepath, page_index): page_index
            for page_index in page_indices
        }
        for future in as_completed(future_to_page):
            page_index = future_to_page[future]
            try:
                page_result = future.result()
            except Exception as exc:
                logger.warning(
                    "Falha OCR na página %d (%s): %s",
                    page_index + 1,
                    Path(filepath).name,
                    exc,
                )
                page_result = _OCRPageData(page_index=page_index)

            if page_result.page_index != page_index:
                page_result.page_index = page_index
            results[page_index] = page_result

    return results


def _normalizar_paginas_ocr(
    pages_only: list[int] | None,
    *,
    page_count: int,
) -> list[int]:
    """Normalize 1-based page numbers to unique zero-based indexes."""
    if pages_only is None:
        return list(range(page_count))

    normalized: list[int] = []
    for page_number in pages_only:
        if not isinstance(page_number, int):
            continue
        if 1 <= page_number <= page_count:
            normalized.append(page_number - 1)
    return sorted(set(normalized))


def _extrair_com_ocr(
    filepath: str,
    pages_only: list[int] | None = None,
) -> ExtractionResult:
    """Extract text with OCR page-by-page using parallel workers."""
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
    page_count = doc.page_count
    doc.close()

    if page_count == 0:
        return ExtractionResult(
            texto="",
            num_paginas=0,
            num_caracteres=0,
            engine_usada="ocr",
            ocr_aplicado=True,
            ocr_fallback_successful=False,
        )

    page_indices = _normalizar_paginas_ocr(pages_only, page_count=page_count)
    if not page_indices:
        return ExtractionResult(
            texto="",
            num_paginas=page_count,
            num_caracteres=0,
            engine_usada="ocr",
            raw_text_by_page=["" for _ in range(page_count)],
            raw_page_hashes=[sha256("".encode("utf-8")).hexdigest() for _ in range(page_count)],
            ocr_aplicado=True,
            ocr_fallback_successful=False,
        )

    started_at = perf_counter()
    worker_fn = partial(
        _extrair_ocr_por_pagina,
        pytesseract_module=pytesseract,
        image_module=Image,
        page_timeout_seconds=_OCR_PAGE_TIMEOUT_SECONDS,
    )
    page_outputs = _executar_ocr_paralelo(
        filepath,
        page_indices,
        worker_fn=worker_fn,
        max_workers=OCR_MAX_WORKERS,
    )
    processing_time_ms = int((perf_counter() - started_at) * 1000)

    ordered_outputs = [
        page_outputs.get(index, _OCRPageData(page_index=index))
        for index in range(page_count)
    ]
    pages_text = [output.text for output in ordered_outputs]
    ocr_confidence_by_page = [output.confidence for output in ordered_outputs]

    preprocess_steps: list[str] = []
    preprocess_aplicado = False
    for output in ordered_outputs:
        if output.preprocess_steps:
            preprocess_aplicado = True
        for step in output.preprocess_steps:
            if step not in preprocess_steps:
                preprocess_steps.append(step)

    page_indices_set = set(page_indices)
    pages_with_ocr = [
        output.page_index + 1
        for output in ordered_outputs
        if output.page_index in page_indices_set and output.text.strip()
    ]

    logger.info(
        "OCR paralelo concluído: %d página(s) processadas de %d, %d worker(s), %d ms (%s)",
        len(page_indices),
        page_count,
        max(1, OCR_MAX_WORKERS),
        processing_time_ms,
        Path(filepath).name,
    )

    texto = "\n".join(pages_text)
    return ExtractionResult(
        texto=texto,
        num_paginas=len(pages_text),
        num_caracteres=len(texto),
        engine_usada="ocr",
        raw_text_by_page=pages_text,
        raw_page_hashes=[sha256((page or "").encode("utf-8")).hexdigest() for page in pages_text],
        pages_with_ocr=pages_with_ocr,
        ocr_aplicado=True,
        ocr_fallback_successful=bool(texto.strip()),
        ocr_preprocess_aplicado=preprocess_aplicado,
        ocr_preprocess_steps=preprocess_steps,
        ocr_confidence_by_page=ocr_confidence_by_page,
        ocr_confidence=(
            round(mean(ocr_confidence_by_page), 3)
            if ocr_confidence_by_page
            else 0.0
        ),
        ocr_processing_time_ms=processing_time_ms,
    )


def _is_noise_line(line: str) -> bool:
    """Return True if line matches known extraction noise patterns."""
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.match(stripped) for pattern in _NOISE_PATTERNS)


def _is_legal_content_line(line: str) -> bool:
    """Return True for short lines that likely contain valid legal content."""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_LEGAL_CONTENT_PATTERN.search(stripped))


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
        if count >= repeated_threshold and not _is_legal_content_line(line)
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

        line_is_legal = _is_legal_content_line(line)

        # Remove long duplicate runs (same line repeated many times consecutively),
        # but preserve legal-content lines that can legitimately repeat.
        if line and line == last_kept:
            duplicate_run += 1
            if duplicate_run >= 2 and not line_is_legal:
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


def _calcular_noise_ratio(texto: str) -> float:
    """Estimate line-noise ratio in [0, 1] for one extracted page/text."""
    lines = [line.strip() for line in str(texto or "").splitlines() if line.strip()]
    if not lines:
        return 1.0
    noise_lines = sum(1 for line in lines if _is_noise_line(line))
    return round(max(0.0, min(1.0, noise_lines / len(lines))), 3)


def _garantir_metadados_por_pagina(resultado: ExtractionResult) -> None:
    """Ensure per-page extraction metadata is populated consistently."""
    if not resultado.raw_text_by_page:
        resultado.raw_text_by_page = [resultado.texto] if resultado.texto else []

    if not resultado.raw_page_hashes or len(resultado.raw_page_hashes) != len(resultado.raw_text_by_page):
        resultado.raw_page_hashes = [
            sha256((page_text or "").encode("utf-8")).hexdigest()
            for page_text in resultado.raw_text_by_page
        ]

    resultado.clean_text_by_page = [
        _limpar_texto(page_text) for page_text in resultado.raw_text_by_page
    ]
    resultado.clean_page_hashes = [
        sha256((page_text or "").encode("utf-8")).hexdigest()
        for page_text in resultado.clean_text_by_page
    ]
    resultado.quality_score_by_page = [
        _calcular_score_qualidade(page_text)
        for page_text in resultado.clean_text_by_page
    ]
    resultado.noise_ratio_by_page = [
        _calcular_noise_ratio(page_text)
        for page_text in resultado.raw_text_by_page
    ]
    if not resultado.ocr_confidence_by_page:
        resultado.ocr_confidence_by_page = [0.0 for _ in resultado.raw_text_by_page]
    elif len(resultado.ocr_confidence_by_page) != len(resultado.raw_text_by_page):
        adjusted = list(resultado.ocr_confidence_by_page[:len(resultado.raw_text_by_page)])
        adjusted.extend([0.0] * max(0, len(resultado.raw_text_by_page) - len(adjusted)))
        resultado.ocr_confidence_by_page = adjusted


def _paginas_que_precisam_ocr(resultado: ExtractionResult) -> list[int]:
    """
    Return 1-based page numbers that likely require OCR.

    Inference from task criteria: quality score is normalized to [0, 1],
    so OCR_TRIGGER_MIN_CHARS_PER_PAGE is converted to a 0-1 threshold.
    """
    if resultado.num_paginas <= 0:
        return []

    _garantir_metadados_por_pagina(resultado)
    quality_threshold = max(
        0.0,
        min(1.0, OCR_TRIGGER_MIN_CHARS_PER_PAGE / 100.0),
    )

    pages: list[int] = []
    for idx in range(min(resultado.num_paginas, len(resultado.raw_text_by_page))):
        quality = (
            resultado.quality_score_by_page[idx]
            if idx < len(resultado.quality_score_by_page)
            else 0.0
        )
        noise = (
            resultado.noise_ratio_by_page[idx]
            if idx < len(resultado.noise_ratio_by_page)
            else 1.0
        )
        clean_chars = len(
            (resultado.clean_text_by_page[idx] if idx < len(resultado.clean_text_by_page) else "").strip()
        )

        low_quality = quality < quality_threshold
        high_noise = noise > 0.8
        low_chars = clean_chars < OCR_TRIGGER_MIN_CHARS_PER_PAGE
        if low_quality or high_noise or low_chars:
            pages.append(idx + 1)

    return pages


def _mesclar_ocr_seletivo(
    base_result: ExtractionResult,
    ocr_result: ExtractionResult,
    *,
    pages_target: list[int],
) -> ExtractionResult:
    """Merge selective OCR output into baseline extraction preserving page order."""
    _garantir_metadados_por_pagina(base_result)
    if not pages_target:
        return base_result

    pages_set = {page for page in pages_target if 1 <= page <= len(base_result.raw_text_by_page)}

    for page_number in pages_set:
        idx = page_number - 1
        ocr_page_text = (
            ocr_result.raw_text_by_page[idx]
            if idx < len(ocr_result.raw_text_by_page)
            else ""
        )
        if ocr_page_text.strip():
            base_result.raw_text_by_page[idx] = ocr_page_text

        ocr_conf = (
            ocr_result.ocr_confidence_by_page[idx]
            if idx < len(ocr_result.ocr_confidence_by_page)
            else 0.0
        )
        if idx < len(base_result.ocr_confidence_by_page):
            base_result.ocr_confidence_by_page[idx] = ocr_conf

    base_result.pages_with_ocr = sorted(
        page
        for page in ocr_result.pages_with_ocr
        if page in pages_set
    )
    base_result.ocr_aplicado = True
    base_result.ocr_fallback_successful = bool(base_result.pages_with_ocr)
    base_result.ocr_preprocess_aplicado = (
        base_result.ocr_preprocess_aplicado or ocr_result.ocr_preprocess_aplicado
    )
    for step in ocr_result.ocr_preprocess_steps:
        if step not in base_result.ocr_preprocess_steps:
            base_result.ocr_preprocess_steps.append(step)
    base_result.ocr_processing_time_ms = max(0, int(base_result.ocr_processing_time_ms)) + max(
        0,
        int(ocr_result.ocr_processing_time_ms),
    )

    if base_result.pages_with_ocr:
        if len(base_result.pages_with_ocr) == len(base_result.raw_text_by_page):
            base_result.engine_usada = "ocr"
        else:
            base_result.engine_usada = f"{base_result.engine_usada}+ocr"

    base_result.texto = "\n".join(base_result.raw_text_by_page)
    base_result.num_caracteres = len(base_result.texto)
    return base_result


def _executar_ocr_compat(
    filepath: str,
    pages_only: list[int] | None = None,
) -> ExtractionResult:
    """Execute OCR keeping compatibility with monkeypatched single-arg callables in tests."""
    try:
        if pages_only is None:
            return _extrair_com_ocr(filepath)
        return _extrair_com_ocr(filepath, pages_only=pages_only)
    except TypeError as exc:
        message = str(exc)
        if pages_only is not None and "pages_only" in message and "unexpected" in message.lower():
            return _extrair_com_ocr(filepath)
        raise


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

    # Optional selective OCR pass (hybrid mode) before full OCR fallback
    if ENABLE_OCR_FALLBACK:
        try:
            paginas_ocr = _paginas_que_precisam_ocr(resultado)
            if paginas_ocr:
                logger.info(
                    "OCR seletivo: %d/%d página(s) alvo em %s",
                    len(paginas_ocr),
                    max(resultado.num_paginas, 1),
                    path.name,
                )
                resultado_ocr_seletivo = _executar_ocr_compat(
                    filepath,
                    pages_only=paginas_ocr,
                )
                resultado = _mesclar_ocr_seletivo(
                    resultado,
                    resultado_ocr_seletivo,
                    pages_target=paginas_ocr,
                )
        except Exception as e:
            logger.warning("OCR seletivo falhou para %s: %s", path.name, e)

    # Full OCR fallback for strongly low-text/scanned PDFs
    if _deve_tentar_ocr(resultado):
        logger.info("Tentando OCR completo: %s", path.name)
        try:
            resultado_ocr = _executar_ocr_compat(filepath)
            if resultado_ocr.num_caracteres > resultado.num_caracteres:
                logger.info(
                    "OCR completo melhorou extração: %d -> %d caracteres (%s)",
                    resultado.num_caracteres,
                    resultado_ocr.num_caracteres,
                    path.name,
                )
                resultado = resultado_ocr
            else:
                logger.info(
                    "OCR completo não trouxe ganho (%d chars, mantendo engine=%s).",
                    resultado_ocr.num_caracteres,
                    resultado.engine_usada,
                )
        except Exception as e:
            logger.warning("OCR completo falhou para %s: %s", path.name, e)

    # Detect scanned PDFs
    _detectar_pdf_escaneado(resultado, filepath)

    # Clean the extracted text and log reduction
    _garantir_metadados_por_pagina(resultado)

    chars_before = len(resultado.texto)
    resultado.texto = _limpar_texto(resultado.texto)
    resultado.num_caracteres = len(resultado.texto)
    resultado.clean_text_by_page = [_limpar_texto(page_text) for page_text in resultado.raw_text_by_page]
    resultado.clean_page_hashes = [
        sha256((page_text or "").encode("utf-8")).hexdigest()
        for page_text in resultado.clean_text_by_page
    ]
    resultado.quality_score_by_page = [_calcular_score_qualidade(page_text) for page_text in resultado.clean_text_by_page]
    resultado.noise_ratio_by_page = [_calcular_noise_ratio(page_text) for page_text in resultado.raw_text_by_page]
    resultado.noise_ratio = (
        round(mean(resultado.noise_ratio_by_page), 3)
        if resultado.noise_ratio_by_page
        else 1.0
    )
    if not resultado.ocr_confidence_by_page:
        resultado.ocr_confidence_by_page = [0.0 for _ in resultado.raw_text_by_page]
    resultado.ocr_confidence = (
        round(mean(resultado.ocr_confidence_by_page), 3)
        if resultado.ocr_confidence_by_page
        else 0.0
    )
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


def extrair_multiplos_documentos(filepaths: list[str]) -> list[DocumentoEntrada]:
    """
    Extract text from multiple documents (.pdf/.docx).

    Note:
        Kept in this module as a compatibility shim. Real dispatch lives in
        src.document_extractor.
    """
    from src.document_extractor import extrair_multiplos_documentos as _extrair_multiplos

    return _extrair_multiplos(filepaths)


def extrair_multiplos_pdfs(filepaths: list[str]) -> list[DocumentoEntrada]:
    """Backward-compatible alias for extrair_multiplos_documentos()."""
    return extrair_multiplos_documentos(filepaths)


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
