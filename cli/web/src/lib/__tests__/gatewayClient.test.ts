import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GatewayClient } from "../gatewayClient";

type Listener = (event?: { data?: string }) => void;

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  private listeners = new Map<string, Listener[]>();
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: Listener) {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((item) => item !== listener),
    );
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close");
  }

  emit(type: string, event?: { data?: string }) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

describe("GatewayClient", () => {
  const originalWebSocket = globalThis.WebSocket;
  const originalWindow = globalThis.window;
  const originalLocation = globalThis.location;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: FakeWebSocket,
    });
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { __ELEVATE_SESSION_TOKEN__: "token" },
    });
    Object.defineProperty(globalThis, "location", {
      configurable: true,
      value: { host: "127.0.0.1:9120", protocol: "http:" },
    });
  });

  afterEach(() => {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: originalWebSocket,
    });
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
    Object.defineProperty(globalThis, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("rejects immediately when the cached socket is no longer open", async () => {
    const client = new GatewayClient();
    const connected = client.connect();
    const socket = FakeWebSocket.instances[0];
    socket.readyState = FakeWebSocket.OPEN;
    socket.emit("open");
    await connected;

    socket.readyState = FakeWebSocket.CLOSING;

    await expect(client.request("prompt.submit", {}, 1_000)).rejects.toThrow(
      /gateway not connected/,
    );
    expect(socket.sent).toEqual([]);
    expect(client.state).toBe("closed");
  });
});
