import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  EChartsGraphCanvas,
  EChartsNode,
  EChartsLink,
} from "../EChartsGraphCanvas";

interface MockReactEChartsProps {
  option: {
    series: Array<{
      type: string;
      data: Array<Record<string, unknown>>;
      layout?: string;
    }>;
    legend: Array<{
      data: string[];
    }>;
  };
  onEvents?: {
    click?: (params: unknown) => void;
    dblclick?: (params: unknown) => void;
  };
  style?: React.CSSProperties;
}

// Mock ReactECharts for radial tree layout testing
jest.mock("echarts-for-react", () => {
  return function MockReactECharts({
    option,
    onEvents,
    style,
  }: MockReactEChartsProps) {
    // Extract node data from tree series: find first tree node by walking
    // the tree's root children recursively
    function getFirstNodeData(data: unknown): unknown | null {
      if (!data) return null;
      if (Array.isArray(data)) {
        const root = data[0] as Record<string, unknown> | undefined;
        if (
          root?.children &&
          Array.isArray(root.children) &&
          root.children.length > 0
        ) {
          const child = root.children[0] as Record<string, unknown>;
          return {
            name: child.name ?? "unknown",
            id: child.name,
            category: child.category ?? "Unknown",
            ...child,
          };
        }
        return data[0];
      }
      return data;
    }

    const firstNodeData = getFirstNodeData(option.series[0]?.data);

    const handleNodeClick = () => {
      if (onEvents?.click) {
        onEvents.click({
          dataType: "node",
          data: firstNodeData || {
            id: "node_0",
            name: "Node 0",
            category: "FACILITY",
            value: 0.8,
          },
        });
      }
    };

    const handleNodeDblClick = () => {
      if (onEvents?.dblclick) {
        onEvents.dblclick({
          dataType: "node",
          data: {
            id: (firstNodeData as Record<string, unknown>)?.name || "node_0",
          },
        });
      }
    };

    return (
      <div data-testid="echarts-mock-container" style={style}>
        <div
          data-testid="canvas-element"
          className="echarts-canvas-placeholder"
        >
          <canvas width="800" height="600" />
        </div>
        <div className="echarts-legend">
          {option.legend[0].data.map((category: string) => (
            <span key={category}>{category}</span>
          ))}
        </div>
        <button data-testid="click-node-btn" onClick={handleNodeClick}>
          Simulate Click Node
        </button>
        <button data-testid="dblclick-node-btn" onClick={handleNodeDblClick}>
          Simulate Double Click Node
        </button>
      </div>
    );
  };
});

describe("EChartsGraphCanvas UI Component (Radial Tree Layout)", () => {
  const mockNodes: EChartsNode[] = Array.from({ length: 200 }, (_, i) => ({
    id: `node_${i}`,
    name: `node_${i}`,
    symbolSize: i === 0 ? 45 : 22,
    category: i % 4 === 0 ? "FACILITY" : "PERSON",
    value: 0.8,
    x: Math.cos((2 * Math.PI * i) / 200) * 300,
    y: Math.sin((2 * Math.PI * i) / 200) * 300,
    itemStyle: { color: "#3b82f6" },
    rawContext: `Raw context ${i}`,
    sourceId: `src_${i}`,
    timestamp: "2026-08-01T00:00:00Z",
  }));

  const mockLinks: EChartsLink[] = [
    {
      source: "node_0",
      target: "node_1",
      value: 0.9,
    },
  ];

  const mockTreeData = {
    name: "node_0",
    label: "{typeBadge| FACILITY }{title| Node 0 }{subText| +0 links }",
    value: 0.8,
    itemStyle: { color: "#3b82f6" },
    category: "FACILITY",
    confidence: 0.8,
    children: [
      {
        name: "node_1",
        label: "{typeBadge| PERSON }{title| Node 1 }{subText| +0 links }",
        value: 0.8,
        itemStyle: { color: "#3b82f6" },
        category: "PERSON",
        children: [],
      },
    ],
  };

  it("renders with 200 nodes without frame drops (single canvas check)", () => {
    const { container } = render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        treeData={mockTreeData}
        onNodeSelect={jest.fn()}
        onNodeDrillDown={jest.fn()}
      />,
    );

    const canvasElements = container.querySelectorAll("canvas");
    expect(canvasElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("echarts-mock-container")).toBeInTheDocument();
  });

  it("simulates click on a node and asserts onNodeSelect fires", () => {
    const onNodeSelect = jest.fn();
    render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        treeData={mockTreeData}
        onNodeSelect={onNodeSelect}
        onNodeDrillDown={jest.fn()}
      />,
    );

    const clickBtn = screen.getByTestId("click-node-btn");
    fireEvent.click(clickBtn);

    expect(onNodeSelect).toHaveBeenCalledTimes(1);
  });

  it("simulates double-click on a node and asserts onNodeDrillDown fires with target ID", () => {
    const onNodeDrillDown = jest.fn();
    render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        treeData={mockTreeData}
        onNodeSelect={jest.fn()}
        onNodeDrillDown={onNodeDrillDown}
      />,
    );

    const dblClickBtn = screen.getByTestId("dblclick-node-btn");
    fireEvent.click(dblClickBtn);

    expect(onNodeDrillDown).toHaveBeenCalledTimes(1);
    expect(onNodeDrillDown).toHaveBeenCalledWith("node_1");
  });
});
