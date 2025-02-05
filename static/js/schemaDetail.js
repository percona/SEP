function isOverflowing(element) {
    return element.scrollHeight > element.offsetHeight;
}

function initializeToggleButtons() {
    const ellipsedElements = document.querySelectorAll('.ellipse');

    ellipsedElements.forEach(element => {
        const buttonId = element.id.replace('create-', 'create-btn-').replace('keys-', 'keys-btn-');
        const button = document.getElementById(buttonId);

        if (!button) {
            console.error(`Button with ID '${buttonId}' not found.`);
            return;
        }

        button.addEventListener('click', function() {
            const targetId = button.getAttribute('data-target');
            toggleContent(targetId, button);
        });

        if (isOverflowing(element)) {
            button.classList.remove('hidden');
        } else {
            button.classList.add('hidden');
            element.classList.add('ellipse');
        }
    });
}

function toggleContent(id, button) {
    const element = document.getElementById(id);

    if (!element) {
        console.error(`Element with ID '${id}' not found.`);
        return;
    }

    if (element.classList.contains('ellipse')) {
        element.classList.remove('ellipse');
        button.textContent = '<<Less ';
    } else {
        element.classList.add('ellipse');
        button.textContent = '>>More';
    }
}

document.addEventListener('DOMContentLoaded', initializeToggleButtons);

window.addEventListener('resize', () => {
    initializeToggleButtons();
});
