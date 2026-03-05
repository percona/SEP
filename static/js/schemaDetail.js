/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

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
