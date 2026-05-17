/**
 * GET /api/ws — WebSocket gateway connection info (M5.1-B).
 *
 * Returns gateway port and topic so clients know where to connect.
 * The actual Socket.io server is the standalone gateway process on port 3001.
 */
import { NextResponse } from "next/server";

export async function GET() {
  const gatewayPort = parseInt(process.env.GATEWAY_PORT ?? "3001", 10);
  return NextResponse.json({
    status: "ok",
    gateway_port: gatewayPort,
    kafka_topic: process.env.KAFKA_ALERTS_TOPIC ?? "analyst-alerts",
    message: `Connect to ws://localhost:${gatewayPort} via Socket.io`,
  });
}
