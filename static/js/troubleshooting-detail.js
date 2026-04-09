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

/**
 * AJAX snippet execution, polling, and output rendering for the
 * Alert Troubleshooting detail page.
 */
(function() {
    'use strict';

    var POLL_INITIAL_MS = 2000;
    var POLL_BACKOFF_MS = 5000;
    var BACKOFF_AFTER_MS = 30000;
    var HOSTNAME_FIELD = '-hostname-';

    function getBaseUri() {
        var cards = document.querySelector('.at-snippet-cards[data-base-uri]');
        if (cards && cards.dataset.baseUri) return cards.dataset.baseUri;
        var path = window.location.pathname;
        var parts = path.split('/');
        parts.pop();
        return parts.join('/');
    }

    function getSharedHost() {
        var sel = document.getElementById('atSharedHost');
        return sel ? sel.value : '';
    }

    function setCardState(card, state, message) {
        var feedback = card.querySelector('.at-run-feedback');
        if (!feedback) {
            feedback = document.createElement('div');
            feedback.className = 'at-run-feedback';
            var formSection = card.querySelector('.at-snippet-form');
            if (formSection) {
                formSection.appendChild(feedback);
            }
        }
        feedback.className = 'at-run-feedback';
        if (state === 'error') {
            feedback.classList.add('at-run-error');
        } else if (state === 'success') {
            feedback.classList.add('at-run-success');
        }
        feedback.textContent = message || '';
    }

    function setButtonLoading(form, loading) {
        var btn = form.querySelector('button[type="submit"]');
        if (!btn) return;
        btn.disabled = loading;
        if (loading) {
            btn.dataset.originalHtml = btn.innerHTML;
            btn.textContent = 'Running…';
            form.classList.add('at-run-loading');
        } else {
            if (btn.dataset.originalHtml) {
                btn.innerHTML = btn.dataset.originalHtml;
            }
            form.classList.remove('at-run-loading');
        }
    }

    function showOutput(card, text) {
        var area = card.querySelector('.at-output-area');
        var pre = card.querySelector('.at-output-pre');
        if (!area || !pre) return;
        area.style.display = '';
        pre.textContent = text;
        pre.scrollTop = pre.scrollHeight;
    }

    function pollOutput(card, form, taskId) {
        var baseUri = getBaseUri();
        var startTime = Date.now();

        function doPoll() {
            fetch(baseUri + '/output/' + encodeURIComponent(taskId), {
                credentials: 'include'
            }).then(function(res) {
                if (!res.ok) {
                    throw new Error('Server returned ' + res.status);
                }
                return res.json();
            }).then(function(data) {
                if (data.output) {
                    showOutput(card, data.output);
                }
                if (data.status === 'running' || data.status === 'pending') {
                    var elapsed = Date.now() - startTime;
                    var interval = elapsed > BACKOFF_AFTER_MS ? POLL_BACKOFF_MS : POLL_INITIAL_MS;
                    setTimeout(doPoll, interval);
                } else {
                    if (!data.output && data.error) {
                        showOutput(card, data.error);
                    } else if (!data.output) {
                        showOutput(card, '');
                    }
                    setButtonLoading(form, false);
                    if (data.status === 'success') {
                        setCardState(card, 'success', 'Completed');
                    } else if (data.status === 'failed') {
                        setCardState(card, 'error', 'Execution failed');
                    } else if (data.status === 'stopped') {
                        setCardState(card, 'error', 'Execution stopped');
                    } else {
                        setCardState(card, 'error', 'Unexpected status: ' + data.status);
                    }
                }
            }).catch(function() {
                setButtonLoading(form, false);
                setCardState(card, 'error', 'Failed to retrieve output');
            });
        }

        doPoll();
    }

    function handleFormSubmit(e) {
        e.preventDefault();
        var form = e.target;
        var card = form.closest('.at-snippet-card');
        if (!card) return;

        var host = getSharedHost();
        if (!host) {
            setCardState(card, 'error', 'Please select an executor host');
            return;
        }

        setCardState(card, '', '');
        setButtonLoading(form, true);

        var formData = new FormData(form);
        formData.set(HOSTNAME_FIELD, host);

        fetch(form.action, {
            method: 'POST',
            body: formData,
            credentials: 'include'
        }).then(function(res) {
            return res.json().then(function(data) {
                return {
                    ok: res.ok,
                    data: data
                };
            });
        }).then(function(result) {
            if (!result.ok || result.data.error) {
                setButtonLoading(form, false);
                setCardState(card, 'error', result.data.error || 'Execution failed');
                return;
            }
            showOutput(card, 'Running…');
            pollOutput(card, form, result.data.task_id);
        }).catch(function() {
            setButtonLoading(form, false);
            setCardState(card, 'error', 'Network error');
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.at-snippet-card form').forEach(function(form) {
            form.addEventListener('submit', handleFormSubmit);
        });
    });
})();
