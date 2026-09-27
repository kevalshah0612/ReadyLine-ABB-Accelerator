import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  Check,
  ClipboardList,
  Database,
  Factory,
  LogOut,
  Plus,
  Radio,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { api } from "./api";
import type {
  Asset,
  AuditRow,
  EventRow,
  Order,
  Part,
  Reading,
  Resources,
  Run,
  Status,
  User,
} from "./types";
import {
  Badge,
  Points,
  plainText,
  date,
  Empty,
  ErrorBox,
  Field,
  Form,
  Modal,
  money,
  num,
  text,
  Trend,
} from "./components";
import {
  AssetForm,
  PartForm,
  ProcedureForm,
  TelemetryForm,
  UserForm,
  WindowForm,
} from "./forms";

type View = "fleet" | "agents" | "orders" | "resources" | "audit";
type Dialog =
  "asset" | "telemetry" | "part" | "window" | "procedure" | "user" | null;
const navigation = [
  { id: "fleet", label: "Fleet intelligence", icon: Activity },
  { id: "agents", label: "Agent runs", icon: Workflow },
  { id: "orders", label: "Work orders", icon: ClipboardList },
  { id: "resources", label: "Planning & resources", icon: Boxes },
  { id: "audit", label: "Activity log", icon: ShieldCheck },
] as const;

export default function App() {
  const [status, setStatus] = useState<Status | null>(null),
    [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true);
  const [view, setView] = useState<View>("fleet"),
    [assets, setAssets] = useState<Asset[]>([]),
    [runs, setRuns] = useState<Run[]>([]),
    [orders, setOrders] = useState<Order[]>([]);
  const [resources, setResources] = useState<Resources>({
      parts: [],
      procedures: [],
      windows: [],
    }),
    [audit, setAudit] = useState<AuditRow[]>([]);
  const [selected, setSelected] = useState(""),
    [runId, setRunId] = useState(""),
    [readings, setReadings] = useState<Reading[]>([]),
    [events, setEvents] = useState<EventRow[]>([]);
  const [dialog, setDialog] = useState<Dialog>(null),
    [part, setPart] = useState<Part | undefined>(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [updated, setUpdated] = useState("");
  const canPlan =
      !!user && ["admin", "supervisor", "planner"].includes(user.role),
    canApprove = !!user && ["admin", "supervisor"].includes(user.role);
  const canComplete = !!user && ["admin", "technician"].includes(user.role);
  const selectedAsset = assets.find((a) => a.id === selected),
    selectedRun = runs.find((r) => r.id === runId);
  const refresh = useCallback(async () => {
    const [a, r, o, s, l] = await Promise.all([
      api<Asset[]>("/assets"),
      api<Run[]>("/runs"),
      api<Order[]>("/work-orders"),
      api<Resources>("/resources"),
      api<AuditRow[]>("/audit"),
    ]);
    setAssets(a);
    setRuns(r);
    setOrders(o);
    setResources(s);
    setAudit(l);
    setUpdated(new Date().toISOString());
    setSelected((previous) =>
      a.some((item) => item.id === previous) ? previous : (a[0]?.id ?? ""),
    );
    setRunId((previous) =>
      r.some((item) => item.id === previous) ? previous : (r[0]?.id ?? ""),
    );
  }, []);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const s = await api<Status>("/status");
        if (live) setStatus(s);
        try {
          const u = await api<User>("/auth/me");
          if (live) setUser(u);
        } catch {
          /* An unauthenticated visitor gets the sign-in form. */
        }
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setBoot(false);
      }
    })();
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!user) return;
    let live = true;
    const load = () =>
      refresh().catch((e) => {
        if (live) setError(e.message);
      });
    load();
    const timer = setInterval(load, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [user, refresh]);
  useEffect(() => {
    if (!selected || !user) return;
    let live = true;
    setReadings([]);
    const load = () =>
      api<Reading[]>(`/assets/${selected}/telemetry`)
        .then((r) => {
          if (live) setReadings(r);
        })
        .catch((e) => {
          if (live) setError(e.message);
        });
    load();
    const timer = setInterval(load, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [selected, user]);
  useEffect(() => {
    setEvents([]);
    if (!runId || !user) return;
    let live = true;
    api<EventRow[]>(`/runs/${runId}/events`)
      .then((rows) => {
        if (live)
          setEvents((current) =>
            [
              ...new Map([...rows, ...current].map((e) => [e.id, e])).values(),
            ].sort((a, b) => a.id - b.id),
          );
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    const stream = new EventSource(`/api/runs/${runId}/stream`);
    stream.onmessage = (e) => {
      const row = JSON.parse(e.data) as EventRow;
      setEvents((current) =>
        current.some((item) => item.id === row.id)
          ? current
          : [...current, row].sort((a, b) => a.id - b.id),
      );
    };
    stream.addEventListener("done", () => {
      stream.close();
      refresh().catch((e) => setError(e.message));
    });
    return () => {
      live = false;
      stream.close();
    };
  }, [runId, user, refresh]);
  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function done() {
    await refresh();
    setDialog(null);
  }
  async function signOut() {
    setBusy(true);
    try {
      await api("/auth/logout", {});
      setUser(null);
      setError("");
      setDialog(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function analyze() {
    if (!selectedAsset) return;
    await action(async () => {
      const run = await api<Run>(`/assets/${selectedAsset.id}/runs`, {});
      setRunId(run.id);
      setView("agents");
    });
  }

  if (boot)
    return (
      <div className="boot">
        <Factory />
        <p>Connecting to ReadyLine…</p>
      </div>
    );
  if (!user)
    return (
      <div className="auth-page">
        <div className="auth-story">
          <div className="wordmark">
            <span className="brand-icon">
              <Activity />
            </span>
            ReadyLine
          </div>
          <p className="eyebrow">MAINTENANCE OPERATIONS</p>
          <h1>
            Maintenance planning.
            <br />
            <span>Ready for review.</span>
          </h1>
          <Points
            items={[
              "Find equipment that needs attention.",
              "Review evidence and approve maintenance plans.",
              "Record repairs and share confirmed findings.",
            ]}
          />
          <div className="auth-footer">
            <Database size={18} />
            Persistent records <span>·</span>
            <ShieldCheck size={18} />
            Human approval
          </div>
        </div>
        <section className="auth-card">
          <p className="eyebrow">YOUR OPERATIONS WORKSPACE</p>
          <h2>
            {status?.setup_required
              ? "Create your administrator"
              : "Welcome back"}
          </h2>
          <p className="muted">
            {status?.setup_required
              ? "Set up the first account to manage this installation."
              : "Sign in to review your fleet and maintenance queue."}
          </p>
          {error && <ErrorBox message={error} />}
          <Form
            label={
              status?.setup_required ? "Create account & sign in" : "Sign in"
            }
            onSubmit={async (d) => {
              const credentials = {
                username: text(d, "username"),
                password: text(d, "password"),
              };
              if (status?.setup_required) await api("/auth/setup", credentials);
              const u = await api<User>("/auth/login", credentials);
              setUser(u);
              setStatus(await api<Status>("/status"));
              setError("");
            }}
          >
            <Field label="Username">
              <input
                name="username"
                required
                minLength={3}
                autoComplete="username"
              />
            </Field>
            <Field label="Password (12+ characters)">
              <input
                name="password"
                type="password"
                required
                minLength={12}
                autoComplete={
                  status?.setup_required ? "new-password" : "current-password"
                }
              />
            </Field>
          </Form>
          <div className="provider-note">
            <Radio size={16} />
            {status?.provider_configured
              ? "NVIDIA credentials configured"
              : "NVIDIA credentials required for analysis"}
          </div>
        </section>
      </div>
    );

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header">
        <div className="header-main">
          <div className="header-brand">
            <span className="brand-rule" />
            <div className="wordmark">ReadyLine</div>
            <span className="project-label">
              ABB Accelerator 2026
              <br />
              Maintenance operations
            </span>
          </div>
          <div className="header-tools">
            <span className="provider-status">
              {status?.provider_configured
                ? "NVIDIA configured"
                : "NVIDIA key missing"}
            </span>
            <div className="account">
              <div>
                {user.username}
                <small>{user.role}</small>
              </div>
              <button
                aria-label="Sign out"
                className="icon-button"
                onClick={signOut}
                disabled={busy}
              >
                <LogOut size={18} />
              </button>
            </div>
          </div>
        </div>
        <nav className="header-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              aria-current={view === item.id ? "page" : undefined}
              className={view === item.id ? "active" : ""}
              onClick={() => setView(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "orders" &&
                orders.some((o) => o.status === "proposed") && (
                  <span className="count">
                    {orders.filter((o) => o.status === "proposed").length}
                  </span>
                )}
            </button>
          ))}
        </nav>
      </header>
      <main id="main-content" tabIndex={-1}>
        <div className="topbar">
          <span>
            OPERATIONS / {navigation.find((n) => n.id === view)?.label}
          </span>
          <div className="sync">
            <span>
              {updated ? `Updated ${date(updated)}` : "Connecting..."}
            </span>
            <button
              className="icon-button"
              disabled={busy}
              aria-label="Refresh records"
              onClick={() => action(refresh)}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <div className="content">
          {error && (
            <div className="error-row">
              <ErrorBox message={error} />
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="Dismiss error"
              >
                ×
              </button>
            </div>
          )}
          {view === "fleet" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">FLEET INTELLIGENCE</p>
                  <h1>Equipment overview</h1>
                  <p className="muted">
                    Measured condition. Traceable decisions. Approved action.
                  </p>
                </div>
                {canPlan && (
                  <button
                    className="button primary"
                    onClick={() => setDialog("asset")}
                  >
                    <Plus size={17} />
                    Register asset
                  </button>
                )}
              </div>
              <div className="metrics">
                <Metric
                  label="Registered assets"
                  value={assets.length.toString()}
                  detail="Equipment in your database"
                />
                <Metric
                  label="Active analyses"
                  value={runs
                    .filter((r) => ["running", "queued"].includes(r.status))
                    .length.toString()}
                  detail="Live agent executions"
                />
                <Metric
                  label="Awaiting approval"
                  value={orders
                    .filter((o) => o.status === "proposed")
                    .length.toString()}
                  detail="Supervisor decisions"
                />
                <Metric
                  label="Completed repairs"
                  value={orders
                    .filter((o) => o.status === "completed")
                    .length.toString()}
                  detail="Recorded fleet evidence"
                />
              </div>
              {!assets.length ? (
                <Empty title="Your fleet starts here">
                  Register an asset, ingest measurements, and add an approved
                  procedure and maintenance windows. No predictions are
                  preloaded.
                </Empty>
              ) : (
                <div className="fleet-layout">
                  <section className="panel fleet-list">
                    <div className="panel-heading">
                      <h2>Assets</h2>
                      <span className="muted">{assets.length} registered</span>
                    </div>
                    {assets.map((a) => (
                      <button
                        key={a.id}
                        className={`asset-item ${a.id === selected ? "selected" : ""}`}
                        onClick={() => setSelected(a.id)}
                      >
                        <div className="asset-icon">
                          <Factory size={19} />
                        </div>
                        <div>
                          <strong>{a.id}</strong>
                          <span>{a.name}</span>
                          <small>{a.area}</small>
                        </div>
                        <div className="asset-score">
                          {a.latest_run?.result?.evidence.calculate_priority
                            ?.score ?? "-"}
                          <small>priority</small>
                        </div>
                      </button>
                    ))}
                  </section>
                  {selectedAsset && (
                    <div className="asset-detail">
                      <section className="panel">
                        <div className="panel-heading">
                          <div>
                            <p className="eyebrow">
                              {selectedAsset.area} /{" "}
                              {selectedAsset.equipment_class}
                            </p>
                            <h2>{selectedAsset.name}</h2>
                          </div>
                          <Badge
                            value={
                              selectedAsset.latest_run?.status ?? "not analyzed"
                            }
                          />
                        </div>
                        <div className="asset-stats">
                          <div>
                            <span>Vibration</span>
                            <strong>
                              {selectedAsset.latest?.vibration ?? "-"}
                              <small> mm/s</small>
                            </strong>
                          </div>
                          <div>
                            <span>Temperature</span>
                            <strong>
                              {selectedAsset.latest?.temperature ?? "-"}
                              <small> °C</small>
                            </strong>
                          </div>
                          <div>
                            <span>Load</span>
                            <strong>
                              {selectedAsset.latest?.load ?? "-"}
                              <small> %</small>
                            </strong>
                          </div>
                        </div>
                        <Trend
                          readings={readings}
                          limit={selectedAsset.vibration_limit}
                        />
                        <div className="source-line">
                          <span>
                            Source:{" "}
                            <b>
                              {selectedAsset.latest?.source ??
                                "No feed connected"}
                            </b>
                          </span>
                          <span>{readings.length} stored samples shown</span>
                        </div>
                        <div className="actions">
                          {canPlan && (
                            <>
                              <button
                                className="button primary"
                                onClick={analyze}
                                disabled={busy || !status?.provider_configured}
                              >
                                <Workflow size={17} />
                                Run agent analysis
                              </button>
                              <button
                                className="button"
                                onClick={() => setDialog("telemetry")}
                              >
                                <Plus size={17} />
                                Ingest telemetry
                              </button>
                            </>
                          )}
                          {selectedAsset.latest_run && (
                            <button
                              className="text-button"
                              onClick={() => {
                                setRunId(selectedAsset.latest_run!.id);
                                setView("agents");
                              }}
                            >
                              Inspect latest run
                              <ArrowUpRight size={16} />
                            </button>
                          )}
                        </div>
                      </section>
                      <div className="info-strip">
                        <ShieldCheck size={19} />
                        <p>
                          Priority scores follow an explicit engineering policy.
                          They are not calibrated failure probabilities. Every
                          repair requires supervisor approval.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
          {view === "agents" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">AGENT OPERATIONS</p>
                  <h1>Analysis results</h1>
                  <p className="muted">
                    Live tool calls, retrieved evidence, and specialist
                    conclusions.
                  </p>
                </div>
                <span className="model-label">
                  {String(
                    events.find((event) => event.kind === "started")?.payload
                      .model ??
                      status?.model ??
                      "",
                  )}
                </span>
              </div>
              {!runs.length ? (
                <Empty title="No agent runs yet">
                  Select an asset in Fleet intelligence and run an analysis.
                </Empty>
              ) : (
                <>
                  <div className="run-selector">
                    <label>
                      Analysis run
                      <select
                        value={runId}
                        onChange={(e) => setRunId(e.target.value)}
                      >
                        {runs.map((r) => (
                          <option value={r.id} key={r.id}>
                            {r.asset_id} · {date(r.created_at)} · {r.status}
                          </option>
                        ))}
                      </select>
                    </label>
                    {selectedRun && <Badge value={selectedRun.status} />}
                  </div>
                  {selectedRun?.error && (
                    <ErrorBox message={selectedRun.error} />
                  )}
                  {selectedRun?.result && (
                    <section
                      className="decision-strip"
                      aria-label="Analysis outcome"
                    >
                      <div>
                        <span>Next step</span>
                        <strong>
                          {selectedRun.status === "escalated"
                            ? "Review the blocking issues"
                            : selectedRun.status === "completed"
                              ? "Review the work proposal"
                              : "Check the run status"}
                        </strong>
                      </div>
                      <div>
                        <span>Priority</span>
                        <strong>
                          {selectedRun.result.evidence.calculate_priority
                            ? `${selectedRun.result.evidence.calculate_priority.score} / 100 (${selectedRun.result.evidence.calculate_priority.level})`
                            : "Not calculated"}
                        </strong>
                      </div>
                      <div>
                        <span>Review deadline</span>
                        <strong>
                          {date(
                            selectedRun.result.evidence.calculate_priority
                              ?.review_deadline,
                          )}
                        </strong>
                      </div>
                      <button
                        className="button"
                        onClick={() => setView("orders")}
                      >
                        View work orders <ArrowUpRight size={16} />
                      </button>
                    </section>
                  )}
                  <div className="agents-grid">
                    {["Health", "Fleet", "Risk", "Work order", "Schedule"].map(
                      (name, i) => {
                        const complete = events.find(
                          (e) => e.agent === name && e.kind === "completed",
                        );
                        const started = events.some(
                          (e) => e.agent === name && e.kind === "started",
                        );
                        const conclusion = complete?.payload as unknown as
                          | {
                              summary: string;
                              observations?: string[];
                              uncertainty: string;
                              disposition: string;
                            }
                          | undefined;
                        return (
                          <section
                            className={`agent-card ${complete ? "finished" : started ? "executing" : ""}`}
                            key={name}
                          >
                            <div className="agent-top">
                              <span className="agent-number">0{i + 1}</span>
                              {complete ? (
                                <Check size={17} />
                              ) : (
                                <Workflow size={17} />
                              )}
                            </div>
                            <h3>{name}</h3>
                            <Badge
                              value={
                                complete
                                  ? conclusion?.disposition === "escalate"
                                    ? "escalated"
                                    : "completed"
                                  : started
                                    ? selectedRun?.status === "failed"
                                      ? "failed"
                                      : "running"
                                    : "waiting"
                              }
                            />
                            {conclusion ? (
                              <>
                                <Points
                                  items={
                                    conclusion.observations?.length
                                      ? conclusion.observations
                                      : conclusion.summary
                                  }
                                />
                                <details className="supporting">
                                  <summary>Decision and limitations</summary>
                                  <Points items={conclusion.summary} />
                                  <h4>Limitations</h4>
                                  <Points items={conclusion.uncertainty} />
                                </details>
                              </>
                            ) : (
                              <p>
                                {started
                                  ? "Reviewing evidence..."
                                  : "Waiting for earlier agents."}
                              </p>
                            )}
                          </section>
                        );
                      },
                    )}
                  </div>
                  {selectedRun?.result?.evidence.evaluate_windows && (
                    <section className="panel section-gap">
                      <div className="panel-heading">
                        <h2>Window evaluation</h2>
                        <span className="muted">
                          Computed from current constraints
                        </span>
                      </div>
                      <WindowTable
                        windows={
                          selectedRun.result.evidence.evaluate_windows.windows
                        }
                      />
                    </section>
                  )}
                  <div className="two-columns">
                    <section className="panel">
                      <div className="panel-heading">
                        <h2>Execution events</h2>
                        <span className="muted">{events.length} recorded</span>
                      </div>
                      <div className="event-list">
                        {events.length ? (
                          events.map((e) => (
                            <details className="event" key={e.id}>
                              <summary>
                                <span className={`event-dot ${e.kind}`} />
                                <strong>{e.agent}</strong>
                                <span>{e.kind.replaceAll("_", " ")}</span>
                                <time>{date(e.created_at)}</time>
                              </summary>
                              <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                            </details>
                          ))
                        ) : (
                          <p className="muted">
                            Queued. Waiting for the worker to start.
                          </p>
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading">
                        <h2>Fleet evidence</h2>
                        <Database size={18} />
                      </div>
                      {selectedRun?.result?.evidence.find_peer_evidence ? (
                        <>
                          <p className="muted">
                            {
                              selectedRun.result.evidence.find_peer_evidence
                                .method
                            }
                          </p>
                          {selectedRun.result.evidence.find_peer_evidence.peers.map(
                            (peer) => (
                              <div className="peer" key={peer.asset_id}>
                                <div>
                                  <strong>{peer.asset_id}</strong>
                                  <span>{peer.name}</span>
                                </div>
                                <b>
                                  {Math.round(peer.similarity * 100)}%
                                  <small>similarity</small>
                                </b>
                                <p>
                                  {peer.confirmed_repairs.length} confirmed
                                  repairs
                                </p>
                                {peer.confirmed_repairs.map((repair) => (
                                  <blockquote key={repair.id}>
                                    <Points items={repair.feedback.finding} />
                                  </blockquote>
                                ))}
                              </div>
                            ),
                          )}
                          {!selectedRun.result.evidence.find_peer_evidence.peers
                            .length && (
                            <Empty title="No comparable assets">
                              Register additional equipment to build fleet
                              evidence.
                            </Empty>
                          )}
                        </>
                      ) : (
                        <Empty title="Evidence will appear here">
                          The Fleet agent retrieves actual asset and repair
                          records.
                        </Empty>
                      )}
                    </section>
                  </div>
                </>
              )}
            </>
          )}
          {view === "orders" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">MAINTENANCE WORKFLOW</p>
                  <h1>Work orders</h1>
                  <p className="muted">
                    Review proposals, reserve resources, and capture confirmed
                    findings.
                  </p>
                </div>
              </div>
              {!orders.length ? (
                <Empty title="No work orders yet">
                  A successful agent run creates a proposal when an appropriate
                  procedure and feasible window exist.
                </Empty>
              ) : (
                <div className="orders">
                  {[...orders]
                    .sort(
                      (a, b) =>
                        [
                          "proposed",
                          "approved",
                          "completed",
                          "cancelled",
                        ].indexOf(a.status) -
                        [
                          "proposed",
                          "approved",
                          "completed",
                          "cancelled",
                        ].indexOf(b.status),
                    )
                    .map((order) => (
                      <OrderCard
                        key={order.id}
                        order={order}
                        observations={
                          runs.find((r) => r.id === order.run_id)?.result
                            ?.agents["Work order"]?.observations
                        }
                        resources={resources}
                        canApprove={canApprove}
                        canComplete={canComplete}
                        busy={busy}
                        act={action}
                        refresh={refresh}
                      />
                    ))}
                </div>
              )}
            </>
          )}
          {view === "resources" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">PLANNING & RESOURCES</p>
                  <h1>Planning and resources</h1>
                  <p className="muted">
                    Manage inventory, approved procedures, and production
                    windows.
                  </p>
                </div>
                {user.role === "admin" && (
                  <button className="button" onClick={() => setDialog("user")}>
                    <Plus size={17} />
                    Add team member
                  </button>
                )}
              </div>
              <div className="two-columns">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Parts inventory</h2>
                    {canPlan && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setPart(undefined);
                          setDialog("part");
                        }}
                      >
                        <Plus size={16} />
                        Add part
                      </button>
                    )}
                  </div>
                  {resources.parts.length ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Part</th>
                            <th>Stock</th>
                            <th>Reserved</th>
                            <th>Available</th>
                          </tr>
                        </thead>
                        <tbody>
                          {resources.parts.map((p) => (
                            <tr key={p.id}>
                              <td>
                                <button
                                  className="text-button"
                                  disabled={!canPlan}
                                  onClick={() => {
                                    setPart(p);
                                    setDialog("part");
                                  }}
                                >
                                  {p.name}
                                </button>
                                <small>{p.id}</small>
                              </td>
                              <td>{p.stock}</td>
                              <td>{p.reserved}</td>
                              <td>
                                <strong>{p.stock - p.reserved}</strong>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty title="No inventory records">
                      Add the parts your maintenance procedures require.
                    </Empty>
                  )}
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Procedure catalog</h2>
                    {canApprove && (
                      <button
                        className="text-button"
                        onClick={() => setDialog("procedure")}
                      >
                        <Plus size={16} />
                        Add procedure
                      </button>
                    )}
                  </div>
                  {resources.procedures.length ? (
                    resources.procedures.map((p) => (
                      <details className="procedure" key={p.id}>
                        <summary>
                          <strong>{p.title}</strong>
                          <span>
                            {p.equipment_class} · {p.duration_hours}h
                          </span>
                        </summary>
                        <Points items={p.source} />
                        <ol>
                          {p.steps.map((s, i) => (
                            <li key={i}>{plainText(s)}</li>
                          ))}
                        </ol>
                      </details>
                    ))
                  ) : (
                    <Empty title="No approved procedures">
                      Agents select from this catalog; they cannot invent a
                      repair procedure.
                    </Empty>
                  )}
                </section>
              </div>
              <section className="panel section-gap">
                <div className="panel-heading">
                  <h2>Maintenance windows</h2>
                  {canPlan && (
                    <button
                      className="button"
                      onClick={() => setDialog("window")}
                    >
                      <Plus size={16} />
                      Add window
                    </button>
                  )}
                </div>
                {resources.windows.length ? (
                  <WindowTable windows={resources.windows} />
                ) : (
                  <Empty title="No production windows">
                    Add time, technician, permit, and production constraints.
                  </Empty>
                )}
              </section>
            </>
          )}
          {view === "audit" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">ACCOUNTABILITY</p>
                  <h1>A record of what changed.</h1>
                  <p className="muted">
                    Server-recorded actions, identities, and timestamps.
                  </p>
                </div>
              </div>
              <section className="panel">
                {audit.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Action</th>
                          <th>Actor</th>
                          <th>Record</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {audit.map((row) => (
                          <tr key={row.id}>
                            <td>{date(row.created_at)}</td>
                            <td>{row.action.replaceAll("_", " ")}</td>
                            <td className="mono">{row.actor.slice(0, 12)}</td>
                            <td className="mono">
                              {row.entity_id.slice(0, 12)}
                            </td>
                            <td>
                              <details>
                                <summary>View</summary>
                                <pre>{JSON.stringify(row.detail, null, 2)}</pre>
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty title="No activity recorded" />
                )}
              </section>
            </>
          )}
        </div>
        <footer className="footer">
          <span>READYLINE / MAINTENANCE OPERATIONS</span>
          <span>
            Plant controls remain read-only · Times shown in your local timezone
          </span>
        </footer>
      </main>
      {dialog && (
        <Modal
          title={
            {
              asset: "Register an asset",
              telemetry: `Ingest telemetry · ${selected}`,
              part: part ? "Update inventory" : "Add inventory",
              window: "Add maintenance window",
              procedure: "Add approved procedure",
              user: "Create team member",
            }[dialog]
          }
          close={() => setDialog(null)}
        >
          {dialog === "asset" && <AssetForm done={done} />}{" "}
          {dialog === "telemetry" && selectedAsset && (
            <TelemetryForm asset={selectedAsset} done={done} />
          )}{" "}
          {dialog === "part" && <PartForm part={part} done={done} />}{" "}
          {dialog === "window" && <WindowForm done={done} />}{" "}
          {dialog === "procedure" && <ProcedureForm done={done} />}{" "}
          {dialog === "user" && <UserForm done={done} />}
        </Modal>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
function WindowTable({ windows }: { windows: Resources["windows"] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Area / start</th>
            <th>End</th>
            <th>Production</th>
            <th>Crew / permit</th>
            <th>Evaluation</th>
          </tr>
        </thead>
        <tbody>
          {windows.map((w) => (
            <tr key={w.id}>
              <td>
                <strong>{w.area}</strong>
                <small>{date(w.starts_at)}</small>
              </td>
              <td>{date(w.ends_at)}</td>
              <td>{Math.round(w.production_fraction * 100)}%</td>
              <td>
                {w.technicians} / {w.permit_ready ? "Ready" : "Pending"}
              </td>
              <td>
                {w.feasible === undefined ? (
                  "Not evaluated"
                ) : w.feasible ? (
                  <>
                    <Badge value="feasible" />
                    <small>
                      {money(w.estimated_disruption_cost ?? 0)} modeled
                      disruption
                    </small>
                  </>
                ) : (
                  <>
                    <Badge value="blocked" />
                    <Points items={w.reasons ?? []} />
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function OrderCard({
  order,
  observations,
  resources,
  canApprove,
  canComplete,
  busy,
  act,
  refresh,
}: {
  order: Order;
  observations?: string[];
  resources: Resources;
  canApprove: boolean;
  canComplete: boolean;
  busy: boolean;
  act: (work: () => Promise<unknown>) => Promise<void>;
  refresh: () => Promise<void>;
}) {
  const window = resources.windows.find((w) => w.id === order.window_id);
  const [checked, setChecked] = useState<number[]>([]);
  return (
    <section className="panel order">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">
            {order.asset_id} / {order.id.slice(0, 8)}
          </p>
          <h2>{plainText(order.plan.procedure.title)}</h2>
        </div>
        <Badge value={order.status} />
      </div>

      <div className="order-facts">
        <div>
          <span>Maintenance window</span>
          <strong>{date(window?.starts_at)}</strong>
        </div>
        <div>
          <span>Expected duration</span>
          <strong>{order.plan.procedure.duration_hours} hours</strong>
        </div>
        <div>
          <span>Priority</span>
          <strong>{order.plan.priority.score} / 100</strong>
        </div>
        <div>
          <span>Review deadline</span>
          <strong>{date(order.plan.priority.review_deadline)}</strong>
        </div>
      </div>
      {order.status === "proposed" && canApprove && (
        <div className="actions">
          <button
            className="button primary"
            disabled={busy}
            onClick={() =>
              act(() => api(`/work-orders/${order.id}/approve`, {}))
            }
          >
            <ShieldCheck size={16} />
            Approve & reserve
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() =>
              act(() => api(`/work-orders/${order.id}/cancel`, {}))
            }
          >
            Reject proposal
          </button>
        </div>
      )}
      {order.status === "approved" && canApprove && (
        <button
          className="text-button danger-text"
          disabled={busy}
          onClick={() => act(() => api(`/work-orders/${order.id}/cancel`, {}))}
        >
          Cancel work & release resources
        </button>
      )}
      <h3>Key findings</h3>
      <Points
        items={observations?.length ? observations : order.plan.agent_summary}
      />
      <details className="supporting">
        <summary>Full assessment and procedure reference</summary>
        <Points items={order.plan.agent_summary} />
        <h4>Procedure reference</h4>
        <Points items={order.plan.procedure.source} />
      </details>
      <div className="chips">
        {order.plan.parts.map((p) => (
          <span key={p.part_id}>
            {p.quantity} × {p.name}
          </span>
        ))}
      </div>
      <details className="procedure" open={order.status === "approved"}>
        <summary>Procedure & execution checklist</summary>
        {order.plan.procedure.steps.map((step, i) => (
          <label className="check step" key={i}>
            <input
              type="checkbox"
              disabled={order.status !== "approved" || !canComplete}
              checked={order.status === "completed" || checked.includes(i)}
              onChange={(e) =>
                setChecked((previous) =>
                  e.target.checked
                    ? [...previous, i]
                    : previous.filter((n) => n !== i),
                )
              }
            />
            <span>
              {i + 1}. {plainText(step)}
            </span>
          </label>
        ))}
      </details>
      {order.status === "approved" && canComplete && (
        <div className="completion">
          <h3>Record confirmed findings</h3>
          <Form
            label="Complete job & save feedback"
            disabled={checked.length !== order.plan.procedure.steps.length}
            onSubmit={async (d) => {
              await api(`/work-orders/${order.id}/complete`, {
                finding: text(d, "finding"),
                actual_hours: num(d, "actual_hours"),
                post_vibration: num(d, "post_vibration"),
                completed_steps: checked,
              });
              await refresh();
            }}
          >
            <Field label="Confirmed finding">
              <textarea
                name="finding"
                required
                minLength={5}
                maxLength={2000}
                rows={3}
              />
            </Field>
            <div className="form-grid">
              <Field label="Actual duration (hours)">
                <input
                  name="actual_hours"
                  type="number"
                  min="0.01"
                  max="168"
                  step="any"
                  required
                />
              </Field>
              <Field label="Measured post-repair vibration (mm/s)">
                <input
                  name="post_vibration"
                  type="number"
                  min="0"
                  max="1000"
                  step="any"
                  required
                />
              </Field>
            </div>
          </Form>
        </div>
      )}
      {order.feedback && (
        <div className="feedback">
          <Check size={18} />
          <div>
            <strong>Confirmed feedback · {date(order.completed_at)}</strong>
            <Points items={order.feedback.finding} />
            <span>
              {order.feedback.actual_hours}h actual ·{" "}
              {order.feedback.post_vibration} mm/s after repair · Available to
              fleet agents
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
