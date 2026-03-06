/*
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

document.addEventListener('DOMContentLoaded', function() {
    var buttons = document.querySelectorAll('.toggle-btn-group .toggle-btn');
    var rows = document.querySelectorAll('.alerts-table tbody tr');
    var selectAll = document.getElementById('select-all-alerts');

    // Service type filter tabs
    buttons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            buttons.forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            var filter = btn.getAttribute('data-filter');
            rows.forEach(function(row) {
                if (filter === 'all' || row.getAttribute('data-service-type') === filter) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                    // Uncheck hidden rows
                    var cb = row.querySelector('.alert-checkbox');
                    if (cb) cb.checked = false;
                }
            });

            // Reset select-all when filter changes
            if (selectAll) selectAll.checked = false;
        });
    });

    // Select all visible checkboxes
    if (selectAll) {
        selectAll.addEventListener('change', function() {
            var checked = selectAll.checked;
            rows.forEach(function(row) {
                if (row.style.display !== 'none') {
                    var cb = row.querySelector('.alert-checkbox');
                    if (cb) cb.checked = checked;
                }
            });
        });

        function updateSelectAll() {
            var visible = [];
            rows.forEach(function(row) {
                if (row.style.display !== 'none') {
                    var cb = row.querySelector('.alert-checkbox');
                    if (cb) visible.push(cb);
                }
            });
            var allChecked = visible.length > 0 && visible.every(function(cb) {
                return cb.checked;
            });
            var someChecked = visible.some(function(cb) {
                return cb.checked;
            });
            selectAll.checked = allChecked;
            selectAll.indeterminate = !allChecked && someChecked;
        }

        rows.forEach(function(row) {
            var cb = row.querySelector('.alert-checkbox');
            if (cb) cb.addEventListener('change', updateSelectAll);
        });
    }
});
