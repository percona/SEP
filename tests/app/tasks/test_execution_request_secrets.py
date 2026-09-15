# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define tests for the execution-request secret-leaf transforms.

Which leaves are protected is fixed by name, so every case here states the
stored document shape rather than deriving it from a settings annotation.
"""

import json
import logging
from typing import Any

import pytest

from app.core.encryption import decrypt, is_encrypted
from app.tasks.execution_request_secrets import (
    ARGS_LEAF,
    CONFIG_LEAF,
    decrypt_request_leaves,
    encrypt_request_leaves,
    ENCRYPTED_LEAVES,
    ENCRYPTED_META_KEYS,
    PAYLOAD_LEAF,
    redact_request_leaves,
    reencrypt_request_leaves,
)
from tests.app.encryption_fixtures import FERNET_SHAPED_PLAINTEXT, foreign_token
from tests.app.tasks.conftest import (
    EXECUTION_REQUEST_ARGS,
    EXECUTION_REQUEST_CONFIG,
    EXECUTION_REQUEST_PAYLOAD,
    request_document,
)


class TestEncryptRequestLeaves:
    """Cover the unconditional write-path transform."""

    def test_encrypts_every_protected_leaf(self):
        """Assert each protected leaf becomes ciphertext of its JSON encoding."""
        stored = encrypt_request_leaves(request_document())

        for leaf in (
            stored["meta"]["args"],
            stored["meta"]["config"],
            stored["payload"],
        ):
            assert is_encrypted(leaf)
        assert decrypt(stored["meta"]["args"]) == json.dumps(EXECUTION_REQUEST_ARGS)
        assert decrypt(stored["meta"]["config"]) == json.dumps(EXECUTION_REQUEST_CONFIG)
        assert decrypt(stored["payload"]) == json.dumps(EXECUTION_REQUEST_PAYLOAD)

    def test_no_credential_survives_in_the_serialised_document(self):
        """Assert the stored JSON carries no plaintext credential anywhere.

        The per-leaf assertions above each name a path, so together they only
        prove the paths they spell. This one holds over the whole document, and
        it is what catches a leaf that is encrypted at its own site while a copy
        of the same secret stays in the clear elsewhere in the request.
        """
        secret = "hunter2"
        assert secret in json.dumps(request_document()), (
            "the fixture must carry the secret before encryption, or the "
            "absence asserted below proves nothing"
        )

        serialised = json.dumps(encrypt_request_leaves(request_document()))

        assert secret not in serialised
        assert "run-python" in serialised

    def test_encrypted_meta_keys_covers_every_meta_leaf(self):
        """Assert the SQL exclusion set names the top-level key of each meta leaf.

        A ``meta`` leaf added to the inventory becomes ciphertext in the column,
        so any SQL predicate over that key silently stops matching unless it is
        skipped. Asserted as a property of the inventory rather than by restating
        the expression, so a derivation that stops covering a leaf fails here
        instead of agreeing with itself.
        """
        meta_leaves = [leaf for leaf in ENCRYPTED_LEAVES if leaf.startswith("meta.")]
        assert meta_leaves, "the inventory must carry at least one meta leaf"
        assert len(ENCRYPTED_META_KEYS) == len(meta_leaves)
        for leaf, key in zip(meta_leaves, ENCRYPTED_META_KEYS, strict=True):
            assert leaf.split(".")[1] == key
            assert "." not in key, "a predicate matches a top-level key, not a path"
        assert PAYLOAD_LEAF not in ENCRYPTED_META_KEYS

    def test_leaves_every_other_leaf_in_the_clear(self):
        """Assert only the protected leaves are rewritten."""
        stored = encrypt_request_leaves(request_document())

        assert stored["task"] == "run-python"
        assert stored["target"] == "node-1"
        assert stored["meta"]["_service_name"] == "mysql-1"
        assert stored["tracking"] == {"allocation_id": None, "evaluation_id": None}

    def test_none_payload_is_left_alone(self):
        """Assert a ``None`` payload stays ``None`` rather than becoming a token."""
        stored = encrypt_request_leaves(request_document(payload=None))

        assert stored["payload"] is None

    def test_absent_meta_is_a_no_op(self):
        """Assert a document carrying no ``meta`` is returned unchanged."""
        document = {"task": "run-python", "target": "node-1", "payload": None}

        assert encrypt_request_leaves(document) == document

    def test_non_mapping_meta_is_a_no_op(self):
        """Assert a ``meta`` that is not an object yields no leaf to rewrite.

        The stored document is only as well-formed as whatever wrote it, and the
        walk has to stop rather than raise when a parent is the wrong shape.
        """
        document = request_document()
        document["meta"] = "not-a-mapping"

        stored = encrypt_request_leaves(document)

        assert stored["meta"] == "not-a-mapping"
        assert is_encrypted(stored["payload"])

    def test_meta_without_args_is_a_no_op(self):
        """Assert a ``meta`` carrying no ``args`` key gains none."""
        document = request_document()
        del document["meta"]["args"]

        stored = encrypt_request_leaves(document)

        assert "args" not in stored["meta"]

    def test_none_args_is_left_alone(self):
        """Assert a ``None`` ``args`` stays ``None``."""
        stored = encrypt_request_leaves(request_document(args=None))

        assert stored["meta"]["args"] is None

    def test_does_not_mutate_the_caller_document(self):
        """Assert the caller's document and its nested ``meta`` survive untouched."""
        document = request_document()

        encrypt_request_leaves(document)

        assert document["meta"]["args"] == EXECUTION_REQUEST_ARGS
        assert document["payload"] == "file://snippets/foo.py"

    def test_preserved_leaf_is_written_back_byte_identically(self):
        """Assert a leaf named in ``preserve`` is stored as the token it arrived as."""
        token = foreign_token()
        document = request_document(payload=token)

        stored = encrypt_request_leaves(document, preserve=(PAYLOAD_LEAF,))

        assert stored["payload"] == token
        assert is_encrypted(stored["meta"]["args"])

    def test_fresh_fernet_shaped_payload_is_encrypted(self):
        """Assert a fresh submission that merely looks encrypted is still encrypted.

        The provenance half of the pair the write path must not decide
        structurally: a caller-supplied document can legitimately be a valid
        Fernet token, and storing it in the clear would expose a real credential.
        """
        token = foreign_token()
        assert is_encrypted(token), "the fixture must be structurally a token"

        stored = encrypt_request_leaves(request_document(payload=token))

        assert stored["payload"] != token
        assert decrypt_request_leaves(stored)[0]["payload"] == token


class TestDecryptRequestLeaves:
    """Cover the read-path transform and its non-raising failure arm."""

    @pytest.mark.parametrize(
        "args",
        [
            "restore --password hunter2",
            ["restore", "--password", "hunter2"],
            {"password": "hunter2"},
            7,
        ],
        ids=["str", "list", "dict", "int"],
    )
    def test_round_trips_every_args_type(self, args: Any):
        """Assert JSON wrapping returns ``args`` as the type it was written with.

        :param args: The ``$.meta.args`` value to round-trip.
        """
        document = request_document(args=args)

        restored, unreadable = decrypt_request_leaves(encrypt_request_leaves(document))

        assert restored == document
        assert unreadable == ()

    def test_legacy_plaintext_row_is_passed_through(self):
        """Assert a row written before the migration ran keeps resolving."""
        document = request_document()

        restored, unreadable = decrypt_request_leaves(document)

        assert restored == document
        assert unreadable == ()

    def test_undecryptable_leaf_is_named_and_left_in_place(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Assert a foreign token is reported, logged, and left as it stands.

        :param caplog: The capture fixture the warning is asserted against.
        """
        token = foreign_token()
        stored = encrypt_request_leaves(request_document(), preserve=(PAYLOAD_LEAF,))
        stored["payload"] = token

        with caplog.at_level(logging.WARNING):
            restored, unreadable = decrypt_request_leaves(stored)

        assert unreadable == (PAYLOAD_LEAF,)
        assert restored["payload"] == token
        assert restored["meta"]["args"] == EXECUTION_REQUEST_ARGS
        assert PAYLOAD_LEAF in caplog.text

    def test_does_not_mutate_the_stored_document(self):
        """Assert the document read out of the row survives untouched."""
        stored = encrypt_request_leaves(request_document())
        args_token = stored["meta"]["args"]

        decrypt_request_leaves(stored)

        assert stored["meta"]["args"] == args_token


class TestReencryptRequestLeaves:
    """Cover the structural, idempotent transform the migration applies."""

    def test_encrypts_a_plaintext_leaf(self):
        """Assert a leaf still in the clear is encrypted."""
        stored = reencrypt_request_leaves(request_document())

        assert is_encrypted(stored["meta"]["args"])
        assert is_encrypted(stored["payload"])

    @pytest.mark.parametrize(
        "args",
        [["restore", "--password", "hunter2"], {"password": "hunter2"}, 7],
        ids=["list", "dict", "int"],
    )
    def test_encrypts_a_non_string_leaf(self, args: Any):
        """Assert a stored row whose ``args`` is not a string is rewritten, not refused.

        The API merges a caller-supplied ``meta`` unvalidated, so the migration
        can meet an ``args`` of any JSON type. ``is_encrypted`` classifies a
        ``str`` and nothing else, so the transform has to decide by type before
        asking it rather than handing it whatever the row holds.

        :param args: The stored ``$.meta.args`` value to rewrite.
        """
        stored = reencrypt_request_leaves(request_document(args=args))

        assert is_encrypted(stored["meta"]["args"])
        assert decrypt_request_leaves(stored)[0]["meta"]["args"] == args

    def test_second_run_rewrites_nothing(self):
        """Assert re-running the migration leaves every leaf byte-identical."""
        once = reencrypt_request_leaves(request_document())

        assert reencrypt_request_leaves(once) == once

    def test_foreign_token_is_never_re_encrypted(self):
        """Assert ciphertext another key produced keeps its only copy of the plaintext."""
        token = foreign_token()

        stored = reencrypt_request_leaves(request_document(payload=token))

        assert stored["payload"] == token

    def test_fernet_shaped_plaintext_stays_in_the_clear(self):
        """Pin the accepted limitation of deciding structurally.

        The migration reads stored rows only, so it cannot tell a legacy
        plaintext that happens to be a well-formed token from ciphertext written
        under a key this process does not hold. Skipping is the safe direction:
        the alternative destroys the only copy of a foreign token's plaintext.
        """
        assert is_encrypted(FERNET_SHAPED_PLAINTEXT), (
            "the fixture must be misread as a token"
        )

        stored = reencrypt_request_leaves(
            request_document(payload=FERNET_SHAPED_PLAINTEXT)
        )

        assert stored["payload"] == FERNET_SHAPED_PLAINTEXT


class TestRedactRequestLeaves:
    """Cover the serialisation-only redaction the response layer applies."""

    def test_named_leaf_serialises_as_none(self):
        """Assert only the named leaf is blanked."""
        document = request_document()

        redacted = redact_request_leaves(document, [ARGS_LEAF])

        assert redacted["meta"]["args"] is None
        assert redacted["payload"] == "file://snippets/foo.py"

    def test_blanks_two_leaves_sharing_one_parent(self):
        """Assert redacting both ``meta`` leaves blanks both, not just the last.

        The walk copies each container on the way down. Copying ``meta`` once per
        leaf rather than once in total would leave the first leaf's write landing
        on a dict the returned document no longer references, so it would vanish
        with no error and the credential would serialise in full.
        """
        redacted = redact_request_leaves(request_document(), [ARGS_LEAF, CONFIG_LEAF])

        assert redacted["meta"]["args"] is None
        assert redacted["meta"]["config"] is None
        assert redacted["meta"]["_service_name"] == "mysql-1"

    def test_does_not_mutate_the_caller_document(self):
        """Assert the dumped document the caller passed survives untouched."""
        document = request_document()

        redact_request_leaves(document, ENCRYPTED_LEAVES)

        assert document["meta"]["args"] == EXECUTION_REQUEST_ARGS
        assert document["payload"] == "file://snippets/foo.py"
