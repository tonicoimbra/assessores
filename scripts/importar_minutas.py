#!/usr/bin/env python3
"""
Script de importação das minutas de referência (gold standard).

Processa os PDFs em minutas_referencia/pdfs/ e gera:
  - minutas_referencia/index.json    → metadados de cada minuta
  - minutas_referencia/textos/       → textos extraídos (.txt)

Uso:
  python3 scripts/importar_minutas.py
  python3 scripts/importar_minutas.py --limite 10  # testar com 10
  python3 scripts/importar_minutas.py --reprocessar  # forçar reprocessamento
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Caminhos ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
PDFS_DIR    = BASE_DIR / "minutas_referencia" / "pdfs"
TEXTOS_DIR  = BASE_DIR / "minutas_referencia" / "textos"
INDEX_FILE  = BASE_DIR / "minutas_referencia" / "index.json"

# ── Padrões de extração ──────────────────────────────────────────────────────

# Tipos de recurso
RE_RESP  = re.compile(r"recurso especial", re.I)
RE_RE    = re.compile(r"recurso extraordin", re.I)
RE_ARESP = re.compile(r"agravo em recurso especial|aresp", re.I)
RE_ARE   = re.compile(r"agravo em recurso extraordin|are\b", re.I)

# Decisão final
RE_INADMITIDO = re.compile(
    r"\b(inadmit|n[ãa]o admito|n[ãa]o conhec|obst[ao]|deserto|intempestiv|prejudicad)",
    re.I
)
RE_ADMITIDO = re.compile(
    r"\b(admito|conhec[eo]|determino o processamento|remetam-se|remeta-se)\b",
    re.I
)
RE_DILIGENCIA = re.compile(
    r"\b(dilig[eê]ncias|intime-se|intime a parte|providencie|comprove|comprova[çc][ãa]o)\b",
    re.I
)

# Súmulas STJ/STF
RE_SUMULA = re.compile(
    r"s[úu]mula[s]?\s+n?[oº°]?\s*(\d+)(?:/([A-Z]+))?",
    re.I
)

# Matérias comuns
MATERIAS_KEYWORDS: dict[str, list[str]] = {
    "reexame_de_prova":          ["reexame de prova", "súmula 7", "sumula 7", "matéria fática", "materia fatica"],
    "prequestionamento":         ["prequestionamento", "prequestionado", "súmula 282", "súmula 356", "sumula 282", "sumula 356"],
    "deficiencia_fundamentacao": ["deficiência de fundamentação", "deficiencia de fundamentacao", "súmula 284", "sumula 284"],
    "fundamentos_inatacados":    ["fundamentos inatacados", "súmula 283", "sumula 283"],
    "duplo_fundamento":          ["duplo fundamento", "súmula 126", "sumula 126"],
    "preparo_deserção":          ["deserção", "deserto", "preparo", "custas"],
    "tempestividade":            ["tempestividade", "intempestivo", "intempestividade", "prazo recursal"],
    "interpretacao_contrato":    ["cláusula contratual", "interpretação contratual", "súmula 5", "sumula 5"],
    "acidente_transito":         ["acidente de trânsito", "acidente de transito", "dpvat", "indenização por danos"],
    "responsabilidade_civil":    ["responsabilidade civil", "danos morais", "dano moral", "danos materiais"],
    "direito_consumidor":        ["código de defesa do consumidor", "cdc", "relação de consumo"],
    "direito_trabalhista":       ["trabalhista", "contrato de trabalho", "rescisão"],
    "direito_previdenciario":    ["previdenciário", "benefício previdenciário", "inss", "aposentadoria"],
    "familia_sucessoes":         ["divórcio", "alimentos", "guarda", "inventário", "herança"],
    "execucao_fiscal":           ["execução fiscal", "certidão de dívida ativa", "cda", "fazenda"],
}

# Número do processo
RE_PROCESSO = re.compile(
    r"(\d{7}-\d{2}\.\d{4}\.\d{1,2}\.\d{2}\.\d{4})",
)

# Câmara/Órgão
RE_CAMARA = re.compile(
    r"(\d+[aª°]?\s*(?:Câmara|Turma|Seção)[^\n,]{0,40})",
    re.I
)


# ── Funções de extração ──────────────────────────────────────────────────────

def extrair_texto_pdf(pdf_path: Path) -> str:
    """Extrai texto via pdftotext (mais rápido e confiável)."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        return f"[ERRO AO EXTRAIR: {e}]"


def detectar_tipo_recurso(texto: str) -> str:
    """Detecta tipo de recurso mencionado na decisão."""
    if RE_ARE.search(texto):
        return "agravo_recurso_extraordinario"
    if RE_ARESP.search(texto):
        return "agravo_recurso_especial"
    if RE_RE.search(texto):
        return "recurso_extraordinario"
    if RE_RESP.search(texto):
        return "recurso_especial"
    return "desconhecido"


def detectar_decisao(texto: str) -> str:
    """Detecta tipo de decisão: inadmitido, admitido, diligencia, desconhecido."""
    # Diligência tem prioridade (ainda não é decisão final)
    if RE_DILIGENCIA.search(texto):
        return "diligencia"
    if RE_INADMITIDO.search(texto):
        return "inadmitido"
    if RE_ADMITIDO.search(texto):
        return "admitido"
    return "desconhecido"


def extrair_sumulas(texto: str) -> list[str]:
    """Extrai todas as súmulas mencionadas."""
    sumulas = set()
    for m in RE_SUMULA.finditer(texto):
        num    = m.group(1)
        orgao  = m.group(2) or ""
        label  = f"{num}/{orgao.upper()}" if orgao else num
        sumulas.add(label)
    return sorted(sumulas)


def extrair_materias(texto: str) -> list[str]:
    """Detecta matérias baseado em palavras-chave."""
    texto_lower = texto.lower()
    encontradas = []
    for materia, keywords in MATERIAS_KEYWORDS.items():
        if any(kw in texto_lower for kw in keywords):
            encontradas.append(materia)
    return encontradas


def extrair_numero_processo(texto: str) -> str:
    """Extrai número do processo no formato CNJ."""
    m = RE_PROCESSO.search(texto)
    return m.group(1) if m else ""


def extrair_camara(texto: str) -> str:
    """Extrai câmara/turma/seção julgadora."""
    m = RE_CAMARA.search(texto)
    return m.group(1).strip() if m else ""


def processar_pdf(pdf_path: Path, textos_dir: Path) -> dict:
    """Processa um PDF e retorna os metadados extraídos."""
    txt_path = textos_dir / (pdf_path.stem + ".txt")

    # Reusar texto já extraído
    if txt_path.exists():
        texto = txt_path.read_text(encoding="utf-8")
    else:
        texto = extrair_texto_pdf(pdf_path)
        txt_path.write_text(texto, encoding="utf-8")

    return {
        "id":              pdf_path.stem,
        "arquivo":         pdf_path.name,
        "tipo_recurso":    detectar_tipo_recurso(texto),
        "decisao":         detectar_decisao(texto),
        "sumulas":         extrair_sumulas(texto),
        "materias":        extrair_materias(texto),
        "numero_processo": extrair_numero_processo(texto),
        "camara":          extrair_camara(texto),
        "chars":           len(texto),
        "importado_em":    datetime.now().isoformat(),
        "avaliacao":       "pendente",  # será atualizado via feedback
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Importa minutas de referência dos PDFs")
    parser.add_argument("--limite",      type=int, default=0,     help="Processar somente N arquivos (0 = todos)")
    parser.add_argument("--reprocessar", action="store_true",     help="Forçar reprocessamento mesmo se já existir texto")
    args = parser.parse_args()

    TEXTOS_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(PDFS_DIR.glob("*.pdf"))
    if not pdfs:
        print("❌ Nenhum PDF encontrado em", PDFS_DIR)
        sys.exit(1)

    if args.limite:
        pdfs = pdfs[:args.limite]

    # Se reprocessar, apagar textos existentes
    if args.reprocessar:
        for f in TEXTOS_DIR.glob("*.txt"):
            f.unlink()

    # Carregar índice existente para não perder avaliações manuais
    existente: dict[str, dict] = {}
    if INDEX_FILE.exists():
        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            existente = {item["id"]: item for item in data}
        except Exception:
            pass

    resultados: list[dict] = []
    erros: list[str] = []

    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i:3d}/{len(pdfs)}] {pdf.name}", end=" ... ", flush=True)
        try:
            meta = processar_pdf(pdf, TEXTOS_DIR)

            # Preservar avaliação humana se já existir
            if meta["id"] in existente:
                antigo = existente[meta["id"]]
                meta["avaliacao"]       = antigo.get("avaliacao", "pendente")
                meta["notas_revisao"]   = antigo.get("notas_revisao", "")
                meta["assessor_revisor"]= antigo.get("assessor_revisor", "")

            resultados.append(meta)
            print(f"✅ {meta['tipo_recurso']} | {meta['decisao']} | súmulas={meta['sumulas']}")
        except Exception as e:
            erros.append(f"{pdf.name}: {e}")
            print(f"❌ ERRO: {e}")

    # Salvar índice
    INDEX_FILE.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Relatório
    total      = len(resultados)
    inadmitidos= sum(1 for r in resultados if r["decisao"] == "inadmitido")
    admitidos  = sum(1 for r in resultados if r["decisao"] == "admitido")
    diligencias= sum(1 for r in resultados if r["decisao"] == "diligencia")
    desconhec  = sum(1 for r in resultados if r["decisao"] == "desconhecido")

    print("\n" + "="*60)
    print(f"✅ Importação concluída: {total} minutas")
    print(f"   Inadmitidos  : {inadmitidos}")
    print(f"   Admitidos    : {admitidos}")
    print(f"   Diligências  : {diligencias}")
    print(f"   Desconhecidos: {desconhec}")
    if erros:
        print(f"\n⚠️  {len(erros)} erros:")
        for e in erros:
            print(f"   {e}")
    print(f"\n📁 Índice salvo em: {INDEX_FILE}")
    print(f"📁 Textos em: {TEXTOS_DIR}")


if __name__ == "__main__":
    main()
