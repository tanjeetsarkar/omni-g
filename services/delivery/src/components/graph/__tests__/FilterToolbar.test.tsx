/**
 * FilterToolbar component tests
 */

import { render, screen, fireEvent } from "@testing-library/react";
import FilterToolbar from "@/components/graph/FilterToolbar";
import type { FilterState } from "@/hooks/useGraphFilter";

const defaultFilterState: FilterState = {
  enabledTypes: new Set(["malware", "threat-actor"]),
  minConfidence: 0,
  searchQuery: "",
};

const defaultProps = {
  availableTypes: ["malware", "threat-actor", "campaign"],
  filterState: defaultFilterState,
  onToggleType: jest.fn(),
  onConfidenceChange: jest.fn(),
  onSearchChange: jest.fn(),
  onReset: jest.fn(),
  shownNodes: 5,
  totalNodes: 10,
};

describe("FilterToolbar", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders the search input", () => {
    render(<FilterToolbar {...defaultProps} />);
    expect(screen.getByLabelText(/search nodes/i)).toBeInTheDocument();
  });

  it("renders a toggle button for each available STIX type", () => {
    render(<FilterToolbar {...defaultProps} />);
    expect(screen.getByRole("button", { name: "malware" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "threat-actor" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "campaign" }),
    ).toBeInTheDocument();
  });

  it("renders the confidence range slider", () => {
    render(<FilterToolbar {...defaultProps} />);
    expect(screen.getByLabelText(/minimum confidence/i)).toBeInTheDocument();
  });

  it("renders the reset button", () => {
    render(<FilterToolbar {...defaultProps} />);
    expect(screen.getByRole("button", { name: /reset/i })).toBeInTheDocument();
  });

  it("calls onToggleType with the correct type when a type button is clicked", () => {
    render(<FilterToolbar {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: "malware" }));
    expect(defaultProps.onToggleType).toHaveBeenCalledWith("malware");
    expect(defaultProps.onToggleType).toHaveBeenCalledTimes(1);
  });

  it("calls onSearchChange with the input value when search text changes", () => {
    render(<FilterToolbar {...defaultProps} />);
    fireEvent.change(screen.getByLabelText(/search nodes/i), {
      target: { value: "emotet" },
    });
    expect(defaultProps.onSearchChange).toHaveBeenCalledWith("emotet");
  });

  it("calls onConfidenceChange with a parsed float when slider changes", () => {
    render(<FilterToolbar {...defaultProps} />);
    fireEvent.change(screen.getByLabelText(/minimum confidence/i), {
      target: { value: "0.7" },
    });
    expect(defaultProps.onConfidenceChange).toHaveBeenCalledWith(0.7);
  });

  it("calls onReset when the reset button is clicked", () => {
    render(<FilterToolbar {...defaultProps} />);
    fireEvent.click(screen.getByRole("button", { name: /reset/i }));
    expect(defaultProps.onReset).toHaveBeenCalledTimes(1);
  });

  it("displays the node count when shownNodes and totalNodes are provided", () => {
    render(<FilterToolbar {...defaultProps} />);
    expect(screen.getByText(/showing 5 of 10 nodes/i)).toBeInTheDocument();
  });

  it("marks enabled types with aria-pressed='true' and disabled with 'false'", () => {
    render(<FilterToolbar {...defaultProps} />);
    // malware and threat-actor are in enabledTypes
    expect(screen.getByRole("button", { name: "malware" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // campaign is NOT in enabledTypes
    expect(screen.getByRole("button", { name: "campaign" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("omits the node count section when shownNodes/totalNodes are undefined", () => {
    const { shownNodes: _s, totalNodes: _t, ...props } = defaultProps;
    render(<FilterToolbar {...props} />);
    expect(
      screen.queryByText(/showing .* of .* nodes/i),
    ).not.toBeInTheDocument();
  });
});
