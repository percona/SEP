document.addEventListener('DOMContentLoaded', () => {

    const body = document.body;
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

    // Reusable function to set up an expandable element (with Floating UI)
    function setupExpandable(container) {
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

    // jQuery behavior for .submitNextForm buttons
    $('.submitNextForm').click(function (e) {
        e.preventDefault();
        $(this).next('form').submit();
    });
});

// Forcing the page to wait until the fonts are loaded
document.fonts.ready.then(() => {
    document.documentElement.classList.add('fonts-loaded');
});
