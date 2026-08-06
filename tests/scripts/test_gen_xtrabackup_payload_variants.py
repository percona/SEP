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

"""Tests for the ``scripts/gen_xtrabackup_payload_variants.py`` generator.

The payloads themselves are never executed by CI (heavy runtime deps), so the
generator, its drift guard, and the per-variant size assertions carry the
verification weight for the shipped variants.
"""

import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "gen_xtrabackup_payload_variants.py"

_gen_spec = importlib.util.spec_from_file_location(
    "gen_xtrabackup_payload_variants", _SCRIPT_PATH
)
assert _gen_spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _gen_spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
gen_variants = importlib.util.module_from_spec(_gen_spec)
sys.modules["gen_xtrabackup_payload_variants"] = gen_variants
_gen_spec.loader.exec_module(gen_variants)

_CHECK_SCRIPT = _PROJECT_ROOT / "scripts" / "check_nomad_payload_size.py"
_size_spec = importlib.util.spec_from_file_location(
    "check_nomad_payload_size", _CHECK_SCRIPT
)
assert _size_spec is not None, f"cannot load {_CHECK_SCRIPT}"
assert _size_spec.loader is not None, f"cannot load {_CHECK_SCRIPT}"
size_gate = importlib.util.module_from_spec(_size_spec)
sys.modules["check_nomad_payload_size"] = size_gate
_size_spec.loader.exec_module(size_gate)

_EXPECTED_NAMES = {
    (): "xtrabackup_noupload_payload",
    ("rsync",): "xtrabackup_rsync_payload",
    ("s3",): "xtrabackup_s3_payload",
    ("gsutil",): "xtrabackup_gsutil_payload",
    ("rsync", "s3"): "xtrabackup_rsync_s3_payload",
    ("rsync", "gsutil"): "xtrabackup_rsync_gsutil_payload",
    ("s3", "gsutil"): "xtrabackup_s3_gsutil_payload",
    ("rsync", "s3", "gsutil"): "xtrabackup_payload",
}


def _canonical() -> str:
    """Return the canonical payload source.

    :return: The canonical payload's text.
    """
    return gen_variants.CANONICAL_SOURCE.read_text(encoding="utf-8")


def _variant_path(providers: tuple[str, ...]) -> Path:
    """Return the on-disk path of the variant carrying ``providers``.

    :param providers: The providers the variant carries.
    :return: The variant's path beside the canonical payload.
    """
    return gen_variants.CANONICAL_SOURCE.parent / gen_variants.variant_name(providers)


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a throwaway copy of the payload tree the generator may rewrite.

    ``main()`` writes variants in place, so pointing the generator at the working
    tree would let a test repair drift -- the very failure the ``--check`` guard
    exists to surface.

    :param tmp_path: The per-test temporary directory.
    :param monkeypatch: The fixture redirecting the generator's module paths.
    :return: The directory holding the sandboxed canonical payload and variants.
    """
    payload_dir = tmp_path / "app/sep/apps/mysql_backups"
    payload_dir.mkdir(parents=True)
    for name in _EXPECTED_NAMES.values():
        shutil.copy(gen_variants.CANONICAL_SOURCE.parent / name, payload_dir / name)
    monkeypatch.setattr(gen_variants, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        gen_variants,
        "CANONICAL_SOURCE",
        payload_dir / gen_variants.CANONICAL_SOURCE.name,
    )
    return payload_dir


class TestInSyncGuard:
    """Assert the shipped variants match the canonical payload (CI drift guard)."""

    def test_check_mode_reports_no_drift(self) -> None:
        """Assert ``--check`` exits 0 for the checked-in tree."""
        assert gen_variants.main(["--check"]) == 0

    def test_selections_cover_every_combination(self) -> None:
        """Enumerate all eight upload selections, each in canonical provider order."""
        assert set(gen_variants.selections()) == set(_EXPECTED_NAMES)

    @pytest.mark.parametrize(
        ("providers", "expected"), sorted(_EXPECTED_NAMES.items()), ids=str
    )
    def test_variant_names_are_pinned(
        self, providers: tuple[str, ...], expected: str
    ) -> None:
        """Assert filenames stay stable -- ``spec.py`` selects payloads by these names."""
        assert gen_variants.variant_name(providers) == expected

    @pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES.values()))
    def test_every_variant_ships(self, name: str) -> None:
        """Assert each selection has a payload file checked in."""
        assert (gen_variants.CANONICAL_SOURCE.parent / name).is_file()

    def test_variant_names_match_the_size_hook_pattern(self) -> None:
        """Assert every variant ends in ``_payload`` so the size gate does not skip it."""
        assert all(name.endswith("_payload") for name in _EXPECTED_NAMES.values())

    def test_canonical_is_never_rewritten(self, sandbox: Path) -> None:
        """Assert the canonical all-providers payload stays hand-edited."""
        canonical = sandbox / gen_variants.CANONICAL_SOURCE.name
        before = canonical.read_text(encoding="utf-8")
        assert gen_variants.main([]) == 0
        assert canonical.read_text(encoding="utf-8") == before

    def test_check_mode_reports_drift(self, sandbox: Path) -> None:
        """Assert ``--check`` fails on a variant edited away from the canonical source."""
        drifted = sandbox / "xtrabackup_rsync_payload"
        edited = drifted.read_text(encoding="utf-8") + "DRIFT = 1\n"
        drifted.write_text(edited, encoding="utf-8")
        assert gen_variants.main(["--check"]) == 1
        assert drifted.read_text(encoding="utf-8") == edited

    def test_rewrite_repairs_drift(self, sandbox: Path) -> None:
        """Assert a regeneration run restores a drifted variant and clears ``--check``."""
        drifted = sandbox / "xtrabackup_rsync_payload"
        drifted.write_text(
            drifted.read_text(encoding="utf-8") + "DRIFT = 1\n", encoding="utf-8"
        )
        assert gen_variants.main([]) == 0
        assert gen_variants.main(["--check"]) == 0


class TestRenderedVariants:
    """Assert each variant carries exactly the providers it is named for."""

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_variant_parses(self, providers: tuple[str, ...]) -> None:
        """Assert the shipped variant is syntactically valid Python."""
        ast.parse(_variant_path(providers).read_text(encoding="utf-8"))

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_omitted_providers_leave_no_trace(self, providers: tuple[str, ...]) -> None:
        """Assert an omitted provider's exclusive names are absent from the variant."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        for provider in gen_variants.PROVIDERS:
            if provider in providers:
                continue
            for name in gen_variants.EXCLUSIVE_NAMES[provider]:
                assert name not in text, f"{provider} leaked {name}"

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_kept_providers_are_present(self, providers: tuple[str, ...]) -> None:
        """Assert every carried provider still defines its class and dispatch entry."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        for provider in providers:
            for name in gen_variants.EXCLUSIVE_NAMES[provider]:
                assert name in text, f"{provider} lost {name}"

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_variant_is_within_the_nomad_limit(
        self, providers: tuple[str, ...]
    ) -> None:
        """Assert every variant clears the 16 KiB dispatch gate after minify+gzip."""
        assert size_gate.check_payload(str(_variant_path(providers))) is None

    def test_omitting_a_provider_reclaims_bytes(self) -> None:
        """Assert the no-upload variant is materially smaller than the canonical one."""
        canonical = _variant_path(("rsync", "s3", "gsutil"))
        noupload = _variant_path(())
        assert len(noupload.read_bytes()) < len(canonical.read_bytes())

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_generated_variants_carry_no_markers(
        self, providers: tuple[str, ...]
    ) -> None:
        """Assert markers are stripped, so no variant reads as a second canonical source."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        if _variant_path(providers) == gen_variants.CANONICAL_SOURCE:
            assert gen_variants.BEGIN in text
        else:
            assert gen_variants.BEGIN not in text
            assert gen_variants.END not in text

    def test_render_is_idempotent(self) -> None:
        """Assert re-rendering an in-sync variant is a no-op (round-trip stable)."""
        for providers in gen_variants.selections():
            path = _variant_path(providers)
            if path == gen_variants.CANONICAL_SOURCE:
                continue
            assert gen_variants.build(_canonical(), providers) == path.read_text(
                encoding="utf-8"
            )


class TestMalformedRegions:
    """Assert the generator refuses a canonical source it cannot read unambiguously."""

    def test_unterminated_region_raises(self) -> None:
        """Reject an opened region with no END rather than silently truncating."""
        with pytest.raises(gen_variants.RegionError, match="unterminated"):
            gen_variants.render(f"a\n{gen_variants.BEGIN} rsync\nb\n", ())

    def test_nested_region_raises(self) -> None:
        """Reject two overlapping regions -- the omission would be ambiguous."""
        source = f"{gen_variants.BEGIN} rsync\n{gen_variants.BEGIN} s3\nx\n"
        with pytest.raises(gen_variants.RegionError, match="nested"):
            gen_variants.render(source, ())

    def test_unopened_end_raises(self) -> None:
        """Reject a stray END marker rather than ignoring it."""
        with pytest.raises(gen_variants.RegionError, match="unopened"):
            gen_variants.render(f"a\n{gen_variants.END} rsync\n", ())

    def test_unknown_provider_raises(self) -> None:
        """Reject a marker naming a provider the generator does not know."""
        source = f"{gen_variants.BEGIN} azure\nx\n{gen_variants.END} azure\n"
        with pytest.raises(gen_variants.RegionError, match="unknown provider"):
            gen_variants.render(source, ())

    def test_stranded_reference_is_rejected(self) -> None:
        """Reject an orphan left behind by a region drawn too narrowly.

        This is the hazard the payload's own test suite cannot catch: the variant
        parses, but names a class it no longer defines, and only breaks on a
        customer host mid-backup.
        """
        with pytest.raises(gen_variants.RegionError, match="still references"):
            gen_variants.validate(
                "x = RsyncUploadProvider\n", ("rsync",), "fake_payload"
            )

    def test_valid_variant_passes_validation(self) -> None:
        """Assert validation accepts a variant with no reference to the omitted provider."""
        gen_variants.validate("x = 1\n", ("rsync", "s3", "gsutil"), "fake_payload")

    def test_unbound_name_is_rejected(self) -> None:
        """Reject a name no line in the variant binds, whatever region owns it.

        The exclusive-name list is hand-maintained, so it cannot know about a symbol
        added to a region later. This sweep needs no bookkeeping and catches it.
        """
        with pytest.raises(gen_variants.RegionError, match="nothing in it defines"):
            gen_variants.validate("x = GS_RETRIES\n", (), "fake_payload")

    def test_builtins_and_module_dunders_are_not_orphans(self) -> None:
        """Assert the sweep does not flag names the interpreter itself supplies."""
        gen_variants.validate("x = len(__file__)\n", (), "fake_payload")

    def test_shipped_variants_have_no_unbound_names(self) -> None:
        """Assert every shipped variant resolves every name it loads."""
        for providers in gen_variants.selections():
            text = _variant_path(providers).read_text(encoding="utf-8")
            omitted = tuple(p for p in gen_variants.PROVIDERS if p not in providers)
            gen_variants.validate(text, omitted, gen_variants.variant_name(providers))
