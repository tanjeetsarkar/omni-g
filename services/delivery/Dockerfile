# ============================================================
# Stage 1: Dependencies
# ============================================================
FROM node:24-alpine AS deps

WORKDIR /app

RUN corepack enable pnpm

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# ============================================================
# Stage 2: Builder
# ============================================================
FROM node:24-alpine AS builder

WORKDIR /app

RUN corepack enable pnpm

ENV CI=true

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm run build

# Compile the WebSocket gateway TypeScript → .gateway-dist/
RUN node_modules/.bin/tsc --project gateway/tsconfig.json

# ============================================================
# Stage 3: Gateway Runtime
# ============================================================
FROM node:24-alpine AS gateway-runtime

WORKDIR /app

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 gateway

# Copy only the compiled gateway and the production dependencies it needs
COPY --from=builder --chown=gateway:nodejs /app/.gateway-dist ./
COPY --from=deps /app/node_modules ./node_modules

USER gateway

EXPOSE 3001 9464

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:9464/metrics || exit 1

CMD ["node", "server.js"]

# ============================================================
# Stage 4: Next.js Runtime
# ============================================================
FROM node:24-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
