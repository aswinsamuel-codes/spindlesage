import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, type Approval, type Me } from "../api";
import { App, parseRoute } from "../App";
import { LineChart } from "../components/LineChart";
import { featureLabel, fmtRelative, powerKw, tempRise } from "../format";
import { SessionProvider } from "../session";
import { ApprovalsView } from "../views/Approvals";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiClient", () => {
  it("sends the API key and JSON body", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { status: "approved" }));
    const client = new ApiClient("ss_test", "/base", fetchImpl);
    await client.decide("a1", "approve", "looks right");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/base/approvals/a1/approve");
    expect(init.method).toBe("POST");
    expect(init.headers["X-API-Key"]).toBe("ss_test");
    expect(JSON.parse(init.body)).toEqual({ note: "looks right" });
  });

  it("surfaces the API's error detail", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(403, { detail: "Four-eyes rule" }));
    const error = await new ApiClient("k", "", fetchImpl).machines().catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.message).toBe("Four-eyes rule");
  });

  it("joins validation errors", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(422, { detail: [{ msg: "bad a" }, { msg: "bad b" }] }));
    const error = await new ApiClient("k", "", fetchImpl).machines().catch((e) => e);
    expect(error.message).toBe("bad a; bad b");
  });
});

describe("format", () => {
  const reading = { process_temperature_k: 310, air_temperature_k: 300, torque_nm: 40, rotational_speed_rpm: 1500 };

  it("derives the same signals as the agent", () => {
    expect(tempRise(reading)).toBe(10);
    expect(powerKw(reading)).toBeCloseTo((40 * 1500 * 2 * Math.PI) / 60 / 1000, 6);
  });

  it("labels features", () => {
    expect(featureLabel("temp_rise_k")).toBe("Temperature rise over ambient");
    expect(featureLabel("torque_nm_log_rolling_std")).toBe("Torque variability");
  });

  it("formats relative times", () => {
    const now = new Date("2026-01-01T00:00:00Z");
    expect(fmtRelative("2026-01-01T08:00:00Z", now)).toBe("in 8 h");
    expect(fmtRelative("2025-12-31T23:30:00Z", now)).toBe("30 min ago");
  });
});

describe("routing", () => {
  it("parses hash routes", () => {
    expect(parseRoute("#/")).toEqual({ name: "overview" });
    expect(parseRoute("#/machines/cnc-sim-01")).toEqual({ name: "machine", id: "cnc-sim-01" });
    expect(parseRoute("#/recommendations/abc")).toEqual({ name: "recommendation", id: "abc" });
    expect(parseRoute("#/approvals")).toEqual({ name: "approvals" });
    expect(parseRoute("#/nowhere")).toEqual({ name: "overview" });
  });
});

const VIEWER: Me = { user_id: "vera", role: "viewer", permissions: ["read"] };
const LEAD: Me = {
  user_id: "carol",
  role: "maintenance_lead",
  permissions: ["read", "request_recommendation", "decide_approval", "complete_action", "read_audit"],
};

function fakeClient(overrides: Partial<Record<keyof ApiClient, unknown>>): ApiClient {
  const base = {
    me: vi.fn(),
    machines: vi.fn().mockResolvedValue([]),
    status: vi.fn(),
    approvals: vi.fn().mockResolvedValue([]),
  };
  return { ...base, ...overrides } as unknown as ApiClient;
}

describe("sign-in", () => {
  it("rejects a bad key with a clear message", async () => {
    const client = fakeClient({ me: vi.fn().mockRejectedValue(new ApiError(401, "Missing or invalid API key")) });
    render(<App makeClient={() => client} />);
    await userEvent.type(screen.getByLabelText("API key"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That API key was not accepted.");
  });

  it("shows navigation by role", async () => {
    const client = fakeClient({ me: vi.fn().mockResolvedValue(VIEWER) });
    render(<App makeClient={() => client} />);
    await userEvent.type(screen.getByLabelText("API key"), "ss_viewer");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/vera/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Approvals" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit trail" })).not.toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("simulated");
  });
});

function approval(overrides: Partial<Approval>): Approval {
  return {
    id: "ap-1",
    recommendation_id: "rec-1",
    machine_id: "cnc-sim-01",
    action_index: 0,
    action_type: "inspect",
    urgency: "immediate",
    description: "Inspect coolant flow",
    evidence_ids: ["ANO-1"],
    status: "pending",
    requested_by: "alice",
    created_utc: "2026-11-21T09:00:00+00:00",
    expires_utc: "2026-11-21T17:00:00+00:00",
    decided_by: null,
    decided_utc: null,
    decision_note: null,
    completed_by: null,
    completed_utc: null,
    completion_note: null,
    ...overrides,
  };
}

function renderApprovals(me: Me, items: Approval[], decide = vi.fn()) {
  const client = fakeClient({ approvals: vi.fn().mockResolvedValue(items), decide });
  render(
    <SessionProvider client={client} me={me} onSignOut={() => {}}>
      <ApprovalsView />
    </SessionProvider>,
  );
  return decide;
}

describe("approvals", () => {
  it("lets a lead approve someone else's request", async () => {
    const decide = renderApprovals(LEAD, [approval({})], vi.fn().mockResolvedValue({}));
    await userEvent.type(await screen.findByLabelText(/Note/), "Inspect at shift change");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap-1", "approve", "Inspect at shift change"));
  });

  it("applies the four-eyes rule in the UI", async () => {
    renderApprovals(LEAD, [approval({ requested_by: "carol" })]);
    expect(await screen.findByText(/four-eyes rule/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("gives viewers no decision buttons", async () => {
    renderApprovals(VIEWER, [approval({})]);
    expect(await screen.findByText("Inspect coolant flow")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/Only maintenance leads can approve/)).toBeInTheDocument();
  });

  it("shows the API's refusal", async () => {
    const decide = vi.fn().mockRejectedValue(new ApiError(409, "A rejection needs a note explaining why"));
    renderApprovals(LEAD, [approval({})], decide);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("needs a note");
  });
});

describe("LineChart", () => {
  it("labels the latest value and handles empty data", () => {
    const points = [
      { t: new Date("2026-01-01T10:00:00Z"), v: 10 },
      { t: new Date("2026-01-01T10:30:00Z"), v: 12.34 },
    ];
    const { rerender } = render(<LineChart title="Temperature rise" unit="K" points={points} />);
    expect(screen.getByRole("img", { name: "Temperature rise" })).toBeInTheDocument();
    expect(screen.getByText("12.3")).toBeInTheDocument();
    rerender(<LineChart title="Torque" unit="Nm" points={[]} />);
    expect(screen.getByText("No readings yet.")).toBeInTheDocument();
  });
});
