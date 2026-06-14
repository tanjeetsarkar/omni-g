import type { Config } from "jest";
import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  coverageProvider: "v8",
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
    // Stub CSS imports from React Flow
    "^@xyflow/react/dist/style\\.css$": "<rootDir>/src/__mocks__/styleMock.ts",
    // Stub @xyflow/react (not installed until pnpm install runs)
    "^@xyflow/react$": "<rootDir>/src/__mocks__/@xyflow/react.tsx",
    // Stub dagre (not installed until pnpm install runs)
    "^dagre$": "<rootDir>/src/__mocks__/dagre.ts",
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
