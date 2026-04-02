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
    function formatBytes(bytes) {
        if (!Number.isFinite(bytes) || bytes < 0) return String(bytes || 0);
        const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        let i = 0,
            val = bytes;
        while (val >= 1024 && i < units.length - 1) {
            val /= 1024;
            i++;
        }
        return `${val.toFixed(val < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
    }

    function parseFileMeta(meta) {
        if (meta && typeof meta === 'object') {
            return {
                size: Number(meta.size) || 0,
                isDir: Boolean(meta.is_dir || meta.isDir),
            };
        }
        return {
            size: Number(meta) || 0,
            isDir: false,
        };
    }

    function filesApiUrl(taskId) {
        return `/files/${encodeURIComponent(taskId)}`;
    }

    function buildExecutorGoneMessage(detail) {
        const $block = $('<div class="sep-stream-error sep-stream-error--gone" role="alert"></div>');
        const summary =
            (detail && detail.message) ||
            'This run is no longer available in the task executor.';
        $block.append($('<p class="sep-stream-error__summary"></p>').text(summary));
        const rows = [];
        if (detail.resource_type) {
            rows.push(['Resource type', detail.resource_type]);
        }
        if (detail.resource_id) {
            rows.push(['Resource', detail.resource_id]);
        }
        if (detail.job_id) {
            rows.push(['Job ID', detail.job_id]);
        }
        if (detail.evaluation_id) {
            rows.push(['Evaluation ID', detail.evaluation_id]);
        }
        if (detail.executor_name) {
            rows.push(['Executor', detail.executor_name]);
        }
        if (rows.length) {
            const $ul = $('<ul class="sep-stream-error__meta"></ul>');
            for (const [k, v] of rows) {
                const $li = $('<li></li>');
                $li.append($('<strong></strong>').text(`${k}: `));
                $li.append(document.createTextNode(String(v)));
                $ul.append($li);
            }
            $block.append($ul);
        }
        if (detail.detail && String(detail.detail) !== summary) {
            $block.append(
                $('<p class="sep-stream-error__nomad"></p>').text(String(detail.detail))
            );
        }
        return $block;
    }

    function fileDownloadUrl(taskId, relPath) {
        return `/files/${encodeURIComponent(taskId)}/download?path=${encodeURIComponent(relPath)}`;
    }

    function updateFileRowDisplay($row) {
        const rawSize = $row.data('file-size');
        const size = Number(rawSize);
        const isDir = String($row.data('file-is-dir')).toLowerCase() === 'true';

        const $nameCell = $row.find('.file-name');
        const rawName = $nameCell.text().replace(/\/$/, '');
        $nameCell.text(isDir ? `${rawName}/` : rawName);

        if (isDir) {
            $row.find('.file-size').text('Folder');
            return;
        }

        const normalizedSize = Number.isFinite(size) ? size : Number(rawSize || 0);
        $row.find('.file-size').text(formatBytes(normalizedSize));
    }

    function ensureFilesModal(taskId, filesMap, taskName) {
        let $modal = $(`#modal-files-${taskId}`);
        if ($modal.length === 0) {
            const rows = Object.entries(filesMap).map(([filename, meta]) => {
                const {
                    size,
                    isDir
                } = parseFileMeta(meta);
                const safeName = $('<div>').text(filename).html();
                const displayName = isDir ? `${safeName}/` : safeName;
                const humanSize = isDir ? 'Folder' : formatBytes(size);

                return `
          <tr data-task-id="${taskId}"
              data-file-name="${safeName}"
              data-file-size="${Number(size)}"
              data-file-is-dir="${isDir}">
            <td class="file-name code">${displayName}</td>
            <td class="file-size number code">${humanSize}</td>
            <td class="options">
              <button type="button" class="icon medium download-file-button"
                      aria-label="Download ${$('<div>').text(filename).html()}">
                <span class="material-symbols-outlined">file_download</span>
              </button>
            </td>
          </tr>
        `;
            }).join('');

            const html = `
          <section>
            <dialog id="modal-files-${taskId}" aria-modal="true"
                    aria-labelledby="modal-files-title-${taskId}"
                    class="fullwidth modal-files">
              <div class="window">
                <header>
                  <h3 id="modal-files-title-${taskId}" class="h5 title">
                    Files for ${$('<div>').text(taskName || '').html()}
                  </h3>
                </header>
                <section class="files-list">
                  <table class="files-table">
                    <thead>
                      <tr><th>File</th><th class="number">Size</th><th class="options">Download</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                  </table>
                </section>
                <footer>
                  <button type="button" class="text large" data-modal-close>
                    Close<sup>ESC</sup>
                  </button>
                </footer>
              </div>
            </dialog>
          </section>
        `;
            const $anchor = $(`dialog#modal-${taskId}`).parent().length ?
                $(`dialog#modal-${taskId}`).parent() :
                $('body');
            $anchor.append(html);
            $modal = $(`#modal-files-${taskId}`);
        }

        $modal.find('tbody tr').each(function() {
            updateFileRowDisplay($(this));
        });

        return $modal;
    }

    function openDialog(id) {
        const el = document.getElementById(id);
        if (el && typeof el.showModal === 'function') el.showModal();
    }

    function closeDialog(el) {
        if (el && typeof el.close === 'function') el.close();
    }

    $('.modal-files').each(function() {
        $(this).find('tbody tr').each(function() {
            updateFileRowDisplay($(this));
        });
    });

    $(document).on('click', '.download-file-button', function() {
        const $btn = $(this);

        if ($btn.data('loading') === true) return;

        const $row = $btn.closest('tr');
        const taskId = $row.data('task-id');
        const filename = String($row.data('file-name') || '');
        const isDir = String($row.data('file-is-dir')).toLowerCase() === 'true';
        if (!taskId || !filename) return;

        $btn.data('loading', true)
            .attr('aria-disabled', 'true')
            .prop('disabled', true)
            .addClass('loading')
            .html(`
            <span class="material-symbols-outlined" aria-hidden="true">hourglass_top</span>
            <span class="label">Preparing download</span>
          `);

        $row.attr('aria-busy', 'true');

        const url = `/files/${encodeURIComponent(taskId)}/download?path=${encodeURIComponent(filename)}`;
        const a = document.createElement('a');
        a.href = url;
        const baseName = filename.split('/').pop();
        a.download = isDir ? `${baseName}.tar.gz` : baseName;
        document.body.appendChild(a);
        a.click();
        a.remove();

        // Reset button after download has been triggered (no reliable "download started" event)
        const ariaLabel = $btn.attr('aria-label') || `Download ${filename}`;
        setTimeout(function() {
            $btn.data('loading', false)
                .attr('aria-disabled', 'false')
                .prop('disabled', false)
                .removeClass('loading')
                .attr('aria-label', ariaLabel)
                .html('<span class="material-symbols-outlined">file_download</span>');
            $row.removeAttr('aria-busy');
        }, 1500);
    });

    $(document).on('click', '.view-files-button', function() {
        const target = $(this).attr('data-modal-target');
        if (target) openDialog(target);
    });



    const lastOffsets = {};
    const loadedCompletedTasks = new Set();
    const executionEventsFetched = new Set();
    const executionEventsStreams = {};
    const executionEventsCache = {};

    function executionEventKey(ev) {
        return JSON.stringify({
            timestamp: ev && ev.timestamp,
            type: ev && ev.type,
            description: ev && ev.description,
            step: ev && ev.step,
        });
    }

    function appendExecutionEvent(taskId, eventObj) {
        executionEventsCache[taskId] = executionEventsCache[taskId] || [];
        const exists = executionEventsCache[taskId].some(function(item) {
            return executionEventKey(item) === executionEventKey(eventObj);
        });
        if (!exists) {
            executionEventsCache[taskId].push(eventObj);
        }
    }

    function closeExecutionEventsStream(taskId) {
        const src = executionEventsStreams[taskId];
        if (src) {
            src.close();
            delete executionEventsStreams[taskId];
        }
    }

    function shouldFetchExecutionEvents($logConsole) {
        const status = String($logConsole.data('task-status') || '').toLowerCase();
        const logsPresent = String($logConsole.data('logs-present')).toLowerCase() !== 'false';
        return (
            status === 'running' ||
            status === 'failed' ||
            status === 'lost' ||
            status === 'stopped' ||
            !logsPresent
        );
    }

    function getSelectedLogStepName($logConsole) {
        const $tab = $logConsole.find('.log-footer .log-step-tab.selected');
        if ($tab.length) {
            return String($tab.attr('data-step-name') || $tab.data('step-name') || '');
        }
        const $first = $logConsole.find('.log-footer .log-step-tab').first();
        return $first.length ?
            String($first.attr('data-step-name') || $first.data('step-name') || '') :
            '';
    }

    /** Show the execution-events panel for the bottom step tab that is selected (or first panel). */
    function syncExecutionEventsStepVisibility($logConsole) {
        const $view = $logConsole.find('.log-events-view');
        if ($view.length === 0) return;
        const stepName = getSelectedLogStepName($logConsole);
        const $panels = $view.find('.log-events-step-panel');
        const $missing = $view.find('.log-events-step-missing');
        $panels.hide();
        $missing.hide();
        if ($panels.length === 0) {
            return;
        }
        if (!stepName) {
            $panels.first().show();
            return;
        }
        let found = false;
        $panels.each(function() {
            const $p = $(this);
            if ($p.attr('data-step-name') === stepName) {
                $p.show();
                found = true;
                return false;
            }
        });
        if (!found) {
            $missing.show();
        }
    }

    function buildExecutionEventsUi($logConsole, taskId, events) {
        const $stderrTab = $logConsole.find('[role="log-tab"][aria-controls*="stderr"]');
        if ($stderrTab.length === 0) return;

        let $eventsTab = $logConsole.find('#tab-events-' + taskId);
        if ($eventsTab.length === 0) {
            $eventsTab = $(
                '<button type="button" class="large" role="log-tab" aria-selected="false">' +
                '<span class="label">Execution events</span></button>'
            );
            $eventsTab.attr('id', 'tab-events-' + taskId);
            $eventsTab.attr('aria-controls', 'log-events-' + taskId);
            $stderrTab.after($eventsTab);
        }

        let $panel = $logConsole.find('#log-events-' + taskId);
        if ($panel.length === 0) {
            $panel = $('<div class="log-events-view"></div>');
            $panel.attr('id', 'log-events-' + taskId);
            $panel.attr('aria-label', 'Execution events');
            $panel.attr('role', 'region');
            $panel.append('<div class="log-events-step-panels"></div>');
            $panel.append(
                $('<div class="log-events-step-missing"></div>').text(
                    'No execution events for this step.'
                )
            );
            $logConsole.find('.log-content').append($panel);
            $panel.hide();
        }

        const $wrap = $panel.find('.log-events-step-panels');
        $wrap.empty();

        const stepOrder = [];
        const byStep = {};
        (Array.isArray(events) ? events : []).forEach(function(ev) {
            const s = ev.step != null && String(ev.step) !== '' ? String(ev.step) : '';
            const key = s || '_';
            if (!byStep[key]) {
                byStep[key] = [];
                stepOrder.push(key);
            }
            byStep[key].push(ev);
        });

        stepOrder.forEach(function(key) {
            const list = byStep[key];
            const dataStep = key === '_' ? '' : key;
            const $section = $('<section class="log-events-step log-events-step-panel"></section>');
            $section.attr('data-step-name', dataStep);
            const $ol = $('<ol class="log-events-step__list"></ol>');
            list.forEach(function(ev) {
                const ts = ev.timestamp != null ? String(ev.timestamp) : '';
                const st = ev.step != null && String(ev.step) !== '' ? String(ev.step) : '';
                const typ = ev.type != null ? String(ev.type) : '';
                const desc = ev.description != null ? String(ev.description) : '';
                const body = st ? typ + '[' + st + '] ' + desc : typ + ' ' + desc;
                const $li = $('<li class="log-events-step__item"></li>');
                $li.append(
                    $('<time class="log-events-step__time relativeTime code"></time>')
                    .attr('datetime', ts)
                    .text(ts)
                );
                $li.append($('<div class="log-events-step__body code"></div>').text(body));
                $ol.append($li);
            });
            $section.append($ol);
            $wrap.append($section);
        });

        if (stepOrder.length === 0) {
            $panel.find('.log-events-step-missing').text('No execution events yet.');
        } else {
            $panel.find('.log-events-step-missing').text('No execution events for this step.');
        }

        syncExecutionEventsStepVisibility($logConsole);
    }

    function fetchExecutionEventsIfNeeded($logConsole, taskId) {
        if (!shouldFetchExecutionEvents($logConsole)) return;
        const status = String($logConsole.data('task-status') || '').toLowerCase();
        const isRunning = status === 'running';
        if (isRunning) {
            if (executionEventsStreams[taskId]) return;
            executionEventsCache[taskId] = executionEventsCache[taskId] || [];
            buildExecutionEventsUi($logConsole, taskId, executionEventsCache[taskId]);
            const src = new EventSource(
                `/stream-logs/${encodeURIComponent(taskId)}/execution-events`
            );
            executionEventsStreams[taskId] = src;
            const $logDialog = $logConsole.closest('dialog');
            if ($logDialog.length) {
                $logDialog[0].addEventListener(
                    'close',
                    function() {
                        closeExecutionEventsStream(taskId);
                    }, {
                        once: true
                    }
                );
            }
            src.onmessage = function(event) {
                let payload;
                try {
                    payload = JSON.parse(event.data);
                } catch (e) {
                    console.warn('Invalid execution event payload:', event.data);
                    return;
                }
                appendExecutionEvent(taskId, payload);
                buildExecutionEventsUi($logConsole, taskId, executionEventsCache[taskId]);
                if (!$logConsole.parent().prop('open')) {
                    closeExecutionEventsStream(taskId);
                }
            };
            src.addEventListener('finish', function() {
                closeExecutionEventsStream(taskId);
            });
            src.addEventListener('sep-error', function() {
                closeExecutionEventsStream(taskId);
            });
            src.onerror = function() {
                if (!$logConsole.parent().prop('open')) {
                    closeExecutionEventsStream(taskId);
                }
            };
            return;
        }
        if (executionEventsFetched.has(taskId)) return;
        fetch(`/execution-events/${encodeURIComponent(taskId)}`, {
                credentials: 'include',
            })
            .then(function(res) {
                return res.ok ? res.json() : [];
            })
            .then(function(events) {
                executionEventsCache[taskId] = Array.isArray(events) ? events : [];
                buildExecutionEventsUi($logConsole, taskId, executionEventsCache[taskId]);
                executionEventsFetched.add(taskId);
            })
            .catch(function() {
                executionEventsFetched.add(taskId);
            });
    }

    window.clearLoadedTasks = function() {
        loadedCompletedTasks.clear();
        executionEventsFetched.clear();
        Object.keys(executionEventsStreams).forEach(closeExecutionEventsStream);
    };

    $('.view-logs-button').click(function() {
        const taskId = $(this).data('task-id');
        const $logConsole = $(`.log-console.streaming-console[data-task-id=${taskId}]`);

        fetchExecutionEventsIfNeeded($logConsole, taskId);

        if (loadedCompletedTasks.has(taskId)) {
            if ($logConsole.find('.log-content').children().length === 0) {
                $logConsole.find('.log-content').html('<div class="log-info">Logs already loaded</div>');
            }
            return;
        }

        if ($logConsole.find('.log-step-content').length > 0) {
            loadedCompletedTasks.add(taskId);
            return;
        }

        lastOffsets[taskId] = lastOffsets[taskId] || {};

        const offsetQueryParams = Object.entries(lastOffsets[taskId]).map(
            ([key, offset]) => `${encodeURIComponent(key)}_offset=${encodeURIComponent(offset)}`
        );
        const offsetQueryString = offsetQueryParams.join('&');

        const eventSource = new EventSource(`/stream-logs/${taskId}?${offsetQueryString}`);
        eventSource.onmessage = function(event) {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (e) {
                console.warn("Non-JSON log chunk, ignoring:", event.data);
                return;
            }
            console.log(`Received log message for task ${taskId}:`, data);

            const {
                msg,
                step,
                type,
                offset
            } = data;

            if (!msg || !step || !type || offset === undefined) {
                console.warn("Ignoring malformed log chunk, missing fields:", data);
                return;
            }

            const offsetKey = `${step}_${type}`;
            if (offset <= (lastOffsets[taskId][offsetKey] || 0)) return;
            lastOffsets[taskId][offsetKey] = offset;



            if ($logConsole.find('.log-step-content[data-step-name="' + step + '"]').length === 0) {
                const stepTab = $('<button type="button" class="text large log-step-tab" data-step-name="' + step + '">' + step + '</button>');
                $logConsole.find('.log-footer .log-tabs').append(stepTab);

                if ($logConsole.find('.log-step-tab').length === 1) stepTab.addClass('selected');

                const stepContent = $('<div class="log-step-content" data-step-name="' + step + '"></div>');
                if ($logConsole.find('.log-step-content').length === 0) stepContent.show();
                else stepContent.hide();

                const stdoutPre = $('<pre class="log-output" data-soft-wrap="container" data-log-type="stdout" style="display: none;"></pre>');
                const stderrPre = $('<pre class="log-output" data-soft-wrap="container" data-log-type="stderr" style="display: none;"></pre>');

                const $checkbox = $logConsole.find('.word-wrap-checkbox');
                if ($checkbox.is(':checked')) {
                    stdoutPre.addClass('soft-wrap');
                    stderrPre.addClass('soft-wrap');
                }

                const selectedTab = $logConsole.find('[role="log-tab"][aria-selected="true"]');
                const selectedLogType = selectedTab.attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';
                if (selectedLogType === 'stdout') stdoutPre.show();
                else stderrPre.show();

                stepContent.append(stdoutPre);
                stepContent.append(stderrPre);
                $logConsole.find('.log-content').append(stepContent);

                const topControlsAfterStep =
                    $logConsole.find('[role="log-tab"][aria-selected="true"]').attr('aria-controls') || '';
                if (topControlsAfterStep.indexOf('log-events') === 0) {
                    syncExecutionEventsStepVisibility($logConsole);
                }
            }

            const $pre = $logConsole.find('.log-step-content[data-step-name="' + step + '"] .log-output[data-log-type="' + type + '"]');
            $pre.append(document.createTextNode(msg));

            const $logContent = $logConsole.find('.log-content');
            $logContent.scrollTop($logContent[0].scrollHeight);

            const selectedTabType = $logConsole.find('[role="log-tab"][aria-selected="true"]').attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';
            if (type !== selectedTabType) {
                $logConsole.find('[role="log-tab"][aria-controls="log-' + type + '-' + taskId + '"]').addClass('tab-notification');
            }

            const selectedStep = $logConsole.find('.log-step-tab.selected').data('step-name');
            if (step !== selectedStep) {
                $logConsole.find('.log-step-tab[data-step-name="' + step + '"]').addClass('tab-notification');
            }

            console.log(`Log console is open: ${$logConsole.parent().prop('open')}`);
            if (!$logConsole.parent().prop('open')) {
                eventSource.close();
            }
        };

        eventSource.addEventListener('finish', function(event) {
            eventSource.close();
            const finishData = JSON.parse(event.data);

            if (lastOffsets[taskId] === 0) {
                setTimeout(() => {
                    window.location.reload()
                }, 5000);
            } else {
                console.log(`Log stream for ${taskId} finished`);

                const statusClass = finishData.status;
                if (finishData.status === 'success') {
                    var icon = 'check';
                    var label = 'Done';
                } else if (finishData.status === 'stopped') {
                    var icon = 'cancel';
                    var label = 'Stopped';
                } else if (finishData.status === 'lost') {
                    var icon = 'question_mark';
                    var label = 'Lost';
                } else {
                    var icon = 'report';
                    var label = 'Failed';
                }

                const statusEl = $(`
                    <div class="status">
                        <div class="${statusClass}">
                            <span class="badge material-symbols-outlined">${icon}</span>
                            <span class="label">${label}</span>
                        </div>
                    </div>
                `);

                (async () => {
                    try {
                        const res = await fetch(`/files/${encodeURIComponent(taskId)}`, {
                            credentials: 'include'
                        });
                        if (!res.ok) return;
                        const filesMap = await res.json();
                        if (!filesMap || Object.keys(filesMap).length === 0) return;

                        const taskName = $logConsole.find('h3.title').text().replace(/^Logs for\s+/, '');
                        ensureFilesModal(taskId, filesMap, taskName);

                        const existingBtn = $logConsole.find('.log-header .view-files-from-log-button');
                        if (existingBtn.length === 0) {
                            const btn = $(`
                          <button type="button"
                                  class="icon medium view-files-from-log-button"
                                  title="View & download files"
                                  aria-label="View & download files"
                                  data-modal-target="modal-files-${taskId}">
                            <span class="material-symbols-outlined">download</span>
                          </button>
                        `);
                            $logConsole.find('.log-header .tabs').append(btn);
                        }

                        $logConsole.on('click', '.view-files-from-log-button', function() {
                            const filesModalId = $(this).attr('data-modal-target');
                            closeDialog($logConsole.closest('dialog')[0]);
                            openDialog(filesModalId);
                        });
                    } catch (err) {
                        console.warn('Could not load files list after finish:', err);
                    }
                })();

                $logConsole.find('.log-footer .log-tabs').append(statusEl);
                $logConsole.addClass(finishData.status);
                delete lastOffsets[taskId];

                loadedCompletedTasks.add(taskId);
            }
        });

        eventSource.addEventListener('sep-error', function(event) {
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch {
                payload = {
                    detail: String(event.data || 'Unknown error')
                };
            }
            console.error(`SSE server error for task ${taskId}:`, payload);

            const code = payload.code;
            const detail = payload.detail;

            const $logContent = $logConsole.find('.log-content');
            if (code === 410 && detail && typeof detail === 'object') {
                $logContent.prepend(buildExecutorGoneMessage(detail));
            } else {
                const text =
                    typeof detail === 'string' ?
                    detail :
                    detail != null ?
                    JSON.stringify(detail, null, 2) :
                    'Unknown stream error';
                $logContent.prepend(
                    $('<div class="sep-stream-error" role="alert"></div>').append(
                        $('<pre class="sep-stream-error__raw"></pre>').text(text)
                    )
                );
            }
            $logContent.scrollTop(0);

            const isGone = code === 410;
            const label = isGone ? 'Not in executor' : 'Stream error';
            const icon = isGone ? 'cloud_off' : 'chat_error';

            const statusEl = $(`
                    <div class="status">
                        <div class="failed">
                            <span class="badge material-symbols-outlined">${icon}</span>
                            <span class="label">${label}</span>
                        </div>
                    </div>
                `);

            $logConsole.find('.log-footer .log-tabs').append(statusEl);
            $logConsole.addClass('failed');

            eventSource.close();
        });

        eventSource.onerror = function(e) {
            console.error(`Error receiving SSE for task ${taskId}:`, e);
            if (lastOffsets[taskId] === 0) {
                eventSource.close();
                setTimeout(() => {
                    window.location.reload()
                }, 5000);
            }
        };
    });

    $('.logs-button').click(function() {
        const logId = $(this).data('log-id');
        const logRow = $('tr.log-row[data-log-id="' + logId + '"]');
        logRow.toggle();
        const button = $(this);
        if (logRow.is(':visible')) {
            button.text('visibility_off');
        } else {
            button.text('visibility');
        }
    });

    $(document).on('change', '.word-wrap-checkbox', function() {
        const $this = $(this);
        const $logConsole = $this.closest('.log-console');
        if ($this.is(':checked')) {
            $logConsole.find('.log-output').addClass('soft-wrap');
        } else {
            $logConsole.find('.log-output').removeClass('soft-wrap');
        }
    });
    // Initialize state for checkboxes that exist at page load
    $('.word-wrap-checkbox').trigger("change");

    $('.toggle-label').click(function(e) {
        $(this).prev(".switch").click();
    });
    $('.modal-log').on('click', 'button[role="log-tab"]', function(e) {
        e.preventDefault();
        const $this = $(this);
        const $modal = $this.closest('.modal-log');
        const $logConsole = $modal.find('.log-console');
        const $logContent = $logConsole.find('.log-content');
        const controls = $this.attr('aria-controls') || '';

        $this.attr('aria-selected', 'true').siblings('[role="log-tab"]').attr('aria-selected', 'false');

        if (controls.indexOf('log-events') === 0) {
            $logContent.find('.log-step-content').hide();
            $logContent.find('.log-events-view').show();
            syncExecutionEventsStepVisibility($logConsole);
            return;
        }

        $logContent.find('.log-events-view').hide();

        const $selectedStepBtn = $logConsole.find('.log-footer .log-step-tab.selected');
        let $stepPane = $();
        if ($selectedStepBtn.length) {
            $stepPane = $logContent.find(
                '.log-step-content[data-step-name="' + $selectedStepBtn.data('step-name') + '"]'
            );
        }
        if ($stepPane.length === 0) {
            $stepPane = $logContent.find('.log-step-content').first();
        }
        $logContent.find('.log-step-content').hide();
        if ($stepPane.length) {
            $stepPane.show();
        }

        const logType = controls.includes('stdout') ? 'stdout' : 'stderr';
        $modal.find('.log-output').hide();
        if ($stepPane.length) {
            $stepPane.find('.log-output[data-log-type="' + logType + '"]').show();
        }
    });

    $('.modal-log').on('click', '.log-step-tab', function(e) {
        e.preventDefault();
        const $this = $(this);
        const $modal = $this.closest('.modal-log');
        const $logConsole = $modal.find('.log-console');
        const $logContent = $logConsole.find('.log-content');
        const stepName = $this.data('step-name');

        $this.addClass('selected').siblings('.log-step-tab').removeClass('selected');

        const topControls = $modal.find('[role="log-tab"][aria-selected="true"]').attr('aria-controls') || '';
        if (topControls.indexOf('log-events') === 0) {
            syncExecutionEventsStepVisibility($logConsole);
            return;
        }

        $logContent.find('.log-events-view').hide();
        $modal.find('.log-step-content').hide();
        const $selectedStep = $modal.find('.log-step-content[data-step-name="' + stepName + '"]');
        $selectedStep.show();

        const selectedTab = $modal.find('[role="log-tab"][aria-selected="true"]');
        const logType = selectedTab.attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';

        $selectedStep.find('.log-output').hide();
        $selectedStep.find('.log-output[data-log-type="' + logType + '"]').show();
    });

});
