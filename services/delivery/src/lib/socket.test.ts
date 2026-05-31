import {
  disconnectSocket,
  getCurrentSubscription,
  getSocket,
  joinTenant,
  subscribe,
} from "@/lib/socket";

type MockListener = (...args: unknown[]) => void;

jest.mock("socket.io-client", () => {
  const instances: Array<{
    connected: boolean;
    connect: jest.Mock;
    disconnect: jest.Mock;
    emit: jest.Mock;
    on: jest.Mock;
    off: jest.Mock;
    _listeners: Record<string, MockListener[]>;
    _triggerConnect: () => void;
    rooms: Set<string>;
  }> = [];

  const createMockSocket = () => {
    const listeners: Record<string, MockListener[]> = {};
    type MockSocketType = {
      connected: boolean;
      connect: jest.Mock;
      disconnect: jest.Mock;
      emit: jest.Mock;
      on: jest.Mock;
      off: jest.Mock;
      _listeners: Record<string, MockListener[]>;
      _triggerConnect: () => void;
      rooms: Set<string>;
    };
    const mockSocket: MockSocketType = {
      connected: false,
      connect: jest.fn(() => {
        mockSocket.connected = true;
      }),
      disconnect: jest.fn(() => {
        mockSocket.connected = false;
      }),
      emit: jest.fn(),
      on: jest.fn((event: string, handler: MockListener): MockSocketType => {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(handler);
        return mockSocket;
      }),
      off: jest.fn((event: string, handler?: MockListener) => {
        if (!listeners[event]) return mockSocket;
        listeners[event] = handler
          ? listeners[event].filter((candidate) => candidate !== handler)
          : [];
        return mockSocket;
      }),
      _listeners: listeners,
      _triggerConnect: () => listeners.connect?.forEach((handler) => handler()),
      rooms: new Set(["socketId"]),
    };

    instances.push(mockSocket);
    return mockSocket;
  };

  return {
    io: jest.fn(() => createMockSocket()),
    __mock: { instances },
  };
});

function getClientMock() {
  return jest.requireMock("socket.io-client").__mock as {
    instances: Array<{
      connected: boolean;
      connect: jest.Mock;
      disconnect: jest.Mock;
      emit: jest.Mock;
      on: jest.Mock;
      off: jest.Mock;
      _listeners: Record<string, MockListener[]>;
      _triggerConnect: () => void;
      rooms: Set<string>;
    }>;
  };
}

describe("socket singleton", () => {
  afterEach(() => {
    disconnectSocket();

    getClientMock().instances.forEach((mockSocket) => {
      mockSocket.connected = false;
      mockSocket.connect.mockClear();
      mockSocket.disconnect.mockClear();
      mockSocket.emit.mockClear();
      mockSocket.on.mockClear();
      mockSocket.off.mockClear();
      Object.keys(mockSocket._listeners).forEach((event) => {
        mockSocket._listeners[event] = [];
      });
    });
    getClientMock().instances.length = 0;
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

    expect(s2).not.toBe(s1);
    expect(getCurrentSubscription()).toBeNull();
  });

  it("subscribe emits subscribe with tenant-only params when already connected", () => {
    getSocket();
    const mockSocket = getClientMock().instances.at(-1)!;
    mockSocket.connected = true;

    subscribe({ tenant_id: "tenant-a" });

    expect(mockSocket.emit).toHaveBeenCalledWith(
      "subscribe",
      { tenant_id: "tenant-a" },
      expect.any(Function),
    );
  });

  it("subscribe includes community_id in emit payload", () => {
    getSocket();
    const mockSocket = getClientMock().instances.at(-1)!;
    mockSocket.connected = true;

    subscribe({ tenant_id: "tenant-a", community_id: "community-1" });

    expect(mockSocket.emit).toHaveBeenCalledWith(
      "subscribe",
      { tenant_id: "tenant-a", community_id: "community-1" },
      expect.any(Function),
    );
  });

  it("getCurrentSubscription returns stored params after subscribe", () => {
    subscribe({
      tenant_id: "tenant-a",
      community_id: "community-1",
      severity: "critical",
    });

    expect(getCurrentSubscription()).toEqual({
      tenant_id: "tenant-a",
      community_id: "community-1",
      severity: "critical",
    });
  });

  it("disconnectSocket clears currentSubscription", () => {
    subscribe({ tenant_id: "tenant-a" });

    disconnectSocket();

    expect(getCurrentSubscription()).toBeNull();
  });

  it("re-emits subscription on reconnect", () => {
    subscribe({
      tenant_id: "tenant-a",
      community_id: "community-1",
      severity: "high",
    });
    const mockSocket = getClientMock().instances.at(-1)!;

    mockSocket.emit.mockClear();
    mockSocket._triggerConnect();

    expect(mockSocket.emit).toHaveBeenCalledWith("subscribe", {
      tenant_id: "tenant-a",
      community_id: "community-1",
      severity: "high",
    });
  });

  it("subscribe twice keeps a single connect handler", () => {
    subscribe({ tenant_id: "tenant-a" });
    subscribe({ tenant_id: "tenant-b", severity: "critical" });

    const mockSocket = getClientMock().instances.at(-1)!;

    expect(mockSocket._listeners.connect).toHaveLength(1);
  });

  it("subscribe does not remove unrelated connect listeners", () => {
    const socket = getSocket();
    const mockSocket = getClientMock().instances.at(-1)!;
    const unrelatedListener = jest.fn();

    socket.on("connect", unrelatedListener);
    subscribe({ tenant_id: "tenant-a" });
    subscribe({ tenant_id: "tenant-b", severity: "critical" });

    expect(mockSocket._listeners.connect).toHaveLength(2);
    mockSocket._triggerConnect();
    expect(unrelatedListener).toHaveBeenCalled();
    expect(mockSocket.emit).toHaveBeenCalledWith("subscribe", {
      tenant_id: "tenant-b",
      severity: "critical",
    });
  });

  it("joinTenant remains backward compatible", () => {
    joinTenant("tenant-a");
    const mockSocket = getClientMock().instances.at(-1)!;
    mockSocket.emit.mockClear();
    mockSocket._triggerConnect();

    expect(getCurrentSubscription()).toEqual({ tenant_id: "tenant-a" });
    expect(mockSocket.emit).toHaveBeenCalledWith("subscribe", {
      tenant_id: "tenant-a",
    });
  });
});
