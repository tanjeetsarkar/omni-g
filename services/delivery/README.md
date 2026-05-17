# Delivery Service

The **Delivery** service is the real-time frontend of Omni-G. It renders the interactive knowledge graph using Sigma.js, receives live analyst alerts via WebSocket, and serves the main dashboard.

## Responsibilities

- **WebSocket Gateway** — subscribes to `analyst-alerts` Kafka topic and broadcasts to connected clients (Phase M5.1)
- **Graph Dashboard** — WebGL-accelerated Sigma.js rendering supporting 100k+ nodes (Phase M5.2)
- **Real-Time Alerts** — highlights new nodes/edges as events arrive
- **Audio Briefings** — plays daily GraphRAG-generated briefings (Phase M5.3)

## Directory Structure

```
delivery/
├── src/
│   ├── app/
│   │   ├── layout.tsx             # Root layout
│   │   ├── page.tsx               # Dashboard home
│   │   └── api/
│   │       ├── health/route.ts    # Liveness probe
│   │       └── ws/route.ts        # WebSocket gateway stub (M5.1)
│   ├── components/
│   │   └── graph/
│   │       └── GraphView.tsx      # Sigma.js renderer
│   ├── lib/
│   │   └── socket.ts             # Socket.io client singleton
│   └── __mocks__/               # Jest stubs for WebGL APIs
├── jest.config.ts
├── jest.setup.ts
├── next.config.ts
├── Dockerfile
└── README.md
```

## Configuration

| Variable              | Default                  | Description                     |
| --------------------- | ------------------------ | ------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001`  | Processor API base URL          |
| `NEXT_PUBLIC_WS_URL`  | `ws://localhost:3001`    | WebSocket gateway URL           |
| `NEO4J_URL`           | `neo4j://localhost:7687` | Neo4j URL (server-side queries) |
| `NEO4J_USER`          | `neo4j`                  | Neo4j username                  |
| `NEO4J_PASSWORD`      | `omni-g-password`        | Neo4j password                  |

## Running Locally

```bash
pnpm install
pnpm dev          # starts on :3000
pnpm test         # run Jest
pnpm build        # production build
```

## API Endpoints

| Method | Path          | Description                     |
| ------ | ------------- | ------------------------------- |
| `GET`  | `/api/health` | Liveness probe                  |
| `GET`  | `/api/ws`     | WebSocket gateway status (M5.1) |

## Docker

```bash
docker build -t omni-g/delivery .
docker run -p 3000:3000 omni-g/delivery
```

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
