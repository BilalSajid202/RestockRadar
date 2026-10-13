"use client";

import React, { useState, useEffect } from "react";

interface ShelfSummary {
  shelf_id: number;
  camera_id: number;
  name: string;
  aisle: string;
  level: string;
  total_facings: number;
  fill_pct: number;
  item_count: number;
  gap_count: number;
  status: "OK" | "LOW" | "EMPTY" | "UNKNOWN";
  last_updated: string | null;
}

interface PlanogramItem {
  zone: number;
  sku_id: number;
  name_en: string;
  name_ur?: string;
  category: string;
  unit_price: number;
  facings: number;
  depth_capacity: number;
}

interface ShelfState {
  shelf_id: number;
  name: string;
  aisle: string;
  level: string;
  total_facings: number;
  roi_polygon: number[][] | null;
  latest_snapshot: {
    item_count: number;
    gap_count: number;
    fill_pct: number;
    status: string;
    captured_at: string;
  } | null;
  latest_frame_path: string | null;
  planogram: PlanogramItem[];
}

interface SnapshotHistoryItem {
  snapshot_id: number;
  captured_at: string;
  fill_pct: number;
  item_count: number;
  gap_count: number;
  status: string;
}

interface SimStatus {
  sim_now: string;
  is_simulated: boolean;
  agent_enabled: boolean;
  dry_run: boolean;
}

interface TicketItem {
  ticket_id: number;
  sku_id: number;
  sku_name: string;
  sku_name_ur?: string;
  supplier_name: string;
  qty: number;
  cost: number;
  status: string;
  approval_required: boolean;
  created_at: string;
  reasoning?: any;
}

const API_BASE = "http://127.0.0.1:8000";

export default function Dashboard() {
  const [shelves, setShelves] = useState<ShelfSummary[]>([]);
  const [selectedShelfId, setSelectedShelfId] = useState<number>(1);
  const [shelfState, setShelfState] = useState<ShelfState | null>(null);
  const [history, setHistory] = useState<SnapshotHistoryItem[]>([]);
  const [simStatus, setSimStatus] = useState<SimStatus | null>(null);
  const [tickets, setTickets] = useState<TicketItem[]>([]);
  const [loadingStep, setLoadingStep] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean>(true);

  // Fetch initial data
  const loadDashboardData = async () => {
    try {
      // 1. Fetch shelves
      const shelvesRes = await fetch(`${API_BASE}/shelves`);
      if (shelvesRes.ok) {
        const data = await shelvesRes.json();
        setShelves(data);
        setBackendOnline(true);
      }

      // 2. Fetch Sim Status
      const simRes = await fetch(`${API_BASE}/sim/status`);
      if (simRes.ok) {
        setSimStatus(await simRes.json());
      }

      // 3. Fetch Tickets
      const ticketsRes = await fetch(`${API_BASE}/tickets`);
      if (ticketsRes.ok) {
        setTickets(await ticketsRes.json());
      }
    } catch (err) {
      console.warn("Backend not reachable, operating with fallback mode", err);
      setBackendOnline(false);
      // Fallback sample data if backend server is offline
      setShelves([
        {
          shelf_id: 1,
          camera_id: 1,
          name: "Dairy & Drinks Shelf A3-L1",
          aisle: "A3",
          level: "L1",
          total_facings: 10,
          fill_pct: 70.0,
          item_count: 7,
          gap_count: 3,
          status: "OK",
          last_updated: new Date().toISOString(),
        },
      ]);
    }
  };

  // Fetch detailed shelf state & history
  const loadShelfDetails = async (id: number) => {
    try {
      const stateRes = await fetch(`${API_BASE}/shelves/${id}/state`);
      if (stateRes.ok) {
        setShelfState(await stateRes.json());
      }

      const histRes = await fetch(`${API_BASE}/shelves/${id}/history?limit=30`);
      if (histRes.ok) {
        setHistory(await histRes.json());
      }
    } catch (err) {
      console.warn("Could not load shelf details", err);
    }
  };

  useEffect(() => {
    loadDashboardData();
  }, []);

  useEffect(() => {
    if (selectedShelfId) {
      loadShelfDetails(selectedShelfId);
    }
  }, [selectedShelfId]);

  // Replay action: advance time
  const handleAdvanceTime = async (minutes: number) => {
    setLoadingStep(true);
    try {
      const res = await fetch(`${API_BASE}/sim/advance`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ delta_minutes: minutes }),
      });
      if (res.ok) {
        await loadDashboardData();
        await loadShelfDetails(selectedShelfId);
      }
    } catch (err) {
      console.error("Failed to advance simulation", err);
    } finally {
      setLoadingStep(false);
    }
  };

  // Reset simulation time
  const handleResetSim = async () => {
    setLoadingStep(true);
    try {
      await fetch(`${API_BASE}/sim/reset`, { method: "POST" });
      await loadDashboardData();
      await loadShelfDetails(selectedShelfId);
    } catch (err) {
      console.error("Failed to reset sim clock", err);
    } finally {
      setLoadingStep(false);
    }
  };

  // Approve restock ticket
  const handleApproveTicket = async (ticketId: number) => {
    try {
      const res = await fetch(`${API_BASE}/tickets/${ticketId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "APPROVED", note: "Approved from UI" }),
      });
      if (res.ok) {
        loadDashboardData();
      }
    } catch (err) {
      console.error("Failed to approve ticket", err);
    }
  };

  // Reject restock ticket
  const handleRejectTicket = async (ticketId: number) => {
    try {
      const res = await fetch(`${API_BASE}/tickets/${ticketId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "REJECTED", note: "Rejected from UI" }),
      });
      if (res.ok) {
        loadDashboardData();
      }
    } catch (err) {
      console.error("Failed to reject ticket", err);
    }
  };

  // Compute aggregated KPI stats
  const totalShelves = shelves.length;
  const avgFill =
    shelves.length > 0
      ? Math.round(shelves.reduce((acc, s) => acc + s.fill_pct, 0) / shelves.length)
      : 0;
  const totalGaps = shelves.reduce((acc, s) => acc + s.gap_count, 0);
  const pendingApprovals = tickets.filter((t) => t.status === "PENDING_APPROVAL").length;

  const currentShelf = shelves.find((s) => s.shelf_id === selectedShelfId) || shelves[0];

  return (
    <div style={{ maxWidth: 1440, margin: "0 auto", padding: "24px 28px" }}>
      {/* Top Navigation & Status Bar */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 28,
          paddingBottom: 20,
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "var(--radius-md)",
              background: "var(--color-accent-gradient)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "var(--shadow-glow)",
            }}
          >
            <span style={{ fontSize: 22, fontWeight: 800 }}>⚡</span>
          </div>
          <div>
            <h1 style={{ fontSize: "1.45rem", fontWeight: 800, letterSpacing: "-0.02em" }}>
              Restock Radar
            </h1>
            <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)" }}>
              See → Predict → Act → Verify | Closed-Loop Autonomous Retail Stock
            </p>
          </div>
        </div>

        {/* Global Controls & Telemetry */}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            className="glass-panel"
            style={{
              padding: "8px 16px",
              display: "flex",
              alignItems: "center",
              gap: 12,
              fontSize: "0.82rem",
            }}
          >
            <span style={{ color: "var(--text-muted)" }}>Sim Clock:</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#38bdf8", fontWeight: 600 }}>
              {simStatus ? new Date(simStatus.sim_now).toLocaleString() : "Syncing..."}
            </span>
          </div>

          <div
            className={`badge ${backendOnline ? "badge-ok" : "badge-low"}`}
            style={{ padding: "6px 14px" }}
          >
            <span className="status-dot"></span>
            {backendOnline ? "API Online" : "Connecting..."}
          </div>
        </div>
      </header>

      {/* KPI Stats Row */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 18,
          marginBottom: 28,
        }}
      >
        <div className="glass-panel" style={{ padding: "18px 22px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Monitored Shelves
          </span>
          <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: 4, color: "var(--text-primary)" }}>
            {totalShelves}
          </div>
          <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>Aisles A1–A4 Camera Active</span>
        </div>

        <div className="glass-panel" style={{ padding: "18px 22px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Average Fill Rate
          </span>
          <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: 4, color: avgFill < 50 ? "#fb7185" : "#34d399" }}>
            {avgFill}%
          </div>
          <div
            style={{
              width: "100%",
              height: 6,
              background: "rgba(255, 255, 255, 0.08)",
              borderRadius: 3,
              marginTop: 8,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${avgFill}%`,
                height: "100%",
                background: avgFill < 50 ? "var(--color-rose)" : "var(--color-emerald)",
                transition: "width 0.5s ease",
              }}
            />
          </div>
        </div>

        <div className="glass-panel" style={{ padding: "18px 22px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Empty Facings (Gaps)
          </span>
          <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: 4, color: totalGaps > 0 ? "#fbbf24" : "var(--text-primary)" }}>
            {totalGaps}
          </div>
          <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>Planogram Mismatches Flagged</span>
        </div>

        <div className="glass-panel" style={{ padding: "18px 22px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
            Pending Human Approvals
          </span>
          <div style={{ fontSize: "2rem", fontWeight: 800, marginTop: 4, color: pendingApprovals > 0 ? "#f43f5e" : "#38bdf8" }}>
            {pendingApprovals}
          </div>
          <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>Above threshold orders waiting</span>
        </div>
      </section>

      {/* Main Grid: Control & Details */}
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1.9fr", gap: 24, alignItems: "start" }}>
        {/* Left Column: Shelves List + Replay Stepper + Tickets */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {/* Replay Controls Box (Milestone 6 core requirement) */}
          <div className="glass-panel" style={{ padding: 22 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <h2 style={{ fontSize: "1.05rem", fontWeight: 700 }}>Simulation & Replay Stepper</h2>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Step through store timeline</span>
            </div>
            <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)", marginBottom: 16 }}>
              Advance the virtual clock to trigger periodic frame ingestion, demand depletion, and replenishment verification:
            </p>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                className="btn btn-secondary"
                disabled={loadingStep}
                onClick={() => handleAdvanceTime(15)}
              >
                +15 Min
              </button>
              <button
                className="btn btn-primary"
                disabled={loadingStep}
                onClick={() => handleAdvanceTime(60)}
              >
                +1 Hour
              </button>
              <button
                className="btn btn-secondary"
                disabled={loadingStep}
                onClick={() => handleAdvanceTime(360)}
              >
                +6 Hours
              </button>
              <button
                className="btn btn-secondary"
                style={{ marginLeft: "auto" }}
                disabled={loadingStep}
                onClick={handleResetSim}
              >
                Reset Clock
              </button>
            </div>
          </div>

          {/* Shelves List */}
          <div className="glass-panel" style={{ padding: 22 }}>
            <h2 style={{ fontSize: "1.05rem", fontWeight: 700, marginBottom: 14 }}>
              Store Shelves Overview
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {shelves.map((s) => {
                const isSelected = s.shelf_id === selectedShelfId;
                const badgeClass =
                  s.status === "OK"
                    ? "badge-ok"
                    : s.status === "LOW"
                    ? "badge-low"
                    : s.status === "EMPTY"
                    ? "badge-empty"
                    : "badge-unknown";

                return (
                  <div
                    key={s.shelf_id}
                    onClick={() => setSelectedShelfId(s.shelf_id)}
                    style={{
                      padding: "14px 18px",
                      borderRadius: "var(--radius-md)",
                      background: isSelected ? "rgba(14, 165, 233, 0.12)" : "rgba(255, 255, 255, 0.03)",
                      border: `1px solid ${isSelected ? "var(--color-accent)" : "var(--border-subtle)"}`,
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{s.name}</div>
                        <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 2 }}>
                          Aisle {s.aisle} • Level {s.level} • {s.total_facings} Facings
                        </div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div className={`badge ${badgeClass}`}>{s.status}</div>
                        <div
                          style={{
                            fontSize: "0.9rem",
                            fontWeight: 700,
                            marginTop: 4,
                            color: s.fill_pct < 40 ? "#fb7185" : "#34d399",
                          }}
                        >
                          {s.fill_pct}% fill
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Restock Tickets & HITL Approvals */}
          <div className="glass-panel" style={{ padding: 22 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <h2 style={{ fontSize: "1.05rem", fontWeight: 700 }}>Restock Tickets (HITL)</h2>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                {tickets.length} total
              </span>
            </div>
            {tickets.length === 0 ? (
              <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", fontStyle: "italic" }}>
                No active replenishment tickets.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {tickets.map((t) => (
                  <div
                    key={t.ticket_id}
                    style={{
                      padding: "14px",
                      borderRadius: "var(--radius-md)",
                      background: "rgba(255, 255, 255, 0.02)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                      <div>
                        <span style={{ fontWeight: 700, fontSize: "0.92rem" }}>
                          {t.sku_name} {t.sku_name_ur ? `(${t.sku_name_ur})` : ""}
                        </span>
                        <div style={{ fontSize: "0.78rem", color: "var(--text-secondary)", marginTop: 2 }}>
                          Supplier: {t.supplier_name} • Qty: {t.qty} units • Cost: {t.cost.toLocaleString()} PKR
                        </div>
                      </div>
                      <span
                        className={`badge ${
                          t.status === "APPROVED" || t.status === "ORDERED"
                            ? "badge-ok"
                            : t.status === "PENDING_APPROVAL"
                            ? "badge-low"
                            : "badge-unknown"
                        }`}
                      >
                        {t.status}
                      </span>
                    </div>

                    {t.status === "PENDING_APPROVAL" && (
                      <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                        <button
                          className="btn btn-success"
                          style={{ padding: "6px 14px", fontSize: "0.78rem" }}
                          onClick={() => handleApproveTicket(t.ticket_id)}
                        >
                          Approve Order
                        </button>
                        <button
                          className="btn btn-danger"
                          style={{ padding: "6px 14px", fontSize: "0.78rem" }}
                          onClick={() => handleRejectTicket(t.ticket_id)}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Live Camera & Planogram & History Chart */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {/* Live Shelf Visual View */}
          <div className="glass-panel" style={{ padding: 22 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div>
                <h2 style={{ fontSize: "1.15rem", fontWeight: 700 }}>
                  {currentShelf ? currentShelf.name : "Shelf Detail"}
                </h2>
                <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                  Camera View & Bounding Box Perception
                </p>
              </div>
              <div style={{ display: "flex", gap: 14 }}>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>ON SHELF</div>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>
                    {shelfState?.latest_snapshot ? shelfState.latest_snapshot.item_count : currentShelf?.item_count || 0}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>GAPS</div>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#fbbf24" }}>
                    {shelfState?.latest_snapshot ? shelfState.latest_snapshot.gap_count : currentShelf?.gap_count || 0}
                  </div>
                </div>
              </div>
            </div>

            {/* Shelf Image Display Container */}
            <div
              style={{
                width: "100%",
                height: 380,
                borderRadius: "var(--radius-md)",
                background: "#050811",
                border: "1px solid var(--border-subtle)",
                position: "relative",
                overflow: "hidden",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {/* Attempt to load backend captured image if available */}
              {shelfState?.latest_frame_path ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`${API_BASE}/static/data/${shelfState.latest_frame_path.replace("backend/data/", "").replace("data/", "")}`}
                  alt="Shelf camera capture"
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                  onError={(e) => {
                    // Fallback to stylized SVG visual
                    (e.target as HTMLElement).style.display = "none";
                  }}
                />
              ) : null}

              {/* Dynamic Overlay Rendering Planogram Facings visually */}
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  alignItems: "center",
                  padding: 20,
                  background: "radial-gradient(circle at center, rgba(14, 165, 233, 0.05) 0%, rgba(9, 13, 22, 0.8) 100%)",
                }}
              >
                <div
                  style={{
                    width: "90%",
                    display: "grid",
                    gridTemplateColumns: "repeat(5, 1fr)",
                    gap: 12,
                    marginBottom: 20,
                  }}
                >
                  {shelfState?.planogram.slice(0, 5).map((p, idx) => (
                    <div
                      key={idx}
                      style={{
                        height: 110,
                        background: "rgba(255, 255, 255, 0.05)",
                        border: "1px solid rgba(56, 189, 248, 0.3)",
                        borderRadius: "var(--radius-sm)",
                        padding: 8,
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "space-between",
                        fontSize: "0.72rem",
                      }}
                    >
                      <span style={{ fontWeight: 700, color: "#38bdf8" }}>Zone {p.zone}</span>
                      <span style={{ color: "#ffffff", fontWeight: 600 }}>{p.name_en}</span>
                      <span style={{ color: "var(--text-muted)" }}>{p.unit_price} PKR</span>
                    </div>
                  ))}
                </div>

                <div
                  style={{
                    width: "90%",
                    display: "grid",
                    gridTemplateColumns: "repeat(5, 1fr)",
                    gap: 12,
                  }}
                >
                  {shelfState?.planogram.slice(5, 10).map((p, idx) => (
                    <div
                      key={idx}
                      style={{
                        height: 110,
                        background: "rgba(255, 255, 255, 0.05)",
                        border: "1px solid rgba(56, 189, 248, 0.3)",
                        borderRadius: "var(--radius-sm)",
                        padding: 8,
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "space-between",
                        fontSize: "0.72rem",
                      }}
                    >
                      <span style={{ fontWeight: 700, color: "#38bdf8" }}>Zone {p.zone}</span>
                      <span style={{ color: "#ffffff", fontWeight: 600 }}>{p.name_en}</span>
                      <span style={{ color: "var(--text-muted)" }}>{p.unit_price} PKR</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Status overlay badge */}
              <div style={{ position: "absolute", top: 16, right: 16 }}>
                <span className="badge badge-ok">Camera Online • 960x960</span>
              </div>
            </div>
          </div>

          {/* Historical Fill % Chart (SVG) */}
          <div className="glass-panel" style={{ padding: 22 }}>
            <h2 style={{ fontSize: "1.05rem", fontWeight: 700, marginBottom: 4 }}>
              Fill Rate History & Replenishment Timeline
            </h2>
            <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: 18 }}>
              Timeline demonstrating continuous customer removals and replenishment cycles
            </p>

            {history.length > 0 ? (
              <div style={{ width: "100%", height: 160, position: "relative" }}>
                <svg
                  viewBox={`0 0 ${Math.max(300, history.length * 20)} 120`}
                  style={{ width: "100%", height: "100%", overflow: "visible" }}
                >
                  {/* Grid lines */}
                  <line x1="0" y1="20" x2="100%" y2="20" stroke="rgba(255,255,255,0.06)" strokeDasharray="4" />
                  <line x1="0" y1="60" x2="100%" y2="60" stroke="rgba(255,255,255,0.06)" strokeDasharray="4" />
                  <line x1="0" y1="100" x2="100%" y2="100" stroke="rgba(255,255,255,0.06)" strokeDasharray="4" />

                  {/* Polyline */}
                  <polyline
                    fill="none"
                    stroke="#0ea5e9"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points={history
                      .map((h, i) => {
                        const x = (i / Math.max(1, history.length - 1)) * 300;
                        const y = 120 - (h.fill_pct / 100) * 100 - 10;
                        return `${x},${y}`;
                      })
                      .join(" ")}
                  />

                  {/* Data Points */}
                  {history.map((h, i) => {
                    const x = (i / Math.max(1, history.length - 1)) * 300;
                    const y = 120 - (h.fill_pct / 100) * 100 - 10;
                    return (
                      <circle
                        key={i}
                        cx={x}
                        cy={y}
                        r="4"
                        fill="#38bdf8"
                        stroke="#090d16"
                        strokeWidth="2"
                      />
                    );
                  })}
                </svg>
              </div>
            ) : (
              <div style={{ height: 100, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
                Step simulation to record historical snapshots.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
