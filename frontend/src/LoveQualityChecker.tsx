/**
 * OpenClaw Colony — Love Quality Checker
 * Visualises the 6-dimension LQ score breakdown with weighted bars.
 */

import React from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

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

interface Props {
  lqScore: LQScore;
}

// ── Dimension metadata ────────────────────────────────────────────────────────

const DIMENSION_META: Record<string, { emoji: string; color: string }> = {
  flourishing:    { emoji: "🌱", color: "#22c55e" },
  harm_reduction: { emoji: "🛡️", color: "#0ea5e9" },
  equity:         { emoji: "⚖️", color: "#a855f7" },
  regenerative:   { emoji: "♻️", color: "#14b8a6" },
  cooperation:    { emoji: "🤝", color: "#f59e0b" },
  beauty:         { emoji: "✨", color: "#ec4899" },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function LoveQualityChecker({ lqScore }: Props) {
  const compositePercent = Math.round(lqScore.composite * 100);
  const thresholdPercent = Math.round(lqScore.threshold * 100);
  const passed           = lqScore.passed;

  return (
    <div style={styles.container}>
      {/* ── Header ── */}
      <div style={styles.header}>
        <span style={styles.headerTitle}>💜 Love Quality Score</span>
        <span
          style={{
            ...styles.badge,
            backgroundColor: passed ? "#14532d" : "#450a0a",
            color: passed ? "#86efac" : "#fca5a5",
            borderColor: passed ? "#22c55e" : "#ef4444",
          }}
        >
          {passed ? "PASS" : "FAIL"} — {compositePercent}%
        </span>
      </div>

      {/* ── Composite bar ── */}
      <div style={styles.compositeRow}>
        <div style={styles.compositeBarTrack}>
          <div
            style={{
              ...styles.compositeBarFill,
              width: `${compositePercent}%`,
              backgroundColor: passed ? "#22c55e" : "#ef4444",
            }}
          />
          {/* Threshold marker */}
          <div
            style={{
              ...styles.thresholdMarker,
              left: `${thresholdPercent}%`,
            }}
          />
        </div>
        <span style={styles.compositeLabel}>
          {lqScore.composite.toFixed(4)} / threshold {lqScore.threshold}
        </span>
      </div>

      {/* ── Rejection reason ── */}
      {lqScore.rejection_reason && (
        <div style={styles.rejectionBox}>
          ⚠ {lqScore.rejection_reason}
        </div>
      )}

      {/* ── Dimension breakdown ── */}
      <div style={styles.dimensionsGrid}>
        {lqScore.dimensions.map((dim) => {
          const meta    = DIMENSION_META[dim.name] ?? { emoji: "•", color: "#94a3b8" };
          const rawPct  = Math.round(dim.raw_score * 100);
          const wgtPct  = Math.round(dim.weighted_score * 100);

          return (
            <div key={dim.name} style={styles.dimCard}>
              <div style={styles.dimHeader}>
                <span style={styles.dimEmoji}>{meta.emoji}</span>
                <span style={styles.dimName}>
                  {dim.name.replace("_", " ")}
                </span>
                <span style={styles.dimWeight}>
                  w={dim.weight.toFixed(2)}
                </span>
              </div>

              {/* Raw score bar */}
              <div style={styles.barTrack}>
                <div
                  style={{
                    ...styles.barFill,
                    width: `${rawPct}%`,
                    backgroundColor: meta.color,
                  }}
                />
              </div>

              <div style={styles.dimScores}>
                <span style={{ color: meta.color }}>
                  raw {dim.raw_score.toFixed(3)}
                </span>
                <span style={styles.dimWeighted}>
                  → weighted {dim.weighted_score.toFixed(3)}
                </span>
              </div>

              <p style={styles.dimRationale}>{dim.rationale}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: "#1e293b",
    border: "1px solid #334155",
    borderRadius: 12,
    padding: 20,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  headerTitle: { fontSize: 18, fontWeight: 700, color: "#f8fafc" },
  badge: {
    fontSize: 13,
    fontWeight: 700,
    padding: "4px 12px",
    borderRadius: 20,
    border: "1px solid",
  },
  compositeRow: { marginBottom: 12 },
  compositeBarTrack: {
    position: "relative",
    height: 12,
    backgroundColor: "#0f172a",
    borderRadius: 6,
    overflow: "visible",
    marginBottom: 6,
  },
  compositeBarFill: {
    height: "100%",
    borderRadius: 6,
    transition: "width 0.4s ease",
  },
  thresholdMarker: {
    position: "absolute",
    top: -4,
    width: 2,
    height: 20,
    backgroundColor: "#f59e0b",
    borderRadius: 1,
    transform: "translateX(-50%)",
  },
  compositeLabel: { fontSize: 12, color: "#94a3b8" },
  rejectionBox: {
    backgroundColor: "#450a0a",
    border: "1px solid #ef4444",
    borderRadius: 8,
    padding: "8px 12px",
    color: "#fca5a5",
    fontSize: 13,
    marginBottom: 16,
  },
  dimensionsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
    gap: 12,
    marginTop: 8,
  },
  dimCard: {
    backgroundColor: "#0f172a",
    borderRadius: 8,
    padding: 12,
    border: "1px solid #1e293b",
  },
  dimHeader: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  dimEmoji: { fontSize: 16 },
  dimName: {
    fontSize: 13,
    fontWeight: 600,
    color: "#e2e8f0",
    textTransform: "capitalize",
    flex: 1,
  },
  dimWeight: { fontSize: 11, color: "#64748b" },
  barTrack: {
    height: 6,
    backgroundColor: "#1e293b",
    borderRadius: 3,
    marginBottom: 6,
    overflow: "hidden",
  },
  barFill: {
    height: "100%",
    borderRadius: 3,
    transition: "width 0.3s ease",
  },
  dimScores: {
    display: "flex",
    gap: 8,
    fontSize: 12,
    marginBottom: 6,
  },
  dimWeighted: { color: "#64748b" },
  dimRationale: {
    fontSize: 11,
    color: "#64748b",
    margin: 0,
    lineHeight: 1.5,
  },
};