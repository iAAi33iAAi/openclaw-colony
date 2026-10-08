import React, { useEffect, useState } from "react";
import SevenAgentInterface from "./SevenAgentInterface";
import "./platform.css";

type Page = "overview" | "requests" | "agents" | "approvals" | "history";

interface HealthResponse {
  status?: string;
  node_id?: string;
}

const NAV_ITEMS: Array<{ id: Page; label: string; description: string; icon: string }> = [
  { id: "overview", label: "Overview", description: "System status", icon: "⌂" },
  { id: "requests", label: "Requests", description: "Submit work", icon: "＋" },
  { id: "agents", label: "AI Agents", description: "7 agent team", icon: "◈" },
  { id: "approvals", label: "Approvals", description: "Human decisions", icon: "✓" },
  { id: "history", label: "History", description: "Verified activity", icon: "◷" },
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
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [nodeId, setNodeId] = useState<string>("");

  useEffect(() => {
    let active = true;

    const checkHealth = async () => {
      try {
        const base = import.meta.env.VITE_API_URL ?? "";
        const response = await fetch(`${base}/health`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: HealthResponse = await response.json();
        if (!active) return;
        setHealth("online");
        setNodeId(data.node_id ?? "");
      } catch {
        if (!active) return;
        setHealth("offline");
      }
    };

    void checkHealth();
    return () => {
      active = false;
    };
  }, []);

  const pageTitle = NAV_ITEMS.find((item) => item.id === page)?.label ?? "Overview";
  const statusLabel =
    health === "online" ? "System online" : health === "offline" ? "API offline" : "Checking system";

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
          <div className="node-card-value">{nodeId || "Local / unregistered"}</div>
          <div className={`status-line status-${health}`}>
            <span className="status-dot" />
            {statusLabel}
          </div>
        </div>

        <nav className="nav-list" aria-label="AETHEL navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-copy">
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-footer-title">What AETHEL does</div>
          <p>
            Requests come in, rules are checked, people can approve important actions,
            work is performed, and the result is recorded.
          </p>
        </div>
      </aside>

      <main className="aethel-main">
        <header className="topbar">
          <div>
            <div className="eyebrow">AETHEL / {pageTitle.toUpperCase()}</div>
            <h1>{pageTitle}</h1>
          </div>
          <button className="primary-button" type="button" onClick={() => setPage("requests")}>
            New request
          </button>
        </header>

        {page === "overview" && (
          <Overview
            health={health}
            nodeId={nodeId}
            onCreateRequest={() => setPage("requests")}
          />
        )}

        {page === "requests" && (
          <section className="page-section">
            <div className="section-intro">
              <div>
                <div className="section-kicker">WORK INTAKE</div>
                <h2>Send a request through AETHEL</h2>
                <p>
                  Start with one task. AETHEL evaluates it, applies the current safety gates,
                  and returns the decision and evidence to the screen.
                </p>
              </div>
              <div className="info-pill">Live request flow</div>
            </div>
            <div className="embedded-panel">
              <SevenAgentInterface />
            </div>
          </section>
        )}

        {page === "agents" && <AgentsPage onCreateRequest={() => setPage("requests")} />}

        {page === "approvals" && <ApprovalsPage onCreateRequest={() => setPage("requests")} />}

        {page === "history" && <HistoryPage />}
      </main>
    </div>
  );
}

function Overview({
  health,
  nodeId,
  onCreateRequest,
}: {
  health: "checking" | "online" | "offline";
  nodeId: string;
  onCreateRequest: () => void;
}) {
  return (
    <div className="dashboard-grid">
      <section className="hero-card">
        <div className="hero-copy">
          <div className="section-kicker">THE FRONT DOOR</div>
          <h2>One place to ask the system to do something.</h2>
          <p>
            AETHEL turns the pieces you have already built into a single operating experience:
            a person or AI submits a request, the system checks it, and the outcome is recorded.
          </p>
          <button className="primary-button" type="button" onClick={onCreateRequest}>
            Create your first request
          </button>
        </div>
        <div className="hero-flow" aria-label="AETHEL request flow">
          {["Request", "Check", "Approve", "Act", "Record"].map((step, index) => (
            <React.Fragment key={step}>
              <div className="flow-step">
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step}</strong>
              </div>
              {index < 4 && <div className="flow-arrow">→</div>}
            </React.Fragment>
          ))}
        </div>
      </section>

      <section className="stat-grid">
        <StatCard
          label="Platform"
          value={health === "online" ? "ONLINE" : health === "offline" ? "OFFLINE" : "CHECKING"}
          detail={nodeId || "Connect the API to identify a node."}
          tone={health === "online" ? "good" : health === "offline" ? "warn" : "neutral"}
        />
        <StatCard label="AI team" value="7" detail="Specialist agents in the current request interface." tone="neutral" />
        <StatCard label="Safety" value="4 gates" detail="The current request path checks four safety gates." tone="neutral" />
        <StatCard label="Evidence" value="Recorded" detail="Completed evaluations can return a lineage hash." tone="neutral" />
      </section>

      <section className="wide-card">
        <div className="card-heading">
          <div>
            <div className="section-kicker">HOW TO USE IT</div>
            <h3>Start with one real task</h3>
          </div>
          <span className="info-pill">No infrastructure knowledge required</span>
        </div>
        <div className="step-grid">
          <Step number="01" title="Write the task" text="Describe what you need the system to evaluate or do." />
          <Step number="02" title="Let AETHEL check it" text="The request goes through the current application and safety pipeline." />
          <Step number="03" title="Review the result" text="See whether it was approved or blocked, and why." />
          <Step number="04" title="Keep the evidence" text="Use the returned task details and lineage information to review the outcome later." />
        </div>
      </section>

      <section className="wide-card">
        <div className="card-heading">
          <div>
            <div className="section-kicker">NEXT LAYER</div>
            <h3>What comes after the first request works</h3>
          </div>
        </div>
        <div className="connector-grid">
          <Connector title="Human approvals" description="Put a real approval screen in front of higher-risk actions." />
          <Connector title="Agent permissions" description="Define exactly what each AI worker is allowed to request or perform." />
          <Connector title="Economic actions" description="Attach value and payment rules to completed work." />
          <Connector title="Physical systems" description="Later connect water, energy, greenhouse, and other real-world systems." />
        </div>
      </section>
    </div>
  );
}

function AgentsPage({ onCreateRequest }: { onCreateRequest: () => void }) {
  return (
    <section className="page-section">
      <div className="section-intro">
        <div>
          <div className="section-kicker">AI WORKFORCE</div>
          <h2>The seven-agent team</h2>
          <p>These are the agents already represented by the current request interface. The next platform step is to give each agent explicit permissions and a visible work history.</p>
        </div>
        <button className="primary-button" type="button" onClick={onCreateRequest}>Create request</button>
      </div>
      <div className="agent-catalog">
        {AGENTS.map((agent, index) => (
          <div className="agent-catalog-card" key={agent.name}>
            <div className="agent-number">0{index + 1}</div>
            <h3>{agent.name}</h3>
            <p>{agent.role}</p>
            <div className="agent-status"><span className="status-dot online" /> Available in request flow</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ApprovalsPage({ onCreateRequest }: { onCreateRequest: () => void }) {
  return (
    <section className="empty-state-panel">
      <div className="empty-state-icon">✓</div>
      <div className="section-kicker">HUMAN AUTHORITY</div>
      <h2>Approval center is the next major screen.</h2>
      <p>
        The current backend request flow already carries an explicit human-consent value.
        This screen is reserved for turning that concept into a real queue where a person can
        review higher-risk actions, approve them, reject them, or ask for more information.
      </p>
      <button className="primary-button" type="button" onClick={onCreateRequest}>Open request flow</button>
    </section>
  );
}

function HistoryPage() {
  return (
    <section className="empty-state-panel">
      <div className="empty-state-icon">◷</div>
      <div className="section-kicker">SYSTEM MEMORY</div>
      <h2>History becomes the audit trail.</h2>
      <p>
        Completed request results already return task information, gate results, timestamps,
        and lineage information. The next step is to turn that response into a searchable history
        page backed by the colony database.
      </p>
      <div className="planned-record">
        <span>Planned record</span>
        <strong>Who requested it → What happened → What was approved → What evidence remains</strong>
      </div>
    </section>
  );
}

function StatCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn" | "neutral";
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value stat-${tone}`}>{value}</div>
      <div className="stat-detail">{detail}</div>
    </div>
  );
}

function Step({ number, title, text }: { number: string; title: string; text: string }) {
  return (
    <div className="step-card">
      <div className="step-number">{number}</div>
      <div>
        <h4>{title}</h4>
        <p>{text}</p>
      </div>
    </div>
  );
}

function Connector({ title, description }: { title: string; description: string }) {
  return (
    <div className="connector-card">
      <div className="connector-dot" />
      <div>
        <h4>{title}</h4>
        <p>{description}</p>
      </div>
    </div>
  );
}
