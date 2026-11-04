"""EN: Convert flat module arguments into engine settings.
RU: Преобразовать плоские аргументы модуля в настройки движка.
"""
from copy import deepcopy

from .schema import require

# EN: One table defines argument types and their internal destinations.
# RU: Одна таблица задаёт типы аргументов и их внутренние пути.
FIELDS = {
    'config_schema_version': ('config.schema_version', {'type': 'int'}),
    'config_mode': ('config.mode', {'type': 'str'}),
    'config_platform': ('config.platform', {'type': 'str'}),
    'config_connection_kubectl': ('config.connection.kubectl', {'type': 'str'}),
    'config_connection_validate_tls': ('config.connection.validate_tls', {'type': 'bool'}),
    'config_connection_timeout_seconds': ('config.connection.timeout_seconds', {'type': 'int'}),
    'config_connection_retries': ('config.connection.retries', {'type': 'int'}),
    'config_connection_kubeconfig': ('config.connection.kubeconfig', {'type': 'str'}),
    'config_connection_context': ('config.connection.context', {'type': 'str'}),
    'config_connection_ca_content': ('config.connection.ca_content', {'type': 'str', 'no_log': True}),
    'config_connection_cert_content': ('config.connection.cert_content', {'type': 'str', 'no_log': True}),
    'config_connection_key_content': ('config.connection.key_content', {'type': 'str', 'no_log': True}),
    'config_deckhouse_basic_authz': ('config.deckhouse.basic_authz', {'type': 'bool'}),
    'config_deckhouse_api_versions_authorization_rule': ('config.deckhouse.profiles.configured.api_versions.AuthorizationRule', {'type': 'str'}),
    'config_deckhouse_api_versions_cluster_authorization_rule': ('config.deckhouse.profiles.configured.api_versions.ClusterAuthorizationRule', {'type': 'str'}),
    'config_deckhouse_ready_checks_user_authz': ('config.deckhouse.profiles.configured.ready_checks.user-authz', {'type': 'list', 'elements': 'dict'}),
    'config_deckhouse_authz_ready_condition': ('config.deckhouse.profiles.configured.authz_ready_condition', {'type': 'str'}),
    'config_deckhouse_mixed_backends': ('config.deckhouse.profiles.configured.mixed_backends', {'type': 'bool'}),
    'config_deckhouse_granular_roles': ('config.deckhouse.profiles.configured.granular_roles', {'type': 'list', 'elements': 'dict'}),
    'config_deckhouse_controller_markers_labels': ('config.deckhouse.profiles.configured.controller_markers.labels', {'type': 'list', 'elements': 'dict'}),
    'config_deckhouse_controller_markers_annotations': ('config.deckhouse.profiles.configured.controller_markers.annotations', {'type': 'list', 'elements': 'dict'}),
    'config_deckhouse_controller_markers_name_prefixes': ('config.deckhouse.profiles.configured.controller_markers.name_prefixes', {'type': 'list', 'elements': 'str'}),
    'config_management_owner': ('config.management.owner', {'type': 'str'}),
    'config_management_prune': ('config.management.prune', {'type': 'bool'}),
    'config_management_adoption': ('config.management.adoption', {'type': 'list', 'elements': 'dict'}),
    'config_management_label_domain': ('config.management.label_domain', {'type': 'str'}),
    'config_management_namespaces': ('config.management.namespaces', {'type': 'list', 'elements': 'str'}),
    'config_management_include_cluster_scoped': ('config.management.include_cluster_scoped', {'type': 'bool'}),
    'config_safety_max_deletions': ('config.safety.max_deletions', {'type': 'int'}),
    'config_safety_allow_empty_desired': ('config.safety.allow_empty_desired', {'type': 'bool'}),
    'config_safety_allow_binding_replacement': ('config.safety.allow_binding_replacement', {'type': 'bool'}),
    'config_safety_protected_namespaces': ('config.safety.protected_namespaces', {'type': 'list', 'elements': 'str'}),
    'config_safety_protected_namespace_prefixes': ('config.safety.protected_namespace_prefixes', {'type': 'list', 'elements': 'str'}),
    'config_safety_allowed_protected_namespaces': ('config.safety.allowed_protected_namespaces', {'type': 'list', 'elements': 'str'}),
    'config_safety_protected_objects': ('config.safety.protected_objects', {'type': 'list', 'elements': 'dict'}),
    'config_server_validation': ('config.server_validation', {'type': 'bool'}),
    'config_wait_timeout_seconds': ('config.wait_timeout_seconds', {'type': 'int'}),
    'config_expected_plan_digest': ('config.expected_plan_digest', {'type': 'str'}),
    'export_mode': ('export.mode', {'type': 'str'}),
    'export_backends': ('export.backends', {'type': 'list', 'elements': 'str'}),
    'export_cluster_roles': ('export.cluster_roles', {'type': 'list', 'elements': 'str'}),
    'export_roles': ('export.roles', {'type': 'list', 'elements': 'dict'}),
    'export_access_levels': ('export.access_levels', {'type': 'list', 'elements': 'str'}),
    'export_namespaces': ('export.namespaces', {'type': 'list', 'elements': 'str'}),
    'export_include_cluster_scoped': ('export.include_cluster_scoped', {'type': 'bool'}),
    'export_exclude_controller_generated': ('export.exclude_controller_generated', {'type': 'bool'}),
    'export_allow_partial': ('export.allow_partial', {'type': 'bool'}),
    'export_destination': ('export.destination', {'type': 'str'}),
    'export_audit_destination': ('export.audit_destination', {'type': 'str'}),
    'matrix_source': ('matrix.source', {'type': 'str'}),
    'matrix_output_dir': ('matrix.output_dir', {'type': 'str'}),
    'matrix_scope': ('matrix.scope', {'type': 'str'}),
    'matrix_namespace_mode': ('matrix.namespace_mode', {'type': 'str'}),
    'matrix_system_namespaces': ('matrix.system_namespaces', {'type': 'list', 'elements': 'str'}),
    'matrix_namespace_include': ('matrix.namespace_include', {'type': 'list', 'elements': 'str'}),
    'matrix_namespace_exclude': ('matrix.namespace_exclude', {'type': 'list', 'elements': 'str'}),
    'matrix_include_system_subjects': ('matrix.include_system_subjects', {'type': 'bool'}),
    'matrix_include_external_users': ('matrix.include_external_users', {'type': 'bool'}),
    'matrix_system_subjects': ('matrix.system_subjects', {'type': 'list', 'elements': 'str'}),
    'matrix_users_include': ('matrix.users_include', {'type': 'list', 'elements': 'str'}),
    'matrix_users_exclude': ('matrix.users_exclude', {'type': 'list', 'elements': 'str'}),
    'matrix_groups_include': ('matrix.groups_include', {'type': 'list', 'elements': 'str'}),
    'matrix_groups_exclude': ('matrix.groups_exclude', {'type': 'list', 'elements': 'str'}),
    'matrix_service_accounts_include': ('matrix.service_accounts_include', {'type': 'list', 'elements': 'str'}),
    'matrix_service_accounts_exclude': ('matrix.service_accounts_exclude', {'type': 'list', 'elements': 'str'}),
    'matrix_service_account_namespaces_include': ('matrix.service_account_namespaces_include', {'type': 'list', 'elements': 'str'}),
    'matrix_service_account_namespaces_exclude': ('matrix.service_account_namespaces_exclude', {'type': 'list', 'elements': 'str'}),
    'matrix_omit_empty_rows': ('matrix.omit_empty_rows', {'type': 'bool'}),
    'matrix_exclude_broad_subjects': ('matrix.exclude_broad_subjects', {'type': 'bool'}),
    'matrix_namespaces': ('matrix.namespaces', {'type': 'list', 'elements': 'str'}),
    'matrix_include_cluster_scoped': ('matrix.include_cluster_scoped', {'type': 'bool'}),
    'matrix_subjects_users': ('matrix.subjects.users', {'type': 'bool'}),
    'matrix_subjects_groups': ('matrix.subjects.groups', {'type': 'bool'}),
    'matrix_subjects_service_accounts': ('matrix.subjects.service_accounts', {'type': 'bool'}),
    'matrix_resolve_group_membership': ('matrix.resolve_group_membership', {'type': 'bool'}),
    'matrix_memberships': ('matrix.memberships', {'type': 'list', 'elements': 'dict'}),
    'matrix_csv_delimiter': ('matrix.csv.delimiter', {'type': 'str'}),
}


def argument_spec():
    """EN: Return typed flat module options, including secret fields.
    RU: Вернуть типизированные плоские параметры, включая секретные поля.

    Returns:
        dict: Ansible argument specification / Спецификация аргументов Ansible.
    """
    spec = {name: deepcopy(field[1]) for name, field in FIELDS.items()}
    spec.update(
        grants={"type": "list", "elements": "dict"},
        certificates={"type": "list", "elements": "dict", "default": [], "options": {
            "name": {"type": "str", "required": True},
            "content": {"type": "str", "required": True, "no_log": True}}},
    )
    return spec


def build_settings(params):
    """EN: Assemble engine settings without changing omitted options.
    RU: Собрать настройки движка, сохраняя смысл пропущенных параметров.

    Args:
        params (dict): Typed flat Ansible parameters / Типизированные плоские параметры Ansible.

    Returns:
        dict: Internal config, export and matrix settings / Внутренние настройки config, export и matrix.

    Raises:
        AccessError: Invalid certificate or mapping entry / Неверный сертификат или элемент сопоставления.
    """
    result = {"config": {}, "export": {}, "matrix": {}}
    for name, (destination, _) in FIELDS.items():
        path = destination.split(".")
        value = params.get(name)
        # EN: Empty optional strings and None retain schema defaults/discovery.
        # RU: Пустые необязательные строки и None сохраняют defaults/discovery схемы.
        if value is None or (value == "" and (name.endswith(("_context", "_content", "_digest"))
                                              or "_api_versions_" in name
                                              or name == "export_audit_destination")):
            continue
        if name.endswith(("_granular_roles", "_markers_labels", "_markers_annotations")):
            key, item = ("name", "scopes") if name.endswith("_granular_roles") else ("key", "value")
            require(all(key in entry and item in entry for entry in value), "Invalid mapping entries: " + name)
            value = {entry[key]: entry[item] for entry in value}
        target = result
        for part in path[:-1]:
            target = target.setdefault(part, {})
        target[path[-1]] = value
    deck = result["config"].get("deckhouse", {})
    if "profiles" in deck:
        deck["compatibility_profile"] = "configured"
    for certificate in params.get("certificates") or []:
        require(certificate["name"] in ("ca_content", "cert_content", "key_content")
                and bool(certificate["content"]), "Invalid TLS certificate entry")
        result["config"].setdefault("connection", {})[certificate["name"]] = certificate["content"]
    return result
