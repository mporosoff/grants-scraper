import { defineConfig } from "@playwright/test";

const e2ePort = Number(process.env.E2E_PORT || 8765);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["line"],
    ["json", { outputFile: "test-results/playwright-results.json" }],
  ],
  outputDir: "test-results/playwright-artifacts",
  use: {
    baseURL: `http://127.0.0.1:${e2ePort}`,
    browserName: "chromium",
    headless: true,
    reducedMotion: "reduce",
    trace: "retain-on-failure",
    viewport: { width: 1280, height: 900 },
  },
  webServer: process.env.E2E_EXTERNAL_SERVER === "1" ? undefined : {
    command: "node tests/e2e/static-server.mjs",
    url: `http://127.0.0.1:${e2ePort}/match_explorer.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
