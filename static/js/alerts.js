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

    // Backup restore functionality
    var restoreForm = document.getElementById('restore-form');
    var restoreBtn = document.getElementById('restore-btn');
    var feedback = document.getElementById('restore-feedback');
    var radios = document.querySelectorAll('#restore-form input[type="radio"]');

    radios.forEach(function(radio) {
        radio.addEventListener('change', function() {
            if (restoreBtn) restoreBtn.disabled = false;
        });
    });

    if (restoreForm) {
        restoreForm.addEventListener('submit', function(e) {
            e.preventDefault();

            var selected = restoreForm.querySelector('input[name="backup_id"]:checked');
            if (!selected) return;

            if (!confirm('This will delete all existing alert rules and recreate them from the selected backup. Continue?')) {
                return;
            }

            restoreBtn.disabled = true;
            restoreBtn.textContent = 'Restoring\u2026';
            feedback.textContent = '';
            feedback.className = 'restore-feedback';

            var formData = new FormData();
            formData.append('backup_id', selected.value);

            var csrfInput = restoreForm.querySelector('input[name="csrf-token"]');
            var headers = {};
            if (csrfInput) {
                headers['X-CSRF-Token'] = csrfInput.value;
            }

            fetch('/alerts/restore', {
                    method: 'POST',
                    body: formData,
                    headers: headers,
                })
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    if (data.status === 'success') {
                        var d = data.details;
                        feedback.className = 'restore-feedback feedback-success';
                        feedback.textContent = 'Restore complete: ' +
                            d.rules_deleted + ' rules deleted, ' +
                            d.rules_created + ' created. ' +
                            d.templates.created + ' templates created, ' +
                            d.templates.skipped + ' skipped.';
                    } else {
                        feedback.className = 'restore-feedback feedback-error';
                        feedback.textContent = 'Restore failed: ' + (data.message || 'Unknown error');
                    }
                })
                .catch(function(err) {
                    feedback.className = 'restore-feedback feedback-error';
                    feedback.textContent = 'Restore failed: ' + err.message;
                })
                .finally(function() {
                    restoreBtn.disabled = false;
                    restoreBtn.textContent = 'Restore';
                });
        });
    }
});
