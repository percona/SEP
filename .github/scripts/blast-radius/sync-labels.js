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
 * Add or remove blast-radius labels on a pull request.
 */

/**
 * Sync ``desired`` labels on a pull request, adding or removing as needed.
 *
 * @param {import('@octokit/rest').Octokit} github Authenticated Octokit client.
 * @param {import('@actions/core')} core Actions core logger.
 * @param {{owner: string, repo: string, issueNumber: number}} target PR coordinates.
 * @param {Record<string, boolean>} desired Label name to whether it should be present.
 * @returns {Promise<void>}
 */
async function syncLabels(github, core, target, desired) {
    const {
        owner,
        repo,
        issueNumber
    } = target;
    const present = new Set(
        (
            await github.paginate(github.rest.issues.listLabelsOnIssue, {
                owner,
                repo,
                issue_number: issueNumber,
                per_page: 100,
            })
        ).map((label) => label.name),
    );

    for (const [name, want] of Object.entries(desired)) {
        if (want && !present.has(name)) {
            await github.rest.issues.addLabels({
                owner,
                repo,
                issue_number: issueNumber,
                labels: [name],
            });
            core.info(`Added ${name}`);
        } else if (!want && present.has(name)) {
            try {
                await github.rest.issues.removeLabel({
                    owner,
                    repo,
                    issue_number: issueNumber,
                    name,
                });
                core.info(`Removed ${name}`);
            } catch (error) {
                if (error.status !== 404) {
                    throw error;
                }
            }
        }
    }
}

module.exports = {
    syncLabels,
};
