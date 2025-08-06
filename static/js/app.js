document.addEventListener('DOMContentLoaded', () => {

    const body = document.body;

    // =============================================
    // Sidebar behaviors
    // =============================================
    // Select all sidebar links
    const sidebarLinks = document.querySelectorAll('.sidebar .list-item');
    const currentPath = window.location.pathname;

    // Set the active sidebar link
    sidebarLinks.forEach(link => {
        if (link.target === '_blank') return;

        const linkPath = new URL(link.href, window.location.origin).pathname;
        const currentPath = window.location.pathname;

        if (linkPath === '/' && currentPath === '/') {
            link.classList.add('active');
            console.log("rool")
        } else if (
            linkPath !== '/' &&
            (currentPath === linkPath || currentPath.startsWith(linkPath))
        ) {
            link.classList.add('active');
            console.log("herer")
        }
    });

    // =============================================
    // GUI theme toggle
    // =============================================
    // Read localstorage to set the theme
    const storedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    // Set theme: use stored theme if available, otherwise use system preference.
    const theme = storedTheme ? storedTheme : (systemPrefersDark ? 'dark' : 'light');
    body.setAttribute('data-theme', theme);

    // Select the theme toggle buttons.
    // Give each toggle a distinguishing class (or data attribute).
    const darkToggle = document.querySelector('.theme-change.dark');
    const lightToggle = document.querySelector('.theme-change.light');

    if (darkToggle) {
        darkToggle.addEventListener('click', (e) => {
            e.preventDefault();
            body.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        });
    }

    if (lightToggle) {
        lightToggle.addEventListener('click', (e) => {
            e.preventDefault();
            body.setAttribute('data-theme', 'light');
            localStorage.setItem('theme', 'light');
        });
    }

    // =============================================
    // Tab functionality
    // =============================================
    // Select all tab buttons and tab panels
    function initTabs(tabsContainer, panelsContainer, storageKey) {
        const tabButtons = tabsContainer.querySelectorAll('[role="tab"]');
        const tabPanels = panelsContainer.querySelectorAll('[role="tabpanel"]');

        // Restore stored state for this container
        const savedTabId = localStorage.getItem(storageKey);
        if (savedTabId) {
            const savedTab = tabsContainer.querySelector(`[role="tab"][aria-controls="${savedTabId}"]`);
            const savedPanel = panelsContainer.querySelector(`#${savedTabId}`);
            if (savedTab && savedPanel) {
                tabButtons.forEach(btn => btn.setAttribute('aria-selected', 'false'));
                tabPanels.forEach(panel => panel.setAttribute('aria-hidden', 'true'));
                savedTab.setAttribute('aria-selected', 'true');
                savedPanel.setAttribute('aria-hidden', 'false');
            }
        } else if (tabButtons.length > 0) {
            // If no saved state, activate the first tab.
            tabButtons.forEach(btn => btn.setAttribute('aria-selected', 'false'));
            tabPanels.forEach(panel => panel.setAttribute('aria-hidden', 'true'));
            const defaultTab = tabButtons[0];
            defaultTab.setAttribute('aria-selected', 'true');
            const targetId = defaultTab.getAttribute('aria-controls');
            const defaultPanel = panelsContainer.querySelector(`#${targetId}`);
            if (defaultPanel) {
                defaultPanel.setAttribute('aria-hidden', 'false');
            }
            localStorage.setItem(storageKey, targetId);
        }

        // Attach click handlers to each tab button.
        tabButtons.forEach(button => {
            button.addEventListener('click', () => {

                // Reset selected state and hide panels within this container only
                tabButtons.forEach(btn => btn.setAttribute('aria-selected', 'false'));
                tabPanels.forEach(panel => panel.setAttribute('aria-hidden', 'true'));

                // Activate the clicked tab and its associated panel
                button.setAttribute('aria-selected', 'true');
                const targetId = button.getAttribute('aria-controls');
                const targetPanel = panelsContainer.querySelector(`#${targetId}`);
                if (targetPanel) {
                    targetPanel.setAttribute('aria-hidden', 'false');
                }
                localStorage.setItem(storageKey, targetId);
            });
        });
    }

    const appAltersStageTabs = document.querySelector('.app-stage.tabs-wrapper');
    if (appAltersStageTabs) {
        initTabs(appAltersStageTabs, appAltersStageTabs, 'appAltersStageTabsId');
    }

    document.querySelectorAll('.modal-log.tabs-wrapper').forEach(container => {
        if (!container.id) {
            container.id = 'modalTabs_' + Math.random().toString(36).substr(2, 9);
        }
        const storageKey = 'modalActiveTab_' + container.id;
        const tabsContainer = container.querySelector('nav.tabs');
        const panelsContainer = container;
        initTabs(tabsContainer, panelsContainer, storageKey);
    });

    // =============================================
    // Moment.js
    // =============================================
    // For dates
    // Note: Relative time formatting is possible, consult documentation
    document.querySelectorAll('.date').forEach(el => {
        const originalDate = el.textContent.trim();
        const mDate = moment(originalDate);
        if (mDate.isValid()) {
            el.textContent = mDate.format('YYYY-MM-DD HH:mm:ss'); // MySQL format
        } else {
            console.warn('Invalid date:', originalDate);
        }
    });

    // =============================================
    // Simple-DataTables
    // Documentation: fiduswriter.github.io/simple-datatables/documentation
    // =============================================
    // Templating
    const templateBase = (options, dom) => `
    <div class='${options.classes.top}'>
        ${options.searchable ? `
        <div class="${options.classes.search} input icon-left">
            <span class="material-symbols-outlined">pageview</span>
            <label aria-label="${options.labels.searchTitle}">
                <input class='${options.classes.input}' placeholder="${options.labels.placeholder}" type='search' title='${options.labels.searchTitle}'${dom.id ? ` aria-controls="${dom.id}"` : ""}>
            </label>
        </div>` : ""}
        ${options.paging && options.perPageSelect ? `
        <div class="${options.classes.dropdown} select">
            <label>
                <span class="material-symbols-outlined">arrow_drop_down</span>
                <span class="label">${options.labels.perPage}</span>
                <select class="${options.classes.selector}"></select>
            </label>
        </div>` : ""}
    </div>
    <div class='${options.classes.container}'${options.scrollY.length ? ` style='height: ${options.scrollY}; overflow-y: auto;'` : ""}></div>
    <div class='${options.classes.bottom}'>
        ${options.paging ? `
        <div class='${options.classes.info}'></div>` : ""}
        <nav class='${options.classes.pagination}' aria-label="Table pagination"></nav>
    </div>`;

    // Base configuration
    const tableDefault = {
        perPageSelect: [10, 20, 50, 100],
        prevText: "chevron_left",
        nextText: "chevron_right",
        searchable: true,
        template: templateBase,
        labels: {
            placeholder: "Search in table...",
            searchTitle: "Search in table",
            pageTitle: "Page {page}",
            perPage: "Entries per page: ",
            noRows: "No entries found",
            info: "{start}–{end} entries of {rows}",
            noResults: "No results match your search query",
        },
        columns: [{
            select: 0,
            sort: "asc"
        }, ],
    };

    // Applying the previous configurations...
    document.querySelectorAll('[data-table]').forEach(table => {
        let config = {
            ...tableDefault
        };

        const dataTable = new simpleDatatables.DataTable(table, config);
        if (typeof dataTable.on === 'function') {
            dataTable.on('datatable.update', () => {
                table.querySelectorAll('.menu').forEach(setupExpandable);
                table.querySelectorAll('[data-tooltip]').forEach(trigger => {
                    if (!trigger._tooltipBound) {
                        bindTooltip(trigger);
                    }
                });
                table.querySelectorAll('[data-modal="trigger"]').forEach(trigger => {
                    if (!trigger._modalBound) {
                        bindModalTrigger(trigger);
                    }
                });
            });
        }
    });

    // =============================================
    // Dropdown menus with Floating UI
    // =============================================
    let openMenu = null;

    function setupExpandable(container) {
        // Prevent duplicate binding:
        if (container._expandableBound) return;

        // Ensure the container has the necessary elements.
        const trigger = container.querySelector('.trigger');
        const content = container.querySelector('.content');
        if (!trigger || !content) return;

        // Initially hide the content.
        content.style.display = 'none';
        trigger.setAttribute('aria-expanded', 'false');
        content.setAttribute('aria-hidden', 'true');

        // Function to update the position using Floating UI.
        function updatePosition() {
            FloatingUIDOM.computePosition(trigger, content, {
                placement: 'bottom',
                middleware: [
                    FloatingUIDOM.offset(4),
                    FloatingUIDOM.flip(),
                    FloatingUIDOM.shift({
                        padding: 16
                    }),
                ],
            }).then(({
                x,
                y
            }) => {
                Object.assign(content.style, {
                    position: 'absolute',
                    left: `${x}px`,
                    top: `${y}px`,
                });
            });
        }

        let cleanupAutoUpdate = null;

        function show() {
            content.style.display = 'block';
            updatePosition();
            cleanupAutoUpdate = FloatingUIDOM.autoUpdate(trigger, content, updatePosition);
            trigger.setAttribute('aria-expanded', 'true');
            content.setAttribute('aria-hidden', 'false');
            openMenu = container;
        }

        function hide() {
            content.style.display = 'none';
            if (cleanupAutoUpdate) {
                cleanupAutoUpdate();
                cleanupAutoUpdate = null;
            }
            trigger.setAttribute('aria-expanded', 'false');
            content.setAttribute('aria-hidden', 'true');
            if (openMenu === container) {
                openMenu = null;
            }
        }

        // Attach the hide and show functions
        container.hideExpandable = hide;
        container.showExpandable = show;

        // Toggle the expandable element when clicking on the trigger
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            if (openMenu && openMenu !== container) {
                openMenu.hideExpandable();
            }
            const computedDisplay = window.getComputedStyle(content).display;
            if (computedDisplay === 'block') {
                hide();
            } else {
                show();
            }
        });

        // Mark that binding is complete.
        container._expandableBound = true;
    }

    // Apply this to all elements that need the expandable behavior.
    const expandables = document.querySelectorAll('.menu');
    expandables.forEach(setupExpandable);

    // Attach a single document-level listener to hide the open menu if the click is outside the open menu.
    document.addEventListener('click', (e) => {
        if (openMenu && !openMenu.contains(e.target)) {
            openMenu.hideExpandable();
        }
    });

    // =============================================
    // Tooltip functionality with Floating UI
    // =============================================
    // Elements with a "data-tooltip" attribute will show a tooltip on hover.
    function bindTooltip(trigger) {
        // If already bound, skip re‑binding.
        if (trigger._tooltipBound) return;

        let tooltipElem = null;
        let cleanupAutoUpdate = null;
        let tooltipTimeout = null;

        function showTooltip() {
            const hasAriaLabel = trigger.hasAttribute('aria-label');
            const tooltipText = hasAriaLabel ? trigger.getAttribute('aria-label') : trigger.getAttribute('data-tooltip');
            let delay = parseInt(trigger.getAttribute('data-tooltip'), 10);
            if (isNaN(delay) || delay === 0) {
                delay = 200;
            }
            tooltipTimeout = setTimeout(() => {
                tooltipElem = document.createElement('div');
                tooltipElem.className = 'tooltip';
                tooltipElem.innerText = tooltipText;
                tooltipElem.style.opacity = '0';
                tooltipElem.style.transition = 'opacity 50ms ease-out';
                document.body.appendChild(tooltipElem);
                FloatingUIDOM.computePosition(trigger, tooltipElem, {
                    placement: 'top',
                    middleware: [
                        FloatingUIDOM.offset(8),
                        FloatingUIDOM.flip(),
                        FloatingUIDOM.shift({
                            padding: 5
                        }),
                    ],
                }).then(({
                    x,
                    y
                }) => {
                    Object.assign(tooltipElem.style, {
                        position: 'absolute',
                        left: `${x}px`,
                        top: `${y}px`,
                    });
                });
                requestAnimationFrame(() => {
                    tooltipElem.style.opacity = '1';
                });
                cleanupAutoUpdate = FloatingUIDOM.autoUpdate(trigger, tooltipElem, () => {
                    FloatingUIDOM.computePosition(trigger, tooltipElem, {
                        placement: 'top',
                        middleware: [
                            FloatingUIDOM.offset(8),
                            FloatingUIDOM.flip(),
                            FloatingUIDOM.shift({
                                padding: 5
                            }),
                        ],
                    }).then(({
                        x,
                        y
                    }) => {
                        Object.assign(tooltipElem.style, {
                            position: 'absolute',
                            left: `${x}px`,
                            top: `${y}px`,
                        });
                    });
                });
            }, delay);
        }

        function hideTooltip() {
            clearTimeout(tooltipTimeout);
            if (tooltipElem) {
                tooltipElem.style.opacity = '0';
                setTimeout(() => {
                    if (tooltipElem && tooltipElem.parentNode) {
                        tooltipElem.parentNode.removeChild(tooltipElem);
                        tooltipElem = null;
                    }
                }, 100);
            }
            if (cleanupAutoUpdate) {
                cleanupAutoUpdate();
                cleanupAutoUpdate = null;
            }
        }
        trigger.addEventListener('mouseenter', showTooltip);
        trigger.addEventListener('mouseleave', hideTooltip);

        // Mark that we've bound tooltip events to this element.
        trigger._tooltipBound = true;
    }

    // =============================================
    // Soft wrapping for log output - Global behavior
    // =============================================
    // Select all triggers and containers based on the data attributes
    const softWrapTriggers = document.querySelectorAll('[data-soft-wrap="trigger"]');
    const softWrapContainers = document.querySelectorAll('[data-soft-wrap="container"]');

    // Function to update all triggers and containers based on the given state
    function setGlobalSoftWrapState(state) {
        // Update every trigger to match the new state
        softWrapTriggers.forEach(trigger => {
            trigger.checked = state;
        });
        // Add or remove the .soft-wrap class on every container
        softWrapContainers.forEach(container => {
            if (state) {
                container.classList.add('soft-wrap');
            } else {
                container.classList.remove('soft-wrap');
            }
        });
    }

    // Attach a change listener to each trigger
    softWrapTriggers.forEach(trigger => {
        trigger.addEventListener('change', function() {
            // When one trigger is changed, update all triggers and containers to match its state
            setGlobalSoftWrapState(this.checked);
        });
    });

    // =============================================
    // Modal logic using <dialog> elements
    // =============================================

    function bindModalTrigger(trigger) {
        if (trigger._modalBound) return;
        trigger.addEventListener('click', (e) => {
            e.preventDefault();
            const targetModalId = trigger.getAttribute('data-modal-target');
            if (!targetModalId) return;
            const modal = document.getElementById(targetModalId);
            if (modal) {
                if (typeof modal.showModal === 'function') {
                    modal.showModal();
                } else {
                    modal.setAttribute('open', '');
                }
                // Update the modal with the task name.
                const taskName = trigger.getAttribute('data-task');
                const modalTaskNameSpan = modal.querySelector('#modalTaskName');
                if (modalTaskNameSpan && taskName) {
                    modalTaskNameSpan.textContent = taskName;
                }
                const taskNameInput = modal.querySelector('#taskName');
                if (taskNameInput && taskName) {
                    taskNameInput.value = taskName;
                    document.getElementById('modalScheduleExecSubmitButton').setAttribute('form', taskName + '-send');
                }

                // Set focus on the first focusable element.
                const focusableElements = modal.querySelectorAll(
                    'a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, object, embed, [contenteditable], [tabindex]:not([tabindex="-1"])'
                );
                if (focusableElements.length) {
                    focusableElements[0].focus();
                }

                // Add a keydown listener to trap focus and enable Escape closing.
                const trapFocus = function(e) {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        closeModal(modal);
                        return;
                    }
                    if (e.key === 'Tab') {
                        const focusable = Array.from(focusableElements).filter(
                            el => el.offsetParent !== null
                        );
                        if (focusable.length === 0) {
                            e.preventDefault();
                            return;
                        }
                        const firstElement = focusable[0];
                        const lastElement = focusable[focusable.length - 1];
                        if (e.shiftKey) {
                            if (document.activeElement === firstElement) {
                                e.preventDefault();
                                lastElement.focus();
                            }
                        } else {
                            if (document.activeElement === lastElement) {
                                e.preventDefault();
                                firstElement.focus();
                            }
                        }
                    }
                };
                modal.addEventListener('keydown', trapFocus);
                modal._trapFocusHandler = trapFocus;
            }
        });
        trigger._modalBound = true;
    }

    // 2. Close modals.
    // Inside each modal, any element with data-modal-close will close its modal.
    const modals = document.querySelectorAll('dialog[aria-modal="true"]');
    modals.forEach(modal => {
        // Set up close buttons.
        modal.querySelectorAll('[data-modal-close]').forEach(closeButton => {
            closeButton.addEventListener('click', (e) => {
                e.preventDefault();
                closeModal(modal);
            });
        });
        // Close modal when clicking on the backdrop (outside of the content).
        modal.addEventListener('click', (e) => {
            const modalContent = modal.querySelector('.window');
            if (modalContent && !modalContent.contains(e.target)) {
                closeModal(modal);
            }
        });
        // When the native cancel event fires (e.g. pressing Escape), close the modal.
        modal.addEventListener('cancel', (e) => {
            e.preventDefault();
            closeModal(modal);
        });
    });

    // Utility function to close modals.
    function closeModal(modal) {
        // Hide the confirmation dialog
        const dialog = document.getElementById('confirmationDialog');
        const dialogContent = document.querySelector('.dialog-content');
        if (dialogContent && dialog) {
            dialogContent.classList.remove('pop-up');
            dialogContent.classList.add('pop-down');
            dialog.style.display = 'none';
        }
        // Hide the modal
        if (typeof modal.close === 'function') {
            modal.close();
        } else {
            modal.removeAttribute('open');
        }
        if (modal._trapFocusHandler) {
            modal.removeEventListener('keydown', modal._trapFocusHandler);
            modal._trapFocusHandler = null;
        }
    }

    // =============================================
    // Binding
    // =============================================
    // Initial binding of tooltips on page load
    document.querySelectorAll('[data-tooltip]').forEach(trigger => {
        bindTooltip(trigger);
    });
    // Initial binding of expandable menus on page load
    document.querySelectorAll('[data-modal="trigger"]').forEach(trigger => {
        bindModalTrigger(trigger);
    });



});

document.fonts.ready.then(() => {
    document.documentElement.classList.add('fonts-loaded');
});
