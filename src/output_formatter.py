"""Output formatter: markdown formatting, file saving, and audit reports."""

import logging
import re
from datetime import datetime
from pathlib import Path

try:
    from docx import Document
    from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
except ImportError:  # pragma: no cover - covered by runtime guard
    Document = None  # type: ignore[assignment]
    WD_PARAGRAPH_ALIGNMENT = None  # type: ignore[assignment]
    qn = None  # type: ignore[assignment]
    Cm = None  # type: ignore[assignment]
    Pt = None  # type: ignore[assignment]

from src.config import OUTPUTS_DIR
from src.models import EstadoPipeline, ResultadoEtapa3

logger = logging.getLogger("copilot_juridico")

INLINE_MARKDOWN_RE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)")


def _resolver_output_dir(output_dir: Path | None = None) -> Path:
    """Resolve and ensure output directory exists."""
    target_dir = output_dir or OUTPUTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


# --- 5.3.1 / 5.3.2 Format draft ---


def formatar_minuta(resultado: ResultadoEtapa3, estado: EstadoPipeline | None = None) -> str:
    """Format the admissibility draft with proper markdown styling."""
    minuta = resultado.minuta_completa

    # 5.3.2 — Bold mandatory fields
    if estado and estado.resultado_etapa1:
        r1 = estado.resultado_etapa1
        if r1.recorrente:
            minuta = minuta.replace(r1.recorrente, f"**{r1.recorrente}**")
        if r1.recorrido:
            minuta = minuta.replace(r1.recorrido, f"**{r1.recorrido}**")
        if r1.especie_recurso:
            minuta = minuta.replace(r1.especie_recurso, f"**{r1.especie_recurso}**")

    # Bold the decision keywords
    for pattern, repl in [
        (r"\b(ADMITO)\b", r"**\1**"),
        (r"\b(INADMITO)\b", r"**\1**"),
    ]:
        minuta = re.sub(pattern, repl, minuta)

    # Avoid double-bold
    minuta = minuta.replace("****", "**")

    return minuta


# --- 5.3.3 Save draft ---


def salvar_minuta(
    minuta_formatada: str,
    numero_processo: str = "sem_numero",
    output_dir: Path | None = None,
) -> Path:
    """Save formatted draft to markdown file in outputs/ directory."""
    target_dir = _resolver_output_dir(output_dir)

    safe_proc = re.sub(r"[^\w\-.]", "_", numero_processo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"minuta_{safe_proc}_{timestamp}.md"
    filepath = target_dir / filename

    filepath.write_text(minuta_formatada, encoding="utf-8")
    logger.info("📄 Minuta salva em: %s", filepath)

    return filepath


def _add_markdown_runs(paragraph: "object", text: str) -> None:
    """Add simple markdown inline formatting (bold/italic) to a DOCX paragraph."""
    for token in INLINE_MARKDOWN_RE.split(text):
        if not token:
            continue
        is_bold = (
            token.startswith("**") and token.endswith("**")
        ) or (token.startswith("__") and token.endswith("__"))
        is_italic = (
            token.startswith("*") and token.endswith("*")
        ) or (token.startswith("_") and token.endswith("_"))

        clean = token
        if is_bold or is_italic:
            clean = token[2:-2] if len(token) > 4 and token[:2] in {"**", "__"} else token[1:-1]

        run = paragraph.add_run(clean)
        run.bold = is_bold
        run.italic = is_italic
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)


def _configure_docx_tjpr(document: "object") -> None:
    """Apply TJPR-compatible baseline formatting to DOCX document."""
    section = document.sections[0]
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(3.0)
    section.bottom_margin = Cm(2.0)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(12)
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal_style.paragraph_format.line_spacing = 1.5
    normal_style.paragraph_format.space_before = Pt(0)
    normal_style.paragraph_format.space_after = Pt(0)


def _add_paragraph_safe(document: "object", style: str | None = None) -> "object":
    """Add paragraph with optional style fallback when style is unavailable."""
    if style:
        try:
            return document.add_paragraph(style=style)
        except KeyError:
            logger.debug("Style '%s' não encontrado no template DOCX. Usando estilo padrão.", style)
    return document.add_paragraph()


def _apply_tjpr_paragraph_format(paragraph: "object", justify: bool = True) -> None:
    """Apply paragraph formatting rules used in TJPR-compatible output."""
    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    if justify:
        paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY


def salvar_minuta_docx(
    minuta_markdown: str,
    numero_processo: str = "sem_numero",
    output_dir: Path | None = None,
) -> Path:
    """Convert markdown draft to DOCX and apply TJPR-compatible formatting."""
    if Document is None:
        raise RuntimeError(
            "Dependência opcional 'python-docx' não instalada. "
            "Adicione no ambiente para usar --formato docx."
        )

    target_dir = _resolver_output_dir(output_dir)
    safe_proc = re.sub(r"[^\w\-.]", "_", numero_processo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = target_dir / f"minuta_{safe_proc}_{timestamp}.docx"

    document = Document()
    _configure_docx_tjpr(document)

    in_code_block = False
    for raw_line in minuta_markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if not stripped:
            document.add_paragraph("")
            continue

        if in_code_block:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(line)
            run.font.name = "Courier New"
            run.font.size = Pt(10)
            paragraph.paragraph_format.line_spacing = 1.0
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            text = heading_match.group(2).strip()
            paragraph = document.add_heading("", level=level)
            _apply_tjpr_paragraph_format(paragraph, justify=False)
            _add_markdown_runs(paragraph, text)
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            paragraph = _add_paragraph_safe(document, style="List Bullet")
            _apply_tjpr_paragraph_format(paragraph)
            _add_markdown_runs(paragraph, bullet_match.group(1))
            continue

        numbered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered_match:
            paragraph = _add_paragraph_safe(document, style="List Number")
            _apply_tjpr_paragraph_format(paragraph)
            _add_markdown_runs(paragraph, numbered_match.group(1))
            continue

        paragraph = document.add_paragraph()
        _apply_tjpr_paragraph_format(paragraph)
        _add_markdown_runs(paragraph, stripped)

    document.save(filepath)
    logger.info("📄 Minuta DOCX salva em: %s", filepath)
    return filepath


# --- 5.3.4 Audit report ---


def gerar_relatorio_auditoria(
    estado: EstadoPipeline,
    alertas: list[str] | None = None,
    numero_processo: str = "sem_numero",
    output_dir: Path | None = None,
) -> Path:
    """Generate audit report alongside the draft."""
    target_dir = _resolver_output_dir(output_dir)

    safe_proc = re.sub(r"[^\w\-.]", "_", numero_processo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = target_dir / f"auditoria_{safe_proc}_{timestamp}.md"

    meta = estado.metadata
    r2 = estado.resultado_etapa2
    r3 = estado.resultado_etapa3

    lines = [
        "# Relatório de Auditoria",
        "",
        f"**Processo:** {numero_processo}",
        f"**Data:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        "",
        "## Tokens Utilizados",
        "",
        "| Métrica | Valor |",
        "|---------|-------|",
        f"| Modelo | {meta.modelo_usado or 'N/A'} |",
        f"| Prompt tokens | {meta.prompt_tokens} |",
        f"| Completion tokens | {meta.completion_tokens} |",
        f"| **Total tokens** | **{meta.total_tokens}** |",
        "",
        "## Modelos Utilizados",
        "",
        "| Etapa | Modelo |",
        "|-------|--------|",
        f"| Etapa 1 (Análise Recursal) | {meta.modelos_utilizados.get('Etapa 1', 'N/A')} |",
        f"| Etapa 2 (Análise Direito) | {meta.modelos_utilizados.get('Etapa 2', 'N/A')} |",
        f"| Etapa 3 (Geração Minuta) | {meta.modelos_utilizados.get('Etapa 3', 'N/A')} |",
        "",
        "## Pipeline",
        "",
        "| Etapa | Status |",
        "|-------|--------|",
        f"| Etapa 1 | {'✅' if estado.resultado_etapa1 else '❌'} |",
        f"| Etapa 2 | {'✅ ' + str(len(r2.temas)) + ' temas' if r2 else '❌'} |",
        f"| Etapa 3 | {'✅ ' + (r3.decisao.value if r3 and r3.decisao else 'sem decisão') if r3 else '❌'} |",
        "",
    ]

    if meta.inicio:
        lines.append(f"**Início:** {meta.inicio.isoformat()}")
    if meta.fim:
        lines.append(f"**Fim:** {meta.fim.isoformat()}")

    if alertas:
        lines.extend(["", "## Alertas de Validação", ""])
        for alerta in alertas:
            lines.append(f"- ⚠️ {alerta}")

    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info("📊 Relatório de auditoria salvo em: %s", filepath)

    return filepath
