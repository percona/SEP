$(document).ready(function () {
    $('.schedule-button').on('click', function () {
        const $scheduleButton = $(this);
        const taskName = $scheduleButton.data('task');
        const $sendForm = $('#' + taskName + '-send');
        const $etaInput = $sendForm.find('.eta-input');
        const $sendButton = $sendForm.find('.send-button');
        const $infoDeleteContainer = $scheduleButton.siblings('.info-delete-container');

        if ($scheduleButton.hasClass('toggled-on')) {
            $scheduleButton.removeClass('toggled-on');
            $scheduleButton.attr('aria-expanded', 'false');

            $etaInput.attr('disabled', true);
            $etaInput.attr('required', false);
            $sendForm.removeClass('expanded');
            $sendButton.attr('title', 'Execute');

            $infoDeleteContainer.show();
        } else {
            $scheduleButton.addClass('toggled-on');
            $scheduleButton.attr('aria-expanded', 'true');

            $sendForm.addClass('expanded');
            $etaInput.attr('disabled', false);
            $etaInput.attr('required', true);
            $sendButton.attr('title', 'Schedule');

            $infoDeleteContainer.hide();

            setTimeout(function () {
                $etaInput.focus();
            }, 500);
        }
    });

    $('.send-form').submit(function() {
        console.log("SUBMIT");
        const $sendForm = $(this);
        const $etaInput = $sendForm.find('.eta-input');
        const etaValue = $etaInput.val();
        console.log(etaValue);
        const $scheduleButton = $sendForm.parent().find('.schedule-button');
        const $etaInputValue = $sendForm.find('.eta-value');
        if ($scheduleButton.hasClass('toggled-on') && etaValue) {
            $etaInputValue.attr('disabled', false);
            const etaDate = new Date(etaValue);
            $etaInputValue.val(etaDate.toISOString());
            console.log(etaDate.toISOString());
        } else {
            $etaInputValue.attr('disabled', true);
        }
        return true;
    });
});
