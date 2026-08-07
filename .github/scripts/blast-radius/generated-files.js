/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

/** Paths discounted from the PR changed-line count. */

const GENERATED_PREFIXES = [
    "frontend/packages/api/src/generated/",
    "frontend/packages/api/specs/",
];

const GENERATED_EXACT = new Set(["poetry.lock", "frontend/pnpm-lock.yaml"]);

/**
 * Return whether ``filename`` is a generated file excluded from diff sizing.
 *
 * @param {string} filename PR changed-file path relative to the repo root.
 * @returns {boolean}
 */
function isGenerated(filename) {
    if (GENERATED_EXACT.has(filename)) {
        return true;
    }
    return GENERATED_PREFIXES.some((prefix) => filename.startsWith(prefix));
}

module.exports = {
    GENERATED_EXACT,
    GENERATED_PREFIXES,
    isGenerated,
};
