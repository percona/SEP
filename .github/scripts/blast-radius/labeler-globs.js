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

/**
 * Parse ``app:<name>`` globs from ``.github/labeler.yml`` and match filenames.
 */

/**
 * Build a map of ``app:<name>`` label to its path globs.
 *
 * @param {string} labelerText Full ``.github/labeler.yml`` contents.
 * @returns {Record<string, string[]>}
 */
function parseAppGlobs(labelerText) {
    const appGlobs = {};
    let currentLabel = null;

    for (const line of labelerText.split("\n")) {
        const keyMatch = line.match(/^([A-Za-z0-9:_-]+):\s*$/);
        if (keyMatch) {
            currentLabel = keyMatch[1].startsWith("app:") ? keyMatch[1] : null;
            if (currentLabel) {
                appGlobs[currentLabel] = [];
            }
            continue;
        }
        if (!currentLabel) {
            continue;
        }
        const globMatch = line.match(/^\s*-\s*'([^']+)'\s*$/);
        if (globMatch) {
            appGlobs[currentLabel].push(globMatch[1]);
        }
    }

    return appGlobs;
}

/**
 * Return whether ``filename`` matches a labeler glob.
 *
 * @param {string} glob Labeler path glob.
 * @param {string} filename PR changed-file path relative to the repo root.
 * @returns {boolean}
 */
function matchGlob(glob, filename) {
    if (glob.endsWith("/**")) {
        return filename.startsWith(glob.slice(0, -2));
    }
    const pattern = glob
        .split("*")
        .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
        .join("[^/]*");
    return new RegExp(`^${pattern}$`).test(filename);
}

/**
 * Return the ``app:<name>`` label for ``filename``, if any.
 *
 * @param {string} filename PR changed-file path relative to the repo root.
 * @param {Record<string, string[]>} appGlobs Parsed labeler app globs.
 * @returns {string | null}
 */
function appOf(filename, appGlobs) {
    for (const [label, globs] of Object.entries(appGlobs)) {
        if (globs.some((glob) => matchGlob(glob, filename))) {
            return label;
        }
    }
    return null;
}

module.exports = {
    parseAppGlobs,
    matchGlob,
    appOf,
};
