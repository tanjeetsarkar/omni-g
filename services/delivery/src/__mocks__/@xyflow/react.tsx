/**
 * Mock for @xyflow/react — used in jsdom test environment.
 * Provides stub components so tests run without WebGL/DOM canvas.
 */
import React from "react";

export const ReactFlow = ({ children }: { children?: React.ReactNode }) =>
  React.createElement("div", { "data-testid": "react-flow" }, children);

export const Background = () => null;
export const Controls = () => null;
export const MiniMap = ({
  nodeColor,
  style,
}: {
  nodeColor?: unknown;
  style?: unknown;
}) => null;

export const Handle = ({
  type,
  position,
}: {
  type: string;
  position: string;
}) =>
  React.createElement("div", {
    "data-handle-type": type,
    "data-handle-position": position,
  });

export const Position = {
  Top: "top",
  Bottom: "bottom",
  Left: "left",
  Right: "right",
} as const;

export const useNodesState = () => [[], jest.fn(), jest.fn()] as const;
export const useEdgesState = () => [[], jest.fn(), jest.fn()] as const;
export const addEdge = jest.fn(
  (connection: unknown, edges: unknown[]) => edges,
);

export type Node = {
  id: string;
  type?: string;
  data: unknown;
  position: { x: number; y: number };
};
export type Edge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};
export type Connection = { source: string; target: string };
export type NodeProps<T = unknown> = {
  id: string;
  type?: string;
  data: T;
  selected?: boolean;
  zIndex?: number;
  isConnectable?: boolean;
  xPos?: number;
  yPos?: number;
  dragging?: boolean;
  positionAbsoluteX?: number;
  positionAbsoluteY?: number;
};
