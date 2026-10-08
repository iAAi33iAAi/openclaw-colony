import React, { useCallback, useEffect, useState } from "react";
import SevenAgentInterface from "./SevenAgentInterface";
import {
  apiFetch,
  clearSessionKeys,
  getAdminKey,
  getApiKey,
  setAdminKey,
  setApiKey,
} from "./api";
import "./platform.css";

type Page =
  | "overview"
  | "requests"
  | "agents"
  | "approvals"
  | "history"
  | "economics"
  | "network"
  | "people"
  | "security"
  | "integrations"
  | "settings";

interface HealthResponse {
  status?: string;
  colony?: string;
  gates?: string;
  version?: string;
  stripe_mode?: string;
  federation?: {
    node_id?: string;
    node_url?: string;
    active_peers?: number;
    total_peers?: number;
  };
  biometric?: { required?: string; ttl_seconds?: number };
}

interface TaskRecord {
  id: number;
  task_id: string;
  action_type: string;
  human_consent: boolean;
  lq_composite: number;
  status: string;
  blocked_at_gate: number | null;
  reason: string | null;
  lineage_hash: string | null;
  submitted_at: string | null;
  completed_at: string | null;
}

interface LineageRecord {
  id: number;
  task_id: string;
  prompt_hash: string;
  lq_composite: number;
  lineage_hash: string;
  prev_hash: string;
  committed_at: string | null;
}

interface PaymentRecord {
  id: number;
  task_id: string;
  lineage_hash: string;
  amount_total_cents: number;
  community_cents: number;
  crew_cents: number;
  architect_cents: number;
  currency: string;
  status: string;
  created_at: string | null;
  stripe_transfer_id: string | null;
}

interface MannaConfig {
  manna_cents_per_task: number;
  split: {
    total_cents: number;
    community_cents: number;
    crew_cents: number;
    architect_cents: number;
  };
  percentages: { community: string; crew: string; architect: string };
  stripe_mode: string;
}

interface FederationStatus {
  node_id: string;
  node_url: string;
  quorum_threshold: number;
  node_state: { state?: string; synced?: boolean | null };
  peers: { active: number; total: number };
  lineage: { record_count: number };
}

interface FederationNode {
  node_id: string;
  base_url: string;
  active: boolean;
  last_seen: string | null;
  last_tip: string | null;
  registered_at: string | null;
}

interface Member {
  member_id: string;
  legal_name: string;
  role: string;
  badge_serial: string;
  enrolled_at: string | null;
  suspended: boolean;
  last_seen_node: string | null;
  last_seen_at: string | null;
  action_scope: string[];
}

interface DuressEvent {
  event_id: string;
  member_id: string;
  legal_name: string;
  location_node: string;
  triggered_at: string;
  task_id: string | null;
  escrow_until: string;
}

interface Integration {
  key: string;
  name: string;
  repository: string;
  role: string;
  status: string;
  connection: string;
  endpoint_env?: string;
  configured?: boolean;
  endpoint?: string;
}

const NAV_ITEMS: Array<{ id: Page; label: string; description: string; icon: string; admin?: boolean }> = [
  { id: "overview", label: "Overview", description: "System status", icon: "⌂" },
  { id: "requests", label: "Requests", description: "Submit work", icon: "＋" },
  { id: "agents", label: "AI Agents", description: "Seven-agent team", icon: "◈" },
  { id: "approvals", label: "Approvals", description: "Human decisions", icon: "✓" },
  { id: "history", label: "History", description: "Verified activity", icon: "◷", admin: true },
  { id: "economics", label: "Economics", description: "Value and payments", icon: "$", admin: true },
  { id: "network", label: "Network", description: "Nodes and federation", icon: "⌁", admin: true },
  { id: "people", label: "People", description: "Members and roles", icon: "●", admin: true },
  { id: "security", label: "Security", description: "Accountability", icon: "◇", admin: true },
  { id: "integrations", label: "Integrations", description: "Repository boundaries", icon: "↔", admin: true },
  { id: "settings", label: "Settings", description: "Connect the platform", icon: "⚙" },
];

const AGENTS = [
  { name: "Strategic", role: "Direction and priorities" },
  { name: "Technical", role: "Technical reasoning" },
  { name: "Resources", role: "Resource planning" },
  { name: "Communications", role: "Communication planning" },
  { name: "Analysis", role: "Research and analysis" },
  { name: "Quality", role: "Quality review" },
  { name: "Innovation", role: "New approaches" },
];

export default function PlatformShell() {
  const [page, setPage] = useState<Page>("overview");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthState, setHealthState] = useState<"checking" | "online" | "offline">("checking");
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [lineage, setLineage] = useState<LineageRecord[]>([]);
  const [payments, setPayments] = useState<PaymentRecord[]>([]);
  const [manna, setManna] = useState<MannaConfig | null>(null);
  const [federation, setFederation] = useState<FederationStatus | null>(null);
  const [nodes, setNodes] = useState<FederationNode[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [duress, setDuress] = useState<DuressEvent[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const refreshHealth = useCallback(async () => {
    try {
      const data = await apiFetch<HealthResponse>("/health", {}, "none");
      setHealth(data);
      setHealthState("online");
    } catch {
      setHealthState("offline");
    }
  }, []);

  const refreshAdmin = useCallback(async () => {
    if (!getAdminKey()) {
      setAdminError(null);
      return;
    }

    setAdminError(null);
    const calls = await Promise.allSettled([
      apiFetch<TaskRecord[]>("/admin/tasks?limit=100", {}, "admin"),
      apiFetch<LineageRecord[]>("/admin/lineage?limit=100", {}, "admin"),
      apiFetch<PaymentRecord[]>("/admin/payments?limit=100", {}, "admin"),
      apiFetch<MannaConfig>("/admin/manna/config", {}, "admin"),
      apiFetch<FederationStatus>("/federation/status", {}, "admin"),
      apiFetch<{ peers: FederationNode[] }>("/federation/nodes", {}, "admin"),
      apiFetch<{ members: Member[] }>("/biometric/members", {}, "admin"),
      apiFetch<{ events: DuressEvent[] }>("/biometric/duress", {}, "admin"),
      apiFetch<{ integrations: Integration[] }>("/admin/integrations", {}, "admin"),
    ]);

    const [tasksResult, lineageResult, paymentsResult, mannaResult, federationResult, nodesResult, membersResult, duressResult, integrationsResult] = calls;

    if (tasksResult.status === "fulfilled") setTasks(tasksResult.value);
    if (lineageResult.status === "fulfilled") setLineage(lineageResult.value);
    if (paymentsResult.status === "fulfilled") setPayments(paymentsResult.value);
    if (mannaResult.status === "fulfilled") setManna(mannaResult.value);
    if (federationResult.status === "fulfilled") setFederation(federationResult.value);
    if (nodesResult.status === "fulfilled") setNodes(nodesResult.value.peers ?? []);
    if (membersResult.status === "fulfilled") setMembers(membersResult.value.members ?? []);
    if (duressResult.status === "fulfilled") setDuress(duressResult.value.events ?? []);
    if (integrationsResult.status === "fulfilled") setIntegrations(integrationsResult.value.integrations ?? []);

    const firstRejected = calls.find((call) => call.status === "rejected");
    if (firstRejected && firstRejected.status === "rejected") {
      setAdminError(firstRejected.reason instanceof Error ? firstRejected.reason.message : String(firstRejected.reason));
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth, reloadTick]);

  useEffect(() => {
    void refreshAdmin();
  }, [refreshAdmin, reloadTick]);

  const pageTitle = NAV_ITEMS.find((item) => item.id === page)?.label ?? "Overview";
  const nodeId = health?.federation?.node_id ?? "Local / unregistered";
  const hasApiKey = Boolean(getApiKey());
  const hasAdminKey = Boolean(getAdminKey());

  return (
    <div className="aethel-app">
      <aside className="aethel-sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-name">AETHEL</div>
            <div className="brand-subtitle">Operations Platform</div>
          </div>
        </div>

        <div className="node-card">
          <div className="node-card-label">NODE</div>
          <div className="node-card-value">{nodeId}</div>
          <div className={`status-line status-${healthState}`}>
            <span className="status-dot" />
            {healthState === "online" ? "System online" : healthState === "offline" ? "API offline" : "Checking system"}
          </div>
        </div>

        <nav className="nav-list" aria-label="AETHEL navigation">
          {NAV_ITEMS.map((item) => (
            <button key={item.id} type="button" className={`nav-item ${page === item.id ? "active" : ""}`} onClick={() => setPage(item.id)}>
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-copy">
                <strong>{item.label}</strong>
                <small>{item.description}{item.admin ? " · admin" : ""}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-footer-title">The AETHEL loop</div>
          <p>Request → Check → Approve → Act → Record. The platform is the front door; the specialist systems stay behind clear boundaries.</p>
        </div>
      </aside>

      <main className="aethel-main">
        <header className="topbar">
          <div>
            <div className="eyebrow">AETHEL / {pageTitle.toUpperCase()}</div>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`connection-chip ${hasApiKey ? "connected" : ""}`}>{hasApiKey ? "API connected" : "API key needed"}</span>
            <button className="secondary-button" type="button" onClick={() => setReloadTick((value) => value + 1)}>Refresh</button>
            <button className="primary-button" type="button" onClick={() => setPage("requests")}>New request</button>
          </div>
        </header>

        {adminError && <AdminNotice message={adminError} onSettings={() => setPage("settings")} />}

        {page === "overview" && (
          <Overview
            health={health}
            healthState={healthState}
            requestCount={tasks.length}
            lineageCount={lineage.length}
            peerCount={federation?.peers.active ?? health?.federation?.active_peers ?? 0}
            hasAdminKey={hasAdminKey}
            onCreateRequest={() => setPage("requests")}
            onSettings={() => setPage("settings")}
          />
        )}
        {page === "requests" && (
          <section className="page-section">
            <div className="section-intro"><div><div className="section-kicker">WORK INTAKE</div><h2>Send a request through AETHEL</h2><p>Describe one task. The current Colony service runs the seven-agent evaluation, safety checks, and result recording.</p></div><span className="info-pill">Live backend</span></div>
            <div className="embedded-panel"><SevenAgentInterface /></div>
          </section>
        )}
        {page === "agents" && <AgentsPage onCreateRequest={() => setPage("requests")} />}
        {page === "approvals" && <ApprovalsPage onCreateRequest={() => setPage("requests")} />}
        {page === "history" && <HistoryPage records={tasks} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "economics" && <EconomicsPage payments={payments} manna={manna} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "network" && <NetworkPage federation={federation} nodes={nodes} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "people" && <PeoplePage members={members} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "security" && <SecurityPage events={duress} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "integrations" && <IntegrationsPage integrations={integrations} hasAdminKey={hasAdminKey} onSettings={() => setPage("settings")} />}
        {page === "settings" && <SettingsPage onSaved={() => { setReloadTick((value) => value + 1); setPage("overview"); }} />}
      </main>
    </div>
  );
}

function Overview({ health, healthState, requestCount, lineageCount, peerCount, hasAdminKey, onCreateRequest, onSettings }: {
  health: HealthResponse | null;
  healthState: "checking" | "online" | "offline";
  requestCount: number;
  lineageCount: number;
  peerCount: number;
  hasAdminKey: boolean;
  onCreateRequest: () => void;
  onSettings: () => void;
}) {
  return (
    <div className="dashboard-grid">
      <section className="hero-card">
        <div className="hero-copy"><div className="section-kicker">THE FRONT DOOR</div><h2>One place for people and AI to ask the system to do something.</h2><p>AETHEL provides one operating surface around the existing Colony engine. Requests come in, the backend checks them, the result comes back, and the evidence can be reviewed from the same site.</p><button className="primary-button" type="button" onClick={onCreateRequest}>Create a request</button></div>
        <div className="hero-flow" aria-label="AETHEL request flow">
          {["Request", "Check", "Approve", "Act", "Record"].map((step, index) => <React.Fragment key={step}><div className="flow-step"><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong></div>{index < 4 && <div className="flow-arrow">→</div>}</React.Fragment>)}
        </div>
      </section>

      <section className="stat-grid">
        <StatCard label="System" value={healthState === "online" ? "ONLINE" : healthState === "offline" ? "OFFLINE" : "CHECKING"} detail={health?.version ? `API ${health.version}` : "Backend health check"} tone={healthState === "online" ? "good" : healthState === "offline" ? "warn" : "neutral"} />
        <StatCard label="Safety" value="4 gates" detail={health?.gates ?? "Current Colony safety path"} tone="neutral" />
        <StatCard label="Requests" value={hasAdminKey ? String(requestCount) : "Admin"} detail={hasAdminKey ? "Evaluated requests" : "Connect an admin key to inspect"} tone="neutral" />
        <StatCard label="History" value={hasAdminKey ? String(lineageCount) : "Admin"} detail={hasAdminKey ? "Lineage records visible" : "Connect an admin key to inspect"} tone="neutral" />
        <StatCard label="Network" value={hasAdminKey ? String(peerCount) : "Admin"} detail={hasAdminKey ? "Active peer nodes" : "Connect an admin key to inspect"} tone="neutral" />
      </section>

      <section className="wide-card">
        <div className="card-heading"><div><div className="section-kicker">USE IT</div><h3>Start with a real task</h3></div><span className="info-pill">No infrastructure knowledge required</span></div>
        <div className="step-grid">
          <Step number="01" title="Write the task" text="Describe what you need the system to evaluate or process." />
          <Step number="02" title="Let AETHEL check it" text="The current Colony backend runs the request through its safety path." />
          <Step number="03" title="Review the result" text="See approved or blocked, the gates, the quality score, and the agent outputs." />
          <Step number="04" title="Keep the evidence" text="Authorized operators can inspect lineage, payments, people, and network state." />
        </div>
      </section>

      {!hasAdminKey && (
        <section className="wide-card callout-card"><div><div className="section-kicker">OPERATOR ACCESS</div><h3>Connect the admin side to unlock the control center.</h3><p>Requests use a normal API key. History, payments, federation, members, security, and integrations use the protected admin interface.</p></div><button className="secondary-button" type="button" onClick={onSettings}>Open settings</button></section>
      )}
    </div>
  );
}

function AgentsPage({ onCreateRequest }: { onCreateRequest: () => void }) {
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">AI WORKFORCE</div><h2>The seven-agent team</h2><p>The current request engine evaluates work through seven specialist agents. The next hardening step is to attach explicit permissions and work history to each one.</p></div><button className="primary-button" type="button" onClick={onCreateRequest}>Create request</button></div><div className="agent-catalog">{AGENTS.map((agent, index) => <div className="agent-catalog-card" key={agent.name}><div className="agent-number">0{index + 1}</div><h3>{agent.name}</h3><p>{agent.role}</p><div className="agent-status"><span className="status-dot online" /> Present in live request flow</div></div>)}</div></section>;
}

function ApprovalsPage({ onCreateRequest }: { onCreateRequest: () => void }) {
  return <section className="empty-state-panel"><div className="empty-state-icon">✓</div><div className="section-kicker">HUMAN AUTHORITY</div><h2>The approval queue is a separate workflow that still needs to be implemented.</h2><p>The current API carries a human-consent value and enforces it during request evaluation, but it does not yet store a durable waiting-for-approval queue. This page deliberately does not pretend otherwise.</p><button className="primary-button" type="button" onClick={onCreateRequest}>Open the live request flow</button></section>;
}

function HistoryPage({ records, hasAdminKey, onSettings }: { records: TaskRecord[]; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="History" description="Connect an admin key to view complete request history." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">SYSTEM MEMORY</div><h2>Request history</h2><p>Every evaluated request is now stored, including blocked requests. Approved requests can also carry a lineage record.</p></div><span className="info-pill">{records.length} loaded</span></div><div className="table-card"><table><thead><tr><th>Task</th><th>Status</th><th>LQ</th><th>Gate</th><th>When</th><th>Lineage</th></tr></thead><tbody>{records.map((record) => <tr key={record.id}><td><code>{record.task_id.slice(0, 12)}</code></td><td><StatusBadge value={record.status} /></td><td>{record.lq_composite.toFixed(3)}</td><td>{record.blocked_at_gate === null ? "—" : `Gate ${record.blocked_at_gate}`}</td><td>{formatDate(record.completed_at ?? record.submitted_at)}</td><td><code>{record.lineage_hash ? record.lineage_hash.slice(0, 18) + "…" : "—"}</code></td></tr>)}{!records.length && <tr><td colSpan={6}><EmptyTable text="No request history is currently stored." /></td></tr>}</tbody></table></div></section>;
}

function EconomicsPage({ payments, manna, hasAdminKey, onSettings }: { payments: PaymentRecord[]; manna: MannaConfig | null; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="Economics" description="Connect an admin key to view payment records and the current MANNA configuration." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">VALUE FLOW</div><h2>Economics</h2><p>Payment data shown here is read from the current Colony database. Live Stripe movement depends on deployment configuration.</p></div><span className="info-pill">{manna?.stripe_mode ?? "unknown"} mode</span></div><div className="stat-grid"><StatCard label="Configured split" value={manna ? `${manna.percentages.community} / ${manna.percentages.crew} / ${manna.percentages.architect}` : "—"} detail="Community / Crew / Architect" tone="neutral" /><StatCard label="Payment records" value={String(payments.length)} detail="Most recent records loaded" tone="neutral" /><StatCard label="Total shown" value={formatMoney(payments.reduce((sum, p) => sum + p.amount_total_cents, 0))} detail="Across loaded records" tone="neutral" /><StatCard label="Mode" value={manna?.stripe_mode?.toUpperCase() ?? "—"} detail="Read from the running service" tone="neutral" /></div><div className="table-card"><table><thead><tr><th>Task</th><th>Total</th><th>Community</th><th>Crew</th><th>Architect</th><th>Status</th></tr></thead><tbody>{payments.map((payment) => <tr key={payment.id}><td><code>{payment.task_id.slice(0, 12)}</code></td><td>{formatMoney(payment.amount_total_cents)}</td><td>{formatMoney(payment.community_cents)}</td><td>{formatMoney(payment.crew_cents)}</td><td>{formatMoney(payment.architect_cents)}</td><td><StatusBadge value={payment.status} /></td></tr>)}{!payments.length && <tr><td colSpan={6}><EmptyTable text="No payment records are currently stored." /></td></tr>}</tbody></table></div></section>;
}

function NetworkPage({ federation, nodes, hasAdminKey, onSettings }: { federation: FederationStatus | null; nodes: FederationNode[]; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="Network" description="Connect an admin key to inspect federation state and peer nodes." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">FEDERATION</div><h2>Network</h2><p>This view shows what the current Colony node reports. It does not claim that peer histories are fully proven identical.</p></div></div><div className="stat-grid"><StatCard label="Node state" value={federation?.node_state.state ?? "unknown"} detail={federation?.node_state.synced ? "Reported synced" : "Sync status not confirmed"} tone="neutral" /><StatCard label="Active peers" value={String(federation?.peers.active ?? 0)} detail={`${federation?.peers.total ?? 0} registered`} tone="neutral" /><StatCard label="Quorum" value={federation ? `${Math.round(federation.quorum_threshold * 100)}%` : "—"} detail="Configured proposal threshold" tone="neutral" /><StatCard label="Lineage" value={String(federation?.lineage.record_count ?? 0)} detail="Records on this node" tone="neutral" /></div><div className="node-grid">{nodes.map((node) => <div className="node-panel" key={node.node_id}><div className="node-panel-head"><strong>{node.node_id}</strong><StatusBadge value={node.active ? "active" : "inactive"} /></div><p>{node.base_url}</p><small>Last seen: {formatDate(node.last_seen)}</small><small>Tip: {node.last_tip ? `${node.last_tip.slice(0, 18)}…` : "none"}</small></div>)}{!nodes.length && <div className="empty-state-panel compact"><h3>No peers registered</h3><p>The current node has no federation peers in its database.</p></div>}</div></section>;
}

function PeoplePage({ members, hasAdminKey, onSettings }: { members: Member[]; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="People" description="Connect an admin key to inspect enrolled members and their roles." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">MEMBERS</div><h2>People</h2><p>Administrative member information currently exposed by the Colony biometric service.</p></div><span className="info-pill">{members.length} members</span></div><div className="table-card"><table><thead><tr><th>Name</th><th>Role</th><th>Badge</th><th>Status</th><th>Last node</th></tr></thead><tbody>{members.map((member) => <tr key={member.member_id}><td>{member.legal_name}</td><td>{member.role}</td><td><code>{member.badge_serial}</code></td><td><StatusBadge value={member.suspended ? "suspended" : "active"} /></td><td>{member.last_seen_node ?? "—"}</td></tr>)}{!members.length && <tr><td colSpan={5}><EmptyTable text="No enrolled members are currently stored." /></td></tr>}</tbody></table></div></section>;
}

function SecurityPage({ events, hasAdminKey, onSettings }: { events: DuressEvent[]; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="Security" description="Connect an admin key to inspect active accountability and duress events." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">ACCOUNTABILITY</div><h2>Security events</h2><p>Review the active duress/escrow records exposed by the current biometric service.</p></div><span className={`severity-pill ${events.length ? "danger" : "good"}`}>{events.length ? `${events.length} active` : "No active events"}</span></div><div className="security-grid">{events.map((event) => <div className="security-panel" key={event.event_id}><div className="node-panel-head"><strong>{event.legal_name}</strong><span className="severity-pill danger">ACTIVE</span></div><p>Node: {event.location_node}</p><p>Task: {event.task_id ?? "none"}</p><small>Triggered: {formatDate(event.triggered_at)}</small><small>Escrow until: {formatDate(event.escrow_until)}</small></div>)}{!events.length && <div className="empty-state-panel compact"><h3>No active duress events</h3><p>The current administrative endpoint reports no unresolved events.</p></div>}</div></section>;
}

function IntegrationsPage({ integrations, hasAdminKey, onSettings }: { integrations: Integration[]; hasAdminKey: boolean; onSettings: () => void }) {
  if (!hasAdminKey) return <ProtectedPage title="Integrations" description="Connect an admin key to see which AETHEL repository boundaries are runtime-connected." onSettings={onSettings} />;
  return <section className="page-section"><div className="section-intro"><div><div className="section-kicker">REPOSITORY BOUNDARIES</div><h2>Integrations</h2><p>This page intentionally separates “running here” from “still needs a service connection.” It prevents the platform from claiming every repository is already one process.</p></div></div><div className="integration-grid">{integrations.map((item) => <div className="integration-card" key={item.key}><div className="integration-top"><span className={`integration-state ${item.status}`}>{item.status.toUpperCase()}</span><code>{item.key}</code></div><h3>{item.name}</h3><p>{item.role}</p><div className="integration-meta"><span>Repo: {item.repository}</span><span>Connection: {item.connection}</span>{item.endpoint_env && <span>Config: {item.endpoint_env} {item.configured ? "✓" : "not set"}</span>}</div></div>)}</div></section>;
}

function SettingsPage({ onSaved }: { onSaved: () => void }) {
  const [apiKey, setApiKeyValue] = useState(getApiKey());
  const [adminKey, setAdminKeyValue] = useState(getAdminKey());
  const [message, setMessage] = useState("");

  const save = () => {
    setApiKey(apiKey);
    setAdminKey(adminKey);
    setMessage("Connection settings saved for this browser tab.");
    window.setTimeout(onSaved, 350);
  };

  const clear = () => {
    clearSessionKeys();
    setApiKeyValue("");
    setAdminKeyValue("");
    setMessage("Connection keys cleared from this browser tab.");
  };

  return <section className="settings-page"><div className="settings-card"><div className="section-kicker">CONNECTION</div><h2>Connect this browser to the Colony service</h2><p>The website talks to the same API that the backend already exposes. Keys are held only in this browser tab using session storage.</p><label className="field-label">Colony API key<input type="password" value={apiKey} onChange={(event) => setApiKeyValue(event.target.value)} placeholder="oc_..." autoComplete="off" /></label><label className="field-label">Admin key<input type="password" value={adminKey} onChange={(event) => setAdminKeyValue(event.target.value)} placeholder="COLONY_ADMIN_KEY" autoComplete="off" /></label><div className="settings-actions"><button className="primary-button" type="button" onClick={save}>Save connection</button><button className="secondary-button" type="button" onClick={clear}>Clear keys</button></div>{message && <div className="success-note">{message}</div>}</div><div className="settings-card"><div className="section-kicker">DEPLOYMENT RULE</div><h3>Keep production secrets out of source code.</h3><p>The browser should receive only credentials appropriate for the operator using it. Privileged operations stay protected by the backend.</p></div></section>;
}

function ProtectedPage({ title, description, onSettings }: { title: string; description: string; onSettings: () => void }) {
  return <section className="empty-state-panel"><div className="empty-state-icon">🔒</div><div className="section-kicker">PROTECTED</div><h2>{title} requires operator access</h2><p>{description}</p><button className="primary-button" type="button" onClick={onSettings}>Open settings</button></section>;
}

function AdminNotice({ message, onSettings }: { message: string; onSettings: () => void }) {
  return <div className="admin-notice"><div><strong>Protected data could not be loaded.</strong><span>{message}</span></div><button className="secondary-button" type="button" onClick={onSettings}>Check keys</button></div>;
}

function StatusBadge({ value }: { value: string }) {
  const good = ["active", "completed", "paid", "success", "ok"].includes(value.toLowerCase());
  return <span className={`status-badge ${good ? "good" : "neutral"}`}>{value}</span>;
}

function EmptyTable({ text }: { text: string }) {
  return <div className="empty-table">{text}</div>;
}

function StatCard({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: "good" | "warn" | "neutral" }) {
  return <div className="stat-card"><div className="stat-label">{label}</div><div className={`stat-value stat-${tone}`}>{value}</div><div className="stat-detail">{detail}</div></div>;
}

function Step({ number, title, text }: { number: string; title: string; text: string }) {
  return <div className="step-card"><div className="step-number">{number}</div><div><h4>{title}</h4><p>{text}</p></div></div>;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}
