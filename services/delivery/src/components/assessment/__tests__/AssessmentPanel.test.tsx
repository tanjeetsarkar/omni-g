/**
 * AssessmentPanel component tests.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import {
  AssessmentPanel,
  AssessmentEmptyState,
} from "@/components/assessment/AssessmentPanel";
import type { Assessment } from "@/types/assessment";

const MOCK_ASSESSMENT: Assessment = {
  id: "assessment--abc123",
  tenant_id: "default",
  kiq_id: "kiq--xyz789",
  hypothesis_id: null,
  conclusion: "Acme Corp is probably planning to acquire Retail Inc.",
  confidence: { low: 0.4, mid: 0.62, high: 0.8 },
  reasoning:
    "Multiple data points suggest Acme Corp has been evaluating acquisition targets in the retail sector.",
  assumptions: [
    "Acme Corp has sufficient capital reserves",
    "No regulatory hurdles",
  ],
  supporting_evidence_ids: ["evidence--a1", "evidence--a2", "evidence--a3"],
  contradicting_evidence_ids: ["evidence--b1"],
  collection_gaps: ["Current financial status of Retail Inc. (FY 2025)"],
  recommended_next_actions: [
    "Collect Acme financial filings",
    "Monitor Retail Inc. board announcements",
  ],
  status: "PUBLISHED",
  produced_by: "PROCESSOR",
  version: 1,
  superseded_by_id: null,
  created: "2026-07-05T10:00:00Z",
  modified: "2026-07-05T10:05:00Z",
};

describe("AssessmentPanel", () => {
  it("renders the BLUF conclusion", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.getByText("Acme Corp is probably planning to acquire Retail Inc."),
    ).toBeInTheDocument();
  });

  it("renders the BLUF label", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("BLUF")).toBeInTheDocument();
  });

  it("renders the status badge", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("PUBLISHED")).toBeInTheDocument();
  });

  it("renders the mid-point confidence percentage", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("Mid-point estimate: 62%")).toBeInTheDocument();
  });

  it("renders the confidence range", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("40%–80%")).toBeInTheDocument();
  });

  it("renders supporting evidence count", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders contradicting evidence count", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders intelligence gap", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.getByText("Current financial status of Retail Inc. (FY 2025)"),
    ).toBeInTheDocument();
  });

  it("renders recommended actions", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.getByText("Collect Acme financial filings"),
    ).toBeInTheDocument();
  });

  it("renders reasoning", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.getByText(/Multiple data points suggest/),
    ).toBeInTheDocument();
  });

  it("collapses detail on toggle click", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    const toggle = screen.getByLabelText("Collapse assessment");
    fireEvent.click(toggle);
    expect(
      screen.queryByText(/Multiple data points suggest/),
    ).not.toBeInTheDocument();
  });

  it("expands detail again after second toggle click", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    const toggle = screen.getByLabelText("Collapse assessment");
    fireEvent.click(toggle);
    const expandToggle = screen.getByLabelText("Expand assessment");
    fireEvent.click(expandToggle);
    expect(
      screen.getByText(/Multiple data points suggest/),
    ).toBeInTheDocument();
  });

  it("calls onDismiss when dismiss button clicked", () => {
    const onDismiss = jest.fn();
    render(
      <AssessmentPanel assessment={MOCK_ASSESSMENT} onDismiss={onDismiss} />,
    );
    const dismiss = screen.getByLabelText("Dismiss assessment");
    fireEvent.click(dismiss);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not render dismiss button when onDismiss is not provided", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.queryByLabelText("Dismiss assessment"),
    ).not.toBeInTheDocument();
  });

  it("renders with testid for integration targeting", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(screen.getByTestId("assessment-panel")).toBeInTheDocument();
  });

  it("renders assumptions when present", () => {
    render(<AssessmentPanel assessment={MOCK_ASSESSMENT} />);
    expect(
      screen.getByText("Acme Corp has sufficient capital reserves"),
    ).toBeInTheDocument();
  });
});

describe("AssessmentEmptyState", () => {
  it("renders no-assessment message", () => {
    render(<AssessmentEmptyState />);
    expect(screen.getByText("No assessment yet")).toBeInTheDocument();
  });

  it("renders explanation text", () => {
    render(<AssessmentEmptyState />);
    expect(screen.getByTestId("assessment-empty-state")).toBeInTheDocument();
  });
});
