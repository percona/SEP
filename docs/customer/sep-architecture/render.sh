#!/usr/bin/env bash
#
# Render sep-architecture.mmd → exports/sep-architecture.pdf
# as a single-page A3 portrait vector PDF.
#
# Pipeline: mermaid-cli renders SVG, the SVG is inlined into an HTML page that
# fixes the @page size to A3 portrait, and Chromium headless prints that page
# to a vector PDF. Going through mermaid-cli's --pdfFit instead emits a
# non-standard tall page that some PDF viewers paginate visually.

set -o nounset
set -o pipefail

# ── Debug ─────────────────────────────────────────────────────────
if [[ ${DEBUG:-0} == "1" ]]; then
    set -o xtrace
fi

# ── UI helpers ────────────────────────────────────────────────────
if command -v ansi > /dev/null 2>&1; then
    error() { ansi -n --bold --red "✗ " >&2 && ansi --red "$*" >&2; }
    success() { ansi -n --bold --green "✓ " >&2 && ansi --green "$*" >&2; }
    info() { ansi -n --bold --cyan "ℹ " >&2 && ansi --cyan "$*" >&2; }
else
    error() { printf '✗ %s\n' "$*" >&2; }
    success() { printf '✓ %s\n' "$*" >&2; }
    info() { printf 'ℹ %s\n' "$*" >&2; }
fi
debug() { [[ ${DEBUG:-0} == "1" ]] && printf '[DEBUG] %s\n' "$*" >&2 || true; }

# ── Dependency checks ─────────────────────────────────────────────
need_cmd() {
    command -v "$1" > /dev/null 2>&1 || {
        error "Missing required command: $1"
        exit 2
    }
}

# Locate a Chromium-flavoured binary; the print-to-pdf flag is identical.
find_chromium() {
    local cmd
    for cmd in chromium chromium-browser google-chrome chrome; do
        if command -v "$cmd" > /dev/null 2>&1; then
            printf '%s\n' "$cmd"
            return 0
        fi
    done
    error "No Chromium binary found (tried: chromium, chromium-browser, google-chrome, chrome)"
    exit 2
}

# ── Usage ─────────────────────────────────────────────────────────
usage() {
    cat << 'EOF'
render.sh [-h|--help]

Render sep-architecture.mmd to exports/sep-architecture.pdf as a single-page
A3 portrait vector PDF.

Requires:
  - npx (Node.js)  — for @mermaid-js/mermaid-cli
  - chromium (or chromium-browser / google-chrome / chrome)
  - sed

Options:
  -h, --help    Show this help and exit

Environment:
  DEBUG=1       Enable shell trace and debug logging
EOF
    exit "${1:-0}"
}

# ── Argument parsing ─────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help) usage 0 ;;
        --)
            shift
            break
            ;;
        -*)
            error "Unknown option: $1"
            usage 2
            ;;
        *) break ;;
    esac
done

need_cmd npx
need_cmd sed
chromium_bin=$(find_chromium)
debug "chromium binary: ${chromium_bin}"

# ── Main ─────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1

src="sep-architecture.mmd"
dst="exports/sep-architecture.pdf"
[[ -f $src ]] || {
    error "Missing source: $src"
    exit 1
}
mkdir -p exports

tmp_svg=$(mktemp --suffix=.svg)
tmp_html=$(mktemp --suffix=.html)
trap 'rm -f "$tmp_svg" "$tmp_html"' EXIT

info "Rendering Mermaid → SVG..."
npx -y @mermaid-js/mermaid-cli -i "$src" -o "$tmp_svg" -b white

info "Wrapping SVG in A3-portrait HTML page..."
{
    cat << 'HEAD'
<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><title>SEP Architecture</title>
<style>
  @page { size: A3 portrait; margin: 0; }
  html, body { margin: 0; padding: 0; background: white;
               -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { width: 297mm; height: 420mm; display: flex;
         align-items: center; justify-content: center; overflow: hidden; }
  .frame { width: 95%; height: 95%; display: flex;
           align-items: center; justify-content: center; }
  .frame > svg { max-width: 100%; max-height: 100%; width: auto; height: auto; }
</style></head><body><div class="frame">
HEAD
    sed -e '/^<?xml/d' "$tmp_svg"
    printf '</div></body></html>\n'
} > "$tmp_html"

info "Printing to vector PDF via ${chromium_bin}..."
"$chromium_bin" --headless --no-sandbox --disable-gpu \
    --print-to-pdf="$dst" \
    --no-pdf-header-footer --virtual-time-budget=10000 --hide-scrollbars \
    "file://${tmp_html}"

success "Rendered: $(realpath "$dst")"
