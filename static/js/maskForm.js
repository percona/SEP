document.addEventListener("DOMContentLoaded", function() {
    const encryptAllCheckbox = document.getElementById("encrypt_all_entities");
    const entityCheckboxes = document.querySelectorAll(".entity-encrypt-checkbox");
    const oneValueInput = document.getElementById("anonymize");

    function updateOneValue() {
        let selectedValues = [...entityCheckboxes]
            .filter(cb => cb.checked)
            .map(cb => parseInt(cb.value, 10));

        oneValueInput.value = selectedValues.length > 0 ? selectedValues.reduce((a, b) => a + b, 0) : 0;
    }

    encryptAllCheckbox.addEventListener("change", function() {
        entityCheckboxes.forEach(checkbox => checkbox.checked = encryptAllCheckbox.checked);
        updateOneValue();
    });

    entityCheckboxes.forEach(checkbox => {
        checkbox.addEventListener("change", function() {
            const anyChecked = [...entityCheckboxes].some(cb => cb.checked);
            encryptAllCheckbox.checked = anyChecked;
            updateOneValue();
        });
    });
});
