import { render, screen } from "@testing-library/react";
import App from "./App";

test("the window shows the orb and can be dragged", () => {
  render(<App />);
  const orb = screen.getByRole("img", { name: "Rosie" });
  expect(orb.hasAttribute("data-tauri-drag-region")).toBe(true);
});
