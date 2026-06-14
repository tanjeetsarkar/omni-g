/**
 * Minimal tests for the new React Flow components.
 * @xyflow/react and dagre are stubbed via jest.config.ts moduleNameMapper.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { EntityNode, type EntityNodeType } from "@/components/graph/EntityNode";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import type { Entity, Relationship } from "@/types/entities";

const MOCK_ENTITY: Entity = {
  id: "entity--abc123",
  type: "Person",
  name: "Alice Smith",
  description: "A notable person",
  properties: { role: "analyst" },
  confidence: 0.85,
  tenant_id: "default",
  source_id: "src-1",
  created: "2026-01-01T00:00:00Z",
  modified: "2026-01-02T00:00:00Z",
};

// ── EntityNode ────────────────────────────────────────────────────────────────

describe("EntityNode", () => {
  const defaultProps = {
    id: "entity--abc123",
    type: "entity",
    data: MOCK_ENTITY,
    selected: false,
    zIndex: 0,
    isConnectable: true,
    xPos: 0,
    yPos: 0,
    dragging: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as unknown as Parameters<typeof EntityNode>[0];

  it("renders entity name", () => {
    render(<EntityNode {...defaultProps} />);
    expect(screen.getByText("Alice Smith")).toBeInTheDocument();
  });

  it("renders type badge", () => {
    render(<EntityNode {...defaultProps} />);
    expect(screen.getByText("Person")).toBeInTheDocument();
  });

  it("renders confidence percentage", () => {
    render(<EntityNode {...defaultProps} />);
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("expands accordion on click to show description", () => {
    render(<EntityNode {...defaultProps} />);
    const card = screen.getByRole("button");
    fireEvent.click(card);
    expect(screen.getByText("A notable person")).toBeInTheDocument();
  });

  it("shows properties when expanded", () => {
    render(<EntityNode {...defaultProps} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("role")).toBeInTheDocument();
    expect(screen.getByText("analyst")).toBeInTheDocument();
  });

  it("renders selected border when selected=true", () => {
    const { container } = render(
      <EntityNode {...{ ...defaultProps, selected: true }} />,
    );
    expect(container.firstChild).toHaveClass("border-indigo-400");
  });
});

// ── KnowledgeGraph ────────────────────────────────────────────────────────────

describe("KnowledgeGraph", () => {
  it("shows empty state when no entities provided", () => {
    render(<KnowledgeGraph entities={[]} relationships={[]} />);
    expect(screen.getByTestId("kg-empty")).toBeInTheDocument();
  });

  it("renders ReactFlow canvas when entities are provided", () => {
    const entities: Entity[] = [MOCK_ENTITY];
    const relationships: Relationship[] = [];
    render(
      <KnowledgeGraph entities={entities} relationships={relationships} />,
    );
    expect(screen.getByTestId("knowledge-graph")).toBeInTheDocument();
  });
});
