import { render, screen } from "@testing-library/react";
import FocusPanel from "@/components/graph/FocusPanel";
import type { GraphNode } from "@/types/graph";

const mockNodes: GraphNode[] = [
  {
    id: "n1",
    label: "Emotet",
    x: 10,
    y: 20,
    stixType: "malware",
    confidence: 0.85,
    communitySummary: "Commodity malware family.",
  },
  {
    id: "n2",
    label: "APT28",
    x: 30,
    y: 40,
    stixType: "threat-actor",
    confidence: 0.95,
    communitySummary: "State-sponsored group.",
  },
];

describe("FocusPanel", () => {
  it('shows placeholder when nodeId is null', () => {
    render(<FocusPanel nodeId={null} nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText(/click a node to inspect/i)).toBeInTheDocument();
  });

  it("shows node label when nodeId is provided", () => {
    render(<FocusPanel nodeId="n1" nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText("Emotet")).toBeInTheDocument();
  });

  it("shows STIX type badge for the selected node", () => {
    render(<FocusPanel nodeId="n1" nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText("malware")).toBeInTheDocument();
  });

  it("shows confidence percentage", () => {
    render(<FocusPanel nodeId="n1" nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText(/85%/)).toBeInTheDocument();
  });

  it("shows community summary", () => {
    render(<FocusPanel nodeId="n1" nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText("Commodity malware family.")).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = jest.fn();
    render(<FocusPanel nodeId="n1" nodes={mockNodes} onClose={onClose} />);
    screen.getByRole("button", { name: /close panel/i }).click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows different node when nodeId changes to n2", () => {
    render(<FocusPanel nodeId="n2" nodes={mockNodes} onClose={jest.fn()} />);
    expect(screen.getByText("APT28")).toBeInTheDocument();
  });
});
