"""Tests for semantic minute selection fallback/composition."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from src import minuta_selector as ms


def _build_long_minuta_with_sections() -> tuple[str, str]:
    secao_i = "I-\n" + ("Contexto inicial. " * 90)
    secao_ii = "II -\n" + ("Fundamentacao extensa. " * 420)
    secao_iii = "III -\n" + ("Diante do exposto, inadmito o recurso especial. " * 35)
    texto = (
        "CABECALHO INICIAL\n\n"
        + secao_i
        + "\n\n"
        + secao_ii
        + "\n\n"
        + secao_iii
    )
    return texto, secao_iii.strip()


def _setup_minutas_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    base_dir = tmp_path / "minutas_referencia"
    textos_dir = base_dir / "textos"
    textos_dir.mkdir(parents=True, exist_ok=True)

    index_file = base_dir / "index.json"
    embeddings_file = base_dir / "embeddings.pkl"

    index_payload = [
        {
            "id": "minuta_a",
            "tipo_recurso": "recurso_especial",
            "decisao": "inadmitido",
            "sumulas": ["7/STJ"],
            "materias": ["reexame_de_prova"],
        },
        {
            "id": "minuta_b",
            "tipo_recurso": "desconhecido",
            "decisao": "inadmitido",
            "sumulas": [],
            "materias": [],
        },
    ]
    index_file.write_text(
        json.dumps(index_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    (textos_dir / "minuta_a.txt").write_text("TEXTO A", encoding="utf-8")
    (textos_dir / "minuta_b.txt").write_text("TEXTO B", encoding="utf-8")
    return index_file, textos_dir, embeddings_file


def _patch_selector_paths(
    monkeypatch,
    *,
    index_file: Path,
    textos_dir: Path,
    embeddings_file: Path,
) -> None:
    monkeypatch.setattr(ms, "INDEX_FILE", index_file)
    monkeypatch.setattr(ms, "TEXTOS_DIR", textos_dir)
    monkeypatch.setattr(ms, "EMBEDDINGS_FILE", embeddings_file)
    monkeypatch.setattr(ms, "_INDEX", None)
    monkeypatch.setattr(ms, "_EMBEDDINGS", None)
    monkeypatch.setattr(ms, "_EMBEDDING_MODEL", None)


def test_selector_falls_back_to_linear_score_when_embeddings_file_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_file, textos_dir, embeddings_file = _setup_minutas_fixture(tmp_path)
    _patch_selector_paths(
        monkeypatch,
        index_file=index_file,
        textos_dir=textos_dir,
        embeddings_file=embeddings_file,
    )

    texto = ms.selecionar_minuta_referencia(
        tipo_recurso="recurso_especial",
        sumulas=["7/STJ"],
        materias=["reexame_de_prova"],
        decisao_estimada="inadmitido",
    )
    assert texto is not None
    assert texto.startswith("TEXTO A")


def test_selector_prefers_semantic_composite_when_embeddings_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_file, textos_dir, embeddings_file = _setup_minutas_fixture(tmp_path)
    _patch_selector_paths(
        monkeypatch,
        index_file=index_file,
        textos_dir=textos_dir,
        embeddings_file=embeddings_file,
    )

    embeddings_file.write_bytes(
        pickle.dumps(
            {
                "minuta_a": [1.0, 0.0],
                "minuta_b": [0.0, 1.0],
            }
        )
    )
    monkeypatch.setattr(
        ms,
        "_obter_query_embedding",
        lambda **_kwargs: [0.0, 1.0],
    )

    texto = ms.selecionar_minuta_referencia(
        tipo_recurso="recurso_especial",
        sumulas=["7/STJ"],
        materias=["reexame_de_prova"],
        decisao_estimada="inadmitido",
    )
    assert texto is not None
    assert texto.startswith("TEXTO B")


def test_recarregar_embeddings_forces_reload_from_disk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_file, textos_dir, embeddings_file = _setup_minutas_fixture(tmp_path)
    _patch_selector_paths(
        monkeypatch,
        index_file=index_file,
        textos_dir=textos_dir,
        embeddings_file=embeddings_file,
    )

    embeddings_file.write_bytes(pickle.dumps({"minuta_a": [1.0, 0.0]}))
    first = ms._carregar_embeddings()
    assert first is not None
    assert "minuta_b" not in first

    embeddings_file.write_bytes(
        pickle.dumps(
            {
                "minuta_a": [1.0, 0.0],
                "minuta_b": [0.0, 1.0],
            }
        )
    )
    ms.recarregar_embeddings()
    second = ms._carregar_embeddings()
    assert second is not None
    assert "minuta_b" in second


def test_truncar_por_secoes_preserva_secao_iii_em_minuta_longa() -> None:
    texto_longo, secao_iii = _build_long_minuta_with_sections()

    resultado = ms._truncar_por_secoes(texto_longo, 6000)

    assert len(texto_longo) > 6000
    assert len(resultado) <= 6000
    assert secao_iii in resultado


def test_selector_preserva_secao_iii_quando_minuta_longa_e_truncada(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_file, textos_dir, embeddings_file = _setup_minutas_fixture(tmp_path)
    _patch_selector_paths(
        monkeypatch,
        index_file=index_file,
        textos_dir=textos_dir,
        embeddings_file=embeddings_file,
    )

    texto_longo, secao_iii = _build_long_minuta_with_sections()
    (textos_dir / "minuta_a.txt").write_text(texto_longo, encoding="utf-8")
    monkeypatch.setattr(ms, "MAX_CHARS_REFERENCIA", 6000)

    texto = ms.selecionar_minuta_referencia(
        tipo_recurso="recurso_especial",
        sumulas=["7/STJ"],
        materias=["reexame_de_prova"],
        decisao_estimada="inadmitido",
    )
    assert texto is not None
    assert len(texto_longo) > 6000
    assert len(texto) <= 6000
    assert secao_iii in texto
