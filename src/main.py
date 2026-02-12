"""CLI interface for the admissibility analysis pipeline."""

import argparse
import logging
import sys
from pathlib import Path

from src.config import (
    OPENAI_MODEL,
    TEMPERATURE,
    setup_logging,
    validate_api_key,
)
from src.pipeline import PipelineAdmissibilidade
from src.state_manager import limpar_checkpoints, listar_checkpoints, restaurar_estado


def _progress_terminal(msg: str, step: int, total: int) -> None:
    """Terminal progress display."""
    bar_len = 20
    filled = int(bar_len * step / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {step}/{total} {msg}", end="", flush=True)
    if step == total:
        print()


def cmd_processar(args: argparse.Namespace) -> None:
    """Execute the analysis pipeline."""
    validate_api_key()

    # Validate PDFs exist
    for pdf in args.pdfs:
        if not Path(pdf).exists():
            print(f"❌ Arquivo não encontrado: {pdf}")
            sys.exit(1)

    pipeline = PipelineAdmissibilidade(
        modelo=args.modelo,
        temperatura=args.temperatura,
        saida_dir=args.saida,
        formato_saida=args.formato,
        progress=_progress_terminal,
    )

    print(f"\n🔄 Iniciando análise de admissibilidade...")
    print(f"   Modelo: {args.modelo}")
    print(f"   Formato: {args.formato}")
    print(f"   PDFs: {len(args.pdfs)} arquivo(s)")
    print()

    try:
        resultado = pipeline.executar(
            pdfs=args.pdfs,
            continuar=args.continuar,
        )

        # 6.2.7 — Final summary
        metricas = pipeline.metricas
        decisao = resultado.decisao.value if resultado.decisao else "N/A"
        print("\n" + "=" * 50)
        print("  📋 RESULTADO DA ANÁLISE")
        print("=" * 50)
        print(f"  Decisão:     {decisao}")
        print(f"  Tokens:      {metricas.get('tokens_totais', 0):,}")
        print(f"  Custo est.:  ${metricas.get('custo_estimado_usd', 0):.4f}")
        print(f"  Tempo:       {metricas.get('tempo_total', 0):.1f}s")
        print(f"  Arquivo:     {metricas.get('arquivo_minuta', 'N/A')}")
        print("=" * 50)

    except KeyboardInterrupt:
        print("\n\n⚠️  Processamento interrompido. Estado salvo no checkpoint.")
        sys.exit(130)
    except Exception as e:
        from src.pipeline import get_friendly_error, handle_pipeline_error, _setup_file_logging
        _setup_file_logging()
        handle_pipeline_error(e)
        print(f"\n{get_friendly_error(e)}")
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Show processing status."""
    checkpoints = listar_checkpoints()
    if not checkpoints:
        print("ℹ️  Nenhum checkpoint encontrado.")
        return

    print(f"\n📋 Checkpoints disponíveis: {len(checkpoints)}\n")
    for cp in checkpoints:
        estado = restaurar_estado(cp["arquivo"])
        etapas = ""
        if estado:
            e1 = "✅" if estado.resultado_etapa1 else "⬜"
            e2 = "✅" if estado.resultado_etapa2 else "⬜"
            e3 = "✅" if estado.resultado_etapa3 else "⬜"
            etapas = f"E1:{e1} E2:{e2} E3:{e3}"
        print(f"  • {cp['processo']:20s} | {cp['modificado']} | {etapas}")


def cmd_limpar(args: argparse.Namespace) -> None:
    """Clear checkpoints."""
    removed = limpar_checkpoints()
    print(f"🗑️  {removed} checkpoint(s) removido(s).")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="copilot-juridico",
        description="Agente de Admissibilidade Recursal — TJPR",
    )
    subparsers = parser.add_subparsers(dest="comando", help="Comandos disponíveis")

    # processar
    proc = subparsers.add_parser("processar", help="Processar PDFs de recurso/acórdão")
    proc.add_argument(
        "pdfs",
        nargs="+",
        help="Caminhos para os arquivos PDF",
    )
    proc.add_argument(
        "--modelo",
        default=OPENAI_MODEL,
        help=f"Modelo OpenAI (default: {OPENAI_MODEL})",
    )
    proc.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURE,
        help=f"Temperatura do LLM (default: {TEMPERATURE})",
    )
    proc.add_argument(
        "--saida",
        default=None,
        help="Diretório de saída customizado",
    )
    proc.add_argument(
        "--formato",
        choices=["md", "docx"],
        default="md",
        help="Formato do arquivo da minuta (default: md)",
    )
    proc.add_argument(
        "--continuar",
        action="store_true",
        help="Retomar processamento do último checkpoint",
    )
    proc.add_argument(
        "--verbose",
        action="store_true",
        help="Logging detalhado (DEBUG)",
    )
    proc.set_defaults(func=cmd_processar)

    # status
    st = subparsers.add_parser("status", help="Mostrar status do processamento")
    st.set_defaults(func=cmd_status)

    # limpar
    lp = subparsers.add_parser("limpar", help="Limpar checkpoints")
    lp.set_defaults(func=cmd_limpar)

    return parser


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.comando:
        parser.print_help()
        sys.exit(0)

    # 6.2.5 — Verbose logging
    if hasattr(args, "verbose") and args.verbose:
        logger = logging.getLogger("assessor_ai")
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG)

    args.func(args)


if __name__ == "__main__":
    setup_logging()
    main()
