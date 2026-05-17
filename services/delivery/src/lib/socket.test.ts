import { disconnectSocket, getSocket } from "@/lib/socket";

// socket.io-client is auto-mocked by Jest via __mocks__ if present,
// but here we mock the module directly for isolation.
jest.mock("socket.io-client", () => ({
  io: jest.fn(() => ({
    connected: false,
    connect: jest.fn(),
    disconnect: jest.fn(),
  })),
}));

describe("socket singleton", () => {
  afterEach(() => {
    disconnectSocket();
    jest.resetModules();
  });

  it("returns the same instance on repeated calls", () => {
    const s1 = getSocket();
    const s2 = getSocket();
    expect(s1).toBe(s2);
  });

  it("disconnectSocket clears the singleton", () => {
    const s1 = getSocket();
    disconnectSocket();
    const s2 = getSocket();
    // After disconnect, a new instance is created
    expect(s2).not.toBe(s1);
  });
});
