"""Tests for dynamic prompt composition."""

import pytest

from src.prompt_loader import (
    PromptConfigurationError,
    build_messages,
    ensure_prompt_contract,
    get_pipeline_prompt_signature,
    get_prompt_signature,
    validate_prompt_contract,
)


def test_build_messages_etapa1_modular() -> None:
    msgs = build_messages(stage="etapa1", user_text="teste etapa 1")
    roles = [m["role"] for m in msgs]
    assert roles[0] == "system"
    assert "developer" in roles
    assert roles[-1] == "user"


def test_build_messages_with_forced_references() -> None:
    msgs = build_messages(
        stage="etapa2",
        user_text="teste etapa 2",
        include_references=True,
    )
    dev_msgs = [m for m in msgs if m["role"] == "developer"]
    assert len(dev_msgs) >= 2  # etapa + referencias


def test_build_messages_legacy_compatibility() -> None:
    legacy = "PROMPT LEGADO COMPLETO"
    msgs = build_messages(
        stage="etapa1",
        user_text="entrada",
        legacy_system_prompt=legacy,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == legacy
    assert msgs[1]["role"] == "user"


def test_get_prompt_signature_stage_has_hash() -> None:
    signature = get_prompt_signature(stage="etapa1")
    assert signature["prompt_profile"]
    assert signature["prompt_version"]
    assert len(signature["prompt_hash_sha256"]) == 64


def test_get_prompt_signature_legacy_extracts_version() -> None:
    legacy = "# Prompt\n> **Versão:** 9.9.9\n\nConteúdo."
    signature = get_prompt_signature(stage="etapa1", legacy_system_prompt=legacy)
    assert signature["prompt_profile"] == "legacy-explicit"
    assert signature["prompt_version"] == "9.9.9"
    assert len(signature["prompt_hash_sha256"]) == 64


def test_get_pipeline_prompt_signature_has_hash() -> None:
    signature = get_pipeline_prompt_signature()
    assert signature["prompt_profile"]
    assert signature["prompt_version"]
    assert len(signature["prompt_hash_sha256"]) == 64


def test_build_messages_raises_when_prompt_missing_and_minimal_disabled(monkeypatch) -> None:
    monkeypatch.setattr("src.prompt_loader.ALLOW_MINIMAL_PROMPT_FALLBACK", False)
    monkeypatch.setattr("src.prompt_loader.get_prompt_component", lambda component: "")
    monkeypatch.setattr("src.prompt_loader._load_legacy_system_prompt", lambda: "")
    with pytest.raises(PromptConfigurationError):
        build_messages(stage="etapa1", user_text="entrada")


def test_build_messages_allows_minimal_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr("src.prompt_loader.ALLOW_MINIMAL_PROMPT_FALLBACK", True)
    monkeypatch.setattr("src.prompt_loader.get_prompt_component", lambda component: "")
    monkeypatch.setattr("src.prompt_loader._load_legacy_system_prompt", lambda: "")
    msgs = build_messages(stage="etapa1", user_text="entrada")
    assert msgs[0]["role"] == "system"
    assert "Não invente informações" in msgs[0]["content"]


def test_validate_prompt_contract_modular_ok() -> None:
    assert validate_prompt_contract() == []


def test_validate_prompt_contract_detects_missing_component(monkeypatch) -> None:
    def _fake_component(name: str) -> str:
        if name == "dev_etapa2":
            return ""
        return "conteúdo mínimo com marcador"

    monkeypatch.setattr("src.prompt_loader.get_prompt_component", _fake_component)
    errors = validate_prompt_contract()
    assert any("dev_etapa2" in e for e in errors)


def test_ensure_prompt_contract_raises_in_strict_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.prompt_loader.validate_prompt_contract",
        lambda legacy_system_prompt=None: ["erro de contrato"],
    )
    with pytest.raises(PromptConfigurationError):
        ensure_prompt_contract(strict=True)


def test_build_messages_uses_legacy_strategy(monkeypatch) -> None:
    monkeypatch.setattr("src.prompt_loader.PROMPT_STRATEGY", "legacy")
    monkeypatch.setattr(
        "src.prompt_loader._load_legacy_system_prompt",
        lambda: "# Prompt\nEtapa 1\nEtapa 2\nEtapa 3",
    )
    msgs = build_messages(stage="etapa2", user_text="entrada")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Etapa 1" in msgs[0]["content"]


def test_validate_prompt_contract_legacy_strategy_missing_file(monkeypatch) -> None:
    monkeypatch.setattr("src.prompt_loader.PROMPT_STRATEGY", "legacy")
    monkeypatch.setattr("src.prompt_loader._load_legacy_system_prompt", lambda: "")
    errors = validate_prompt_contract()
    assert any("PROMPT_STRATEGY=legacy" in e for e in errors)
