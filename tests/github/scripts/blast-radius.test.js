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
    readFileSync
} = require("node:fs");
const {
    test
} = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const {
    LARGE_DIFF_THRESHOLD
} = require("../../../.github/scripts/blast-radius/constants");
const {
    isGenerated
} = require("../../../.github/scripts/blast-radius/generated-files");
const {
    parseAppGlobs,
    matchGlob,
    appOf,
} = require("../../../.github/scripts/blast-radius/labeler-globs");
const {
    computeBlastRadius
} = require("../../../.github/scripts/blast-radius/compute");

const LABELER_PATH = path.join(
    __dirname,
    "../../../.github/labeler.yml",
);
const labelerText = readFileSync(LABELER_PATH, "utf8");
const appGlobs = parseAppGlobs(labelerText);

test("parseAppGlobs discovers all app labels from committed labeler.yml", () => {
    const labels = Object.keys(appGlobs);
    assert.equal(labels.length, 15);
    assert.ok(labels.includes("app:report"));
    assert.ok(labels.includes("app:archives"));
});

test("archives template alias resolves through labeler globs", () => {
    assert.equal(appOf("templates/archiver/report.j2", appGlobs), "app:archives");
    assert.equal(appOf("templates/archives/report.j2", appGlobs), null);
});

test("e2e hyphen aliases resolve to underscore app labels", () => {
    assert.equal(
        appOf("frontend/packages/e2e/tests/mysql-backups.spec.ts", appGlobs),
        "app:mysql_backups",
    );
    assert.equal(
        appOf(
            "frontend/packages/e2e/tests/alert-troubleshooting.spec.ts",
            appGlobs,
        ),
        "app:alert_troubleshooting",
    );
});

test("svc and cross-cutting paths are not app slices", () => {
    assert.equal(appOf("app/tasks/worker.py", appGlobs), null);
    assert.equal(appOf("app/core/config.py", appGlobs), null);
    assert.equal(appOf(".github/labeler.yml", appGlobs), null);
});

test("inventory e2e prefix matches the app label", () => {
    assert.equal(
        appOf("frontend/packages/e2e/tests/inventory-sync.spec.ts", appGlobs),
        "app:inventory",
    );
});

test("matchGlob supports directory and wildcard patterns", () => {
    assert.ok(matchGlob("app/sep/apps/report/**", "app/sep/apps/report/routes.py"));
    assert.ok(
        matchGlob(
            "frontend/packages/e2e/tests/report*.spec.ts",
            "frontend/packages/e2e/tests/report.spec.ts",
        ),
    );
});

test("isGenerated discounts lockfiles and generated API client paths", () => {
    assert.ok(isGenerated("poetry.lock"));
    assert.ok(isGenerated("frontend/pnpm-lock.yaml"));
    assert.ok(isGenerated("frontend/packages/api/src/generated/client.ts"));
    assert.ok(!isGenerated("app/sep/apps/report/routes.py"));
});

test("computeBlastRadius marks a single-app PR as isolated", () => {
    const files = [{
        filename: "app/sep/apps/report/a.py",
        additions: 1,
        deletions: 0
    }, {
        filename: "frontend/packages/apps/report/b.ts",
        additions: 2,
        deletions: 0
    }, ];
    const result = computeBlastRadius(files, appGlobs, isGenerated);
    assert.equal(result.appIsolated, true);
    assert.deepEqual(result.touchedApps, ["app:report"]);
});

test("computeBlastRadius rejects mixed-app and cross-cutting PRs", () => {
    const mixedApps = [{
        filename: "app/sep/apps/report/a.py",
        additions: 1,
        deletions: 0
    }, {
        filename: "app/sep/apps/alerts/b.py",
        additions: 1,
        deletions: 0
    }, ];
    assert.equal(computeBlastRadius(mixedApps, appGlobs, isGenerated).appIsolated, false);

    const crossCutting = [{
        filename: "app/sep/apps/report/a.py",
        additions: 1,
        deletions: 0
    }, {
        filename: "app/core/x.py",
        additions: 1,
        deletions: 0
    }, ];
    assert.equal(
        computeBlastRadius(crossCutting, appGlobs, isGenerated).appIsolated,
        false,
    );

    const githubOnly = [{
        filename: ".github/labeler.yml",
        additions: 10,
        deletions: 0
    }];
    assert.equal(computeBlastRadius(githubOnly, appGlobs, isGenerated).appIsolated, false);
});

test("computeBlastRadius applies the 1500-line threshold with generated discount", () => {
    const atThreshold = [{
        filename: "app/sep/apps/report/a.py",
        additions: 1000,
        deletions: 500
    }, ];
    assert.equal(
        computeBlastRadius(atThreshold, appGlobs, isGenerated).largeDiff,
        false,
    );

    const overThreshold = [{
        filename: "app/sep/apps/report/a.py",
        additions: 1000,
        deletions: 501
    }, ];
    assert.equal(
        computeBlastRadius(overThreshold, appGlobs, isGenerated).largeDiff,
        true,
    );

    const discounted = [{
        filename: "app/sep/apps/report/a.py",
        additions: 100,
        deletions: 0
    }, {
        filename: "frontend/packages/api/src/generated/x.ts",
        additions: 5000,
        deletions: 0
    }, {
        filename: "poetry.lock",
        additions: 9000,
        deletions: 0
    }, ];
    const result = computeBlastRadius(discounted, appGlobs, isGenerated);
    assert.equal(result.changedLines, 100);
    assert.equal(result.largeDiff, false);
    assert.equal(LARGE_DIFF_THRESHOLD, 1500);
});
