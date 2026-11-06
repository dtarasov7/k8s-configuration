# k8s-configuration

Ansible role managing Kubernetes and Deckhouse authorization through the installed kubectl. Supports dry/apply/export/matrix, check/diff, UID-bound adoption, bounded pruning, basic Deckhouse authorization resources. No custom HTTP client, kubernetes.core or Kubernetes SDK is used.

The role manages access assignments for existing subjects only. It never creates, updates or deletes User/Group objects, passwords or group memberships. Deckhouse User/Group objects are read only for permission matrices. Vanilla Kubernetes identities remain external. The role does not create LDAP/OIDC identities, certificates, namespaces, Role/ClusterRole definitions, service accounts or tokens. It references existing roles and identities.

## Result files on the Ansible controller

Dry (including plan), export and matrix automatically save their results on the machine running ansible-playbook. kubectl/API reads stay on the selected target host. File tasks delegate to localhost with local connection, ansible_playbook_python and become=false. No controller entry in inventory is needed.

```yaml
k8s_configuration_report_path: '{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml'
k8s_configuration_export_destination: '{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml'
k8s_configuration_export_audit_destination: '{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml'
k8s_configuration_matrix_output_dir: '{{ playbook_dir }}/output/{{ inventory_hostname }}'
k8s_configuration_matrix_filename: matrix.csv
k8s_configuration_matrix_bindings_filename: bindings.csv
k8s_configuration_matrix_subjects_filename: subjects.csv
```

These are the defaults. report_path/export_destination include the filename; matrix_output_dir and the three *_filename variables configure CSV placement/names. Relative paths resolve against playbook_dir on the controller; ~ expands for the controller user. Files of one result must have distinct paths. Dry requires a nonempty report_path. An empty export_audit_destination disables only the additional audit. Apply does not automatically save reports.

Dry saves the sanitized plan, export the importable inventory plus separate audit, matrix its three CSV reports. New directories use 0700 and files 0600; existing directory permissions are preserved. File contents stay hidden from --diff. Final output lists controller file paths.

--check reads the cluster and previews file changes without writing files. changed can indicate controller file changes even though the Kubernetes API is read-only. Unchanged repeated runs are idempotent.

## Requirements and example

Execution host: Python 3.8+, kubectl, kubeconfig, network access and appropriate API permissions. PyYAML is not required by the role runtime on the execution host. Control node: ansible-core 2.12+ with its supported Python version. Install dependencies separately; see requirements-legacy.txt and requirements-modern.txt. The legacy 2.12 branch is EOL. Exactly one execution host must remain after combining play hosts and --limit. Hostnames, groups, all, lists and patterns are allowed. Multiple effective hosts fail before kubectl; serial: 1 does not bypass the full selected-host check (ansible_play_hosts_all). Use gather_facts: false to validate before host connections. Serialize runs per cluster/owner.

```ini
[access_executor]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3
```

```yaml
- name: Manage access
  hosts: access_executor
  gather_facts: false
  vars:
    k8s_configuration_config_mode: dry
    k8s_configuration_config_platform: vanilla
    k8s_configuration_config_connection_kubeconfig: /etc/ansible/cluster.yaml
    k8s_configuration_config_connection_context: prod
    k8s_configuration_config_management_owner: platform
    k8s_configuration_config_management_namespaces: [development]
    k8s_configuration_config_management_include_cluster_scoped: false
    k8s_configuration_grants:
    - id: readers
      backend: rbac
      subjects:
      - {kind: Group, name: 'oidc:readers'}
      roleRef: {kind: ClusterRole, name: view}
      scope: {namespaces: [development]}
  roles:
  - role: k8s-configuration
```

```bash
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.ini access.yml
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.ini access.yml --check --diff
```

Modes are dry (default), apply, export and matrix. Dry independently reads and reports planned additions, changes and removals with no Kubernetes writes; saving the controller report may set changed=true. Apply --check predicts changes without writes; --diff shows sanitized before/after. Export --check still exports, previewing the file write without creating it. Matrix reads current RBAC and prepares CSV reports; --check previews file writes. The old plan spelling remains a compatibility alias. Server validation runs only during real apply.

## Included examples

- [Minimal INI inventory](examples/inventory.ini) and [playbook](examples/playbook.yml) for vanilla Kubernetes.
- [Complete Deckhouse example](examples/deckhouse/README.md) following the manual-test-dkp layout: INI inventory, group_vars with compact grants, fixtures, dry/apply, export, matrix, OpenLDAP and assignment removal.

INI inventory defines hosts and Ansible connection settings. Structured subjects, roleRef and scope values belong in YAML group_vars or playbook vars, using the compact form shown in manual-test-dkp.

## Public variables

k8s_configuration_grants has no default: omitted means unmanaged, [] means explicitly empty. The k8s_configuration_users and k8s_configuration_groups parameters have been removed; manage identities outside this role. Domain data (references, memberships and rules) remain lists of objects.

Additional variables: k8s_configuration_no_log=true, k8s_configuration_report_path (controller dry report), k8s_configuration_certificates=[] ({name, content}: ca_content/cert_content/key_content). k8s_configuration_result is the registered result; export contains assignments only and its contents stay hidden in task output. Unknown module-payload fields are rejected.

### Flat configuration settings

| Variable | Default | Purpose and usage |
| --- | --- | --- |
| `k8s_configuration_config_schema_version` | `1` | Settings schema version; validated before execution. Only version 1 is supported. |
| `k8s_configuration_config_mode` | `"dry"` | Operation mode: dry builds a plan, apply writes changes, export saves assignments, matrix generates permission CSVs; plan is a legacy alias for dry. |
| `k8s_configuration_config_platform` | `"vanilla"` | Cluster platform: vanilla uses Kubernetes RBAC; deckhouse additionally supports Deckhouse APIs. |
| `k8s_configuration_config_connection_kubectl` | `"kubectl"` | Executable name or path on the execution host; all cluster API operations use this kubectl binary. |
| `k8s_configuration_config_connection_validate_tls` | `true` | Enables API TLS certificate verification; false disables certificate verification in kubectl. |
| `k8s_configuration_config_connection_timeout_seconds` | `30` | API request and kubectl process timeout in seconds. |
| `k8s_configuration_config_connection_retries` | `2` | Number of GET retries for transient errors; writes are not automatically retried. |
| `k8s_configuration_config_connection_kubeconfig` | `""` | Kubeconfig path on the execution host; an empty string leaves kubeconfig selection to kubectl. |
| `k8s_configuration_config_connection_context` | `""` | Kubeconfig context to use; an empty string uses the current kubectl context. |
| `k8s_configuration_config_connection_ca_content` | `""` | PEM CA content for API certificate verification; supplied to kubectl through a temporary file on the execution host. |
| `k8s_configuration_config_connection_cert_content` | `""` | PEM client certificate content; supplied to kubectl through a temporary file on the execution host. |
| `k8s_configuration_config_connection_key_content` | `""` | PEM client private key content; supplied to kubectl through a temporary file on the execution host. |
| `k8s_configuration_config_deckhouse_basic_authz` | `false` | Allows managing and pruning basic Deckhouse AuthorizationRule/ClusterAuthorizationRule resources; required for backend: deckhouse. |
| `k8s_configuration_config_deckhouse_api_versions_authorization_rule` | `""` | Pins the Deckhouse AuthorizationRule API version; an empty string enables automatic served-version discovery. |
| `k8s_configuration_config_deckhouse_api_versions_cluster_authorization_rule` | `""` | Pins the Deckhouse ClusterAuthorizationRule API version; an empty string enables automatic served-version discovery. |
| `k8s_configuration_config_deckhouse_ready_checks_user_authz` | `[]` | Additional user-authz readiness checks through the API: a list of {path, pointer, equals or minimum} entries. |
| `k8s_configuration_config_deckhouse_authz_ready_condition` | `""` | Name of the status.conditions entry to wait for after applying AR/CAR; an empty string disables this additional check. |
| `k8s_configuration_config_deckhouse_mixed_backends` | `false` | Allows using backend: rbac and backend: deckhouse together in desired assignments. |
| `k8s_configuration_config_deckhouse_granular_roles` | `[]` | List of {name, scopes: [namespace, cluster]} entries defining permitted scopes for special d8:* and user-authz:* roles. |
| `k8s_configuration_config_deckhouse_controller_markers_labels` | `[]` | List of {key, value} labels identifying controller-generated objects; protects them from changes and supports excluding them from exports. |
| `k8s_configuration_config_deckhouse_controller_markers_annotations` | `[]` | List of {key, value} annotations identifying controller-generated objects; protects them from changes and supports excluding them from exports. |
| `k8s_configuration_config_deckhouse_controller_markers_name_prefixes` | `[]` | Object name prefixes identifying controller-generated resources; protects them from changes and supports excluding them from exports. |
| `k8s_configuration_config_management_owner` | `"ansible-access-manager"` | Owner identifier used in ownership labels and deterministic resource names. |
| `k8s_configuration_config_management_prune` | `false` | Deletes owned objects missing from explicitly provided desired-state sections, subject to safety limits. |
| `k8s_configuration_config_management_adoption` | `[]` | Explicit references including UID for adopting existing resources; does not permit deleting resources owned by others. |
| `k8s_configuration_config_management_label_domain` | `"access-manager.ansible.local"` | Domain for ownership labels; used to identify resources managed by this role. |
| `k8s_configuration_config_management_namespaces` | `null` | Limits management to these namespaces; null allows all namespaces, while an empty list excludes namespaced resources. |
| `k8s_configuration_config_management_include_cluster_scoped` | `true` | Allows managing resources without a namespace; false excludes them from the management scope. |
| `k8s_configuration_config_safety_max_deletions` | `10` | Maximum deletions per plan, including binding replacements; exceeding the limit blocks execution. |
| `k8s_configuration_config_safety_allow_empty_desired` | `false` | Allows pruning an explicitly empty desired-state section; otherwise clearing that section is blocked. |
| `k8s_configuration_config_safety_allow_binding_replacement` | `false` | Allows deleting and recreating a binding when its immutable roleRef changes. |
| `k8s_configuration_config_safety_protected_namespaces` | `["kube-system", "kube-public", "kube-node-lease", "default", "loghouse"]` | Namespace names in which resource changes and deletions are blocked, except for explicitly allowed exceptions. |
| `k8s_configuration_config_safety_protected_namespace_prefixes` | `["kube-", "d8-"]` | Namespace prefixes that block resource changes and deletions, except for explicitly allowed exceptions. |
| `k8s_configuration_config_safety_allowed_protected_namespaces` | `[]` | Exact namespace names exempt from name/prefix protection; other safety restrictions still apply. |
| `k8s_configuration_config_safety_protected_objects` | `[]` | References to resources that must not be changed or deleted; protects emergency and service access assignments. |
| `k8s_configuration_config_server_validation` | `false` | Enables server-side dry-run validation before a real apply; dry and Ansible check modes send no validation requests. |
| `k8s_configuration_config_wait_timeout_seconds` | `60` | Maximum wait in seconds for observing write results and Deckhouse resource readiness. |
| `k8s_configuration_config_expected_plan_digest` | `""` | Expected plan digest from dry; a nonempty value blocks apply if the computed plan differs. |

### Additional role settings

| Variable | Default | Purpose and usage |
| --- | --- | --- |
| `k8s_configuration_report_path` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml"` | Destination YAML path for the dry plan on the Ansible controller; must be nonempty. Ansible check only predicts the write. |
| `k8s_configuration_no_log` | `true` | Hides sensitive role task arguments and results in Ansible output; enabled by default. |
| `k8s_configuration_certificates` | `[]` | List of {name, content} entries containing resolved TLS material; ca_content, cert_content or key_content overrides the corresponding connection_*_content setting. |

### Grant schema

Grant fields: id, backend (rbac/deckhouse), subjects, scope; roleRef {kind, name} for rbac or accessLevel/options for Deckhouse. Optional state and target_name. Deterministic names incorporate owner/id/kind/namespace and a digest. target_name preserves original exported/adopted names and requires a single physical target.

Subjects: `{kind: User|Group, name}` or `{kind: ServiceAccount, name, namespace}`. Names are preserved literally, including case and prefixes. Use the email for a local Deckhouse User and spec.name for a Group. Subjects and exported grants no longer contain source.

Scope contains exactly one of cluster=true, nonempty namespaces, or nonempty namespace_selector {matchLabels, matchExpressions}. Selectors only work for Deckhouse CAR. CAR cluster scope additionally requires include_system_namespaces boolean. RBAC ClusterRoleBinding cannot exclude namespaces. RoleBinding references a Role in its namespace or a ClusterRole; ClusterRoleBinding references a ClusterRole only.

AR access levels: User, PrivilegedUser, Editor, Admin. CAR additionally supports ClusterEditor, ClusterAdmin, SuperAdmin. Options: allowScale and portForwarding, both default false. Referenced Deckhouse d8:/user-authz: granular role names/scopes must be explicitly approved by the profile.

Absent grants need id/backend/scope/state and optional target_name; subjects/roleRef are unnecessary. All deletion protections still apply.

### Active Directory / LDAP usernames

For an individual assignment, set `subjects.kind: User` and use the exact Kubernetes username in `subjects.name`, preserving case and prefixes. The role passes the name unchanged. LDAP/Dex/OIDC settings determine the resulting name; email, `DOMAIN\login` and `sAMAccountName` are not universal formats.

Run this command with the intended user's kubeconfig after authenticating through AD/LDAP:

```bash
kubectl auth whoami -o yaml
```

Use `status.userInfo.username`. An administrator's kubeconfig returns the administrator's identity instead.

For example, if the username is `ivan.petrov@example.org`:

```yaml
k8s_configuration_grants:
- id: ivan-read
  backend: rbac
  subjects:
  - {kind: User, name: ivan.petrov@example.org}
  roleRef: {kind: ClusterRole, name: view}
  scope: {namespaces: [development]}
```

The configured external provider handles authentication. The role creates the access assignment only; no AD account or local Deckhouse User is created or required for this assignment.

Sources: [kubectl auth whoami](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_auth/kubectl_auth_whoami/), [Kubernetes authentication](https://kubernetes.io/docs/reference/access-authn-authz/authentication/).

### Deckhouse capability checks

Discovery selects served API versions and verifies resource scope, CRD Established status and the selected version's schema/required fields for AR/CAR. Empty k8s_configuration_config_deckhouse_api_versions_* values enable automatic discovery; nonempty values pin an API version. CRD presence alone is not module readiness.

user-authz requires a Module with phase=Ready, EnabledByModuleManager=True and IsReady=True. ModuleConfig is optional; an existing spec.enabled=false blocks the run. Forbidden is not treated as absence. Module state and ModuleConfig presence/version are guarded again before apply. [Module status](https://deckhouse.io/products/kubernetes-platform/documentation/v1/architecture/module-development/run/)

CAR requiring multitenancy still needs explicit enableMultiTenancy=true in user-authz ModuleConfig. Absence never implies support; the role does not create ModuleConfig.

Ordinary runs rely on API/capability checks. ready_checks_user_authz provides optional extra {path, pointer, equals|minimum} probes; no fictitious user-authz-controller is assumed.

granular_roles is a list of {name, scopes: [namespace|cluster]}, replacing role→scopes maps. controller_markers_labels/annotations are {key,value} lists; name_prefixes is a string list. mixed_backends remains an explicit operator opt-in. authz_ready_condition defaults to empty; do not invent a Ready condition for unsupported CRDs.

### Export fields

Export fields: mode managed/scoped (managed), backends, cluster_roles, roles, access_levels, namespaces, include_cluster_scoped (true), exclude_controller_generated (true), allow_partial (false), destination (controller export.yml), optional audit_destination (controller export-audit.yml by default).

Scoped mode requires explicit role/access-level allowlists and captures manual objects. Managed mode also captures manual edits to owned objects. Empty namespaces imposes no namespace filter; cluster-scoped bindings are included unless explicitly disabled. CAR selectors are preserved whole.

The destination contains only `k8s_configuration_grants`, ready for vars_files/group_vars or insertion into inventory vars. Audit is written separately to audit_destination. Configure the destination cluster's kubeconfig/profile/owner separately. Namespaces and referenced roles/service accounts must already exist there.

Export contains only k8s_configuration_grants with access assignments. User/Group definitions, group memberships, passwords and hashes are never exported, including as dependencies. Subjects retain literal names. Files use mode 0600; namespace and Role/ClusterRole prerequisites must exist on the destination cluster.

Unsupported selected resources/dependencies block file creation by default. allow_partial=true explicitly permits an incomplete snapshot for review. target_name preserves original names; applying to unowned existing resources still requires UID-bound adoption. Export does not take ownership. Review empty sections before enabling prune.

### Secret sources

Ansible Vault, local files and optional HashiCorp Vault work through inventory variables. No lookup logic is embedded in tasks or the Python client. Example:

```yaml
example_vault_certificate_path: ""
example_local_certs_path: ./certs/
# Optional alternative, requires community.hashi_vault on the control node:
k8s_configuration_certificates:
  - name: ca_content
    content: >-
      {{ lookup('community.hashi_vault.hashi_vault', example_vault_certificate_path + ':ca')
         if example_vault_certificate_path | length > 0
         else lookup('file', example_local_certs_path + 'ca.pem') }}
```

Use cert_content/key_content similarly or keep paths in kubeconfig. Sensitive arguments, server error bodies and arbitrary exception details never enter public reports.

## Reconciliation and safety

Ownership labels use label_domain/owner, /managed-by=ansible, /section; annotations /grant-id and /schema-version. Never change owner/domain without a migration. Foreign/partial owners, protected objects and controller-generated resources are immutable to this role. Controller detection covers ownerReferences, Helm/Deckhouse markers, rbac.deckhouse.io/automated and explicit profile markers. Adoption cannot override another owner.

Reads use complete pagination. Before apply, cluster UID, observed objects, referenced roles, CRDs, module/probe versions and namespace labels are rechecked. PATCH uses UID/resourceVersion test operations; DELETE uses preconditions. Unknown permission fields block adoption/management. Foreign metadata is preserved; subject lists are authoritative. RoleRef changes require replacement opt-in and interrupt access. Finalizers are never forcibly removed.

Assignments are created and updated before stale assignments are deleted. Partial failures stop remaining pruning; completed/pending operations are returned. No automatic rollback. Backend migration creates before deleting and may overlap permissions.

Dry files contain add/change/remove and metadata (cluster_uid, cluster_version, owner, digest). Additions and removals are described once, without apiVersion/apiGroup or internal metadata. change.fields contains only changed before/after values; replacement: true marks replacement. adoption appears only for actual adoption. privilege_change was removed: the report does not assess effective privilege increases/decreases. An unchanged dry run has empty add/change/remove lists. Use matrix for permission analysis. The module diagnostic result and standard --diff retain before/after; the dry file is a concise projection. Digests exclude secrets; pin secret CI inputs separately.

Executor permissions: get/list bindings and namespaces, get referenced roles, create/patch/delete selected kinds plus assigned privileges or bind permission. Deckhouse also needs Module/ModuleConfig/CRD reads (Deployment for extra probes); matrices also list User/Group objects. Authorization objects are listed cluster-wide to detect dependencies, even with namespace-limited writes. Read failures block reconciliation. Protect executor and emergency bindings explicitly; the role never grants itself cluster-admin.

Tags: pre-req, install, ssl, config. No OS users or services are created. The module automatically removes temporary TLS files and kubectl caches. Revoke assignments with state: absent or prune; there is no clean task.

## Validation

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i roles/k8s-configuration/examples/inventory.ini roles/k8s-configuration/examples/playbook.yml --syntax-check
```

Transport tests require kubectl, openssl and loopback sockets. HTTPS integration executes the actual packaged Ansible role. Molecule default uses Docker with a prepared RED OS/Python 3.8/PyYAML/kubectl image and a separate real kind API, not CRD mocks. No privileged/systemd executor is needed. See README.md for exact cluster/image setup commands and tests/execution-environment/Dockerfile for the optional dependency image. Set KAM_TEST_KUBECONFIG and KAM_MOLECULE_IMAGE, then run molecule test from the role directory.

The dedicated kind fixture has three control-plane nodes. Tests cover real allowed/denied access, idempotence, export, roleRef replacement, deletion and restoration. tests/degradation.py stops one fixture node and always restarts it. tests/integration/deckhouse.yml requires an explicitly configured disposable Deckhouse cluster, its profile and inventory. Actual validation results and remaining environment limitations are recorded in VALIDATION.md.

## Rename migration

Use role `k8s-configuration` and variables prefixed `k8s_configuration_`; the custom module is k8s_configuration. Replace old k8s_access_manager variable names in inventory. Existing owner/domain labels and generated object names remain unchanged. Galaxy metadata uses the normalized name k8s_configuration.

## Execution placement

`hosts: redos8` executes the role and kubectl on that inventory host. `hosts: localhost` uses the Ansible controller; explicitly configured localhost must use ansible_connection: local. Kubeconfig, kubectl, auth plugins, TLS files and cluster-operation become apply to that execution host. Result files for dry/export/matrix are written on the Ansible controller without become.

With `hosts: all`, choose the host using `ansible-playbook -i inventory/hosts.ini playbook.yaml -l redos8` or `-l localhost`. Localhost must be included in the inventory and the original play hosts. Groups, lists, patterns and `hosts: "{{ target_host }}"` are supported: only the effective host count after --limit matters. A singleton group works without --limit; multiple effective hosts fail even with serial: 1. If no hosts match, Ansible skips the play before the role runs. Inventory groups still supply group_vars.

Commands use argv without a shell. GET/POST/DELETE use raw kubectl operations; updates use kubectl patch --type=json. Payloads and patches use stdin; arguments contain no tokens, keys or password hashes. UID/resourceVersion JSON Patch tests and DeleteOptions preconditions are preserved. Planning and bounded pruning remain in the role.

## Access matrix: mode: matrix

`matrix` reads cluster state through kubectl and writes `matrix.csv`, `bindings.csv` and `subjects.csv` on the Ansible controller. It sends GET requests only; no SubjectAccessReview or desired-state reconciliation. With source=cluster, desired grants are neither evaluated nor submitted. All bindings, including manual and controller-generated ones, are included by default.

```yaml
k8s_configuration_config_mode: matrix
k8s_configuration_config_platform: vanilla
k8s_configuration_config_connection_kubeconfig: /etc/ansible/cluster.yaml
k8s_configuration_config_connection_context: prod
k8s_configuration_matrix_output_dir: '{{ playbook_dir }}/output/{{ inventory_hostname }}'
k8s_configuration_matrix_source: cluster
k8s_configuration_matrix_scope: cluster
k8s_configuration_matrix_namespaces: []
k8s_configuration_matrix_include_cluster_scoped: true
k8s_configuration_matrix_subjects_users: true
k8s_configuration_matrix_subjects_groups: true
k8s_configuration_matrix_subjects_service_accounts: false
k8s_configuration_matrix_resolve_group_membership: true
k8s_configuration_matrix_memberships: []
k8s_configuration_matrix_csv_delimiter: ;
```

All options are optional. Defaults match this example except memberships=[]. The controller output directory defaults to playbook_dir/output/inventory_hostname. Unknown options fail validation. Delimiters: semicolon, comma or tab. A memberships entry accepts kind User or ServiceAccount (requiring namespace), name, groups and complete. A complete list replaces inferred Deckhouse membership; incomplete lists add known groups. Standard authentication/ServiceAccount groups always apply. This is an audit dictionary, not a cluster membership update.

matrix.csv begins with namespace, api_group, resource, resource_name, non_resource_url and action; subsequent columns are User:<username>, Group:<claim> and ServiceAccount:<namespace>/<name>. Empty api_group means core API; empty resource_name means all names, distinct from a literal '*' in resourceNames. Rows come from assigned rules; wildcard expansion uses discovery, without reading workloads or Secret contents.

For action=standard the fixed mask is **GLWCUPDX**:

| G | L | W | C | U | P | D | X |
| --- | --- | --- | --- | --- | --- | --- | --- |
| get | list | watch | create | update | patch | delete | deletecollection |

Uppercase means the subject is named directly in the binding; lowercase means access through known group membership. Direct grants win casing, while every source remains in bindings.csv. A dot means no grant in the selected RBAC with known membership; '?' means user membership is incomplete. Known positive grants remain letters. GLWcupd. means direct get/list/watch, inherited create/update/patch/delete and no deletecollection. Cluster-wide scope, role aggregation and controller generation do not determine casing.

Special verbs (bind, escalate, impersonate, approve, use, custom verbs) have separate action=<verb> rows with Y/y/./?. action=* preserves permission for all special verbs, including future ones. Symbolic resource wildcards are retained alongside concrete rows. Namespace <cluster> identifies cluster resources/URLs, '*' all namespaces, <all-scopes> a symbolic rule across scopes, <unknown> an undiscovered resource with unknown scope (warning).

RoleBinding stays within its namespace even when referencing ClusterRole. ClusterRoleBinding permissions expand into current namespaces and cluster resources. Namespace filters preserve applicable ClusterRoleBinding grants. include_cluster_scoped=false removes cluster resources/URLs, not namespaced grants from those bindings. resourceNames have separate rows, with broader grants projected onto them. Named list/watch require a matching metadata.name field selector. Name restrictions do not grant top-level create or deletecollection; named subresource create is included. Letters describe authorization rules, not HTTP endpoint support. [RBAC semantics](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

bindings.csv explains each source: subject, direct/inherited origin, via_group, scope, full verbs, binding/role, aggregationRule and Deckhouse owner-UID provenance. Observed rules of aggregated ClusterRoles are authoritative; future aggregation results are not fabricated. subjects.csv includes identity, known groups, membership_complete and information sources. Kubernetes has no complete external user/group registry. ServiceAccounts are listed from the API, merged with their canonical User alias, and assigned system:authenticated, system:serviceaccounts and system:serviceaccounts:<namespace>. system:anonymous uses system:unauthenticated. External User columns show direct grants only; local Deckhouse memberships are resolved from Kubernetes. [Authentication](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)

For platform=deckhouse, matrix discovers served APIs and reads User, Group, AuthorizationRule and ClusterAuthorizationRule. It requires no module readiness probes. User becomes email; Group becomes spec.name. Known nested groups are expanded; cycles/unresolved references fail. resolve_group_membership=false disables inferred Deckhouse membership while explicit memberships still work. Local Deckhouse Users become complete after resolving local group membership. This describes local authentication, not an external-provider token using the same username; disabling resolution leaves membership incomplete.

AR/CAR appear as deckhouse-declaration records, including original authorization parameters and selector-matched namespaces; permissions come only from actual RBAC. Generated bindings are linked only through owner UID. Unlinked declarations have reconciliation=unverified, without guessing from resource names. Linked scope/subject drift is flagged as linked-scope-or-subject-mismatch. linked-by-owner-uid establishes provenance, not complete reconciliation of declared permissions. Unsupported legacy namespace scope is preserved as declaration fields with an empty namespace list and warning.

Required permissions: GET discovery for every served API version; list namespaces, Role/ClusterRole/RoleBinding/ClusterRoleBinding; list ServiceAccount when enabled; list the four Deckhouse kinds for that platform. Discovery/read errors and dangling roleRef fail before writing files; previous report files remain untouched. scope=managed includes only owned bindings and explicitly warns about omitted grants, including unowned controller-generated bindings. management.namespaces/safety do not limit the audit; use k8s_configuration_matrix_namespaces.

New controller directories use mode 0700 and files 0600; existing directory permissions are preserved. CSV uses UTF-8 without BOM, LF, deterministic sorting, CSV quoting and spreadsheet formula protection (leading apostrophe). No password hashes/tokens enter reports. --diff never shows CSV contents. Repeated unchanged runs are idempotent. --check still reads the cluster and previews filesystem changes without writing files. Files are already on the controller; no fetch step is needed.

This is a sequential RBAC snapshot with known membership, not an atomic snapshot or login test. Existing tokens may carry stale claims. Webhook/Node/ABAC, system:masters authorization bypass, admission and indirect privilege escalation are outside the calculation. SAR verification is not part of the role.

### Matrix filters

Defaults hide `system:*` users/groups, all ServiceAccount columns and system namespaces. System namespaces are `kube-system`, `kube-public`, `kube-node-lease`, plus `d8-*` for Deckhouse. `default` remains an application namespace. Override `k8s_configuration_matrix_system_namespaces` and `k8s_configuration_matrix_system_subjects` to replace this classification.

All variables below use the `k8s_configuration_matrix_` prefix:

| Variable suffix | Default | Meaning |
| --- | --- | --- |
| `namespace_mode` | `application` | Namespace selection: application excludes system namespaces, system selects system namespaces, all includes both. |
| `system_namespaces` | See above | Names and glob patterns identifying system namespaces; defaults include standard Kubernetes namespaces and d8-* on Deckhouse. |
| `namespaces` | `[]` | Exact namespace names for the matrix; an empty list imposes no restriction, and a missing namespace causes an error. |
| `namespace_include` | `[]` | Namespace names and glob patterns to include; an empty list adds no restriction, and other filters still apply. |
| `namespace_exclude` | `[]` | Namespace names and glob patterns to exclude after inclusion filters have been applied. |
| `include_system_subjects` | `false` | Includes system users and groups identified by matrix_system_subjects, subject to other filters. |
| `include_external_users` | `false` | Includes users without a local Deckhouse User; their columns show direct assignments only, without inherited group permissions. |
| `system_subjects` | `['system:*']` | Names and glob patterns identifying system users and groups for include_system_subjects; defaults to system:*. |
| `users_include` | `[]` | Names and glob patterns of users to include; uses email on Deckhouse. An empty list imposes no restriction. |
| `users_exclude` | `[]` | Names and glob patterns of users to exclude; uses email on Deckhouse. |
| `groups_include` | `[]` | Names and glob patterns of groups to include; uses spec.name on Deckhouse. An empty list imposes no restriction. |
| `groups_exclude` | `[]` | Names and glob patterns of groups to exclude; uses spec.name on Deckhouse. |
| `subjects_service_accounts` | `false` | Includes ServiceAccount columns and reads their API collection, subject to other filters. |
| `service_accounts_include` | `[]` | Names and glob patterns of ServiceAccounts to include, in namespace/name format; an empty list imposes no restriction. |
| `service_accounts_exclude` | `[]` | Names and glob patterns of ServiceAccounts to exclude, in namespace/name format. |
| `service_account_namespaces_include` | `[]` | Names and glob patterns of ServiceAccount namespaces used to select columns; an empty list imposes no restriction. |
| `service_account_namespaces_exclude` | `[]` | Names and glob patterns of ServiceAccount namespaces whose columns are excluded. |
| `omit_empty_rows` | `true` | Removes rows whose visible cells contain only dots; rows with unknown permissions (?) remain. |
| `exclude_broad_subjects` | `true` | Excludes subjects with wildcard apiGroups/resources and no resourceNames restriction, plus known inheriting subjects; external Users are checked only for direct grants. |

By default, `k8s_configuration_matrix_exclude_broad_subjects: true` removes groups, users and enabled ServiceAccounts with broad grants: a rule contains apiGroups=["*"] and resources=["*"], with absent/empty resourceNames. Any verbs qualify, including read-only get/list/watch. Grants must apply within the report scope: a ClusterRoleBinding or a RoleBinding in at least one selected namespace. Even an administrator of just one selected namespace is excluded entirely.

Known local group members, ServiceAccounts and nested groups are also excluded; external Users are checked against direct grants only; unknown external memberships are not inferred. Role names such as cluster-admin are not criteria. Named-resource restrictions, a resource wildcard within a specific API group, and enumerated resource lists do not qualify automatically. This detects explicit wildcard grants, not every possible administrative capability.

Excluded subjects' rules do not seed matrix rows; otherwise those rows would remain as '?' for other users with incomplete membership. All grants of those subjects, including narrow ones, are removed from report sources. Other hidden groups still contribute inherited grants. Summary fields excluded_broad_subjects and excluded_broad_subject_names cover all detected broad subjects, including those already hidden by other filters. Set k8s_configuration_matrix_exclude_broad_subjects=false to restore broad subjects and their rows; other filters still apply.

Local Deckhouse User/Group membership is read from Kubernetes on each run, including nested groups and legacy User.spec.groups; emails are normalized to lowercase. With resolve_group_membership=true, local membership is complete without an inventory dictionary. Failed reads, cycles, unresolved references or ambiguous emails/claims stop the report. Disabling resolution leaves local User memberships incomplete.

include_external_users=false hides external User columns and prevents their direct User rules from seeding rows. External group columns remain without inferring LDAP members. Vanilla User identities are all external. Explicitly enable the option to audit direct User bindings; only direct grants are shown using uppercase letters and dots. This setting affects matrix only, not apply/export. excluded_external_users counts omitted external User identities.

Globs are case sensitive (`*`, `?`, `[abc]`), not regexes. An empty include imposes no restriction. Filters intersect; exclude wins over include. Explicit inclusion does not bypass system filters: select namespace_mode=system or all for kube-system. A glob matching nothing is valid and may produce a header-only CSV.

Hidden groups still contribute inherited permissions to local Deckhouse Users and ServiceAccounts, including system:authenticated. Resource namespace filters are independent of ServiceAccount namespace filters. include_cluster_scoped controls cluster resources/URLs independently. Unknown-scope resources remain <unknown> with a warning. With namespace restrictions, symbolic */<all-scopes> rows expand only to selected namespaces and, when enabled, <cluster>.

Rows containing '?' remain even without known positive grants. Supply confirmed complete memberships to reduce unknowns; never mark an unverified group list complete merely to shrink a report.

subjects.csv contains selected columns only. RBAC records in bindings.csv explain selected subjects/rows and retain hidden group names as inheritance sources. AR/CAR declarations are selected by relevant subjects (including groups of visible subjects) and namespace; resolved_namespaces is restricted to the selection. Original declaration parameters remain intact and do not represent calculated permissions.

The summary exposes filters, selected_namespaces, excluded_namespaces, excluded_subjects and omitted_empty_rows. Subject counts cover identities discovered within audit scope, not a complete external identity registry. Filters restrict the report; discovery/RBAC reads still require cluster-wide permissions. A warning identifies filtered reports.

Regular users/groups accessing system namespaces:

```yaml
k8s_configuration_matrix_namespace_mode: system
k8s_configuration_matrix_include_cluster_scoped: false
```

Organization users in project namespaces:

```yaml
k8s_configuration_matrix_namespace_include: [project-*]
k8s_configuration_matrix_namespace_exclude: [project-archive]
k8s_configuration_matrix_users_include: ['*@example.org']
k8s_configuration_matrix_users_exclude: [bot-*]
k8s_configuration_matrix_subjects_groups: false
```

For a full selection including system identities, use namespace_mode=all, include_system_subjects=true, include_external_users=true, subjects_service_accounts=true, omit_empty_rows=false, exclude_broad_subjects=false; clear namespaces and all include/exclude lists, keep scope=cluster and include_cluster_scoped=true.


### Flat export and matrix defaults

| Variable | Default | Purpose and usage |
| --- | --- | --- |
| `k8s_configuration_export_mode` | `"managed"` | Export scope: managed selects owned assignments; scoped selects assignments by the configured roles and accessLevel lists. |
| `k8s_configuration_export_backends` | `["rbac", "deckhouse"]` | Assignment backends to export: rbac and/or deckhouse. |
| `k8s_configuration_export_cluster_roles` | `[]` | ClusterRole names used to select RBAC assignments in scoped export mode; role definitions are not exported. |
| `k8s_configuration_export_roles` | `[]` | List of {namespace, name} entries selecting Role assignments in scoped export mode; role definitions are not exported. |
| `k8s_configuration_export_access_levels` | `[]` | accessLevel values used to select AR/CAR assignments in scoped export mode. |
| `k8s_configuration_export_namespaces` | `[]` | Exact namespace names for exporting namespaced assignments; an empty list imposes no namespace restriction. |
| `k8s_configuration_export_include_cluster_scoped` | `true` | Includes assignments without a namespace in exports, independently of export_namespaces. |
| `k8s_configuration_export_exclude_controller_generated` | `true` | Excludes controller-generated objects from exports, using ownerReferences and configured markers for detection. |
| `k8s_configuration_export_allow_partial` | `false` | Allows a partial export when some assignments cannot be imported; limitations are recorded in the separate audit. |
| `k8s_configuration_export_destination` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml"` | Destination YAML path for exported assignments on the Ansible controller; relative paths resolve against playbook_dir. |
| `k8s_configuration_export_audit_destination` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml"` | Separate export-audit YAML path on the Ansible controller; an empty string disables saving the audit. |

| Variable | Default | Purpose and usage |
| --- | --- | --- |
| `k8s_configuration_matrix_output_dir` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}"` | Directory for the three matrix CSV files on the Ansible controller; relative paths resolve against playbook_dir. |
| `k8s_configuration_matrix_scope` | `"cluster"` | Assignment scope: cluster includes all bindings; managed includes only bindings labeled for the configured role owner. |
| `k8s_configuration_matrix_namespaces` | `[]` | Exact namespace names for the matrix; an empty list imposes no restriction, and a missing namespace causes an error. |
| `k8s_configuration_matrix_include_cluster_scoped` | `true` | Includes cluster-resource and URL rows; false retains namespaced permissions, including those granted by ClusterRoleBinding. |
| `k8s_configuration_matrix_subjects_users` | `true` | Includes user columns in the matrix, subject to other subject filters. |
| `k8s_configuration_matrix_subjects_groups` | `true` | Includes group columns; hidden groups may still contribute inherited permissions. |
| `k8s_configuration_matrix_subjects_service_accounts` | `false` | Includes ServiceAccount columns and reads their API collection, subject to other filters. |
| `k8s_configuration_matrix_resolve_group_membership` | `true` | Enables reading Deckhouse Group membership for inherited permissions; explicit matrix_memberships still apply when false. |
| `k8s_configuration_matrix_memberships` | `[]` | User/ServiceAccount group-membership dictionary for the report; groups and complete are required. complete: true replaces inferred membership, false extends it. |
| `k8s_configuration_matrix_csv_delimiter` | `";"` | Single-character field separator for all three matrix CSV files; defaults to a semicolon. |
| `k8s_configuration_matrix_source` | `cluster` | Assignment source: cluster reads live bindings; inventory uses inventory grants and current role definitions from the API. |
| `k8s_configuration_matrix_filename` | `"{{ 'matrix-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'matrix.csv' }}"` | Permission-matrix CSV filename within matrix_output_dir; defaults to matrix.csv or matrix-inventory.csv depending on matrix_source. |
| `k8s_configuration_matrix_bindings_filename` | `"{{ 'bindings-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'bindings.csv' }}"` | Permission-source CSV filename within matrix_output_dir; defaults to bindings.csv or bindings-inventory.csv depending on matrix_source. |
| `k8s_configuration_matrix_subjects_filename` | `"{{ 'subjects-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'subjects.csv' }}"` | Subject-details CSV filename within matrix_output_dir; defaults to subjects.csv or subjects-inventory.csv depending on matrix_source. |
| `k8s_configuration_matrix_namespace_mode` | `application` | Namespace selection: application excludes system namespaces, system selects system namespaces, all includes both. |
| `k8s_configuration_matrix_system_namespaces` | `"{{ ['kube-system', 'kube-public', 'kube-node-lease'] + (['d8-*'] if k8s_configuration_config_platform == 'deckhouse' else []) }}"` | Names and glob patterns identifying system namespaces; defaults include standard Kubernetes namespaces and d8-* on Deckhouse. |
| `k8s_configuration_matrix_namespace_include` | `[]` | Namespace names and glob patterns to include; an empty list adds no restriction, and other filters still apply. |
| `k8s_configuration_matrix_namespace_exclude` | `[]` | Namespace names and glob patterns to exclude after inclusion filters have been applied. |
| `k8s_configuration_matrix_include_system_subjects` | `false` | Includes system users and groups identified by matrix_system_subjects, subject to other filters. |
| `k8s_configuration_matrix_include_external_users` | `false` | Includes users without a local Deckhouse User; their columns show direct assignments only, without inherited group permissions. |
| `k8s_configuration_matrix_system_subjects` | `['system:*']` | Names and glob patterns identifying system users and groups for include_system_subjects; defaults to system:*. |
| `k8s_configuration_matrix_users_include` | `[]` | Names and glob patterns of users to include; uses email on Deckhouse. An empty list imposes no restriction. |
| `k8s_configuration_matrix_users_exclude` | `[]` | Names and glob patterns of users to exclude; uses email on Deckhouse. |
| `k8s_configuration_matrix_groups_include` | `[]` | Names and glob patterns of groups to include; uses spec.name on Deckhouse. An empty list imposes no restriction. |
| `k8s_configuration_matrix_groups_exclude` | `[]` | Names and glob patterns of groups to exclude; uses spec.name on Deckhouse. |
| `k8s_configuration_matrix_service_accounts_include` | `[]` | Names and glob patterns of ServiceAccounts to include, in namespace/name format; an empty list imposes no restriction. |
| `k8s_configuration_matrix_service_accounts_exclude` | `[]` | Names and glob patterns of ServiceAccounts to exclude, in namespace/name format. |
| `k8s_configuration_matrix_service_account_namespaces_include` | `[]` | Names and glob patterns of ServiceAccount namespaces used to select columns; an empty list imposes no restriction. |
| `k8s_configuration_matrix_service_account_namespaces_exclude` | `[]` | Names and glob patterns of ServiceAccount namespaces whose columns are excluded. |
| `k8s_configuration_matrix_omit_empty_rows` | `true` | Removes rows whose visible cells contain only dots; rows with unknown permissions (?) remain. |
| `k8s_configuration_matrix_exclude_broad_subjects` | `true` | Excludes subjects with wildcard apiGroups/resources and no resourceNames restriction, plus known inheriting subjects; external Users are checked only for direct grants. |


CSV filenames:

- `k8s_configuration_matrix_filename`: `matrix.csv`.
- `k8s_configuration_matrix_bindings_filename`: `bindings.csv`.
- `k8s_configuration_matrix_subjects_filename`: `subjects.csv`.


Matrix boolean switches accept YAML booleans and CLI key=value values, for example `-e k8s_configuration_matrix_include_external_users=true`. The role normalizes strings before schema validation. Typed JSON extra-vars also work: `-e '{"k8s_configuration_matrix_include_external_users": true}'`.

External Users show direct grants only when include_external_users is enabled: uppercase letters and dots, with no inherited grants or question marks. A dot means no direct assignment, not denial of group-based access. A User is local when its subject name matches the normalized spec.email of a discovered Deckhouse User. All vanilla Users are external. subjects.csv adds rights_basis: direct_only for external Users, direct_and_groups for other subjects. membership_complete still describes knowledge of membership, not the calculation mode. Explicit memberships do not enable inheritance for external Users. Their bindings.csv records contain only direct sources.


The role no longer accepts access_checks or runs SubjectAccessReview during apply or before prune. Inspect actual role-based permissions with matrix. No additional post-apply binding checks were added.

Subject migration: remove source. Replace former static User references with their email and static Group references with spec.name; existing external/ServiceAccount names stay unchanged. Local User/Group management has been removed; manage identities outside this role.

Inventory exports use compact YAML: each subject is a flow mapping, roleRef and scope are flow mappings. The parsed inventory schema is unchanged.

The example_* lookup variables belong to inventory and are defined in the example; they are not role parameters. The role receives resolved values through k8s_configuration_certificates and connection_*_content.

Mixed authorization warnings list the relevant subject and concrete RBAC and Deckhouse bindings; unrelated cluster subjects are not listed.

### Inventory assignment matrix

Set k8s_configuration_config_mode=matrix and k8s_configuration_matrix_source=inventory. The default source=cluster audits current bindings. Inventory mode uses only k8s_configuration_grants and current Role/ClusterRole rules from the API; it does not read or include live bindings. Explicit grants are required; [] is an empty set. Namespace RoleBindings, ClusterRoleBindings and omitted state: absent assignments are supported. Missing roles/namespaces fail before files are written. Aggregated roles use currently observed rules.

Local Deckhouse membership still comes from live User/Group collections; identity definitions from inventory are not accepted. Existing filters, masks, direct-only external User columns and local group inheritance apply. Enable k8s_configuration_matrix_include_external_users for external User columns. summary.source, subjects.csv inventory-binding provenance and bindings.csv record_type=inventory-rbac identify the source.

Default controller filenames are matrix-inventory.csv, bindings-inventory.csv and subjects-inventory.csv; explicit filename variables override them. This is permissions from the inventory assignments only, not complete effective access after apply. Other bindings, prune/adoption/deletion guards, future role aggregation are excluded. Use dry to validate the apply plan. GET-only; --check writes no reports.

Inventory mode currently supports backend: rbac on vanilla and Deckhouse. Native Deckhouse AR/CAR requests fail clearly because accessLevel has no direct roleRef and controller-generated permissions cannot be inferred safely. Audit those through source=cluster after apply.
