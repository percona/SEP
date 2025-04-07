document.addEventListener('DOMContentLoaded', () => {

    const body = document.body;

    // Sidebar behaviors
    // =============================================
    // Select all sidebar links
    const sidebarLinks = document.querySelectorAll('.sidebar .list-item');
    const currentPath = window.location.pathname;

    // Set the active sidebar link
    sidebarLinks.forEach(link => {
        const linkPath = new URL(link.href, window.location.origin).pathname;
        if (linkPath === currentPath) {
            link.classList.add('active');
        }
    });

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

    // Dropdown menus with Floating UI
    // =============================================
    // Import Floating UI
    function setupExpandable(container) {

        // Ensure the container has the necessary elements.
        const trigger = container.querySelector('.trigger');
        const content = container.querySelector('.content');
        if (!trigger || !content) return;

        // Initially hide the content.
        content.style.display = 'none';

        // Set initial ARIA state for accessibility.
        trigger.setAttribute('aria-expanded', 'false');
        content.setAttribute('aria-hidden', 'true');

        // Function to update the position using Floating UI.
        function updatePosition() {
            FloatingUIDOM.computePosition(trigger, content, {
                placement: 'bottom',
                middleware: [
                    FloatingUIDOM.offset(4),
                    FloatingUIDOM.flip(),
                    FloatingUIDOM.shift({ padding: 16 }),
                ],
            }).then(({ x, y }) => {
                Object.assign(content.style, {
                    position: 'absolute',
                    left: `${x}px`,
                    top: `${y}px`,
                });
            });
        }

        // Variable to store the cleanup function from autoUpdate.
        let cleanupAutoUpdate = null;

        function show() {
            content.style.display = 'block';
            updatePosition();
            // Start autoUpdate so the menu repositions on changes (e.g., resize).
            cleanupAutoUpdate = FloatingUIDOM.autoUpdate(trigger, content, updatePosition);
            trigger.setAttribute('aria-expanded', 'true');
            content.setAttribute('aria-hidden', 'false');
        }

        function hide() {
            content.style.display = 'none';
            if (cleanupAutoUpdate) {
                cleanupAutoUpdate(); // Stop auto-updating when hidden.
                cleanupAutoUpdate = null;
            }
            trigger.setAttribute('aria-expanded', 'false');
            content.setAttribute('aria-hidden', 'true');
        }

        // Toggle the expandable element when clicking the trigger.
        trigger.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent the click from propagating.
            if (content.style.display === 'block') {
                hide();
            } else {
                show();
            }
        });

        // Hide the expandable element when clicking outside its container.
        document.addEventListener('click', (e) => {
            if (!container.contains(e.target)) {
                hide();
            }
        });
    }

    // Apply this to all elements that need the expandable behavior.
    const expandables = document.querySelectorAll('.menu');
    expandables.forEach(setupExpandable);

    // Tab functionality
    // =============================================
    // Select all tab buttons and tab panels
    const tabButtons = document.querySelectorAll('[role="tab"]');
    const tabContents = document.querySelectorAll('[role="tabpanel"]');

    // Restore tab state on load
    const savedTabId = localStorage.getItem('activeTabId');
    if (savedTabId) {
        // Find the saved tab and panel
        const savedTab = document.querySelector(`[role="tab"][aria-controls="${savedTabId}"]`);
        const savedPanel = document.getElementById(savedTabId);

        // If both exist, set them as active
        if (savedTab && savedPanel) {
            tabButtons.forEach(btn => btn.setAttribute('aria-selected', 'false'));
            tabContents.forEach(panel => panel.setAttribute('aria-hidden', 'true'));

            // Mark saved tab as selected
            savedTab.setAttribute('aria-selected', 'true');
            savedPanel.setAttribute('aria-hidden', 'false');
        }
    }

    // Listen for tab clicks
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {

            // Set aria-selected to false on all tabs
            tabButtons.forEach(btn => btn.setAttribute('aria-selected', 'false'));

            // Hide all panels
            tabContents.forEach(panel => panel.setAttribute('aria-hidden', 'true'));

            // Mark clicked tab as selected
            button.setAttribute('aria-selected', 'true');

            // Show its panel
            const targetId = button.getAttribute('aria-controls');
            const targetPanel = document.getElementById(targetId);
            targetPanel.setAttribute('aria-hidden', 'false');

            // Save selected tab in localStorage
            localStorage.setItem('activeTabId', targetId);
        });
    });

    // Simple-DataTables
    // Documentation: fiduswriter.github.io/simple-datatables/documentation
    // =============================================
    // Templating
    const templateBase = (options, dom) => `
    <div class='${options.classes.top}'>
        ${ options.searchable ? `
        <div class='${options.classes.search}'>
            <span class="material-symbols-outlined">pageview</span>
            <label class="visually-hidden">${options.labels.searchTitle}</label>
            <input class='${options.classes.input}' placeholder='${options.labels.placeholder}' type='search' title='${options.labels.searchTitle}'${dom.id ? ` aria-controls="${dom.id}"` : ""}>
        </div>` : "" }
        ${ options.paging && options.perPageSelect ? `
        <div class='${options.classes.dropdown}'>
            <label>
                <span class="material-symbols-outlined">arrow_drop_down</span>
                <span class="label">${options.labels.perPage}</span>
                <select class='${options.classes.selector}'></select>
            </label>
        </div>` : "" }
    </div>
    <div class='${options.classes.container}'${options.scrollY.length ? ` style='height: ${options.scrollY}; overflow-y: auto;'` : ""}></div>
    <div class='${options.classes.bottom}'>
        ${ options.paging ? `
        <div class='${options.classes.info}'></div>` : "" }
        <nav class='${options.classes.pagination}' aria-label="Table pagination"></nav>
    </div>`;

    // Base configuration
    const tableDefault = {
        perPage: 3,
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
        }
    };

    // Define custom configurations for specific tables
    const tableSavedTasks = {
        columns: [
            { select: 0, sort: true },
            { select: 3, sortable: false, searchable: false, headerClass: "options", cellClass: "options" }
        ]
    };

    // Applying configurations
    document.querySelectorAll('[data-table]').forEach(table => {
        let config = { ...tableDefault };
        if (table.getAttribute('data-table') === 'saved-tasks') {
            config = { ...config, ...tableSavedTasks };
        }
        // Initialize Simple-DataTables
        new simpleDatatables.DataTable(table, config);
    });

    // Behavior for .submitNextForm buttons
    // =============================================
    document.querySelectorAll('.submitNextForm').forEach(button => {
        button.addEventListener('click', e => {
            // Prevent default action of the button
            e.preventDefault();
            let nextElem = button.nextElementSibling;
            // Find the next form element
            while (nextElem && nextElem.tagName.toLowerCase() !== 'form') {
                nextElem = nextElem.nextElementSibling;
            }
            // If a form is found, submit it
            if (nextElem) {
                nextElem.submit();
            }
        });
    });

});

// Forcing the page to wait until the fonts are loaded
document.fonts.ready.then(() => {
    document.documentElement.classList.add('fonts-loaded');
});
