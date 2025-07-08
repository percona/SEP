import React from "react";
import * as ReactDOM from "react-dom/client";
import App from "./App";

// Don't auto-render - let the consuming application control when to render
// The App component will be exposed via Module Federation for external use

// Make React and ReactDOM available globally for Module Federation
window.React = React;
window.ReactDOM = ReactDOM;
