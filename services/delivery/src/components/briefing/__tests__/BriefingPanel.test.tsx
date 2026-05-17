/**
 * BriefingPanel component tests
 */

import { render, screen, waitFor } from "@testing-library/react";
import BriefingPanel from "@/components/briefing/BriefingPanel";

global.fetch = jest.fn();

describe("BriefingPanel", () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  it("renders list of briefings from mocked API response", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        briefings: [
          { id: "b1", date: "2025-01-15", title: "Morning Brief – Jan 15" },
          { id: "b2", date: "2025-01-16", title: "Morning Brief – Jan 16" },
        ],
      }),
    });

    render(<BriefingPanel tenantId="acme" />);

    await waitFor(() => {
      expect(screen.getByText("Morning Brief – Jan 15")).toBeInTheDocument();
      expect(screen.getByText("Morning Brief – Jan 16")).toBeInTheDocument();
    });
  });

  it('shows "Briefings unavailable" on error', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        briefings: [],
        error: "processor unavailable",
      }),
    });

    render(<BriefingPanel tenantId="acme" />);

    await waitFor(() => {
      expect(screen.getByText(/processor unavailable/i)).toBeInTheDocument();
    });
  });

  it("shows skeleton while loading", () => {
    // Never resolves — keeps it in loading state
    (global.fetch as jest.Mock).mockReturnValueOnce(new Promise(() => {}));

    render(<BriefingPanel tenantId="acme" />);

    expect(screen.getByLabelText(/loading briefings/i)).toBeInTheDocument();
  });

  it("shows 'No briefings available' when list is empty", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ briefings: [] }),
    });

    render(<BriefingPanel tenantId="acme" />);

    await waitFor(() => {
      expect(screen.getByText(/no briefings available/i)).toBeInTheDocument();
    });
  });

  it("shows Play buttons for each briefing", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        briefings: [
          { id: "b1", date: "2025-01-15", title: "Brief A" },
          { id: "b2", date: "2025-01-16", title: "Brief B" },
        ],
      }),
    });

    render(<BriefingPanel tenantId="acme" />);

    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: /play/i });
      expect(buttons).toHaveLength(2);
    });
  });
});
