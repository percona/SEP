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

    window.clearLoadedTasks = function() {
        loadedCompletedTasks.clear();
    };

    $('.view-logs-button').click(function() {
        const taskId = $(this).data('task-id');
        const $logConsole = $(`.log-console.streaming-console[data-task-id=${taskId}]`);

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

                const selectedTab = $logConsole.find('[role="log-tab"][aria-selected="true"]');
                const selectedLogType = selectedTab.attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';
                if (selectedLogType === 'stdout') stdoutPre.show();
                else stderrPre.show();

                stepContent.append(stdoutPre);
                stepContent.append(stderrPre);
                $logConsole.find('.log-content').append(stepContent);
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

            const statusEl = $(`
                    <div class="status">
                        <div class="failed">
                            <span class="badge material-symbols-outlined">chat_error</span>
                            <span class="label">Stream error</span>
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

    $('.word-wrap-checkbox').change(function() {
        const $this = $(this);
        const $logConsole = $this.closest('.log-console');
        if ($this.is(':checked')) {
            $logConsole.find('.log-output').addClass('soft-wrap');
        } else {
            $logConsole.find('.log-output').removeClass('soft-wrap');
        }
    });
    $('.word-wrap-checkbox').trigger("change");

    $('.toggle-label').click(function(e) {
        $(this).prev(".switch").click();
    });
    $('.modal-log').on('click', 'button[role="log-tab"]', function(e) {
        e.preventDefault();
        const $this = $(this);
        const $modal = $this.closest('.modal-log');
        const logType = $this.attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';

        $this.attr('aria-selected', 'true').siblings('[role="log-tab"]').attr('aria-selected', 'false');

        $modal.find('.log-output').hide();
        $modal.find('.log-step-content:visible .log-output[data-log-type="' + logType + '"]').show();
    });

    $('.modal-log').on('click', '.log-step-tab', function(e) {
        e.preventDefault();
        const $this = $(this);
        const $modal = $this.closest('.modal-log');
        const stepName = $this.data('step-name');

        $this.addClass('selected').siblings('.log-step-tab').removeClass('selected');

        $modal.find('.log-step-content').hide();
        const $selectedStep = $modal.find('.log-step-content[data-step-name="' + stepName + '"]');
        $selectedStep.show();

        const selectedTab = $modal.find('[role="log-tab"][aria-selected="true"]');
        const logType = selectedTab.attr('aria-controls').includes('stdout') ? 'stdout' : 'stderr';

        $selectedStep.find('.log-output').hide();
        $selectedStep.find('.log-output[data-log-type="' + logType + '"]').show();
    });

});
