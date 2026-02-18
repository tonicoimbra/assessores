"""Canonical regression suite for prompt composition across pipeline stages."""

import pytest

from src.prompt_loader import build_messages, get_prompt_signature


@pytest.mark.parametrize(
    ("stage", "include_references", "expected_developer_msgs", "developer_marker"),
    [
        ("etapa1", None, 1, "Developer Prompt — Etapa 1"),
        ("etapa2", None, 1, "Developer Prompt — Etapa 2"),
        ("etapa3", None, 1, "Developer Prompt — Etapa 3"),
        ("etapa2", True, 2, "Referências Longas"),
    ],
)
def test_prompt_regression_canonical_messages(
    stage: str,
    include_references: bool | None,
    expected_developer_msgs: int,
    developer_marker: str,
) -> None:
    messages = build_messages(
        stage=stage,
        user_text=f"caso canônico {stage}",
        include_references=include_references,
    )

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "assessor jurídico do TJPR" in messages[0]["content"]

    dev_messages = [m for m in messages if m["role"] == "developer"]
    assert len(dev_messages) == expected_developer_msgs
    assert any(developer_marker in m["content"] for m in dev_messages)


def test_prompt_signature_is_deterministic_for_stage() -> None:
    sig_a = get_prompt_signature(stage="etapa2")
    sig_b = get_prompt_signature(stage="etapa2")
    assert sig_a == sig_b

