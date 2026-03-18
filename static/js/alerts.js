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

    // PagerDuty widget
    var pdWidget = document.getElementById('pagerduty-widget');

    function showFeedback(message, isError) {
        var feedback = document.getElementById('pd-feedback');
        if (!feedback) return;
        feedback.textContent = message;
        feedback.className = 'pd-feedback ' + (isError ? 'error' : 'success');
    }

    function getPdCsrfToken() {
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
        var csrfToken = getPdCsrfToken();
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

        var csrfToken = getPdCsrfToken();
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
                formData.append('csrf-token', csrfInput.value);
                headers['X-CSRF-Token'] = csrfInput.value;
            }

            fetch('/alerts/restore', {
                    method: 'POST',
                    body: formData,
                    headers: headers,
                })
                .then(function(response) {
                    if (!response.ok) {
                        return response.json().catch(function() {
                            return {
                                status: 'error',
                                message: 'Request failed with status ' + response.status
                            };
                        }).then(function(data) {
                            if (data.status === 'error') return data;
                            return {
                                status: 'error',
                                message: data.message || data.error || 'Request failed'
                            };
                        });
                    }
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
                        feedback.textContent = 'Restore failed: ' + (data.message || data.error || 'Unknown error');
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
