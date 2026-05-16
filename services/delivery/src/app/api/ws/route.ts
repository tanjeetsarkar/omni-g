/**
 * WebSocket gateway stub (M5.1).
 *
 * Phase M5.1 will replace this with a full Socket.io server that:
 *   - subscribes to the `analyst-alerts` Kafka topic
 *   - broadcasts events to connected WebSocket clients, filtered by tenant
 *   - tracks connection lifecycle and Prometheus metrics
 *
 * Next.js App Router does not natively support long-lived WebSocket upgrades.
 * The production gateway will run as a separate Node.js process on port 3001
 * alongside the Next.js server. This route provides a placeholder for the
 * REST-based status endpoint.
 */
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    status: "not_implemented",
    message: "WebSocket gateway is implemented in Phase M5.1",
    gateway_port: 3001,
  });
}
