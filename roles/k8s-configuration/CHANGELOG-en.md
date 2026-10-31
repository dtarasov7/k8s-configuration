# Changelog

## 1.1.0

- Renamed role to k8s-configuration, module/variables to k8s_configuration. Kept ownership and generated resource names stable.
- Added independent dry mode with three operation summaries; retained plan alias. Fixed standard diff and export --check.
- Export writes inventory variables directly, with separate audit. Standalone users/groups and private bcrypt hashes can be recreated on another cluster.
- Unsupported selected resources block export by default; incomplete snapshots require allow_partial.


## 1.0.0 — 2026-10-23

- Added a REST-only Ansible role for vanilla Kubernetes and Deckhouse access management.
- Implemented plan/apply/export, check/diff, strict validation, ownership/adoption, bounded pruning and optimistic concurrency.
- Added local User/Group, basic AuthorizationRule/ClusterAuthorizationRule and explicit Deckhouse compatibility profiles.
- Added unit/HTTPS integration, RED OS Molecule with a real kind API and control-plane failure testing.
- A production Deckhouse profile requires target-version verification; API fixtures do not validate a real Deckhouse controller.
