import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./themes.css";
import "./styles.css";
import { installJournal } from "./shared/errorReport/journal";
import { installDebugMode } from "./shared/debug/debugMode";
import { DEFAULT_UI_THEME, applyUiTheme } from "./shared/uiThemes/uiThemes";

installJournal();
installDebugMode();
applyUiTheme(DEFAULT_UI_THEME);

const root = document.getElementById("root");

if (!root) {
  throw new Error("p2pKanban root element is missing");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
