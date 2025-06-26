// document.addEventListener('DOMContentLoaded', () => {
//     // Edting behavior for the current task
//     // ==============================
//     // Select editing trigger button and their targets
//     const editButton = document.querySelector('.triggerEditTask[data-modal-target="modalEditTask"]');

//     // Scheduling modal – update hidden ETA value
//     // ==============================
//     const editModal = document.getElementById('modalEditTask');
//     if (editModal) {
//         const submitEditButton = editModal.querySelector('#modalEditTaskSubmitButton');
//     }

//     document.addEventListener('DOMContentLoaded', function() {
//         const editForm = document.getElementById('edit-task-form');
//         const dialog = document.getElementById('modalEditTask');

//         editForm.addEventListener('submit', function(event) {
//             // First: close the modal
//             dialog.close();

//             // Small delay to let modal hide before confirm appears
//             setTimeout(() => {
//                 const confirmMessage = editForm.dataset.confirmMessage || 'Are you sure?';
//                 const confirmed = confirm(confirmMessage);

//                 if (confirmed) {
//                     // Manually submit the form (since we previously prevented it)
//                     editForm.submit();
//                 } else {
//                     // If not confirmed, do nothing
//                 }
//             }, 10); // Slight delay to allow dialog to disappear

//             // Stop the default form submission for now
//             event.preventDefault();
//         });
//     });

// });
