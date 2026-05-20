/**
 * OpenClaw Colony — Seven Agent Interface
 * Task dispatch UI: submits prompts to the colony, displays per-agent outputs
 * and the Aethel sovereignty verdict.
 */

import React, { useState } from "react";
import LoveQualityChecker from "./LoveQualityChecker";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentOutput {
  agent: string;
  domain: string;
  summary: string;
  flags: string[];
  [key: string]: unknown;
}

interface LQDimension {
  name: string;
  weight: number;
  raw_score: number;
  weighted_score: number;
  rationale: string;
}

interface LQScore {
  composite: number;
  passed: boolean;
  threshold: number;
  rejection_reason: string | null;
  dimensions: LQDimension[];
}

interface GateStatus {
  verdict: "PASS" | "FAIL" | "NOT_REACHED";
  reason: string | null;
}

interface ColonyResponse {
  task_id: string;
  prompt: string;
  lq_score: LQScore;
  aethel_verdict: "APPROVED" | "BLOCKED";
  aethel_gates: Record<string, GateStatus>;
  committed_action: string | null;
  lineage_hash: string | null;
  timestamp: string;
  agent_outputs?: Record<string, AgentOutput>;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const AGENT_NAMES = [
  "Strategic",
  "Technical",
  "Resources",
  "Communications",
  "Analysis",
  "Quality",
  "Innovation",
];

const AGENT_COLORS: Record<string, string> = {
  Strategic:      "#6366f1",
  Technical:      "#0ea5e9",
  Resources:      "#22c55e",
  Communications: "#f59e0b",
  Analysis:       "#ec4899",
  Quality:        "#8b5cf6",
  Innovation:     "#14b8a6",
};

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// ── Component ─────────────────────────────────────────────────────────────────

export default function SevenAgentInterface() {
  const [prompt, setPrompt]           = useState("");
  const [consent, setConsent]         = useState(true);
  const [loading, setLoading]         = useState(false);
  const [result, setResult]           = useState<ColonyResponse | null>(null);
  const [error, setError]             = useState<string | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${API_BASE}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), human_consent: consent }),
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`Colony API error ${res.status}: ${body}`);
      }

      const data: ColonyResponse = await res.json();
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const verdictColor =
    result?.aethel_verdict === "APPROVED" ? "#22c55e" : "#ef4444";

  return (
    <div style={styles.container}>
      {/* ── Header ── */}
      <header style={styles.header}>
        <h1 style={styles.title}>🦅 OpenClaw Colony</h1>
        <p style={styles.subtitle}>
          Sovereignty-first · 7-Agent · Love Quality Governed
        </p>
      </header>

      {/* ── Agent grid ── */}
      <section style={styles.agentGrid}>
        {AGENT_NAMES.map((name) => (
          <div
            key={name}
            style={{
              ...styles.agentCard,
              borderColor: AGENT_COLORS[name],
              opacity: loading ? 0.6 : 1,
            }}
            onClick={() => setActiveAgent(activeAgent === name ? null : name)}
          >
            <div
              style={{
                ...styles.agentDot,
                backgroundColor: loading ? "#f59e0b" : "#22c55e",
              }}
            />
            <span style={styles.agentName}>{name}</span>
            {result?.agent_outputs?.[name] && (
              <span style={styles.agentCheck}>✓</span>
            )}
          </div>
        ))}
      </section>

      {/* ── Agent detail panel ── */}
      {activeAgent && result?.agent_outputs?.[activeAgent] && (
        <div style={styles.agentDetail}>
          <h3 style={{ color: AGENT_COLORS[activeAgent], margin: "0 0 8px" }}>
            {activeAgent} Agent
          </h3>
          <p style={styles.detailText}>
            {result.agent_outputs[activeAgent].summary}
          </p>
          {result.agent_outputs[activeAgent].flags?.length > 0 && (
            <p style={styles.flagText}>
              ⚠ Flags: {result.agent_outputs[activeAgent].flags.join(", ")}
            </p>
          )}
        </div>
      )}

      {/* ── Task input ── */}
      <form onSubmit={handleSubmit} style={styles.form}>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='Enter a task, proposal, or decision for the Colony to evaluate…'
          style={styles.textarea}
          rows={4}
          disabled={loading}
        />

        <label style={styles.consentLabel}>
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            disabled={loading}
            style={{ marginRight: 8 }}
          />
          I confirm explicit human consent for this action (Gate 1 — Sovereignty)
        </label>

        <button type="submit" disabled={loading || !prompt.trim()} style={styles.button}>
          {loading ? "Colony processing…" : "Submit to Colony"}
        </button>
      </form>

      {/* ── Error ── */}
      {error && (
        <div style={styles.errorBox}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* ── Result ── */}
      {result && (
        <div style={styles.resultContainer}>
          {/* Verdict banner */}
          <div style={{ ...styles.verdictBanner, backgroundColor: verdictColor }}>
            <span style={styles.verdictText}>
              {result.aethel_verdict === "APPROVED" ? "✅ APPROVED" : "🚫 BLOCKED"}
            </span>
            <span style={styles.verdictSub}>
              Aethel Sovereignty Verdict · Task {result.task_id.slice(0, 8)}
            </span>
          </div>

          {/* Aethel gates */}
          <div style={styles.gatesRow}>
            {Object.entries(result.aethel_gates).map(([key, gate]) => (
              <div
                key={key}
                style={{
                  ...styles.gateCard,
                  borderColor: gate.verdict === "PASS" ? "#22c55e" : "#ef4444",
                }}
              >
                <div style={styles.gateName}>{key.replace("_", " ").toUpperCase()}</div>
                <div
                  style={{
                    ...styles.gateVerdict,
                    color: gate.verdict === "PASS" ? "#22c55e" : "#ef4444",
                  }}
                >
                  {gate.verdict}
                </div>
                {gate.reason && (
                  <div style={styles.gateReason}>{gate.reason}</div>
                )}
              </div>
            ))}
          </div>

          {/* LQ Score panel */}
          <LoveQualityChecker lqScore={result.lq_score} />

          {/* Lineage hash */}
          {result.lineage_hash && (
            <div style={styles.lineageBox}>
              <strong>Lineage Hash:</strong>{" "}
              <code style={styles.hashCode}>{result.lineage_hash}</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 900,
    margin: "0 auto",
    padding: "24px 16px",
    fontFamily: "'Inter', system-ui, sans-serif",
    color: "#e2e8f0",
    backgroundColor: "#0f172a",
    minHeight: "100vh",
  },
  header: { textAlign: "center", marginBottom: 32 },
  title: { fontSize: 32, fontWeight: 700, margin: 0, color: "#f8fafc" },
  subtitle: { color: "#94a3b8", margin: "8px 0 0" },
  agentGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
    gap: 12,
    marginBottom: 24,
  },
  agentCard: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "12px 8px",
    border: "2px solid",
    borderRadius: 10,
    cursor: "pointer",
    backgroundColor: "#1e293b",
    transition: "opacity 0.2s",
    position: "relative",
  },
  agentDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    marginBottom: 6,
  },
  agentName: { fontSize: 13, fontWeight: 600, textAlign: "center" },
  agentCheck: { position: "absolute", top: 6, right: 8, color: "#22c55e", fontSize: 12 },
  agentDetail: {
    backgroundColor: "#1e293b",
    border: "1px solid #334155",
    borderRadius: 10,
    padding: 16,
    marginBottom: 20,
  },
  detailText: { fontSize: 14, color: "#cbd5e1", margin: 0 },
  flagText: { fontSize: 13, color: "#f59e0b", marginTop: 8 },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    marginBottom: 24,
  },
  textarea: {
    width: "100%",
    padding: 12,
    borderRadius: 8,
    border: "1px solid #334155",
    backgroundColor: "#1e293b",
    color: "#e2e8f0",
    fontSize: 15,
    resize: "vertical",
    boxSizing: "border-box",
  },
  consentLabel: {
    display: "flex",
    alignItems: "center",
    fontSize: 14,
    color: "#94a3b8",
    cursor: "pointer",
  },
  button: {
    padding: "12px 24px",
    backgroundColor: "#6366f1",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
    alignSelf: "flex-start",
  },
  errorBox: {
    backgroundColor: "#450a0a",
    border: "1px solid #ef4444",
    borderRadius: 8,
    padding: 12,
    color: "#fca5a5",
    marginBottom: 16,
  },
  resultContainer: { display: "flex", flexDirection: "column", gap: 16 },
  verdictBanner: {
    borderRadius: 10,
    padding: "16px 20px",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  verdictText: { fontSize: 22, fontWeight: 700, color: "#fff" },
  verdictSub: { fontSize: 13, color: "rgba(255,255,255,0.8)" },
  gatesRow: { display: "flex", gap: 12, flexWrap: "wrap" },
  gateCard: {
    flex: "1 1 160px",
    border: "2px solid",
    borderRadius: 8,
    padding: 12,
    backgroundColor: "#1e293b",
  },
  gateName: { fontSize: 11, color: "#94a3b8", marginBottom: 4, fontWeight: 600 },
  gateVerdict: { fontSize: 16, fontWeight: 700 },
  gateReason: { fontSize: 12, color: "#94a3b8", marginTop: 6 },
  lineageBox: {
    backgroundColor: "#1e293b",
    border: "1px solid #334155",
    borderRadius: 8,
    padding: 12,
    fontSize: 13,
    color: "#94a3b8",
    wordBreak: "break-all",
  },
  hashCode: {
    fontFamily: "monospace",
    color: "#a5b4fc",
    fontSize: 12,
  },
};