"""Deterministic property-based tests for parsers and normalization helpers."""

from __future__ import annotations

import random
import re
import string

from src.etapa1 import (
    _normalizar_evidencia as _normalizar_evidencia_etapa1,
    _normalizar_int as _normalizar_int_etapa1,
)
from src.etapa2 import (
    _normalizar_evidencia as _normalizar_evidencia_etapa2,
    _normalizar_int as _normalizar_int_etapa2,
    _normalizar_texto_busca,
)
from src.pdf_processor import _parse_osd_rotation


def _rng(seed: int = 20260218) -> random.Random:
    """Return deterministic pseudo-random generator."""
    return random.Random(seed)


def _random_text(rng: random.Random, length: int) -> str:
    charset = string.ascii_letters + string.digits + " \t\n-_/.,:;!?()[]{}áéíóúãõçÁÉÍÓÚÃÕÇ"
    return "".join(rng.choice(charset) for _ in range(length))


def test_property_normalizar_int_roundtrip_for_integer_like_values() -> None:
    rng = _rng()
    for _ in range(250):
        value = rng.randint(-1_000_000, 1_000_000)
        text_value = f"   {value}   "
        assert _normalizar_int_etapa1(value) == value
        assert _normalizar_int_etapa2(value) == value
        assert _normalizar_int_etapa1(text_value) == value
        assert _normalizar_int_etapa2(text_value) == value


def test_property_normalizar_int_rejects_non_integer_strings() -> None:
    rng = _rng(123)
    invalid_samples = ["", "abc", "12.4", "3,14", "1e3", "true", "none"]
    for _ in range(250):
        token = "".join(rng.choice(string.ascii_letters + ".,/") for _ in range(6))
        invalid_samples.append(token)

    for sample in invalid_samples:
        assert _normalizar_int_etapa1(sample) is None
        assert _normalizar_int_etapa2(sample) is None


def test_property_normalizar_evidencia_output_constraints_and_idempotence() -> None:
    rng = _rng(55)
    candidates = [
        None,
        "",
        "texto",
        "  12  ",
        "-4",
        "0",
        0,
        1,
        99,
        -1,
        {},
        [],
    ]

    for _ in range(220):
        payload = {
            "citacao_literal": rng.choice(candidates),
            "ancora": rng.choice(candidates),
            "pagina": rng.choice(candidates),
            "offset_inicio": rng.choice(candidates),
        }

        for normalizer in (_normalizar_evidencia_etapa1, _normalizar_evidencia_etapa2):
            normalized = normalizer(payload)
            if normalized is None:
                continue

            assert normalized.pagina is None or normalized.pagina > 0
            assert normalized.offset_inicio is None or normalized.offset_inicio >= 0
            assert normalized.citacao_literal == normalized.citacao_literal.strip()
            assert normalized.ancora == normalized.ancora.strip()

            # Idempotence: normalizing normalized payload keeps same semantic output.
            restored = normalizer(normalized.model_dump(mode="json"))
            assert restored is not None
            assert restored.model_dump(mode="json") == normalized.model_dump(mode="json")


def test_property_normalizar_evidencia_non_dict_returns_none() -> None:
    samples = [None, "", "x", 1, 3.14, [], (), {"nested": []}]
    for sample in samples:
        if isinstance(sample, dict) and "citacao_literal" not in sample:
            assert _normalizar_evidencia_etapa1(sample) is None
            assert _normalizar_evidencia_etapa2(sample) is None
            continue
        if not isinstance(sample, dict):
            assert _normalizar_evidencia_etapa1(sample) is None
            assert _normalizar_evidencia_etapa2(sample) is None


def test_property_normalizar_texto_busca_is_idempotent_and_sanitized() -> None:
    rng = _rng(999)
    for _ in range(250):
        raw = _random_text(rng, rng.randint(0, 90))
        normalized = _normalizar_texto_busca(raw)
        assert normalized == _normalizar_texto_busca(normalized)
        assert normalized == normalized.lower()
        assert normalized == normalized.strip()
        assert "  " not in normalized
        assert re.fullmatch(r"[a-z0-9 ]*", normalized) is not None


def test_property_normalizar_texto_busca_is_accent_insensitive() -> None:
    pairs = [
        ("ação revisional", "acao revisional"),
        ("CÂMARA CÍVEL", "CAMARA CIVEL"),
        ("Súmula nº 7 do STJ", "Sumula n 7 do STJ"),
        ("JURISDIÇÃO e ÓBICE", "JURISDICAO e OBICE"),
    ]
    for accented, plain in pairs:
        assert _normalizar_texto_busca(accented) == _normalizar_texto_busca(plain)


def test_property_parse_osd_rotation_accepts_only_supported_angles() -> None:
    rng = _rng(321)
    for _ in range(260):
        angle = rng.randint(-360, 360)
        osd_text = f"Page number: 0\nRoTaTe: {angle}\nOrientation confidence: 12.3"
        expected = angle if angle in {0, 90, 180, 270} else 0
        assert _parse_osd_rotation(osd_text) == expected


def test_property_parse_osd_rotation_defaults_to_zero_without_rotation_field() -> None:
    rng = _rng(222)
    for _ in range(80):
        text = _random_text(rng, rng.randint(0, 120))
        if "rotate:" in text.lower():
            continue
        assert _parse_osd_rotation(text) == 0
