$(document).ready(function () {
    const lastMessagesIds = {};
    $('.log-console.streaming-console').each(function () {
        const $logConsole = $(this);
        const taskId = $logConsole.data('task-id');
        lastMessagesIds[taskId] = 0;

        const eventSource = new EventSource('/stream-logs/' + taskId);

        eventSource.onmessage = function (event) {
            const data = JSON.parse(event.data);

            const logId = data.id
            if (logId <= lastMessagesIds[taskId]) {
                return;
            }
            lastMessagesIds[taskId] = logId

            const msg = data.msg;
            const step = data.step;
            const type = data.type;

            if ($logConsole.find('.log-step-content[data-step-name="' + step + '"]').length === 0) {
                const stepTab = $('<a href="#" class="log-step-tab" data-step-name="' + step + '">' + step + '</a>');
                $logConsole.find('.log-bottom-bar .log-tabs').append(stepTab);

                if ($logConsole.find('.log-step-tab').length === 1) {
                    stepTab.addClass('selected');
                }

                const stepContent = $('<div class="log-step-content" data-step-name="' + step + '"></div>');
                if ($logConsole.find('.log-step-content').length === 0) {
                    stepContent.show();
                } else {
                    stepContent.hide();
                }

                const stdoutPre = $('<pre class="log-output" data-log-type="stdout" style="display: none;"></pre>');
                const stderrPre = $('<pre class="log-output" data-log-type="stderr" style="display: none;"></pre>');

                const selectedLogType = $logConsole.find('.log-type-tab.selected').data('log-type');
                if (selectedLogType === 'stdout') {
                    stdoutPre.css("display", "block");
                } else {
                    stderrPre.css("display", "block");
                }

                stepContent.append(stdoutPre);
                stepContent.append(stderrPre);
                $logConsole.find('.log-content').append(stepContent);
            }

            const preElement = $logConsole.find('.log-step-content[data-step-name="' + step + '"] .log-output[data-log-type="' + type + '"]');
            preElement.append(document.createTextNode(msg));

            const $logContent = $logConsole.find('.log-content');
            $logContent.scrollTop($logContent[0].scrollHeight);

            const selectedLogType = $logConsole.find('.log-type-tab.selected').data('log-type');
            if (type !== selectedLogType) {
                const $typeTab = $logConsole.find('.log-type-tab[data-log-type="' + type + '"]');
                $typeTab.addClass('tab-notification');
            }

            const selectedStepName = $logConsole.find('.log-step-tab.selected').data('step-name');
            if (step !== selectedStepName) {
                const $stepTab = $logConsole.find('.log-step-tab[data-step-name="' + step + '"]');
                $stepTab.addClass('tab-notification');
            }
        };

        eventSource.addEventListener('finish', function (event) {
            eventSource.close();
            if (lastMessagesIds[taskId] === 0) {
                window.location.reload();
            } else {
                console.log(`Log stream for ${taskId} finished`);
                const completedIcon = $('<i class="icons unselectable" style="color: #8ACE00; margin-left: auto;" title="Task completed">check_circle</i>');
                $logConsole.find('.log-bottom-bar').append(completedIcon);
                $logConsole.addClass('completed');
                delete lastMessagesIds[taskId];
            }
        });

        eventSource.onerror = function (e) {
            console.error(`Error receiving SSE for task ${taskId}: ${e}`);
            if (lastMessagesIds[taskId] === 0) {
                eventSource.close();
                window.location.reload();
            }
        };
    });

    $('.logs-button').click(function () {
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

    $('.log-type-tab').click(function (e) {
        e.preventDefault();
        const $this = $(this);
        const logType = $this.data('log-type');
        const $logConsole = $this.closest('.log-console');

        $this.closest('.log-tabs').find('.log-type-tab').removeClass('selected');
        $this.addClass('selected');

        $logConsole.find('.log-output').hide();
        $logConsole.find('.log-step-content:visible .log-output[data-log-type="' + logType + '"]').show();

        $this.removeClass('tab-notification');
    });

    $('.log-console').on('click', '.log-step-tab', function (e) {
        e.preventDefault();
        const $this = $(this);
        const stepName = $this.data('step-name');
        const $logConsole = $this.closest('.log-console');

        $this.closest('.log-tabs').find('.log-step-tab').removeClass('selected');
        $this.addClass('selected');

        $logConsole.find('.log-step-content').hide();
        $logConsole.find('.log-step-content[data-step-name="' + stepName + '"]').show();

        const selectedLogType = $logConsole.find('.log-type-tab.selected').data('log-type');
        $logConsole.find('.log-output').hide();
        $logConsole.find('.log-step-content[data-step-name="' + stepName + '"] .log-output[data-log-type="' + selectedLogType + '"]').show();

        $this.removeClass('tab-notification');
    });

    $('.word-wrap-checkbox').change(function () {
        const $this = $(this);
        const $logConsole = $this.closest('.log-console');
        if ($this.is(':checked')) {
            $logConsole.find('.log-output').addClass('word-wrap');
        } else {
            $logConsole.find('.log-output').removeClass('word-wrap');
        }
    });
    $('.word-wrap-checkbox').trigger("change");

    $('.toggle-label').click(function (e) {
        $(this).prev(".switch").click();
    });
});
