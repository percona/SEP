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

const {
    LARGE_DIFF_THRESHOLD
} = require("./constants");
const {
    appOf
} = require("./labeler-globs");

/**
 * Count changed lines across PR files, excluding generated paths.
 *
 * @param {Array<{filename: string, additions?: number, deletions?: number}>} files
 * @param {(filename: string) => boolean} isGenerated Predicate for discounted paths.
 * @returns {number}
 */
function countChangedLines(files, isGenerated) {
    let changedLines = 0;
    for (const file of files) {
        if (!isGenerated(file.filename)) {
            changedLines += (file.additions || 0) + (file.deletions || 0);
        }
    }
    return changedLines;
}

/**
 * Compute blast-radius signals from a PR file list.
 *
 * @param {Array<{filename: string, additions?: number, deletions?: number}>} files
 * @param {Record<string, string[]>} appGlobs Parsed ``app:<name>`` globs.
 * @param {(filename: string) => boolean} isGenerated Predicate for discounted paths.
 * @returns {{changedLines: number, largeDiff: boolean, appIsolated: boolean, touchedApps: string[]}}
 */
function computeBlastRadius(files, appGlobs, isGenerated) {
    const changedLines = countChangedLines(files, isGenerated);
    const largeDiff = changedLines > LARGE_DIFF_THRESHOLD;

    const touchedApps = new Set();
    let hasNonAppFile = false;
    for (const file of files) {
        const app = appOf(file.filename, appGlobs);
        if (app === null) {
            hasNonAppFile = true;
        } else {
            touchedApps.add(app);
        }
    }

    const appIsolated =
        files.length > 0 && !hasNonAppFile && touchedApps.size === 1;

    return {
        changedLines,
        largeDiff,
        appIsolated,
        touchedApps: [...touchedApps],
    };
}

module.exports = {
    countChangedLines,
    computeBlastRadius,
};
