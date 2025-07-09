// Bootstrap file for Module Federation
// This ensures the Module Federation container is ready before loading the app

const loadApp = async () => {
    // Wait for Module Federation container to be available
    if (window.sep_host) {
        try {
            // Wait for the container to be ready
            await window.sep_host.init();
            console.log("Module Federation container ready");
        } catch (error) {
            // Silently ignore Module Federation initialization errors
            // This is expected when not consuming remote modules
            console.warn("Module Federation init skipped (not using remote modules)");
        }
    }

    // Import and start the application
    await import("./index.js");
};

loadApp();
