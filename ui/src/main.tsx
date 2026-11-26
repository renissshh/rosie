import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Deck from "./Deck";
import "./styles.css";
import { windowKind } from "./windows";

// One page, two windows: the orb (index.html) and the Command Deck (index.html#deck).
const kind = windowKind();
document.body.dataset.window = kind;

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>{kind === "deck" ? <Deck /> : <App />}</StrictMode>,
);
