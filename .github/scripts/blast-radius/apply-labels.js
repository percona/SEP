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
 * Entry point for the Labels workflow blast-radius step.
 *
 * Loaded via ``actions/github-script`` ``script-path`` after checking out the
 * base branch ``.github/`` tree only — never PR-head code.
 */

const fs = require("fs");
const path = require("path");

const {
    isGenerated
} = require("./generated-files");
const {
    parseAppGlobs
} = require("./labeler-globs");
const {
    computeBlastRadius
} = require("./compute");
const {
    syncLabels
} = require("./sync-labels");

/**
 * Compute and sync ``large-diff`` / ``app-isolated`` on the current PR.
 *
 * @param {{github: import('@octokit/rest').Octokit, context: import('@actions/github').context, core: import('@actions/core')}} env
 * @returns {Promise<void>}
 */
async function applyBlastRadiusLabels({
    github,
    context,
    core
}) {
    const pr = context.payload.pull_request;
    if (!pr) {
        core.info("No pull_request in payload; skipping.");
        return;
    }

    const {
        owner,
        repo
    } = context.repo;
    const files = await github.paginate(github.rest.pulls.listFiles, {
        owner,
        repo,
        pull_number: pr.number,
        per_page: 100,
    });

    const labelerPath = path.join(
        process.env.GITHUB_WORKSPACE,
        ".github",
        "labeler.yml",
    );
    const labelerText = fs.readFileSync(labelerPath, "utf8");
    const appGlobs = parseAppGlobs(labelerText);
    const {
        changedLines,
        largeDiff,
        appIsolated,
        touchedApps
    } =
    computeBlastRadius(files, appGlobs, isGenerated);

    core.info(
        `changedLines=${changedLines} largeDiff=${largeDiff} ` +
        `appIsolated=${appIsolated} apps=[${touchedApps.join(", ")}]`,
    );

    await syncLabels(
        github,
        core, {
            owner,
            repo,
            issueNumber: pr.number
        }, {
            "large-diff": largeDiff,
            "app-isolated": appIsolated
        },
    );
}

module.exports = applyBlastRadiusLabels;
