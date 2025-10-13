$(document).ready(function() {
    const cronstrue = window.cronstrue;

    // ========================================
    // Helper Functions
    // ========================================

    function humanizeCronExpression(cronExpression) {
        try {
            let humanized = cronstrue.toString(cronExpression);
            return humanized.charAt(0).toLowerCase() + humanized.slice(1);
        } catch (e) {
            console.error('Invalid cron expression:', cronExpression);
            return null;
        }
    }

    function updateCronDescription($input) {
        const cronExpression = $input.val();
        const $cronDescription = $input.closest('.cron-inputs').find('.cron-description');

        if (cronExpression) {
            const humanized = humanizeCronExpression(cronExpression);
            if (humanized) {
                $cronDescription.text(humanized);
                $input.removeClass('invalid');
            } else {
                $cronDescription.text('Invalid cron expression');
                $input.addClass('invalid');
            }
        } else {
            $cronDescription.text('');
        }
    }

    function validateScheduleInputs($row, isCronMode) {
        if (isCronMode) {
            const $cronInput = $row.find('input[name="cron_expression"]');
            const cronExpression = $cronInput.val();

            if (!cronExpression) {
                alert('Please provide a cron expression.');
                $cronInput.addClass('invalid');
                return false;
            }

            if (!humanizeCronExpression(cronExpression)) {
                alert('Invalid cron expression.');
                $cronInput.addClass('invalid');
                return false;
            }

            $cronInput.removeClass('invalid');
        } else {
            const $intervalInput = $row.find('input[name="interval_every"]');
            if ($intervalInput.val() === '') {
                alert('Please provide an interval every value.');
                $intervalInput.addClass('invalid');
                return false;
            }
            $intervalInput.removeClass('invalid');
        }

        return true;
    }

    function updateDateTimeInput($row) {
        const $dateInput = $row.find('input[type="datetime-local"]');
        const dateValue = $dateInput.val();

        if (dateValue) {
            const $dateInputValue = $row.find('.date-value');
            const awareDate = new Date(dateValue);
            $dateInputValue.val(awareDate.toISOString());
        }
    }

    function togglePeriodMode($link) {
        const taskId = $link.data('task-id');
        let $intervalDiv, $cronDiv;

        if (taskId) {
            const $editRow = $(`.edit-periodic-task-row[data-task-id="${taskId}"]`);
            $intervalDiv = $editRow.find('.interval-inputs');
            $cronDiv = $editRow.find('.cron-inputs');
        } else {
            $intervalDiv = $('.new-periodic-task-row .interval-inputs');
            $cronDiv = $('.new-periodic-task-row .cron-inputs');
        }

        $intervalDiv.toggleClass('hidden');
        $cronDiv.toggleClass('hidden');

        const cronIsActive = $intervalDiv.hasClass('hidden');
        $intervalDiv.children().attr('required', !cronIsActive).attr('disabled', cronIsActive);
        $cronDiv.find('div').first().children().attr('required', cronIsActive).attr('disabled', !cronIsActive);
        $link.text(cronIsActive ? 'change to interval mode' : 'change to cron mode');
    }

    function initializeSelect2($select, browserTimezone = null) {
        $select.select2({
            placeholder: 'Select a timezone',
            width: '130px',
        });

        if (browserTimezone && availableTimezones.includes(browserTimezone)) {
            $select.val(browserTimezone).trigger('change');
        } else {
            $select.val('UTC').trigger('change');
        }
    }

    // ========================================
    // Initialization
    // ========================================

    // Humanize cron expressions in table
    $('.period-cell.period-crontab').each(function() {
        const cronExpression = $(this).text().trim();
        const timezone = $(this).data('timezone');

        if (cronExpression) {
            const humanized = humanizeCronExpression(cronExpression);
            if (humanized) {
                const displayText = timezone.length > 0 ? `${humanized} (${timezone})` : humanized;
                $(this).attr('title', displayText);
            }
        }
    });

    // Set delete confirmation messages
    $('#scheduled-tasks-table .delete-form').each(function() {
        const taskName = $(this).closest('tr').find('td:first').text().trim();
        const periodCell = $(this).closest('tr').find('.period-cell');
        const periodDescription = periodCell.attr('title') || periodCell.text().trim();
        $(this).attr('data-confirm-message',
            `Are you sure you want to delete the periodic task for "${taskName}" (${periodDescription})?`);
    });

    // ========================================
    // Event Handlers - Enable/Disable Toggles
    // ========================================

    $('.new-periodic-task-enable-checkbox, .edit-periodic-task-enable-checkbox').change(function() {
        const checkbox = $(this);
        const enabled = checkbox.is(':checked');
        checkbox.parent('label.switch').siblings('input[name="enabled"]').val(enabled ? 'true' : 'false');
    });

    $('.enable-checkbox').change(function(e) {
        e.preventDefault();
        const checkbox = $(this);
        const form = checkbox.closest('.enable-form');
        const taskName = checkbox.closest('tr').find('td:first').text().trim();
        const enabled = checkbox.is(':checked');
        const action = enabled ? 'enable' : 'disable';
        const periodCell = checkbox.closest('tr').find('.period-cell');
        const periodDescription = periodCell.attr('title') || periodCell.text().trim();

        const confirmMessage = `Are you sure you want to ${action} the periodic execution of "${taskName}" ${periodDescription}?`;
        if (confirm(confirmMessage)) {
            form.find('input[name="enabled"]').val(enabled ? 'true' : 'false');
            form.submit();
        } else {
            checkbox.prop('checked', !enabled);
        }
    });

    // ========================================
    // Event Handlers - Task Links
    // ========================================

    $('.task-link').click(function() {
        const targetId = $(this).attr('href').substring(1);
        const $targetRow = $('#' + targetId);

        if ($targetRow.length) {
            $targetRow.addClass('highlighted-row');
            setTimeout(() => $targetRow.removeClass('highlighted-row'), 3000);
        }
    });

    // ========================================
    // Event Handlers - Cron Expression Input
    // ========================================

    $('input[name="cron_expression"]').on('input', function() {
        updateCronDescription($(this));
    });

    // ========================================
    // Event Handlers - New Task Creation
    // ========================================

    $('.discard-button').click(function() {
        $('#add-periodic-task-button-container').show();
        $('#new-periodic-task-form').trigger('reset');
        $('.cron-description').text('');
        $('.interval-inputs').removeClass('hidden');
        $('.cron-inputs').addClass('hidden');
        $('#scheduled-tasks-table').removeClass('create-mode');
    });

    $('.change-period-mode').click(function(e) {
        e.preventDefault();
        togglePeriodMode($(this));
    });

    $('#add-periodic-task-button').click(function() {
        $('#add-periodic-task-button-container').hide();
        $('#scheduled-tasks-table').addClass('create-mode');

        const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        initializeSelect2($('select[name="cron_timezone"]'), browserTimezone);
    });

    $('#save-button').click(function(e) {
        e.preventDefault();

        const $newTaskRow = $('.new-periodic-task-row');
        const $cronDiv = $newTaskRow.find('.cron-inputs');
        const $intervalDiv = $newTaskRow.find('.interval-inputs');
        const isCronMode = !$cronDiv.hasClass('hidden');

        if (!validateScheduleInputs($newTaskRow, isCronMode)) {
            return false;
        }

        updateDateTimeInput($newTaskRow);

        const $runPythonForm = $("#run-python-send");
        if ($runPythonForm.length) {
            if (!$runPythonForm.get(0).reportValidity()) {
                return false;
            }

            const runPythonFormData = $runPythonForm.serializeArray();
            runPythonFormData.forEach(function(data) {
                if (data.name !== "csrf-token") {
                    const inputName = data.name === "payload" ?
                        "execute_request_payload" :
                        `execute_request_meta_${data.name.replace('meta_', '')}`;

                    $('<input>', {
                        type: 'hidden',
                        name: inputName,
                        value: data.value
                    }).appendTo("#new-periodic-task-form");
                }
            });
        }

        $('#new-periodic-task-form').submit();
        return true;
    });

    // ========================================
    // Event Handlers - Edit Mode
    // ========================================

    $('.edit-button').click(function() {
        const taskId = $(this).data('task-id');
        const $currentRow = $(this).closest('tr');
        const $editRow = $(`.edit-periodic-task-row[data-task-id="${taskId}"]`);

        $('.edit-periodic-task-row').hide();
        $('#scheduled-tasks-table tbody > tr:not(.edit-periodic-task-row)').show();

        $currentRow.hide();
        $editRow.show();

        $editRow.find('input, select').each(function() {
            if ($(this).attr('type') !== 'hidden') {
                $(this).data('original-value', $(this).val());
            }
        });

        const $timezoneSelect = $editRow.find('select[name="cron_timezone"]');
        if (!$timezoneSelect.hasClass('select2-hidden-accessible')) {
            initializeSelect2($timezoneSelect);
        }

        const $cronInput = $editRow.find('input[name="cron_expression"]');
        if (!$cronInput.closest('.cron-inputs').hasClass('hidden')) {
            updateCronDescription($cronInput);
        }
    });

    $('.cancel-edit-button').click(function() {
        const taskId = $(this).data('task-id');
        const $editRow = $(`.edit-periodic-task-row[data-task-id="${taskId}"]`);
        const $currentRow = $editRow.prev('tr');

        $editRow.hide();
        $currentRow.show();

        $editRow.find('input, select').each(function() {
            if ($(this).attr('type') === 'checkbox') {
                const originalChecked = $currentRow.find('.enable-checkbox').is(':checked');
                $(this).prop('checked', originalChecked);
            } else if ($(this).attr('type') !== 'hidden') {
                // Reset other inputs to their original values
                $(this).val($(this).data('original-value') || '');
            }
        });
    });

    $('.save-edit-button').click(function(e) {
        e.preventDefault();

        const taskId = $(this).data('task-id');
        const $editRow = $(`.edit-periodic-task-row[data-task-id="${taskId}"]`);
        const $cronDiv = $editRow.find('.cron-inputs');
        const isCronMode = !$cronDiv.hasClass('hidden');

        if (!validateScheduleInputs($editRow, isCronMode)) {
            return false;
        }

        updateDateTimeInput($editRow);

        const taskName = $editRow.find('td:first span').text().trim();
        const periodCell = $editRow.find('.period-cell');
        const periodDescription = periodCell.attr('title') || periodCell.text().trim();

        const confirmMessage = `Are you sure you want to update the periodic task for "${taskName}" (${periodDescription})?`;
        if (!confirm(confirmMessage)) {
            return false;
        }

        const $form = $(`#edit-periodic-task-form-${taskId}`);
        const formData = new FormData();

        formData.append('csrf-token', $form.find('input[name="csrf-token"]').val());

        const enabled = $editRow.find('.edit-periodic-task-enable-checkbox').is(':checked');
        formData.append('enabled', enabled ? 'true' : 'false');

        const startTimeValue = $editRow.find('input[name="start_time"]').val();
        if (startTimeValue) {
            formData.append('start_time', startTimeValue);
        }

        if (isCronMode) {
            const cronExpression = $editRow.find('input[name="cron_expression"]').val();
            const cronTimezone = $editRow.find('select[name="cron_timezone"]').val();
            if (cronExpression) {
                formData.append('cron_expression', cronExpression);
                formData.append('cron_timezone', cronTimezone);
            }
        } else {
            const intervalEvery = $editRow.find('input[name="interval_every"]').val();
            const intervalPeriod = $editRow.find('select[name="interval_period"]').val();
            if (intervalEvery) {
                formData.append('interval_every', intervalEvery);
                formData.append('interval_period', intervalPeriod);
            }
        }

        fetch($form.attr('action'), {
            method: 'POST',
            body: formData
        }).then(response => {
            if (response.ok) {
                window.location.reload();
            } else {
                alert('Failed to update periodic task. Please try again.');
            }
        }).catch(error => {
            console.error('Error updating periodic task:', error);
            alert('Failed to update periodic task. Please try again.');
        });

        return true;
    });
});
