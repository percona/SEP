import React from "react";
import * as ReactDOM from "react-dom/client";
import App from "./App";

// Make React and ReactDOM available globally for Module Federation
// This must happen before any other imports that might use React
window.React = React;
window.ReactDOM = ReactDOM;

// Initialize Module Federation container
const initializeApp = async () => {
    // Wait for Module Federation container to be available
    if (window.sep_host) {
        try {
            // Initialize the container
            await window.sep_host.init();

            console.log("Module Federation container initialized successfully");
        } catch (error) {
            // Silently ignore Module Federation initialization errors
            // This is expected when not consuming remote modules
            console.warn("Module Federation init skipped (not using remote modules)");
        }
    }

    // Check if we're running standalone (not as a remote module)
    const container = document.getElementById("root");
    if (container) {
        const root = ReactDOM.createRoot(container);
        root.render( <
            React.StrictMode >
            <
            App / >
            <
            /React.StrictMode>
        );
    }
};

// Start the application
initializeApp();
