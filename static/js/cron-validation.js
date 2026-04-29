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

// Mirrors the field-by-field check enforced by the backend in
// app/sep/utils/forms.py::parse_crontab_form_fields. Loaded by every page
// that exposes a cron_expression input (periodic-tasks UI and inventory-sync
// schedule UI) so submit-time validation behaves the same in both contexts.
(function(global) {
    'use strict';

    const CRON_FIELD_COUNT = 5;
    const CRON_FIELD_PATTERNS = [
        /^[\d*/,\-]+$/, // minute
        /^[\d*/,\-]+$/, // hour
        /^[\d*/,\-?LW]+$/i, // day of month
        /^[\d*/,\-A-Z]+$/i, // month
        /^[\d*/,\-A-Z#?L]+$/i, // day of week
    ];

    function hasValidCronFieldCharacters(cronExpression) {
        const parts = cronExpression.trim().split(/\s+/);
        if (parts.length !== CRON_FIELD_COUNT) {
            return false;
        }
        return parts.every((part, index) => CRON_FIELD_PATTERNS[index].test(part));
    }

    function hasInvalidZeroStep(cronExpression) {
        return cronExpression
            .trim()
            .split(/\s+/)
            .some((part) => part
                .split(',')
                .some((segment) => {
                    if (!segment.includes('/')) {
                        return false;
                    }
                    const step = segment.split('/')[1];
                    return /^\d+$/.test(step) && Number(step) === 0;
                }));
    }

    function isCronExpressionValid(cronExpression) {
        if (!cronExpression) {
            return false;
        }
        const trimmed = cronExpression.trim();
        if (!hasValidCronFieldCharacters(trimmed)) {
            return false;
        }
        if (hasInvalidZeroStep(trimmed)) {
            return false;
        }
        return true;
    }

    global.cronValidation = {
        FIELD_COUNT: CRON_FIELD_COUNT,
        hasValidCronFieldCharacters: hasValidCronFieldCharacters,
        hasInvalidZeroStep: hasInvalidZeroStep,
        isCronExpressionValid: isCronExpressionValid,
    };
})(window);
