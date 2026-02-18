"""CLI interface for the admissibility analysis pipeline."""

import argparse
import logging
import sys
from pathlib import Path

from src.golden_baseline import gerar_baseline_dataset_ouro
from src.operational_dashboard import gerar_dashboard_operacional
from src.quality_gates import (
    evaluate_quality_gates,
    find_latest_baseline_file,
    load_baseline_payload,
    save_quality_gate_report,
)
from src.regression_alerts import (
    evaluate_regression_alerts,
    find_previous_baseline_file,
    load_baseline_payload as load_regression_baseline_payload,
    save_regression_alert_report,
)
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
        handle_pipeline_error(
            e,
            estado=pipeline.estado_atual,
            processo_id=getattr(pipeline, "_ultimo_processo_id", "default"),
            metricas=pipeline.metricas,
            contexto={
                "origem": "cli",
                "pdfs_informados": len(args.pdfs),
                "formato_saida": args.formato,
            },
        )
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


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Generate operational dashboard from execution snapshots."""
    snapshot_dir = Path(args.entrada) if args.entrada else None
    output_dir = Path(args.saida) if args.saida else None
    dashboard_json, dashboard_md, payload = gerar_dashboard_operacional(
        snapshot_dir=snapshot_dir,
        output_dir=output_dir,
    )
    print("\n📈 Dashboard operacional gerado")
    print(f"   Execuções analisadas: {payload['execucoes']['total']}")
    print(f"   JSON: {dashboard_json}")
    print(f"   Markdown: {dashboard_md}")


def cmd_baseline(args: argparse.Namespace) -> None:
    """Generate quality baseline from golden dataset."""
    golden_root = Path(args.entrada) if args.entrada else None
    output_dir = Path(args.saida) if args.saida else None
    baseline_json, baseline_md, payload = gerar_baseline_dataset_ouro(
        golden_root=golden_root,
        output_dir=output_dir,
    )
    summary = payload["summary"]["metrics"]
    print("\n📊 Baseline do dataset ouro gerada")
    print(f"   Casos analisados: {payload['summary']['num_cases']}")
    print(f"   Etapa 1 (campos críticos): {summary['etapa1_critical_fields_accuracy']:.4f}")
    print(f"   Etapa 2 (temas): {summary['etapa2_temas_count_accuracy']:.4f}")
    print(f"   Etapa 3 (decisão): {summary['etapa3_decisao_accuracy']:.4f}")
    print(f"   JSON: {baseline_json}")
    print(f"   Markdown: {baseline_md}")


def cmd_quality_gate(args: argparse.Namespace) -> None:
    """Evaluate production quality gates from baseline report."""
    baseline_path = Path(args.baseline) if args.baseline else None
    baseline_dir = Path(args.baseline_dir) if args.baseline_dir else None
    output_dir = Path(args.saida) if args.saida else None

    if baseline_path is None:
        baseline_path = find_latest_baseline_file(baseline_dir)
        if baseline_path is None:
            print("❌ Nenhum baseline encontrado. Gere primeiro com: baseline")
            sys.exit(2)

    payload = load_baseline_payload(baseline_path)
    report = evaluate_quality_gates(payload)
    report_path = save_quality_gate_report(report, output_dir=output_dir)

    print("\n🧪 Quality gate avaliado")
    print(f"   Baseline: {baseline_path}")
    print(f"   Report: {report_path}")
    for gate in report["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        print(
            f"   [{status}] {gate['metric']}: "
            f"{gate['observed']:.4f} >= {gate['threshold']:.4f}"
        )

    if not report["passed"]:
        print("❌ Gate de qualidade reprovado.")
        sys.exit(2)
    print("✅ Gate de qualidade aprovado.")


def cmd_alerts(args: argparse.Namespace) -> None:
    """Evaluate automatic regression alerts for extraction/decision quality."""
    baseline_path = Path(args.baseline) if args.baseline else None
    baseline_dir = Path(args.baseline_dir) if args.baseline_dir else None
    previous_baseline_path = Path(args.previous_baseline) if args.previous_baseline else None
    output_dir = Path(args.saida) if args.saida else None

    if baseline_path is None:
        baseline_path = find_latest_baseline_file(baseline_dir)
        if baseline_path is None:
            print("❌ Nenhum baseline encontrado. Gere primeiro com: baseline")
            sys.exit(2)

    if previous_baseline_path is None:
        previous_baseline_path = find_previous_baseline_file(
            current_baseline=baseline_path,
            baseline_dir=baseline_dir,
        )

    current_payload = load_regression_baseline_payload(baseline_path)
    previous_payload = (
        load_regression_baseline_payload(previous_baseline_path)
        if previous_baseline_path is not None
        else None
    )
    report = evaluate_regression_alerts(
        current_payload=current_payload,
        previous_payload=previous_payload,
        current_baseline_path=baseline_path,
        previous_baseline_path=previous_baseline_path,
    )
    report_path = save_regression_alert_report(report, output_dir=output_dir)

    print("\n🚨 Alertas de regressão avaliados")
    print(f"   Baseline atual: {baseline_path}")
    if previous_baseline_path is not None:
        print(f"   Baseline anterior: {previous_baseline_path}")
    else:
        print("   Baseline anterior: não disponível")
    print(f"   Report: {report_path}")

    for check in report["checks"]:
        status = "PASS" if check["passed"] else "ALERT"
        previous = (
            f"{check['previous']:.4f}"
            if isinstance(check["previous"], float)
            else "n/d"
        )
        delta = f"{check['delta']:.4f}" if isinstance(check["delta"], float) else "n/d"
        print(
            f"   [{status}] {check['metric']}: atual={check['observed']:.4f} "
            f"anterior={previous} delta={delta}"
        )

    if report["has_alerts"]:
        for alert in report["alerts"]:
            print(f"   - {alert['message']}")
        print("❌ Regressão detectada.")
        sys.exit(2)
    print("✅ Sem regressão crítica.")


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

    # dashboard
    db = subparsers.add_parser(
        "dashboard",
        help="Gerar dashboard operacional a partir de snapshots",
    )
    db.add_argument(
        "--entrada",
        default=None,
        help="Diretório de snapshots (default: outputs/)",
    )
    db.add_argument(
        "--saida",
        default=None,
        help="Diretório para salvar dashboard (default: outputs/)",
    )
    db.set_defaults(func=cmd_dashboard)

    # baseline
    bl = subparsers.add_parser(
        "baseline",
        help="Gerar baseline de qualidade no dataset ouro",
    )
    bl.add_argument(
        "--entrada",
        default=None,
        help="Diretório do dataset ouro (default: tests/fixtures/golden/)",
    )
    bl.add_argument(
        "--saida",
        default=None,
        help="Diretório para salvar baseline (default: outputs/)",
    )
    bl.set_defaults(func=cmd_baseline)

    # quality-gate
    qg = subparsers.add_parser(
        "quality-gate",
        help="Avaliar gate de qualidade a partir do baseline do dataset ouro",
    )
    qg.add_argument(
        "--baseline",
        default=None,
        help="Arquivo baseline JSON específico (default: último em --baseline-dir)",
    )
    qg.add_argument(
        "--baseline-dir",
        default=None,
        help="Diretório com baseline_dataset_ouro_*.json (default: outputs/)",
    )
    qg.add_argument(
        "--saida",
        default=None,
        help="Diretório para salvar relatório de gate (default: outputs/)",
    )
    qg.set_defaults(func=cmd_quality_gate)

    # alerts
    al = subparsers.add_parser(
        "alerts",
        help="Avaliar alertas automáticos de regressão (extração/decisão)",
    )
    al.add_argument(
        "--baseline",
        default=None,
        help="Arquivo baseline JSON atual (default: último em --baseline-dir)",
    )
    al.add_argument(
        "--baseline-dir",
        default=None,
        help="Diretório com baseline_dataset_ouro_*.json (default: outputs/)",
    )
    al.add_argument(
        "--previous-baseline",
        default=None,
        help="Arquivo baseline JSON anterior (default: autodetectado)",
    )
    al.add_argument(
        "--saida",
        default=None,
        help="Diretório para salvar relatório de alertas (default: outputs/)",
    )
    al.set_defaults(func=cmd_alerts)

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
