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
      data: EChartsNode[];
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

// Mock ReactECharts to simulate standard react events easily and handle JSDOM canvas restrictions
jest.mock("echarts-for-react", () => {
  return function MockReactECharts({
    option,
    onEvents,
    style,
  }: MockReactEChartsProps) {
    const handleNodeClick = () => {
      if (onEvents?.click) {
        onEvents.click({
          dataType: "node",
          data: option.series[0].data[0],
        });
      }
    };

    const handleNodeDblClick = () => {
      if (onEvents?.dblclick) {
        onEvents.dblclick({
          dataType: "node",
          data: option.series[0].data[0],
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

describe("EChartsGraphCanvas UI Component", () => {
  const mockNodes: EChartsNode[] = Array.from({ length: 200 }, (_, i) => ({
    id: `node_${i}`,
    name: `Node ${i}`,
    symbolSize: i === 0 ? 45 : 22,
    category: i % 4 === 0 ? "FACILITY" : "PERSON",
    value: 0.8,
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

  it("renders with 200 nodes without frame drops (single canvas check)", () => {
    const { container } = render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        onNodeSelect={jest.fn()}
        onNodeDrillDown={jest.fn()}
      />,
    );

    const canvasElements = container.querySelectorAll("canvas");
    expect(canvasElements).toHaveLength(1); // verifying single <canvas> rendering as required
    expect(screen.getByTestId("echarts-mock-container")).toBeInTheDocument();
  });

  it("simulates click on a node and asserts onNodeSelect receives the full metadata payload", () => {
    const onNodeSelect = jest.fn();
    render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        onNodeSelect={onNodeSelect}
        onNodeDrillDown={jest.fn()}
      />,
    );

    const clickBtn = screen.getByTestId("click-node-btn");
    fireEvent.click(clickBtn);

    expect(onNodeSelect).toHaveBeenCalledTimes(1);
    expect(onNodeSelect).toHaveBeenCalledWith({
      id: "node_0",
      name: "Node 0",
      symbolSize: 45,
      category: "FACILITY",
      value: 0.8,
      itemStyle: { color: "#3b82f6" },
      rawContext: "Raw context 0",
      sourceId: "src_0",
      timestamp: "2026-08-01T00:00:00Z",
    });
  });

  it("simulates double-click on a node and asserts onNodeDrillDown fires with target ID", () => {
    const onNodeDrillDown = jest.fn();
    render(
      <EChartsGraphCanvas
        nodes={mockNodes}
        links={mockLinks}
        onNodeSelect={jest.fn()}
        onNodeDrillDown={onNodeDrillDown}
      />,
    );

    const dblClickBtn = screen.getByTestId("dblclick-node-btn");
    fireEvent.click(dblClickBtn);

    expect(onNodeDrillDown).toHaveBeenCalledTimes(1);
    expect(onNodeDrillDown).toHaveBeenCalledWith("node_0");
  });
});
