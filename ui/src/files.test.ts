// @vitest-environment node
// Windows file names ignore case: "./orb" and "./Orb" are the same module there.
// The Windows CI caught exactly that once; this keeps it from coming back.
import { readdirSync } from "node:fs";
import { join } from "node:path";

test("no two modules differ only in letter case", () => {
  const names = readdirSync(join(process.cwd(), "src"));
  const modules = names.map((name) => name.replace(/\.(ts|tsx|css)$/, "").toLowerCase());
  const clashes = names.filter((_, i) => modules.indexOf(modules[i]) !== i);
  expect(names.length).toBeGreaterThan(5);
  expect(clashes).toEqual([]);
});
