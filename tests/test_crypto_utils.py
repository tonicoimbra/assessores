"""Tests for crypto_utils: Fernet encryption / decryption utilities."""

from __future__ import annotations

import json
import pytest

import src.crypto_utils as cu


class TestGenerateKey:
    def test_retorna_string_valida(self) -> None:
        key = cu.generate_key()
        assert isinstance(key, str)
        assert len(key) == 44  # URL-safe base64 of 32 bytes

    def test_chaves_sao_unicas(self) -> None:
        assert cu.generate_key() != cu.generate_key()


class TestEncryptDecryptRoundTrip:
    def test_round_trip_json(self) -> None:
        key = cu.generate_key()
        data = {"processo_id": "123", "erro": {"tipo": "ValueError"}, "nested": [1, 2, 3]}
        blob = cu.encrypt_json(data, key)
        result = cu.decrypt_json(blob, key)
        assert result == data

    def test_blob_e_binario_opaco(self) -> None:
        key = cu.generate_key()
        data = {"secret": "dado_processual_sigiloso"}
        blob = cu.encrypt_json(data, key)
        # Encrypted blob should NOT be valid JSON
        with pytest.raises(Exception):
            json.loads(blob)

    def test_chave_errada_lanca_value_error(self) -> None:
        key1 = cu.generate_key()
        key2 = cu.generate_key()
        blob = cu.encrypt_json({"x": 1}, key1)
        with pytest.raises(ValueError, match="chave incorreta"):
            cu.decrypt_json(blob, key2)


class TestSemChave:
    def test_encrypt_sem_chave_retorna_json_em_texto(self) -> None:
        data = {"campo": "valor"}
        blob = cu.encrypt_json(data, "")
        # Should be valid JSON (plaintext mode)
        assert json.loads(blob.decode("utf-8")) == data

    def test_decrypt_sem_chave_le_json_texto(self) -> None:
        data = {"campo": "valor"}
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        result = cu.decrypt_json(raw, "")
        assert result == data


class TestEncryptDecryptText:
    def test_texto_round_trip(self) -> None:
        key = cu.generate_key()
        original = "Recorrente: João da Silva"
        blob = cu.encrypt_text(original, key)
        assert cu.decrypt_text(blob, key) == original

    def test_sem_chave_volta_texto_bruto(self) -> None:
        original = "texto simples"
        blob = cu.encrypt_text(original, "")
        assert cu.decrypt_text(blob, "") == original

    def test_chave_invalida_lanca_excecao(self) -> None:
        key = cu.generate_key()
        blob = cu.encrypt_text("dado", key)
        wrong_key = cu.generate_key()
        with pytest.raises(ValueError, match="chave incorreta"):
            cu.decrypt_text(blob, wrong_key)
