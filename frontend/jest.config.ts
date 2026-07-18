import type { Config } from "jest";
import nextJest from "next/jest";

const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testPathIgnorePatterns: [
    "<rootDir>/node_modules/",
    "<rootDir>/.next/",
    "<rootDir>/e2e/",
    // The dark-factory PRD drift queue mirrors changed files as empty
    // timestamped markers (e.g. `.prd-drift-queue/<ts>_Foo.test.tsx`); jest
    // would otherwise match those `*.test.*` names as empty (failing) suites.
    "<rootDir>/.prd-drift-queue/",
  ],
  coverageDirectory: "coverage",
  coverageProvider: "v8",
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/layout.tsx",
    // Pure type-only modules contribute zero executable lines but
    // still count toward "statements" once instrumented -- exclude
    // them so the gate measures actual logic coverage.
    "!src/types/**",
  ],
  // Stream 6 PR 1 -- no-regression coverage gate.
  //
  // Current measured coverage (v0.4.0-dev, 591 tests):
  //   statements 57.08% / branches 76.25% / functions 72.28% / lines 57.08%
  //
  // The plan (Stream 6 D.2) targets 60% overall. We set the gate
  // *just below* current numbers so a small refactor that nudges a
  // metric by 1-2 points does not break CI on contact. The intent
  // is to ratchet these thresholds *upward* over time as new test
  // surface lands -- never relax them. If a PR drops coverage below
  // the floor, the fix is to add tests, not to lower the gate.
  coverageThreshold: {
    global: {
      statements: 55,
      branches: 70,
      functions: 70,
      lines: 55,
    },
  },
};

export default createJestConfig(config);
