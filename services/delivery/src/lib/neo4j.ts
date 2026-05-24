/**
 * Neo4j driver singleton for Next.js route handlers.
 *
 * Uses a module-level singleton to avoid connection pool exhaustion in
 * serverless / hot-reload environments.  Do NOT close the driver per request.
 */

import neo4j, { Driver } from "neo4j-driver";

let _driver: Driver | null = null;

export function getDriver(): Driver {
  if (_driver) return _driver;

  const url = process.env.NEO4J_URL ?? "bolt://localhost:7687";
  const user = process.env.NEO4J_USER ?? "neo4j";
  const password = process.env.NEO4J_PASSWORD ?? "omni-g-password";

  _driver = neo4j.driver(url, neo4j.auth.basic(user, password), {
    maxConnectionPoolSize: 10,
    connectionAcquisitionTimeout: 5000,
  });

  return _driver;
}
