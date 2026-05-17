import { render, screen } from "@testing-library/react";
import AlertBadge from "@/components/graph/AlertBadge";

describe("AlertBadge", () => {
  it('shows "No alerts" when count is 0', () => {
    render(<AlertBadge count={0} />);
    expect(screen.getByText(/no alerts/i)).toBeInTheDocument();
  });

  it("renders the alert count when count > 0", () => {
    render(<AlertBadge count={5} />);
    expect(screen.getByText(/5 alerts/i)).toBeInTheDocument();
  });

  it("renders singular 'alert' for count of 1", () => {
    render(<AlertBadge count={1} />);
    expect(screen.getByText(/1 alert$/i)).toBeInTheDocument();
  });

  it("renders pulsing dot when count > 0", () => {
    const { container } = render(<AlertBadge count={3} />);
    const dot = container.querySelector(".animate-pulse");
    expect(dot).toBeInTheDocument();
  });

  it("does not render pulsing dot when count is 0", () => {
    const { container } = render(<AlertBadge count={0} />);
    const dot = container.querySelector(".animate-pulse");
    expect(dot).not.toBeInTheDocument();
  });
});
