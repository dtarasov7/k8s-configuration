# Changelog

## 2.9.0 — 2026-11-03

- Removed local User/Group lifecycle management, passwords and membership updates. Removed users/groups, password_updates, prune_identities, User/Group API version settings and ready_checks_user_authn. Matrices retain read-only identity discovery; grants reference existing subjects. Updated manual inventories, documentation and tests.
- Removed intermediate vars/main.yml. The module receives typed flat arguments directly from execute.yml and assembles internal settings in Python, preserving unmanaged grants and lazy grant evaluation in read modes.
- Removed expected_image and manual_dkp_deckhouse_image plus Deckhouse image/Deployment rollout checks. Module readiness and API/CRD checks remain. Updated documentation and tests.

## 2.8.1 — 2026-11-03

- Added 109 bilingual EN/RU docstrings covering purpose, parameter types, results and expected errors. Documented all 8 classes and main functions across 9 Python files, plus complex transport/reconciliation/matrix/export/Jinja behavior. Executable logic is unchanged, verified by AST comparison with docstrings removed.


## 2.8.0 — 2026-11-03

- Added matrix_source: cluster/inventory. Inventory matrices use grants and current Role/ClusterRole rules without reading live bindings or writing to Kubernetes; local membership comes from the API. Absent assignments are omitted; missing roles/namespaces fail the report. Separate *-inventory.csv defaults and manual scenarios. RBAC is supported on vanilla/Deckhouse; native AR/CAR prediction is explicitly rejected rather than fabricated.


## 2.7.0 — 2026-11-03

- Dry files now use add/change/remove and metadata. Each addition/removal is described once; updates show changed fields only. Preserved digest, replacement markers and actual adoption/collision transitions. Removed privilege_change. Mixed authorization warnings identify relevant subjects and RBAC/Deckhouse objects. Standard --diff and module diagnostic results are preserved.


## 2.6.1 — 2026-11-03

- Removed obsolete export_include_identities from the vanilla inventory and three unused Vault/certificate paths from defaults. Lookup examples define their own example_* variables. Added runtime-consumer checks for defaults and unknown role-setting checks for all manual inventories/scenarios.


## 2.6.0 — 2026-11-03

- Export always contains k8s_configuration_grants only. Removed include_identities and User/Group, membership, bcrypt and identity-dependency serialization. Identity definitions are excluded from export audit as well. Literal subject names and compact formatting are preserved.


## 2.5.1 — 2026-11-03

- Compact YAML in manual inventories and exports: flow subjects/roleRef/scope. Deckhouse baseline adds a node-reader ClusterRoleBinding. Default exports contain grants only, omitting users/groups and identity dependencies; explicit include_identities=true preserves full migration.


## 2.5.0 — 2026-11-03

- Removed source from grant subjects. User/Group use literal names; ServiceAccount also requires namespace. Export preserves email/group claims instead of local identity references. Updated manual fixtures, Molecule, tests and docs; roleRef/scope remain unchanged.


## 2.4.0 — 2026-11-03

- Removed access_checks, post-apply/pre-prune SubjectAccessReview and the SAR requirement for Deckhouse profiles without a Ready condition. Removed manual inventory check lists and the SAR-only explicit-scope scenario. Use matrix to inspect permissions; no additional post-apply binding checks were introduced.


## 2.3.3 — 2026-11-03

- Dry plans include only actual create/update/replace/delete operations in changes. Unchanged objects contribute to summary.noop without before/after payloads. Dry after apply with the same inventory produces empty planned lists and changes.


## 2.3.2 — 2026-11-03

- External matrix Users show direct grants only, using uppercase letters and dots. Group grants, including system:authenticated, produce neither inherited letters nor question marks. Local Deckhouse Users and ServiceAccounts retain inheritance.
- subjects.csv adds rights_basis (direct_only/direct_and_groups); audit sources, broad-subject filtering and declaration selection follow the same calculation scope.


## 2.3.1 — 2026-11-03

- Normalize matrix boolean switches with Ansible bool before invoking the module. CLI key=value extra-vars such as k8s_configuration_matrix_include_external_users=true/false no longer fail type validation.
- Added coverage for true/false strings across all nine switches and actual ansible-playbook key=value external-user toggling.


## 2.3.0 — 2026-11-03

- Matrix resolves complete local Deckhouse membership from live User/Group objects, including nested groups and legacy User.spec.groups. Disabling resolution retains unknown membership.
- External users default to group-only reporting without member inference. include_external_users=true restores direct User columns; excluded User rules no longer seed rows.
- Removed fixed manual-test membership dictionaries; reports follow live cluster changes. Added excluded_external_users, regression checks and exact group-claim matching documentation.


## 2.2.3 — 2026-11-02

- Added explicit complete group memberships for the 16 local fixture users in manual-test-dkp. Their matrix cells use letters/dots; other users retain unknown membership markers.
- manual_dkp_matrix_memberships overrides the list; an empty list disables the fixture assumption. Documented synchronization and LDAP membership extensions.
- Tested manifest consistency, inherited grants and preservation of unknowns for external users. Role runtime remains unchanged.


## 2.2.2 — 2026-11-02

- Manual-test-dkp now manages grants only; kubectl fixtures provision User/Group and additional Kubernetes Role/ClusterRole resources.
- Added 16 local fixture users with test password 12121212 and four groups; removed password lookups and identity-management scenarios from the manual inventory.
- Baseline combines local and fictional LDAP claims: 13 grants, 16 RoleBindings and 42 SAR checks. Updated native AR, cleanup/export instructions and added group-binding.
- Tests cover fixture identity/role preservation during grants, idempotence and cleanup. Role runtime remains unchanged.


## 2.2.1 — 2026-11-02

- Matrix excludes subjects with wildcard grants across all API groups/resources without resourceNames, regardless of verbs, and known members of those groups by default.
- Excluded grants no longer seed matrix rows, preventing extra unknown-only rows for remaining users.
- Added exclude_broad_subjects, exclusion counts/names, and updated manual inventories, documentation and design.


## 2.2.0 — 2026-11-02

- Matrix now hides system namespaces/identities and ServiceAccounts by default and drops dot-only rows.
- Added independent application/system/all namespace modes, configurable system classification, and glob include/exclude filters for users, groups, namespaces and ServiceAccounts.
- Hidden groups still contribute inherited grants; unknown membership rows remain visible.
- Source/subject CSVs follow the selection; summaries expose filters and exclusion counts. Updated manual fixtures and RU/EN documentation.


## 2.1.0 — 2026-11-02

- Removed the legacy configuration dictionary check.
- Dry/export/matrix automatically save results on the Ansible controller; kubectl stays on the selected target.
- Controller file tasks use local connection, controller Python and become=false. Missing directories are created; existing directory permissions are preserved; files use 0600.
- Inventory variables configure dry/export paths, matrix directory and all three CSV filenames. Relative paths resolve against playbook_dir; check mode previews writes.
- Updated manual inventories/documentation and regression coverage, including output delegation with an unusable target SSH/Python/become configuration.

## 2.0.0 — 2026-11-02

- Breaking change: public config/export/matrix settings are flat k8s_configuration_* variables. Legacy dictionaries fail validation; desired-state lists keep their schemas.
- Deckhouse readiness uses Module phase and EnabledByModuleManager/IsReady conditions. ModuleConfig is optional; explicit disable and read failures still block reconciliation.
- Discover served APIs and verify resource scope plus Established CRD/version/schema. Exact image pinning is optional, disabled by default.
- Missing module settings never imply multitenancy support. Module/ModuleConfig observations are rechecked before writes.
- Updated manual inventories/scenarios, examples, Molecule, private module payload assembly, documentation and tests. Typed safety.max_deletions supports templated numeric variables.

## 1.3.1 — 2026-11-02

- Matrix derives item kinds from discovered collections when list items omit kind/apiVersion.
- Null optional rules/subjects/members and PolicyRule lists are handled as empty lists.
- Unexpected errors include exception type and code file/line without exception text, API objects or credentials.
- Added regression coverage with HTTPS list items lacking TypeMeta and roles containing rules: null.

## 1.3.0 — 2026-11-02

- The Deckhouse matrix scenario defaults to existing namespaces without test fixtures; namespace filter errors list the missing names.
- Added GET-only matrix mode: GLWCUPDX CSV matrix, complete grant provenance and subject/membership report.
- Direct uppercase and inherited lowercase grants, unknown membership markers, wildcards, named resources, subresources, special verbs and observed aggregated roles.
- Deckhouse User/Group and AR/CAR audit without controller readiness requirements; generated-binding provenance requires owner UID.
- Private CSV output with check/idempotence and spreadsheet formula protection. Matrix/export no longer evaluate desired identities or password lookups.
- Added unit/integration checks and manual matrix scenarios for vanilla Kubernetes and Deckhouse.

## 1.2.1 — November 1, 2026

- Validate the effective hosts after play hosts and --limit: exactly one is allowed; multiple hosts fail before kubectl, including with serial: 1.
- Allow groups, all, lists and patterns; replace the custom action plugin with built-in assert and ansible_play_hosts_all.
- The manual example uses hosts: access_test and supports -l redos8. Updated documentation and host-selection integration tests.


## 1.2.0 — November 1, 2026

- Replaced custom HTTPS/TLS transport with installed kubectl, retaining modes, check/diff and UID/resourceVersion guards for PATCH/DELETE.
- Select one literal play host or localhost for controller execution. Reject groups, all, patterns and multiple hosts even with --limit/serial. Inventory group_vars remain supported.
- Added connection.kubectl; context selection does not change current-context. kubectl handles kubeconfig and credential plugins; role runtime no longer requires PyYAML.
- Updated manual-test, documentation and tests.


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
