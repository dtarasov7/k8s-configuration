# k8s-configuration

Ansible role managing Kubernetes and Deckhouse authorization through HTTPS REST. Supports dry/apply/export, check/diff, UID-bound adoption, bounded pruning, local Deckhouse User/Group and basic authorization resources. Runtime does not depend on kubernetes.core, Kubernetes SDK or kubectl.

Vanilla Kubernetes identities remain external. The role does not create LDAP/OIDC identities, certificates, namespaces, Role/ClusterRole definitions, service accounts or tokens. It references existing roles and identities.

## Requirements and example

Execution host: Python 3.8+, PyYAML, kubeconfig, network access and appropriate API permissions. Control node: ansible-core 2.12+ with its supported Python version. Install dependencies separately; see requirements-legacy.txt and requirements-modern.txt. The legacy 2.12 branch is EOL. Use one execution host and serialize runs per cluster/owner.

```yaml
# inventory.yml
all:
  hosts:
    access_executor:
      ansible_connection: local
      ansible_python_interpreter: /usr/bin/python3
```

```yaml
- name: Manage access
  hosts: access_executor
  gather_facts: false
  vars:
    k8s_configuration_config:
      mode: dry
      platform: vanilla
      connection:
        kubeconfig: /etc/ansible/cluster.yaml
        context: prod
      management:
        owner: platform
        namespaces: [development]
        include_cluster_scoped: false
    k8s_configuration_grants:
      - id: readers
        backend: rbac
        subjects:
          - kind: Group
            source: external
            name: oidc:readers
        roleRef:
          kind: ClusterRole
          name: view
        scope:
          namespaces: [development]
  roles:
    - role: k8s-configuration
```

```bash
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml --check --diff
```

Modes are dry (default), apply, export. Dry independently reads and reports planned additions, changes and removals with changed=false. Apply --check predicts changes without writes; --diff shows sanitized before/after. Export --check still exports, previewing the file write without creating it. Export hashes stay hidden from diff. The old plan spelling remains a compatibility alias. Server validation runs only during real apply.

## Public variables

| Variable | Default and meaning |
| --- | --- |
| k8s_configuration_config | Main configuration below |
| k8s_configuration_users | Undefined: leave section unmanaged; local Deckhouse Users |
| k8s_configuration_groups | Undefined: leave section unmanaged; local Deckhouse Groups |
| k8s_configuration_grants | Undefined: leave section unmanaged; authorization assignments |
| k8s_configuration_export | `{destination: ./k8s-configuration-export.yml}`, export configuration below |
| k8s_configuration_report_path | Empty; optional sanitized report path on execution host |
| k8s_configuration_no_log | true; hide full result except sanitized --diff; export is always hidden |
| k8s_configuration_certificates | `[]`; pre-resolved `{name, content}` TLS entries, supported names ca_content/cert_content/key_content |
| k8s_configuration_hashi_vault_path | Empty; optional Vault lookup path used in inventory variables |
| k8s_configuration_hashi_vault_path_password | Empty; optional password-secret lookup path |
| k8s_configuration_local_certs_path | `./certs/`, optional local lookup base |
| k8s_configuration_result | Registered result; export includes sensitive bcrypt inventory, keep private |

Undefined sections are not pruned; explicitly empty sections represent empty desired state. Pruning them additionally requires allow_empty_desired. Unknown input fields fail validation. Config dictionaries receive internal defaults regardless of Ansible hash_behaviour.

### Configuration fields

| Field | Default / contract |
| --- | --- |
| schema_version | 1 |
| mode | dry/apply/export; default dry |
| platform | vanilla/deckhouse; default vanilla |
| connection.kubeconfig | Required execution-host file |
| connection.context | kubeconfig current-context |
| connection.validate_tls | true; insecure kubeconfig requires explicit false |
| connection.timeout_seconds | 30, range 1..3600 |
| connection.retries | 2, range 0..5; bounded retries for GET |
| connection.ca_content/cert_content/key_content | Optional PEM overrides |
| management.owner | ansible-access-manager, Kubernetes label value |
| management.label_domain | access-manager.ansible.local; keep fixed after first apply |
| management.prune | false |
| management.prune_identities | false; also required for explicit absent User/Group |
| management.adoption | `[]`; exact group/resource/namespace?/name/uid references |
| management.namespaces | null: all; otherwise restrict writes and pruning to listed namespaces |
| management.include_cluster_scoped | true; false also excludes User/Group management |
| safety.max_deletions | 10, including replacements |
| safety.allow_empty_desired | false |
| safety.allow_binding_replacement | false |
| safety.protected_namespaces | kube-system, kube-public, kube-node-lease, default, loghouse |
| safety.protected_namespace_prefixes | kube-, d8- |
| safety.allowed_protected_namespaces | `[]`; exact exceptions |
| safety.protected_objects | `[]`; exact group/resource/namespace?/name references |
| deckhouse.basic_authz | false |
| deckhouse.compatibility_profile | Required profile name for Deckhouse |
| deckhouse.profiles | `{}`; operator-supplied version-specific profiles |
| server_validation | false; explicitly enables dryRun=All POST/PATCH before apply only |
| wait_timeout_seconds | 60; deletion, readiness and access-check timeout |
| expected_plan_digest | Optional fail-on-drift plan digest |
| access_checks | `[]`; SubjectAccessReview checks after apply |

Kubeconfig supports token, rotating tokenFile and certificate/key paths or data. Relative paths resolve against kubeconfig. One context/file only; no exec/auth-provider, OIDC refresh, basic auth, proxy-url, tls-server-name, extensions or impersonation. Redirects are forbidden. TLS content uses private 0600 temporary files in a 0700 directory and is cleaned in finally.

### Identity and grant schemas

User fields: name, source=static, email (lowercase), optional password_hash (raw bcrypt), password_policy (on_create or managed), allow_collision (false), state (present or absent). A new User requires a hash. on_create preserves an existing password; managed requires a hash and profile.password_updates=true. No TTL, UserOperation, 2FA reset or session revocation.

Group fields: name, source=static, claim_name, members (complete list of present inventory User names), optional allow_collision/state. Nested groups are unsupported. Explicit allow_collision sets the Deckhouse collision annotation for that identity only.

Grant fields: id, backend (rbac/deckhouse), subjects, scope; roleRef {kind, name} for rbac or accessLevel/options for Deckhouse. Optional state and target_name. Deterministic names incorporate owner/id/kind/namespace and a digest. target_name preserves original exported/adopted names and requires a single physical target.

Subjects: `{kind: User|Group, source: external|static, name}` or `{kind: ServiceAccount, source: serviceaccount, name, namespace}`. Static references resolve to local email/claim_name; external names are preserved exactly. Source is not part of Kubernetes identity and does not isolate matching claim strings.

Scope contains exactly one of cluster=true, nonempty namespaces, or nonempty namespace_selector {matchLabels, matchExpressions}. Selectors only work for Deckhouse CAR. CAR cluster scope additionally requires include_system_namespaces boolean. RBAC ClusterRoleBinding cannot exclude namespaces. RoleBinding references a Role in its namespace or a ClusterRole; ClusterRoleBinding references a ClusterRole only.

AR access levels: User, PrivilegedUser, Editor, Admin. CAR additionally supports ClusterEditor, ClusterAdmin, SuperAdmin. Options: allowScale and portForwarding, both default false. Referenced Deckhouse d8:/user-authz: granular role names/scopes must be explicitly approved by the profile.

Absent identities need name/source/state. Absent grants need id/backend/scope/state and optional target_name; subjects/roleRef are unnecessary. All deletion protections still apply.

### Deckhouse profiles

No production profile is pre-approved because the target Deckhouse version/edition was not supplied. Operators must validate a profile on their test cluster. See the full YAML example in README.md; field names and schemas are identical in both languages.

Required profile fields:

- deckhouse_image: exact image string of d8-system/deckhouse Deployment; readiness and observedGeneration are checked.
- api_versions: explicit User, Group, AuthorizationRule and ClusterAuthorizationRule versions (deckhouse.io/v1 or v1alpha1), verified using discovery and served CRD schemas.
- mixed_backends: boolean acknowledging tested mixed basic/RBAC semantics.
- ready_checks: user-authz and, when identities/export are involved, user-authn probe lists. A probe has GET path, JSON pointer and exactly one of equals/minimum.

Optional profile fields: authz_ready_condition (e.g. Ready; observed generation is checked), password_updates (false), granular_roles mapping role names to [namespace, cluster] allowed scopes, controller_markers {labels, annotations, name_prefixes}. Without an authz Ready condition, basic grants require explicit positive access_checks.

ModuleConfig must be readable and not explicitly disabled; absent ModuleConfig fails closed. Probes must prove module readiness even if CRDs remain installed. CAR requires verified enableMultiTenancy=true, including cluster scope. Selectors that currently match protected namespaces fail; future label changes can expand their reach. Namespace lists provide a more predictable boundary.

Access checks are config.access_checks entries with user, optional groups, resourceAttributes, allowed. resourceAttributes supports namespace/verb/group/version/resource/subresource/name; verb/resource are required. Supply group claims explicitly: SAR does not query IdP membership. Positive and negative checks require permission to create SubjectAccessReview. Positive checks also run before stale pruning. All checks execute after apply, including noop, and never during plan/check.

### Export fields

Export fields: mode managed/scoped (managed), backends, cluster_roles, roles, access_levels, namespaces, include_cluster_scoped (true), exclude_controller_generated (true), include_identities (true), allow_partial (false), destination (`./k8s-configuration-export.yml`), optional audit_destination.

Scoped mode requires explicit role/access-level allowlists and captures manual objects. Managed mode also captures manual edits to owned objects. Empty namespaces imposes no namespace filter; cluster-scoped bindings are included unless explicitly disabled. CAR selectors are preserved whole.

The destination contains only `k8s_configuration_users`, `k8s_configuration_groups`, `k8s_configuration_grants`, ready for vars_files/group_vars or insertion into inventory vars. Audit is written separately to audit_destination. Configure the destination cluster's kubeconfig/profile/owner separately. Namespaces and referenced roles/service accounts must already exist there.

Standalone selected User/Group resources and grant dependencies are included. Local User bcrypt hashes are exported as password_hash to allow recreation on another cluster. They are never printed to stdout, audit or diff; export tasks always use no_log and private 0600 files. Encrypt files containing hashes with Ansible Vault before committing them. Tokens, client keys and sessions are excluded.

Unsupported selected resources/dependencies block file creation by default. allow_partial=true explicitly permits an incomplete snapshot for review. target_name preserves original names; applying to unowned existing resources still requires UID-bound adoption. Export does not take ownership. Review empty sections before enabling prune.

### Secret sources

Ansible Vault, local files and optional HashiCorp Vault work through inventory variables. No lookup logic is embedded in tasks or the Python client. Example:

```yaml
k8s_configuration_hashi_vault_path: ""
k8s_configuration_hashi_vault_path_password: secret=team/data/k8s-users
vault_jane_bcrypt: "{{ lookup('file', 'private/jane.bcrypt') | trim }}"
# Optional alternative, requires community.hashi_vault on the control node:
# vault_jane_bcrypt: "{{ lookup('community.hashi_vault.hashi_vault', k8s_configuration_hashi_vault_path_password + ':jane') }}"
k8s_configuration_certificates:
  - name: ca_content
    content: >-
      {{ lookup('community.hashi_vault.hashi_vault', k8s_configuration_hashi_vault_path + ':ca')
         if k8s_configuration_hashi_vault_path | length > 0
         else lookup('file', k8s_configuration_local_certs_path + 'ca.pem') }}
```

Use cert_content/key_content similarly or keep paths in kubeconfig. Password salts/hashes are not regenerated during apply. Sensitive arguments, server error bodies and arbitrary exception details never enter public reports.

## Reconciliation and safety

Ownership labels use label_domain/owner, /managed-by=ansible, /section; annotations /grant-id and /schema-version. Never change owner/domain without a migration. Foreign/partial owners, protected objects and controller-generated resources are immutable to this role. Controller detection covers ownerReferences, Helm/Deckhouse markers, rbac.deckhouse.io/automated and explicit profile markers. Adoption cannot override another owner.

Reads use complete pagination. Before apply, cluster UID, observed objects, referenced roles, CRDs, module/probe versions and namespace labels are rechecked. PATCH uses UID/resourceVersion test operations; DELETE uses preconditions. Unknown permission fields block adoption/management. Foreign metadata is preserved; subject/member lists are authoritative. RoleRef changes require replacement opt-in and interrupt access. Finalizers are never forcibly removed.

Order: users, groups, grants, stale grants, groups, users. Partial failures stop remaining pruning; completed/pending operations are returned. No automatic rollback. Backend migration creates before deleting and may overlap permissions. Identity deletion checks remaining API references but does not revoke sessions or existing tokens.

Plans report before/after, counts, digest and conservative privilege_change (increase for create, decrease for delete, unknown otherwise). Password changes reveal only a flag. Digests exclude secrets; pin secret CI inputs separately. Server dry-run does not prove controller convergence and cannot completely validate replacement before deletion.

Executor permissions: get/list bindings and namespaces, get referenced roles, create/patch/delete selected kinds plus assigned privileges or bind permission. Deckhouse also needs Deployment/ModuleConfig/CRD reads and identity list access. Authorization objects are listed cluster-wide to detect dependencies, even with namespace-limited writes. Read failures block reconciliation. Protect executor and emergency bindings explicitly; the role never grants itself cluster-admin.

Tags: pre-req, install, user, ssl, config; clean is opt-in, ends the play and does not delete cluster access or reports. No OS users/services are created. Temporary TLS files are cleaned automatically.

## Validation

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i roles/k8s-configuration/examples/inventory.yml roles/k8s-configuration/examples/playbook.yml --syntax-check
```

Transport tests require openssl and loopback sockets. HTTPS integration executes the actual packaged Ansible role. Molecule default uses Docker with a prepared RED OS/Python 3.8/PyYAML image and a separate real kind API, not CRD mocks. No privileged/systemd executor is needed. See README.md for exact cluster/image setup commands and tests/execution-environment/Dockerfile for the optional dependency image. Set KAM_TEST_KUBECONFIG and KAM_MOLECULE_IMAGE, then run molecule test from the role directory.

The dedicated kind fixture has three control-plane nodes. Tests cover real allowed/denied access, idempotence, export, roleRef replacement, deletion and restoration. tests/degradation.py stops one fixture node and always restarts it. tests/integration/deckhouse.yml requires an explicitly configured disposable Deckhouse cluster, its profile, inventory and positive/negative access checks. Actual validation results and remaining environment limitations are recorded in VALIDATION.md.

## Rename migration

Use role `k8s-configuration` and variables prefixed `k8s_configuration_`; the custom module is k8s_configuration. Replace old k8s_access_manager variable names in inventory. Existing owner/domain labels and generated object names remain unchanged. Galaxy metadata uses the normalized name k8s_configuration.
