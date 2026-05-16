// Stub Sigma for jsdom — the real implementation requires WebGL.
const Sigma = jest.fn().mockImplementation(() => ({
  kill: jest.fn(),
  refresh: jest.fn(),
}));

export { Sigma };
