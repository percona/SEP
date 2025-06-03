document.addEventListener('DOMContentLoaded', () => {
    // Scheduling behavior for saved tasks
    // ==============================
    // Select all scheduling trigger buttons and their targets
    const scheduleButtons = document.querySelectorAll('.triggerScheduleExec[data-modal-target="modalScheduleExec"]');
    scheduleButtons.forEach(scheduleButton => {
        scheduleButton.addEventListener('click', function(e) {
            const taskName = this.getAttribute('data-task');
            if (!taskName) return;
            // Find form and submit button
            const sendForm = document.getElementById(taskName + '-send');
            if (!sendForm) return;
            const sendButton = sendForm.querySelector('button');
            // Locate the info-delete container
            const parentTD = this.closest('td');
            let infoDeleteContainer = null;
            if (parentTD) {
                infoDeleteContainer = parentTD.querySelector('.info-delete-container');
            }

            // Toggle scheduling state on this button.
            if (this.classList.contains('toggled-on')) {
                this.classList.remove('toggled-on');
                this.setAttribute('aria-expanded', 'false');
                sendForm.classList.remove('expanded');
                sendForm.setAttribute('data-confirm-message', `Are you sure you want to execute task "${taskName}" now?`);
                if (sendButton) {
                    sendButton.setAttribute('title', 'Execute');
                }
            } else {
                this.classList.add('toggled-on');
                this.setAttribute('aria-expanded', 'true');
                sendForm.classList.add('expanded');
                sendForm.setAttribute('data-confirm-message', `Are you sure you want to schedule task "${taskName}"?`);
                if (sendButton) {
                    sendButton.setAttribute('title', 'Schedule');
                }
            }
        });
    });
    // Scheduling modal – update hidden ETA value
    // ==============================
    const scheduleModal = document.getElementById('modalScheduleExec');
    if (scheduleModal) {
        const dateTimeInput = scheduleModal.querySelector('#dateTimeInput');
        const modalEtaInput = scheduleModal.querySelector('#modalEtaValue');
        const submitScheduleButton = scheduleModal.querySelector('#modalScheduleExecSubmitButton');

        if (dateTimeInput && modalEtaInput) {
            ['focus', 'blur', 'change'].forEach(function(eventType) {
                dateTimeInput.addEventListener(eventType, function() {
                    submitScheduleButton.disabled = true;
                    const etaValue = this.value;
                    if (etaValue) {
                        const isoStr = new Date(etaValue).toISOString();
                        modalEtaInput.disabled = false;
                        modalEtaInput.value = isoStr;
                        // Also update the send form's hidden ETA value:
                        // the modal should have a hidden input #taskName containing the taskName.
                        const taskNameInput = scheduleModal.querySelector('#taskName');
                        if (taskNameInput && taskNameInput.value) {
                            const sendForm = document.getElementById(taskNameInput.value + '-send');
                            if (sendForm) {
                                const etaValueInput = sendForm.querySelector('.eta-value');
                                if (etaValueInput) {
                                    etaValueInput.disabled = false;
                                    etaValueInput.value = isoStr;
                                }
                            }
                        }
                        console.log("Scheduled ETA (ISO):", isoStr);
                        submitScheduleButton.disabled = false;
                    } else {
                        modalEtaInput.disabled = true;
                    }
                });
            })
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        const scheduleForm = document.getElementById('schedule-task-form');
        const dialog = document.getElementById('modalScheduleExec');
        const etaInput = document.getElementById('dateTimeInput');
        const etaHidden = document.getElementById('modalEtaValue');

        scheduleForm.addEventListener('submit', function(event) {
            // First: close the modal
            dialog.close();

            // Small delay to let modal hide before confirm appears
            setTimeout(() => {
                const confirmMessage = scheduleForm.dataset.confirmMessage || 'Are you sure?';
                const confirmed = confirm(confirmMessage);

                if (confirmed) {
                    // Enable and set the hidden eta value
                    etaHidden.value = etaInput.value;
                    etaHidden.disabled = false;

                    // Manually submit the form (since we previously prevented it)
                    scheduleForm.submit();
                } else {
                    // If not confirmed, do nothing
                }
            }, 10); // Slight delay to allow dialog to disappear

            // Stop the default form submission for now
            event.preventDefault();
        });
    });

});

// $(document).ready(function() {
//     $('.schedule-button').on('click', function() {
//         const $scheduleButton = $(this);
//         const taskName = $scheduleButton.data('task');
//         const $sendForm = $('#' + taskName + '-send');
//         const $etaInput = $sendForm.find('.eta-input');
//         const $sendButton = $sendForm.find('.send-button');
//         const $infoDeleteContainer = $scheduleButton.siblings('.info-delete-container');

//         if ($scheduleButton.hasClass('toggled-on')) {
//             $scheduleButton.removeClass('toggled-on');
//             $scheduleButton.attr('aria-expanded', 'false');

//             $etaInput.attr('disabled', true);
//             $etaInput.attr('required', false);
//             $sendForm.removeClass('expanded');
//             $sendForm.attr('data-confirm-message', `Are you sure you want to execute task "${taskName}" now?`);
//             $sendButton.attr('title', 'Execute');


//             $infoDeleteContainer.show();
//         } else {
//             $scheduleButton.addClass('toggled-on');
//             $scheduleButton.attr('aria-expanded', 'true');

//             $sendForm.addClass('expanded');
//             $etaInput.attr('disabled', false);
//             $etaInput.attr('required', true);
//             $sendForm.attr('data-confirm-message', `Are you sure you want to schedule task "${taskName}"?`);
//             $sendButton.attr('title', 'Schedule');

//             $infoDeleteContainer.hide();

//             setTimeout(function() {
//                 $etaInput.focus();
//             }, 500);
//         }
//     });

//     $('.eta-input').change(function() {
//         const $sendForm = $(this).parent().parent();
//         const $etaInput = $(this);
//         const etaValue = $etaInput.val();
//         const $scheduleButton = $sendForm.find('.schedule-button');
//         const $etaInputValue = $sendForm.find('.eta-value');
//         if ($scheduleButton.hasClass('toggled-on') && etaValue) {
//             $etaInputValue.attr('disabled', false);
//             const etaDate = new Date(etaValue);
//             $etaInputValue.val(etaDate.toISOString());
//             console.log(etaDate.toISOString());
//         } else {
//             $etaInputValue.attr('disabled', true);
//         }
//         return true;
//     });
// });
