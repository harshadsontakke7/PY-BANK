"""Run with:  python -m unittest discover tests   (no database needed)."""
import unittest
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security import (hash_pin, verify_pin, parse_amount, is_valid_pin, mask_account)


class SecurityTests(unittest.TestCase):
    def test_hash_roundtrip_and_random_salt(self):
        s1, h1 = hash_pin("1234")
        s2, h2 = hash_pin("1234")
        self.assertNotEqual(s1, s2)
        self.assertTrue(verify_pin("1234", s1, h1))
        self.assertFalse(verify_pin("1235", s1, h1))

    def test_compatible_with_streamlit_scheme(self):
        # Re-implementation of the ORIGINAL app's hashing, written independently.
        import hashlib
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        legacy = hashlib.pbkdf2_hmac("sha256", b"4321", salt, 300_000).hex()
        self.assertTrue(verify_pin("4321", salt.hex(), legacy))

    def test_bad_salt_is_rejected_not_crashing(self):
        self.assertFalse(verify_pin("1234", "not-hex", "abc"))

    def test_pin_validation(self):
        self.assertTrue(is_valid_pin("0123"))
        for bad in ("", "123", "12345", "12a4", "١٢٣٤", "12 4"):
            self.assertFalse(is_valid_pin(bad), bad)

    def test_amounts(self):
        self.assertEqual(parse_amount("1,250.5"), Decimal("1250.50"))
        self.assertEqual(parse_amount("0", allow_zero=True), Decimal("0.00"))
        for bad in ("", "0", "-5", "abc", "NaN", "Infinity", "1e400", "10.005", "1000000000000"):
            with self.assertRaises(ValueError, msg=bad):
                parse_amount(bad)

    def test_mask(self):
        self.assertEqual(mask_account("1234567890"), "••••7890")


if __name__ == "__main__":
    unittest.main()
