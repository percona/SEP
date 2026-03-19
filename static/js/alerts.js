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

    function clearChildren(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    function clearResults() {
        if (!resultsContainer) return;
        clearChildren(resultsContainer);
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
        clearChildren(pdWidget);

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
        clearChildren(pdWidget);

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

    // Backup detail & restore functionality
    var restoreDialog = document.getElementById('dialog-restore-confirm');
    var detailDialog = document.getElementById('dialog-backup-detail');
    var feedback = document.getElementById('restore-feedback');
    var pendingRestoreId = null;

    function getBackupCsrfToken() {
        var input = document.getElementById('backup-csrf-token');
        return input ? input.value : '';
    }

    function buildDetailSection(title, items, renderItem) {
        var section = el('div', {
            className: 'backup-detail-section'
        }, [
            el('h4', {
                textContent: title + ' (' + items.length + ')'
            })
        ]);
        var list = el('ul');
        items.forEach(function(item) {
            list.appendChild(renderItem(item));
        });
        section.appendChild(list);
        return section;
    }

    document.querySelectorAll('.backup-detail-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var backupId = btn.getAttribute('data-backup-id');
            var backupDate = btn.getAttribute('data-backup-date');
            var dateSpan = document.getElementById('detail-date');
            var content = document.getElementById('detail-content');

            dateSpan.textContent = backupDate;
            clearChildren(content);
            content.appendChild(el('p', {
                className: 'text-muted',
                textContent: 'Loading\u2026'
            }));
            detailDialog.showModal();

            fetch('/alerts/backups/' + backupId).then(function(response) {
                if (!response.ok) throw new Error('Failed to load backup details');
                return response.json();
            }).then(function(data) {
                clearChildren(content);

                if (data.templates.length) {
                    content.appendChild(buildDetailSection('Templates', data.templates, function(t) {
                        var li = el('li', {
                            textContent: t.name
                        });
                        if (t.summary) {
                            li.appendChild(el('span', {
                                className: 'detail-type',
                                textContent: ' \u2014 ' + t.summary
                            }));
                        }
                        return li;
                    }));
                }

                if (data.rules.length) {
                    content.appendChild(buildDetailSection('Rules', data.rules, function(r) {
                        return el('li', {
                            textContent: r.title
                        });
                    }));
                }

                if (data.contact_points.length) {
                    content.appendChild(buildDetailSection('Contact Points', data.contact_points, function(cp) {
                        var li = el('li', {
                            textContent: cp.name
                        });
                        if (cp.type) {
                            li.appendChild(el('span', {
                                className: 'detail-type',
                                textContent: ' (' + cp.type + ')'
                            }));
                        }
                        return li;
                    }));
                }

                if (data.folders.length) {
                    content.appendChild(buildDetailSection('Folders', data.folders, function(f) {
                        return el('li', {
                            textContent: f.title
                        });
                    }));
                }

                if (data.notification_policy_receiver) {
                    var policySection = el('div', {
                        className: 'backup-detail-section'
                    }, [
                        el('h4', {
                            textContent: 'Notification Policy'
                        })
                    ]);
                    var policyList = el('ul');
                    var policyItem = el('li');
                    policyItem.appendChild(document.createTextNode('Receiver: '));
                    policyItem.appendChild(el('strong', {
                        textContent: data.notification_policy_receiver
                    }));
                    policyList.appendChild(policyItem);
                    policySection.appendChild(policyList);
                    content.appendChild(policySection);
                }

                if (!content.hasChildNodes()) {
                    content.appendChild(el('p', {
                        className: 'text-muted',
                        textContent: 'This backup is empty.'
                    }));
                }
            }).catch(function(err) {
                clearChildren(content);
                content.appendChild(el('p', {
                    className: 'text-muted',
                    textContent: 'Error: ' + err.message
                }));
            });
        });
    });

    document.querySelectorAll('.backup-restore-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            pendingRestoreId = btn.getAttribute('data-backup-id');
            var backupDate = btn.getAttribute('data-backup-date');
            document.getElementById('restore-confirm-date').textContent = backupDate;
            restoreDialog.showModal();
        });
    });

    var confirmBtn = document.getElementById('restore-confirm-btn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', function() {
            if (!pendingRestoreId) return;
            restoreDialog.close();

            feedback.textContent = 'Restoring\u2026';
            feedback.className = 'restore-feedback';

            var csrfToken = getBackupCsrfToken();
            var formData = new FormData();
            formData.append('backup_id', pendingRestoreId);
            formData.append('csrf-token', csrfToken);

            fetch('/alerts/restore', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRF-Token': csrfToken
                },
            }).then(function(response) {
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
            }).then(function(data) {
                if (data.status === 'success') {
                    var d = data.details;
                    feedback.className = 'restore-feedback feedback-success';
                    var msg = 'Restore complete: ' +
                        d.rules_deleted + ' rules deleted, ' +
                        d.rules_created + ' created';
                    if (d.rules_skipped > 0) {
                        msg += ', ' + d.rules_skipped + ' skipped';
                    }
                    msg += '. ' +
                        d.templates.created + ' templates created, ' +
                        d.templates.skipped + ' skipped.';
                    feedback.textContent = msg;
                } else {
                    feedback.className = 'restore-feedback feedback-error';
                    feedback.textContent = 'Restore failed: ' + (data.message || data.error || 'Unknown error');
                }
            }).catch(function(err) {
                feedback.className = 'restore-feedback feedback-error';
                feedback.textContent = 'Restore failed: ' + err.message;
            }).finally(function() {
                pendingRestoreId = null;
            });
        });
    }
});
