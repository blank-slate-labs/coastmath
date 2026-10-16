import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Before the planner's modules, so a hosting package's startup runs before any store reads saved preferences.
import "@extensions/startup";
import "./theme.css";
import TerminalRouter from "./terminal_router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TerminalRouter />
  </StrictMode>,
);
