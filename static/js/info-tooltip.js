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

/**
 * Info icon tooltips - visibility toggle, appended to dialog for correct stacking.
 * Uses position:fixed for viewport-relative positioning.
 */
(function() {
    'use strict';

    const TOOLTIP_ID = 'info-tooltip-floating';
    const OFFSET = 8;

    function initInfoTooltips(container) {
        const scope = container || document;

        scope.querySelectorAll('.info-icon[data-tooltip]').forEach(function(icon) {
            if (icon.dataset.tooltipInit) return;
            icon.dataset.tooltipInit = '1';

            icon.addEventListener('mouseenter', function() {
                const text = icon.getAttribute('data-tooltip');
                if (!text) return;

                const dialog = icon.closest('dialog');
                const tooltipParent = dialog || document.body;

                let el = document.getElementById(TOOLTIP_ID);
                if (!el) {
                    el = document.createElement('div');
                    el.id = TOOLTIP_ID;
                    el.className = 'info-tooltip-floating';
                    tooltipParent.appendChild(el);
                } else if (el.parentNode !== tooltipParent) {
                    tooltipParent.appendChild(el);
                }

                el.textContent = text;
                const rect = icon.getBoundingClientRect();
                el.style.left = rect.left + (rect.width / 2) + 'px';
                el.style.top = (rect.bottom + OFFSET) + 'px';
                el.style.transform = 'translateX(-50%)';
                el.classList.add('visible');
            });

            icon.addEventListener('mouseleave', function() {
                const el = document.getElementById(TOOLTIP_ID);
                if (el) el.classList.remove('visible');
            });

            icon.addEventListener('focus', function() {
                icon.dispatchEvent(new Event('mouseenter'));
            });

            icon.addEventListener('blur', function() {
                icon.dispatchEvent(new Event('mouseleave'));
            });
        });
    }

    window.initInfoTooltips = initInfoTooltips;
})();
