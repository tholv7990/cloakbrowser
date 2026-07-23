from __future__ import annotations

from cloud.passwords import hash_password, needs_rehash, verify_password


def test_hash_verifies_and_hides_the_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple") is True
    assert verify_password(hashed, "wrong password") is False
    # The plaintext never appears in the stored hash; it's an argon2id hash.
    assert "correct horse" not in hashed
    assert hashed.startswith("$argon2id$")


def test_same_password_hashes_differently_each_time():
    # Distinct salts → distinct hashes (no rainbow-table shortcut).
    assert hash_password("same-password") != hash_password("same-password")


def test_a_current_hash_does_not_need_rehash():
    assert needs_rehash(hash_password("whatever-1234")) is False
