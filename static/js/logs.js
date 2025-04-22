$(document).ready(function() {
    const lastMessagesIds = {};

    $('.log-console.streaming-console').each(function() {
        const $logConsole = $(this);
        const taskId = $logConsole.data('task-id');
        lastMessagesIds[taskId] = 0;

        const eventSource = new EventSource('/stream-logs/' + taskId);

        eventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            const logId = data.id;

            if (logId <= lastMessagesIds[taskId]) return;
            lastMessagesIds[taskId] = logId;

            const {
                msg,
                step,
                type
            } = data;

            if ($logConsole.find('.log-step-content[data-step-name="' + step + '"]').length === 0) {
                const stepTab = $('<button type="button" class="text large log-step-tab" data-step-name="' + step + '">' + step + '</button>');
                $logConsole.find('.log-footer .log-tabs').append(stepTab);

                if ($logConsole.find('.log-step-tab').length === 1) stepTab.addClass('selected');

                const stepContent = $('<div class="log-step-content" data-step-name="' + step + '"></div>');
                if ($logConsole.find('.log-step-content').length === 0) stepContent.show();
                else stepContent.hide();

                const stdoutPre = $('<pre class="log-output" data-log-type="stdout" style="display: none;"></pre>');
                const stderrPre = $('<pre class="log-output" data-log-type="stderr" style="display: none;"></pre>');

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
        };

        eventSource.addEventListener('finish', function(event) {
            eventSource.close();
            const finishData = JSON.parse(event.data);

            if (lastMessagesIds[taskId] === 0) {
                window.location.reload();
            } else {
                console.log(`Log stream for ${taskId} finished`);

                const statusClass = finishData.status === 'success' ? 'success' : 'error';
                const icon = finishData.status === 'success' ? 'check' : 'report';
                const label = finishData.status === 'success' ? 'Done' : 'Failed';

                const statusEl = $(`
                    <div class="status">
                        <div class="${statusClass}">
                            <span class="badge material-symbols-outlined">${icon}</span>
                            <span class="label">${label}</span>
                        </div>
                    </div>
                `);

                $logConsole.find('.log-footer .log-tabs').append(statusEl);
                $logConsole.addClass(finishData.status);
                delete lastMessagesIds[taskId];
            }
        });

        eventSource.onerror = function(e) {
            console.error(`Error receiving SSE for task ${taskId}:`, e);
            if (lastMessagesIds[taskId] === 0) {
                eventSource.close();
                window.location.reload();
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
            $logConsole.find('.log-output').addClass('word-wrap');
        } else {
            $logConsole.find('.log-output').removeClass('word-wrap');
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
