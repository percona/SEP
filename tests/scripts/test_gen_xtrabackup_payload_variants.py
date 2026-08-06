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
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "gen_xtrabackup_payload_variants.py"

_spec = importlib.util.spec_from_file_location(
    "gen_xtrabackup_payload_variants", _SCRIPT_PATH
)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
GEN = importlib.util.module_from_spec(_spec)
sys.modules["gen_xtrabackup_payload_variants"] = GEN
_spec.loader.exec_module(GEN)

_CHECK_SCRIPT = _PROJECT_ROOT / "scripts" / "check_nomad_payload_size.py"
_size_spec = importlib.util.spec_from_file_location(
    "check_nomad_payload_size", _CHECK_SCRIPT
)
assert _size_spec is not None, f"cannot load {_CHECK_SCRIPT}"
assert _size_spec.loader is not None, f"cannot load {_CHECK_SCRIPT}"
SIZE = importlib.util.module_from_spec(_size_spec)
sys.modules["check_nomad_payload_size"] = SIZE
_size_spec.loader.exec_module(SIZE)

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
    """Return the canonical payload source."""
    return GEN.CANONICAL_SOURCE.read_text(encoding="utf-8")


def _variant_path(providers: tuple[str, ...]) -> Path:
    """Return the on-disk path of the variant carrying ``providers``."""
    return GEN.CANONICAL_SOURCE.parent / GEN.variant_name(providers)


class TestInSyncGuard:
    """Assert the shipped variants match the canonical payload (CI drift guard)."""

    def test_check_mode_reports_no_drift(self) -> None:
        """``--check`` exits 0 for the checked-in tree."""
        assert GEN.main(["--check"]) == 0

    def test_selections_cover_every_combination(self) -> None:
        """Enumerate all eight upload selections, each in canonical provider order."""
        assert set(GEN.selections()) == set(_EXPECTED_NAMES)

    @pytest.mark.parametrize(
        ("providers", "expected"), sorted(_EXPECTED_NAMES.items()), ids=str
    )
    def test_variant_names_are_pinned(self, providers, expected) -> None:
        """Assert filenames stay stable -- ``spec.py`` selects payloads by these names."""
        assert GEN.variant_name(providers) == expected

    @pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES.values()))
    def test_every_variant_ships(self, name) -> None:
        """Assert each selection has a payload file checked in."""
        assert (GEN.CANONICAL_SOURCE.parent / name).is_file()

    def test_variant_names_match_the_size_hook_pattern(self) -> None:
        """Assert every variant ends in ``_payload`` so the size gate does not skip it."""
        assert all(name.endswith("_payload") for name in _EXPECTED_NAMES.values())

    def test_canonical_is_never_rewritten(self) -> None:
        """The canonical payload is the all-providers variant and stays hand-edited."""
        before = _canonical()
        assert GEN.main([]) == 0
        assert _canonical() == before


class TestRenderedVariants:
    """Assert each variant carries exactly the providers it is named for."""

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_variant_parses(self, providers) -> None:
        """Assert the shipped variant is syntactically valid Python."""
        ast.parse(_variant_path(providers).read_text(encoding="utf-8"))

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_omitted_providers_leave_no_trace(self, providers) -> None:
        """Assert an omitted provider's exclusive names are absent from the variant."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        for provider in GEN.PROVIDERS:
            if provider in providers:
                continue
            for name in GEN.EXCLUSIVE_NAMES[provider]:
                assert name not in text, f"{provider} leaked {name}"

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_kept_providers_are_present(self, providers) -> None:
        """Assert every carried provider still defines its class and dispatch entry."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        for provider in providers:
            for name in GEN.EXCLUSIVE_NAMES[provider]:
                assert name in text, f"{provider} lost {name}"

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_variant_is_within_the_nomad_limit(self, providers) -> None:
        """Assert every variant clears the 16 KiB dispatch gate after minify+gzip."""
        assert SIZE.check_payload(str(_variant_path(providers))) is None

    def test_omitting_a_provider_reclaims_bytes(self) -> None:
        """Assert the no-upload variant is materially smaller than the canonical one."""
        canonical = _variant_path(("rsync", "s3", "gsutil"))
        noupload = _variant_path(())
        assert len(noupload.read_bytes()) < len(canonical.read_bytes())

    @pytest.mark.parametrize("providers", sorted(_EXPECTED_NAMES), ids=str)
    def test_generated_variants_carry_no_markers(self, providers) -> None:
        """Assert markers are stripped, so no variant reads as a second canonical source."""
        text = _variant_path(providers).read_text(encoding="utf-8")
        if _variant_path(providers) == GEN.CANONICAL_SOURCE:
            assert GEN.BEGIN in text
        else:
            assert GEN.BEGIN not in text
            assert GEN.END not in text

    def test_render_is_idempotent(self) -> None:
        """Re-rendering an in-sync variant is a no-op (round-trip stable)."""
        for providers in GEN.selections():
            path = _variant_path(providers)
            if path == GEN.CANONICAL_SOURCE:
                continue
            assert GEN.build(_canonical(), providers) == path.read_text(
                encoding="utf-8"
            )


class TestMalformedRegions:
    """Assert the generator refuses a canonical source it cannot read unambiguously."""

    def test_unterminated_region_raises(self) -> None:
        """An opened region with no END is a hard error, not a silent truncation."""
        with pytest.raises(GEN.RegionError, match="unterminated"):
            GEN.render(f"a\n{GEN.BEGIN} rsync\nb\n", ())

    def test_nested_region_raises(self) -> None:
        """Two overlapping regions are rejected -- the omission would be ambiguous."""
        source = f"{GEN.BEGIN} rsync\n{GEN.BEGIN} s3\nx\n"
        with pytest.raises(GEN.RegionError, match="nested"):
            GEN.render(source, ())

    def test_unopened_end_raises(self) -> None:
        """A stray END marker is rejected rather than ignored."""
        with pytest.raises(GEN.RegionError, match="unopened"):
            GEN.render(f"a\n{GEN.END} rsync\n", ())

    def test_unknown_provider_raises(self) -> None:
        """A marker naming a provider the generator does not know is a hard error."""
        with pytest.raises(GEN.RegionError, match="unknown provider"):
            GEN.render(f"{GEN.BEGIN} azure\nx\n{GEN.END} azure\n", ())

    def test_stranded_reference_is_rejected(self) -> None:
        """A region drawn too narrowly leaves an orphan, which must fail at build time.

        This is the hazard the payload's own test suite cannot catch: the variant
        parses, but names a class it no longer defines, and only breaks on a
        customer host mid-backup.
        """
        with pytest.raises(GEN.RegionError, match="still references"):
            GEN.validate("x = RsyncUploadProvider\n", ("rsync",), "fake_payload")

    def test_valid_variant_passes_validation(self) -> None:
        """Assert validation accepts a variant with no reference to the omitted provider."""
        GEN.validate("x = 1\n", ("rsync", "s3", "gsutil"), "fake_payload")
