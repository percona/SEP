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
    var pushBtn = document.getElementById('push-to-pmm');
    var resultsContainer = document.getElementById('push-results');

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
                }
            });

            if (selectAll) selectAll.checked = false;
            updatePushButton();
        });
    });

    if (selectAll) {
        selectAll.addEventListener('change', function() {
            var checked = selectAll.checked;
            rows.forEach(function(row) {
                if (row.style.display !== 'none') {
                    var cb = row.querySelector('.alert-checkbox');
                    if (cb) cb.checked = checked;
                }
            });
            updatePushButton();
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
            if (cb) {
                cb.addEventListener('change', function() {
                    updateSelectAll();
                    updatePushButton();
                });
            }
        });
    }

    function getSelectedNames() {
        var names = [];
        rows.forEach(function(row) {
            var cb = row.querySelector('.alert-checkbox');
            if (cb && cb.checked) names.push(cb.value);
        });
        return names;
    }

    function updatePushButton() {
        if (!pushBtn) return;
        var selected = getSelectedNames();
        if (selected.length > 0) {
            pushBtn.style.display = '';
            pushBtn.disabled = false;
        } else {
            pushBtn.style.display = 'none';
            pushBtn.disabled = true;
        }
    }

    function getCsrfToken() {
        var input = document.querySelector('input[name="csrf-token"]');
        if (input) return input.value;
        return '';
    }

    function updateBadge(templateName, newStatus) {
        rows.forEach(function(row) {
            var cb = row.querySelector('.alert-checkbox');
            if (cb && cb.value === templateName) {
                var badges = row.querySelectorAll('.alert-badge');
                badges.forEach(function(badge) {
                    if (badge.classList.contains('badge-absent') ||
                        badge.classList.contains('badge-unknown')) {
                        if (newStatus === 'success') {
                            badge.className = 'alert-badge badge-present';
                            badge.textContent = 'Present';
                        }
                    }
                });
            }
        });
    }

    function clearResults() {
        if (!resultsContainer) return;
        while (resultsContainer.firstChild) {
            resultsContainer.removeChild(resultsContainer.firstChild);
        }
    }

    function showResults(results) {
        if (!resultsContainer) return;
        clearResults();
        results.forEach(function(r) {
            var el = document.createElement('div');
            el.className = 'push-result push-result-' + r.status;
            el.textContent = r.name + ': ' + r.message;
            resultsContainer.appendChild(el);
        });
        resultsContainer.style.display = '';
    }

    if (pushBtn) {
        pushBtn.addEventListener('click', function() {
            var selected = getSelectedNames();
            if (selected.length === 0) return;

            pushBtn.disabled = true;
            pushBtn.textContent = 'Pushing...';

            var formData = new FormData();
            selected.forEach(function(name) {
                formData.append('selected_templates', name);
            });
            formData.append('csrf-token', getCsrfToken());

            fetch('/alerts/push', {
                method: 'POST',
                body: formData,
            }).then(function(response) {
                return response.json();
            }).then(function(data) {
                if (data.results) {
                    showResults(data.results);
                    data.results.forEach(function(r) {
                        if (r.status === 'success') {
                            updateBadge(r.name, 'success');
                        }
                    });
                } else if (data.error || data.detail) {
                    showResults([{
                        name: 'Error',
                        status: 'error',
                        message: data.error || data.detail
                    }]);
                }
            }).catch(function(err) {
                showResults([{
                    name: 'Error',
                    status: 'error',
                    message: 'Network error: ' + err.message
                }]);
            }).finally(function() {
                pushBtn.disabled = false;
                pushBtn.textContent = 'Push to PMM';
                updatePushButton();
            });
        });
    }

    updatePushButton();
});
