#!/usr/bin/env python3
"""Gera embeddings semânticos para minutas de referência."""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEXTOS_DIR = BASE_DIR / "minutas_referencia" / "textos"
EMBEDDINGS_FILE = BASE_DIR / "minutas_referencia" / "embeddings.pkl"
MODEL_NAME_DEFAULT = "paraphrase-multilingual-MiniLM-L12-v2"


def _iter_chunks(items: list[Path], chunk_size: int) -> list[list[Path]]:
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def gerar_embeddings(
    *,
    textos_dir: Path,
    output_path: Path,
    model_name: str,
    batch_size: int,
) -> int:
    """Indexa todos os .txt de minutas em um pickle id -> vector."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Dependência ausente: sentence-transformers. "
            "Instale com `pip install -r requirements.txt`."
        ) from exc

    txt_files = sorted(textos_dir.glob("*.txt"))
    if not txt_files:
        raise RuntimeError(f"Nenhum .txt encontrado em {textos_dir}")

    model = SentenceTransformer(model_name)
    embeddings: dict[str, list[float]] = {}

    for chunk in _iter_chunks(txt_files, max(1, batch_size)):
        chunk_texts = [p.read_text(encoding="utf-8", errors="ignore") for p in chunk]
        vectors = model.encode(
            chunk_texts,
            batch_size=max(1, batch_size),
            show_progress_bar=False,
        )
        for file_path, vector in zip(chunk, vectors):
            raw = vector.tolist() if hasattr(vector, "tolist") else vector
            embeddings[file_path.stem] = [float(v) for v in raw]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pickle.dumps(embeddings))
    return len(embeddings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Indexa embeddings de minutas de referência.")
    parser.add_argument(
        "--textos-dir",
        default=str(TEXTOS_DIR),
        help="Diretório com arquivos .txt das minutas.",
    )
    parser.add_argument(
        "--output",
        default=str(EMBEDDINGS_FILE),
        help="Arquivo de saída .pkl (dict: id -> vector).",
    )
    parser.add_argument(
        "--model",
        default=MODEL_NAME_DEFAULT,
        help="Modelo sentence-transformers a ser usado.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Tamanho de lote para inferência de embeddings.",
    )
    args = parser.parse_args()

    textos_dir = Path(args.textos_dir)
    output_path = Path(args.output)
    try:
        total = gerar_embeddings(
            textos_dir=textos_dir,
            output_path=output_path,
            model_name=args.model,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(f"❌ Falha ao indexar embeddings: {exc}")
        return 1

    print(f"✅ Embeddings gerados: {total}")
    print(f"📁 Arquivo: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
