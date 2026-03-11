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

    // PagerDuty widget
    var pdForm = document.getElementById('pd-form');
    var pdFeedback = document.getElementById('pd-feedback');
    var pdRevealBtn = document.getElementById('pd-reveal-btn');
    var pdMaskedKey = document.getElementById('pd-masked-key');
    var pdDeleteBtn = document.getElementById('pd-delete-btn');

    function showFeedback(message, isError) {
        if (!pdFeedback) return;
        pdFeedback.textContent = message;
        pdFeedback.className = 'pd-feedback ' + (isError ? 'error' : 'success');
    }

    if (pdForm) {
        pdForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var csrfToken = pdForm.querySelector('[name="csrf-token"]').value;
            var integrationKey = pdForm.querySelector('[name="integration_key"]').value;

            if (!integrationKey) {
                showFeedback('Integration key is required.', true);
                return;
            }

            var formData = new FormData();
            formData.append('integration_key', integrationKey);

            fetch('/alerts/pagerduty', {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': csrfToken
                },
                body: formData
            }).then(function(response) {
                return response.json().then(function(data) {
                    return {
                        ok: response.ok,
                        data: data
                    };
                });
            }).then(function(result) {
                if (result.ok) {
                    showFeedback('PagerDuty integration ' + result.data.status + ' successfully.', false);
                    if (pdMaskedKey) {
                        pdMaskedKey.textContent = result.data.masked_key;
                    }
                    pdForm.querySelector('[name="integration_key"]').value = '';
                    setTimeout(function() {
                        window.location.reload();
                    }, 1500);
                } else {
                    showFeedback(result.data.error || 'An error occurred.', true);
                }
            }).catch(function() {
                showFeedback('Network error. Please try again.', true);
            });
        });
    }

    if (pdRevealBtn && pdMaskedKey) {
        var revealed = false;
        var originalText = pdMaskedKey.textContent;

        pdRevealBtn.addEventListener('click', function() {
            if (revealed) {
                pdMaskedKey.textContent = originalText;
                pdRevealBtn.querySelector('.material-symbols-outlined').textContent = 'visibility';
                revealed = false;
                return;
            }

            fetch('/alerts/pagerduty/token').then(function(response) {
                if (!response.ok) {
                    showFeedback('Failed to retrieve token.', true);
                    return null;
                }
                return response.json();
            }).then(function(data) {
                if (data && data.token) {
                    pdMaskedKey.textContent = data.token;
                    pdRevealBtn.querySelector('.material-symbols-outlined').textContent = 'visibility_off';
                    revealed = true;
                }
            }).catch(function() {
                showFeedback('Network error. Please try again.', true);
            });
        });
    }

    if (pdDeleteBtn) {
        pdDeleteBtn.addEventListener('click', function() {
            if (!confirm('Are you sure you want to delete the PagerDuty integration?')) {
                return;
            }

            var csrfToken = pdForm.querySelector('[name="csrf-token"]').value;

            fetch('/alerts/pagerduty/delete', {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': csrfToken
                }
            }).then(function(response) {
                return response.json().then(function(data) {
                    return {
                        ok: response.ok,
                        data: data
                    };
                });
            }).then(function(result) {
                if (result.ok) {
                    showFeedback('PagerDuty integration deleted.', false);
                    setTimeout(function() {
                        window.location.reload();
                    }, 1500);
                } else {
                    showFeedback(result.data.error || 'An error occurred.', true);
                }
            }).catch(function() {
                showFeedback('Network error. Please try again.', true);
            });
        });
    }
});
