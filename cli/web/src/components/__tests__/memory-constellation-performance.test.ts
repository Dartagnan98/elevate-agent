import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const componentPath = path.resolve(testDir, "../MemoryConstellation.tsx");

function source(): string {
  return readFileSync(componentPath, "utf8");
}

describe("MemoryConstellation animation loop", () => {
  it("stops scheduling frames after the graph settles", () => {
    const text = source();

    expect(text).toContain("const wakeSimulationRef = useRef<(() => void) | null>(null)");
    expect(text).toMatch(/if \(alpha === 0 && globalGrow >= 1\) \{\s+return;\s+\}/);
    expect(text).not.toMatch(
      /if \(alpha === 0 && globalGrow >= 1\) \{\s+raf = requestAnimationFrame\(step\);/,
    );
  });

  it("wakes the stopped loop when interactions re-arm motion", () => {
    const text = source();
    const wakeCalls = text.match(/wakeSimulationRef\.current\?\.\(\);/g) ?? [];

    expect(wakeCalls.length).toBeGreaterThanOrEqual(4);
    expect(text).toContain("sim.alpha = 1;");
    expect(text).toContain("sim.alpha = Math.max(sim.alpha, 0.6);");
    expect(text).toContain("if (simRef.current) simRef.current.alpha = 0.5;");
  });
});
