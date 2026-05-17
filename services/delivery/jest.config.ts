import type { Config } from "jest";
import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  coverageProvider: "v8",
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
    // Stub WebGL / canvas APIs not available in jsdom
    "^sigma$": "<rootDir>/src/__mocks__/sigma.ts",
    "^graphology$": "<rootDir>/src/__mocks__/graphology.ts",
    "^graphology-layout-forceatlas2$": "<rootDir>/src/__mocks__/graphology-layout-forceatlas2.ts",
  },
  testMatch: [
    "<rootDir>/src/**/*.test.{ts,tsx}",
    "<rootDir>/tests/**/*.test.{ts,tsx}",
    "<rootDir>/gateway/**/*.test.{ts,tsx}",
  ],
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/app/layout.tsx",
    "!src/app/globals.css",
  ],
};

export default createJestConfig(config);
