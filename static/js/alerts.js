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
    var pdWidget = document.getElementById('pagerduty-widget');

    function showFeedback(message, isError) {
        var feedback = document.getElementById('pd-feedback');
        if (!feedback) return;
        feedback.textContent = message;
        feedback.className = 'pd-feedback ' + (isError ? 'error' : 'success');
    }

    function getCsrfToken() {
        var input = pdWidget.querySelector('[name="csrf-token"]');
        return input ? input.value : '';
    }

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function(k) {
                if (k === 'className') {
                    node.className = attrs[k];
                } else if (k === 'textContent') {
                    node.textContent = attrs[k];
                } else {
                    node.setAttribute(k, attrs[k]);
                }
            });
        }
        (children || []).forEach(function(c) {
            node.appendChild(c);
        });
        return node;
    }

    function buildFeedbackDiv() {
        return el('div', {
            id: 'pd-feedback',
            className: 'pd-feedback'
        });
    }

    function buildCsrfInput(csrfToken) {
        return el('input', {
            type: 'hidden',
            name: 'csrf-token',
            value: csrfToken
        });
    }

    function renderConfigured(csrfToken) {
        while (pdWidget.firstChild) {
            pdWidget.removeChild(pdWidget.firstChild);
        }

        pdWidget.appendChild(el('h4', {
            textContent: 'PagerDuty Integration'
        }));

        var badge = el('span', {
            className: 'alert-badge badge-present',
            textContent: 'Configured'
        });
        pdWidget.appendChild(el('div', {
            className: 'pd-status'
        }, [badge]));

        var form = el('form', {
            id: 'pd-form',
            className: 'pd-form'
        }, [
            buildCsrfInput(csrfToken),
            el('label', {
                for: 'pd-integration-key',
                textContent: 'Update Integration Key'
            }),
            el('input', {
                type: 'password',
                id: 'pd-integration-key',
                name: 'integration_key',
                placeholder: 'Enter new PagerDuty key'
            }),
            el('div', {
                className: 'pd-form-actions'
            }, [
                el('button', {
                    type: 'submit',
                    className: 'contained small',
                    textContent: 'Update'
                }),
                el('button', {
                    type: 'button',
                    className: 'text small pd-delete-btn',
                    id: 'pd-delete-btn',
                    textContent: 'Delete'
                })
            ])
        ]);
        pdWidget.appendChild(form);
        pdWidget.appendChild(buildFeedbackDiv());

        bindPdEvents();
    }

    function renderNotConfigured(csrfToken) {
        while (pdWidget.firstChild) {
            pdWidget.removeChild(pdWidget.firstChild);
        }

        pdWidget.appendChild(el('h4', {
            textContent: 'PagerDuty Integration'
        }));
        pdWidget.appendChild(el('span', {
            className: 'alert-badge badge-absent',
            textContent: 'Not Configured'
        }));

        var form = el('form', {
            id: 'pd-form',
            className: 'pd-form'
        }, [
            buildCsrfInput(csrfToken),
            el('label', {
                for: 'pd-integration-key',
                textContent: 'Integration Key'
            }),
            el('input', {
                type: 'password',
                id: 'pd-integration-key',
                name: 'integration_key',
                placeholder: 'Enter PagerDuty integration key',
                required: 'required'
            }),
            el('button', {
                type: 'submit',
                className: 'contained small',
                textContent: 'Create'
            })
        ]);
        pdWidget.appendChild(form);
        pdWidget.appendChild(buildFeedbackDiv());

        bindPdEvents();
    }

    function bindPdEvents() {
        var form = document.getElementById('pd-form');
        var deleteBtn = document.getElementById('pd-delete-btn');

        if (form) {
            form.addEventListener('submit', handleSave);
        }
        if (deleteBtn) {
            deleteBtn.addEventListener('click', handleDelete);
        }
    }

    function handleSave(e) {
        e.preventDefault();
        var form = document.getElementById('pd-form');
        var csrfToken = getCsrfToken();
        var integrationKey = form.querySelector('[name="integration_key"]').value;

        if (!integrationKey) {
            showFeedback('Integration key is required.', true);
            return;
        }

        var formData = new FormData();
        formData.append('integration_key', integrationKey);
        formData.append('csrf-token', csrfToken);

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
                renderConfigured(csrfToken);
                showFeedback('PagerDuty integration ' + result.data.status + ' successfully.', false);
            } else {
                showFeedback(result.data.error || 'An error occurred.', true);
            }
        }).catch(function() {
            showFeedback('Network error. Please try again.', true);
        });
    }

    function handleDelete() {
        if (!confirm('Are you sure you want to delete the PagerDuty integration?')) {
            return;
        }

        var csrfToken = getCsrfToken();
        var formData = new FormData();
        formData.append('csrf-token', csrfToken);

        fetch('/alerts/pagerduty/delete', {
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
                renderNotConfigured(csrfToken);
                showFeedback('PagerDuty integration deleted.', false);
            } else {
                showFeedback(result.data.error || 'An error occurred.', true);
            }
        }).catch(function() {
            showFeedback('Network error. Please try again.', true);
        });
    }

    if (pdWidget) {
        bindPdEvents();
    }
});
