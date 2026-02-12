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
        });
    }

    window.initInfoTooltips = initInfoTooltips;
})();
