# ADR-0005: One-Command Installer Over Manual Deployment

**Date:** 2026-05-20
**Status:** Accepted
**Vector:** Access

## Decision
The primary deployment path is:
  curl -sSL https://openclaw.net/install | bash

Manual deployment is documented but not the primary path.

## Why
- The mission requires reaching non-technical communities
- Every additional step is a person who does not get protected
- Complexity is the enemy of adoption
- Adoption is the enemy of the problem we are solving

## Consequences
- install.sh must be maintained as a first-class artifact
- Every deployment change must be reflected in install.sh
- CI must verify the install path works on a clean machine

## Invariant
**If a non-technical community member cannot deploy a node,**
**the Access vector is violated.**
**Fix the installer before shipping the feature.**
