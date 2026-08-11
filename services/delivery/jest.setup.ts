import "@testing-library/jest-dom";

// Mock next/navigation useRouter for components that call it in jsdom.
// BriefingPanel uses useRouter for navigation; tests don't exercise the
// navigation path, so a no-op mock is sufficient.
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    prefetch: jest.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));
