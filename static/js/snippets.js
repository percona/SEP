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

$(document).ready(function() {
    $('a.downloadSnippet').click(function() {
        const $anchor = $(this);
        const snippetFilename = $.escapeSelector($anchor.data('snippet-filename'));
        const $approveButton = $(`#${snippetFilename}-approval > button[type=submit]:is([disabled])`);
        $approveButton.prop("disabled", false);
        $approveButton.attr("title", $approveButton.data("next-title"));
    })
});

$(document).ready(function() {
    const $checkboxes = $('.snippetCheckbox');
    const $selectAll = $('#selectAllSnippets');
    const $bulkBar = $('#snippetsBulkBar');
    if (!$checkboxes.length) {
        return;
    }

    function updateBulkBar() {
        const checkedCount = $checkboxes.filter(':checked').length;
        const total = $checkboxes.length;
        $bulkBar.prop('hidden', checkedCount === 0);
        $selectAll.prop('checked', checkedCount > 0 && checkedCount === total);
        $selectAll.prop('indeterminate', checkedCount > 0 && checkedCount < total);
    }

    $selectAll.on('change', function() {
        $checkboxes.prop('checked', this.checked);
        updateBulkBar();
    });
    $checkboxes.on('change', updateBulkBar);
    updateBulkBar();
});
