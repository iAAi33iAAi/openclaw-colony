# AETHEL Interop v1

The AETHEL platform is the execution control plane. External runtimes contribute
analysis or domain computation through a versioned JSON contract.

## Boundaries

| Engine | Role | Execution authority |
|---|---|---|
| Colony + Rust/PyO3 kernel | Safety, action, lineage | Yes |
| CAIOS / Project Andrew | Paradox/entropy reasoning | No; advisory |
| Sports Math | Allocation/routing/optimization | No; advisory |
| Project Mono / ALGA_FOLD_KERNEL | Change-control evidence | No; returns a gate decision |
| Undermoon | Protocol/conformance compatibility | No; canonical status remains blocked |
| AETHEL Grid | Event/state reconstruction bootstrap | No; canonical SPEC-004 remains separate |

Every external response uses aethel-interop/1 and must be treated as evidence,
not as an authorization token.

## CAIOS

CAIOS remains an external GPL-3.0 repository. The supported integration pattern is
a pinned checkout referenced by CAIOS_SOURCE_PATH; the Colony repository does
not vendor or fork the CAIOS source.

Use tools/bootstrap_caios.ps1 on Windows or tools/bootstrap_caios.sh on Linux/macOS.
