"""HMAC plan-signing: capability token mint/verify behavior."""
import os
import unittest
from unittest import mock

from core.plan_signer import KEY_ENV, mint, verify_token

KEY = "unit-test-key-123"


def with_key(extra=None):
    env = {KEY_ENV: KEY}
    if extra:
        env.update(extra)
    return mock.patch.dict(os.environ, env, clear=False)


class TestPlanSigner(unittest.TestCase):
    def test_roundtrip(self):
        with with_key():
            tok = mint(["delete_file", "write_file"], ttl_s=600)
            self.assertTrue(verify_token(tok, "delete_file"))
            self.assertTrue(verify_token(tok, "write_file"))

    def test_explicit_key_param(self):
        tok = mint(["delete_file"], ttl_s=600, key=KEY)
        self.assertTrue(verify_token(tok, "delete_file", key=KEY))

    def test_wrong_tool_rejected(self):
        with with_key():
            tok = mint(["write_file"], ttl_s=600)
            self.assertFalse(verify_token(tok, "delete_file"))

    def test_tampered_scope_rejected(self):
        with with_key():
            tok = mint(["write_file"], ttl_s=600)
            tampered = tok.replace("write_file", "delete_file")
            self.assertFalse(verify_token(tampered, "delete_file"))

    def test_tampered_signature_rejected(self):
        with with_key():
            tok = mint(["delete_file"], ttl_s=600)
            bad = tok[:-1] + ("0" if tok[-1] != "0" else "1")
            self.assertFalse(verify_token(bad, "delete_file"))

    def test_expired_rejected(self):
        with with_key():
            tok = mint(["delete_file"], ttl_s=-5)
            self.assertFalse(verify_token(tok, "delete_file"))

    def test_malformed_rejected(self):
        with with_key():
            for bad in ("", "garbage", "v1.a.b", "v9.delete_file.9999999999.abc"):
                self.assertFalse(verify_token(bad, "delete_file"),
                                 f"should reject {bad!r}")

    def test_wrong_key_rejected(self):
        with with_key():
            tok = mint(["delete_file"], ttl_s=600)
            self.assertFalse(verify_token(tok, "delete_file", key="other-key"))

    def test_missing_key_mint_raises(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY_ENV, None)
            with self.assertRaises(RuntimeError):
                mint(["delete_file"])

    def test_missing_key_verify_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(KEY_ENV, None)
            self.assertFalse(verify_token("v1.delete_file.9999999999.abc",
                                          "delete_file"))

    def test_scope_order_irrelevant(self):
        with with_key():
            tok = mint(["write_file", "delete_file"], ttl_s=600)
            self.assertTrue(verify_token(tok, "delete_file"))
            self.assertTrue(verify_token(tok, "write_file"))

    def test_empty_scope_raises(self):
        with with_key():
            with self.assertRaises(ValueError):
                mint([])


if __name__ == "__main__":
    unittest.main()
