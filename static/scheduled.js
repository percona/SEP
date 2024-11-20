$(document).ready(function () {
    const cronstrue = window.cronstrue;

    $('.period-cell.period-crontab').each(function () {
        const cronExpression = $(this).text().trim();
        const timezone = $(this).data('timezone');
        if (cronExpression) {
            try {
                let humanized = cronstrue.toString(cronExpression);
                humanized = humanized.charAt(0).toLowerCase() + humanized.slice(1);
                if (timezone.length > 0) {
                    humanized += ` (${timezone})`;
                }
                $(this).attr('title', humanized);
            } catch (e) {
                console.error('Invalid cron expression:', cronExpression);
            }
        }
    });

    $('.new-periodic-task-enable-checkbox').change(function(e) {
        const checkbox = $(this);
        const enabled = checkbox.is(':checked');
        checkbox.parent('label.switch').siblings('input[name="enabled"]').val(enabled ? 'true' : 'false');
    });

    $('.enable-checkbox').change(function (e) {
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
            checkbox.closest('.enable-form').find('input[name="enabled"]').val(enabled ? 'true' : 'false');
            form.submit();
        } else {
            checkbox.prop('checked', !enabled);
        }
    });

    // Highlight task for 3 seconds
    $('.task-link').click(function (e) {
        var targetId = $(this).attr('href').substring(1);
        var $targetRow = $('#' + targetId);

        if ($targetRow.length) {
            $targetRow.addClass('highlighted-row');
            setTimeout(function () {
                $targetRow.removeClass('highlighted-row');
            }, 3000);
        }
    });

    // Update cron description on input
        $('input[name="cron_expression"]').on('input', function() {
            const cronExpression = $(this).val();
            const $cronDescription = $('.cron-description');
            if (cronExpression) {
                try {
                    const humanized = cronstrue.toString(cronExpression);
                    $cronDescription.text(humanized);
                    $(this).removeClass('invalid');
                } catch (e) {
                    $cronDescription.text('Invalid cron expression');
                    $(this).addClass('invalid');
                }
            } else {
                $cronDescription.text('');
            }
        });

        // Handle discard button
        $('.discard-button').click(function() {
            $('#add-periodic-task-button-container').show();
            $('#new-periodic-task-form').trigger('reset');
            $('.cron-description').text('');
            $('.interval-inputs').removeClass('hidden');
            $('.cron-inputs').addClass('hidden');
            $('#scheduled-tasks-table').removeClass('create-mode');
        });

    // Handle switching between interval and cron modes
        $('.change-period-mode').click(function() {
            const intervalDiv = $('.interval-inputs');
            const cronDiv = $('.cron-inputs');
            intervalDiv.toggleClass('hidden');
            cronDiv.toggleClass('hidden');
            const cronIsActive = intervalDiv.hasClass('hidden')
            intervalDiv.children().attr('required', !cronIsActive);
            intervalDiv.children().attr('disabled', cronIsActive);
            cronDiv.find('div').first().children().attr('required', cronIsActive);
            cronDiv.find('div').first().children().attr('disabled', !cronIsActive);
            $(this).text(cronIsActive ? 'change to interval mode' : 'change to cron mode');
        });

    // Show the form row when "+" button is clicked
    $('#add-periodic-task-button').click(function() {
        $('#add-periodic-task-button-container').hide();
        $('#scheduled-tasks-table').addClass('create-mode');

        // Initialize Select2 for timezone selection
        const $timezoneSelect = $('select[name="cron_timezone"]');
        $timezoneSelect.select2({
            placeholder: 'Select a timezone',
            width: '130px',
        });

        // Auto-select browser's timezone
        const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (availableTimezones.includes(browserTimezone)) {
            $timezoneSelect.val(browserTimezone).trigger('change');
        } else {
            $timezoneSelect.val('UTC').trigger('change');
        }
    });

    // Handle validation before form submission
    $('#new-periodic-task-form').submit(function(e) {
        const $cronDiv = $('.cron-inputs');
        if (!$cronDiv.hasClass('hidden')) {
            const cronExpression = $('input[name="cron_expression"]').val();
            if (cronExpression) {
                try {
                    cronstrue.toString(cronExpression);
                    $('input[name="cron_expression"]').removeClass('invalid');
                } catch (e) {
                    alert('Invalid cron expression.');
                    $('input[name="cron_expression"]').addClass('invalid');
                    return false;
                }
            } else {
                alert('Please provide a cron expression.');
                $('input[name="cron_expression"]').addClass('invalid');
                return false;
            }
        }
        $('.new-periodic-task-row input[type="datetime-local"]').each(function() {
            const $dateInput = $(this);
            const dateValue = $dateInput.val();
            if (dateValue) {
                const $dateInputValue = $dateInput.siblings('.date-value');
                const awareDate = new Date($dateInput.val());
                $dateInputValue.val(awareDate.toISOString());
            }

        });
        return true;
    });
});
