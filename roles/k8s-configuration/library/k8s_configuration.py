#!/usr/bin/python
# -*- coding: utf-8 -*-
"""EN: Dispatch Ansible modes through the kubectl-based access manager.
RU: Выполнять режимы Ansible через управление доступом на базе kubectl.
"""
DOCUMENTATION = r"""
---
module: k8s_configuration
short_description: Plan, apply, export and audit Kubernetes and Deckhouse access
version_added: "1.0.0"
description:
  - Manage owned primary authorization resources through kubectl.
  - User and Group objects are read only for matrices; identity lifecycle and passwords are not managed.
  - Dry mode reads the cluster and returns a plan without changes.
  - Matrix mode returns cluster or inventory RBAC assignments with current cluster role rules as CSV strings.
  - Check mode previews apply, export and matrix without writing resources or files.
options:
  config_schema_version:
    description: Flat role setting k8s_configuration_config_schema_version.
    type: int
  config_mode:
    description: Flat role setting k8s_configuration_config_mode.
    type: str
  config_platform:
    description: Flat role setting k8s_configuration_config_platform.
    type: str
  config_connection_kubectl:
    description: Flat role setting k8s_configuration_config_connection_kubectl.
    type: str
  config_connection_validate_tls:
    description: Flat role setting k8s_configuration_config_connection_validate_tls.
    type: bool
  config_connection_timeout_seconds:
    description: Flat role setting k8s_configuration_config_connection_timeout_seconds.
    type: int
  config_connection_retries:
    description: Flat role setting k8s_configuration_config_connection_retries.
    type: int
  config_connection_kubeconfig:
    description: Flat role setting k8s_configuration_config_connection_kubeconfig.
    type: str
  config_connection_context:
    description: Flat role setting k8s_configuration_config_connection_context.
    type: str
  config_connection_ca_content:
    description: Flat role setting k8s_configuration_config_connection_ca_content.
    type: str
  config_connection_cert_content:
    description: Flat role setting k8s_configuration_config_connection_cert_content.
    type: str
  config_connection_key_content:
    description: Flat role setting k8s_configuration_config_connection_key_content.
    type: str
  config_deckhouse_basic_authz:
    description: Flat role setting k8s_configuration_config_deckhouse_basic_authz.
    type: bool
  config_deckhouse_api_versions_authorization_rule:
    description: Flat role setting k8s_configuration_config_deckhouse_api_versions_authorization_rule.
    type: str
  config_deckhouse_api_versions_cluster_authorization_rule:
    description: Flat role setting k8s_configuration_config_deckhouse_api_versions_cluster_authorization_rule.
    type: str
  config_deckhouse_ready_checks_user_authz:
    description: Flat role setting k8s_configuration_config_deckhouse_ready_checks_user_authz.
    type: list
    elements: dict
  config_deckhouse_authz_ready_condition:
    description: Flat role setting k8s_configuration_config_deckhouse_authz_ready_condition.
    type: str
  config_deckhouse_mixed_backends:
    description: Flat role setting k8s_configuration_config_deckhouse_mixed_backends.
    type: bool
  config_deckhouse_granular_roles:
    description: Flat role setting k8s_configuration_config_deckhouse_granular_roles.
    type: list
    elements: dict
  config_deckhouse_controller_markers_labels:
    description: Flat role setting k8s_configuration_config_deckhouse_controller_markers_labels.
    type: list
    elements: dict
  config_deckhouse_controller_markers_annotations:
    description: Flat role setting k8s_configuration_config_deckhouse_controller_markers_annotations.
    type: list
    elements: dict
  config_deckhouse_controller_markers_name_prefixes:
    description: Flat role setting k8s_configuration_config_deckhouse_controller_markers_name_prefixes.
    type: list
    elements: str
  config_management_owner:
    description: Flat role setting k8s_configuration_config_management_owner.
    type: str
  config_management_prune:
    description: Flat role setting k8s_configuration_config_management_prune.
    type: bool
  config_management_adoption:
    description: Flat role setting k8s_configuration_config_management_adoption.
    type: list
    elements: dict
  config_management_label_domain:
    description: Flat role setting k8s_configuration_config_management_label_domain.
    type: str
  config_management_namespaces:
    description: Flat role setting k8s_configuration_config_management_namespaces.
    type: list
    elements: str
  config_management_include_cluster_scoped:
    description: Flat role setting k8s_configuration_config_management_include_cluster_scoped.
    type: bool
  config_safety_max_deletions:
    description: Flat role setting k8s_configuration_config_safety_max_deletions.
    type: int
  config_safety_allow_empty_desired:
    description: Flat role setting k8s_configuration_config_safety_allow_empty_desired.
    type: bool
  config_safety_allow_binding_replacement:
    description: Flat role setting k8s_configuration_config_safety_allow_binding_replacement.
    type: bool
  config_safety_protected_namespaces:
    description: Flat role setting k8s_configuration_config_safety_protected_namespaces.
    type: list
    elements: str
  config_safety_protected_namespace_prefixes:
    description: Flat role setting k8s_configuration_config_safety_protected_namespace_prefixes.
    type: list
    elements: str
  config_safety_allowed_protected_namespaces:
    description: Flat role setting k8s_configuration_config_safety_allowed_protected_namespaces.
    type: list
    elements: str
  config_safety_protected_objects:
    description: Flat role setting k8s_configuration_config_safety_protected_objects.
    type: list
    elements: dict
  config_server_validation:
    description: Flat role setting k8s_configuration_config_server_validation.
    type: bool
  config_wait_timeout_seconds:
    description: Flat role setting k8s_configuration_config_wait_timeout_seconds.
    type: int
  config_expected_plan_digest:
    description: Flat role setting k8s_configuration_config_expected_plan_digest.
    type: str
  export_mode:
    description: Flat role setting k8s_configuration_export_mode.
    type: str
  export_backends:
    description: Flat role setting k8s_configuration_export_backends.
    type: list
    elements: str
  export_cluster_roles:
    description: Flat role setting k8s_configuration_export_cluster_roles.
    type: list
    elements: str
  export_roles:
    description: Flat role setting k8s_configuration_export_roles.
    type: list
    elements: dict
  export_access_levels:
    description: Flat role setting k8s_configuration_export_access_levels.
    type: list
    elements: str
  export_namespaces:
    description: Flat role setting k8s_configuration_export_namespaces.
    type: list
    elements: str
  export_include_cluster_scoped:
    description: Flat role setting k8s_configuration_export_include_cluster_scoped.
    type: bool
  export_exclude_controller_generated:
    description: Flat role setting k8s_configuration_export_exclude_controller_generated.
    type: bool
  export_allow_partial:
    description: Flat role setting k8s_configuration_export_allow_partial.
    type: bool
  export_destination:
    description: Flat role setting k8s_configuration_export_destination.
    type: str
  export_audit_destination:
    description: Flat role setting k8s_configuration_export_audit_destination.
    type: str
  matrix_source:
    description: Flat role setting k8s_configuration_matrix_source.
    type: str
  matrix_output_dir:
    description: Flat role setting k8s_configuration_matrix_output_dir.
    type: str
  matrix_scope:
    description: Flat role setting k8s_configuration_matrix_scope.
    type: str
  matrix_namespace_mode:
    description: Flat role setting k8s_configuration_matrix_namespace_mode.
    type: str
  matrix_system_namespaces:
    description: Flat role setting k8s_configuration_matrix_system_namespaces.
    type: list
    elements: str
  matrix_namespace_include:
    description: Flat role setting k8s_configuration_matrix_namespace_include.
    type: list
    elements: str
  matrix_namespace_exclude:
    description: Flat role setting k8s_configuration_matrix_namespace_exclude.
    type: list
    elements: str
  matrix_include_system_subjects:
    description: Flat role setting k8s_configuration_matrix_include_system_subjects.
    type: bool
  matrix_include_external_users:
    description: Flat role setting k8s_configuration_matrix_include_external_users.
    type: bool
  matrix_system_subjects:
    description: Flat role setting k8s_configuration_matrix_system_subjects.
    type: list
    elements: str
  matrix_users_include:
    description: Flat role setting k8s_configuration_matrix_users_include.
    type: list
    elements: str
  matrix_users_exclude:
    description: Flat role setting k8s_configuration_matrix_users_exclude.
    type: list
    elements: str
  matrix_groups_include:
    description: Flat role setting k8s_configuration_matrix_groups_include.
    type: list
    elements: str
  matrix_groups_exclude:
    description: Flat role setting k8s_configuration_matrix_groups_exclude.
    type: list
    elements: str
  matrix_service_accounts_include:
    description: Flat role setting k8s_configuration_matrix_service_accounts_include.
    type: list
    elements: str
  matrix_service_accounts_exclude:
    description: Flat role setting k8s_configuration_matrix_service_accounts_exclude.
    type: list
    elements: str
  matrix_service_account_namespaces_include:
    description: Flat role setting k8s_configuration_matrix_service_account_namespaces_include.
    type: list
    elements: str
  matrix_service_account_namespaces_exclude:
    description: Flat role setting k8s_configuration_matrix_service_account_namespaces_exclude.
    type: list
    elements: str
  matrix_omit_empty_rows:
    description: Flat role setting k8s_configuration_matrix_omit_empty_rows.
    type: bool
  matrix_exclude_broad_subjects:
    description: Flat role setting k8s_configuration_matrix_exclude_broad_subjects.
    type: bool
  matrix_namespaces:
    description: Flat role setting k8s_configuration_matrix_namespaces.
    type: list
    elements: str
  matrix_include_cluster_scoped:
    description: Flat role setting k8s_configuration_matrix_include_cluster_scoped.
    type: bool
  matrix_subjects_users:
    description: Flat role setting k8s_configuration_matrix_subjects_users.
    type: bool
  matrix_subjects_groups:
    description: Flat role setting k8s_configuration_matrix_subjects_groups.
    type: bool
  matrix_subjects_service_accounts:
    description: Flat role setting k8s_configuration_matrix_subjects_service_accounts.
    type: bool
  matrix_resolve_group_membership:
    description: Flat role setting k8s_configuration_matrix_resolve_group_membership.
    type: bool
  matrix_memberships:
    description: Flat role setting k8s_configuration_matrix_memberships.
    type: list
    elements: dict
  matrix_csv_delimiter:
    description: Flat role setting k8s_configuration_matrix_csv_delimiter.
    type: str
  grants:
    description: Desired authorization assignments.
    type: list
    elements: dict
  certificates:
    description: TLS content entries with name and content fields.
    type: list
    elements: dict
author:
  - Platform Team
"""
EXAMPLES = r"""
- name: Plan namespace access
  k8s_configuration:
    config_connection_kubeconfig: /etc/ansible/kubeconfig
    config_management_owner: platform
    grants:
      - id: readers
        backend: rbac
        subjects:
          - kind: Group
            name: readers
        roleRef:
          kind: ClusterRole
          name: view
        scope:
          namespaces: [development]
"""
RETURN = r"""
plan:
  description: Credential-free plan including optimistic concurrency digest.
  type: dict
  returned: when planning or applying
exported:
  description: Normalized inventory and audit of unsupported resources.
  type: dict
  returned: when exporting
matrix:
  description: CSV files, counts and limitations of the current RBAC snapshot.
  type: dict
  returned: in matrix mode
completed:
  description: Successfully completed operations before returning or failing.
  type: list
  returned: when applying
"""
import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.access_manager.settings import argument_spec, build_settings
from ansible.module_utils.access_manager.client import Client
from ansible.module_utils.access_manager.schema import (
    AccessError,
    validate_config,
    validate_inventory,
    unexpected_error,
)
from ansible.module_utils.access_manager.reconcile import Engine
from ansible.module_utils.access_manager.export import export_state
from ansible.module_utils.access_manager.matrix import Matrix


def run(module):
    """EN: Execute the selected mode and return sanitized results through Ansible.
    RU: Выполнить выбранный режим и передать безопасный результат через Ansible.

    Args:
        module (AnsibleModule): Parsed parameters and check/diff flags / Разобранные параметры и флаги check/diff.

    Returns:
        None: Ends through exit_json or fail_json / Завершает работу через exit_json или fail_json.

    Raises:
        SystemExit: Ansible terminates after publishing the result / Ansible завершает процесс после передачи результата.
    """
    client, engine, failure = None, None, None
    result = {"changed": False}
    try:
        settings = build_settings(module.params)
        cfg = validate_config(settings["config"])
        # EN: Read modes validate grants separately when required.
        # RU: Режимы чтения проверяют grants отдельно при необходимости.
        read_only = cfg["mode"] in ("export", "matrix")
        inventory = validate_inventory(
            cfg,
            grants=None if read_only else module.params["grants"],
        )
        requested_mode = cfg["mode"]
        if module.check_mode and requested_mode == "apply":
            cfg["mode"] = "dry"
        if module.check_mode or cfg["mode"] == "dry":
            cfg["server_validation"] = False
        client = Client(cfg["connection"])
        if cfg["mode"] == "matrix":
            # EN: Matrix validates grants only for inventory source; cluster audits ignore them.
            # RU: Grants проверяются только для inventory-матрицы; аудит кластера их игнорирует.
            result["matrix"] = Matrix(client, cfg, settings["matrix"],
                                      grants=module.params["grants"]).report()
        else:
            engine = Engine(client, cfg, inventory)
            engine.prepare(export=cfg["mode"] == "export")
            if cfg["mode"] == "export":
                result["exported"] = export_state(engine, settings["export"])
            else:
                if cfg["mode"] == "apply":
                    result["changed"] = engine.apply()
                result["plan"] = engine.report()
                if module.check_mode and requested_mode == "apply":
                    result["changed"] = any(o["action"] != "noop" for o in engine.operations)
                if module._diff:
                    result["diff"] = [
                        {
                            "before_header": "%s/%s/%s" % (c["kind"], c["namespace"], c["name"]),
                            "after_header": "%s/%s/%s" % (c["kind"], c["namespace"], c["name"]),
                            "before": json.dumps(c["before"], indent=2, ensure_ascii=False) + "\n",
                            "after": json.dumps(c["after"], indent=2, ensure_ascii=False) + "\n",
                        }
                        for c in result["plan"]["changes"] if c["action"] != "noop"
                    ]
            result["completed"] = engine.completed
    except AccessError as exc:
        failure = str(exc)
    except Exception as exc:
        # Never return arbitrary exception text or traceback: API data may contain credentials.
        failure = unexpected_error(exc)
    finally:
        if client:
            client.close()
            if client.cleanup_warnings:
                result["warnings"] = client.cleanup_warnings
    if failure:
        result["changed"] = engine.changed if engine else False
        result["completed"] = engine.completed if engine else []
        if engine:
            result["plan"] = engine.report()
            result["pending"] = [
                c
                for c in result["plan"]["changes"]
                if c["action"] != "noop"
                and {k: c[k] for k in ("action", "kind", "namespace", "name")}
                not in result["completed"]
            ]
        module.fail_json(msg=failure, **result)
    module.exit_json(**result)


def main():
    """EN: Declare module arguments and preserve omission before dispatch.
    RU: Объявить аргументы модуля и сохранить смысл пропущенных значений перед запуском.

    Returns:
        None: Dispatches the Ansible module / Запускает модуль Ansible.

    Raises:
        SystemExit: Ansible validation or execution terminates / Завершение проверки или выполнения Ansible.
    """
    module = AnsibleModule(
        argument_spec=argument_spec(),
        supports_check_mode=True,
    )
    run(module)


if __name__ == "__main__":
    main()
