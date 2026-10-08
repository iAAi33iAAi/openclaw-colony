/**
 * AETHEL platform front door.
 *
 * The existing SevenAgentInterface remains the live request workflow.
 * PlatformShell adds the product structure around it so AETHEL has one
 * understandable place for people to enter, navigate, and eventually manage
 * requests, approvals, agents, history, and physical connectors.
 */
import React from "react";
import PlatformShell from "./PlatformShell";

export default function App() {
  return <PlatformShell />;
}
