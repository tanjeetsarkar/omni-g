"use client";
import { useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Edge,
  type Connection,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import { EntityNode, type EntityNodeType } from "./EntityNode";
import type { Entity, Relationship } from "../../types/entities";

const nodeTypes = { entity: EntityNode } as NodeTypes;

const NODE_WIDTH = 220;
const NODE_HEIGHT = 80;

function applyDagreLayout(
  nodes: EntityNodeType[],
  edges: Edge[],
): EntityNodeType[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 80, nodesep: 60 });

  nodes.forEach((n) =>
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }),
  );
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      ...n,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });
}

interface KnowledgeGraphProps {
  entities: Entity[];
  relationships: Relationship[];
  newEntities?: Entity[];
}

export function KnowledgeGraph({
  entities,
  relationships,
  newEntities = [],
}: KnowledgeGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<EntityNodeType>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges],
  );

  // Build nodes + edges and apply dagre layout whenever entities/relationships change
  useEffect(() => {
    if (entities.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const rawNodes: EntityNodeType[] = entities.map((e) => ({
      id: e.id,
      type: "entity" as const,
      data: e as Entity & Record<string, unknown>,
      position: { x: 0, y: 0 }, // overwritten by dagre
    }));

    const rawEdges: Edge[] = relationships.map((r) => ({
      id: r.id,
      source: r.source_ref,
      target: r.target_ref,
      label: r.type,
      style: { stroke: "#64748b" },
      labelStyle: { fill: "#94a3b8", fontSize: 10 },
      animated: false,
    }));

    const laid = applyDagreLayout(rawNodes, rawEdges);
    setNodes(laid);
    setEdges(rawEdges);
  }, [entities, relationships, setNodes, setEdges]);

  // Animate new real-time entities into the graph
  useEffect(() => {
    if (newEntities.length === 0) return;

    setNodes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const truly_new = newEntities.filter((e) => !existingIds.has(e.id));
      if (truly_new.length === 0) return prev;

      const maxX = prev.reduce((m, n) => Math.max(m, n.position.x), 0);
      const clusterX = maxX + NODE_WIDTH * 2;

      const newNodes: EntityNodeType[] = truly_new.map((e, i) => ({
        id: e.id,
        type: "entity" as const,
        data: e as Entity & Record<string, unknown>,
        position: { x: clusterX, y: i * (NODE_HEIGHT + 20) },
      }));

      return [...prev, ...newNodes];
    });
  }, [newEntities, setNodes]);

  if (entities.length === 0 && newEntities.length === 0) {
    return (
      <div
        className="flex items-center justify-center w-full h-full text-slate-500 text-sm"
        data-testid="kg-empty"
      >
        Search for entities to explore the Knowledge Graph.
      </div>
    );
  }

  return (
    <div className="w-full h-full" data-testid="knowledge-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={4}
      >
        <Background color="#334155" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={(n) => {
            const data = n.data as unknown as Entity | undefined;
            return data ? "#6366f1" : "#64748b";
          }}
          style={{ background: "#1e293b" }}
        />
      </ReactFlow>
    </div>
  );
}
