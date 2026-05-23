// Stub Sigma for jsdom — the real implementation requires WebGL.
const Sigma = jest.fn().mockImplementation(() => {
  const listeners: Record<string, Array<(...args: unknown[]) => void>> = {};
  return {
    kill: jest.fn(),
    refresh: jest.fn(),
    getGraph: jest.fn(),
    on: jest
      .fn()
      .mockImplementation((event: string, cb: (...args: unknown[]) => void) => {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(cb);
      }),
    off: jest
      .fn()
      .mockImplementation((event: string, cb: (...args: unknown[]) => void) => {
        if (listeners[event]) {
          listeners[event] = listeners[event].filter((l) => l !== cb);
        }
      }),
    emit: jest.fn().mockImplementation((event: string, ...args: unknown[]) => {
      (listeners[event] ?? []).forEach((cb) => cb(...args));
    }),
  };
});

export { Sigma };
