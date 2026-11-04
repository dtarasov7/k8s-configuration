"""EN: Export access assignments while preserving literal subject names.
RU: Экспортировать назначения с сохранением буквальных имён субъектов.
"""
import hashlib

from .schema import require, mapping, names, boolean, validate_inventory
from .render import AUTHZ, IDENTITIES, canonical, owned, clean
from .reconcile import unsupported


def validate_export(raw):
    """EN: Validate export selection and distinct output destinations.
    RU: Проверить выборку экспорта и различие путей результатов.

    Args:
        raw (dict): Export filters and destinations / Фильтры экспорта и пути результатов.

    Returns:
        dict: Validated options with defaults / Проверенные параметры со значениями по умолчанию.

    Raises:
        AccessError: Invalid mode, filters or conflicting paths / Неверный режим, фильтры или совпадающие пути.
    """
    mapping(
        raw,
        [
            "mode",
            "backends",
            "cluster_roles",
            "roles",
            "access_levels",
            "namespaces",
            "include_cluster_scoped",
            "exclude_controller_generated",
            "destination",
            "audit_destination",
            "allow_partial",
        ],
        "export",
    )
    cfg = {
        "mode": "managed",
        "backends": ["rbac", "deckhouse"],
        "cluster_roles": [],
        "roles": [],
        "access_levels": [],
        "namespaces": [],
        "include_cluster_scoped": True,
        "exclude_controller_generated": True,
        "allow_partial": False,
    }
    cfg.update(raw)
    require(cfg["mode"] in ("managed", "scoped"), "Invalid export mode")
    for key in ("backends", "cluster_roles", "access_levels", "namespaces"):
        names(cfg[key], "export." + key)
    require(set(cfg["backends"]) <= {"rbac", "deckhouse"}, "Invalid export backend")
    for key in (
        "include_cluster_scoped", "exclude_controller_generated", "allow_partial"
    ):
        boolean(cfg[key], "export." + key)
    for key in ("destination", "audit_destination"):
        if key in cfg:
            require(isinstance(cfg[key], str) and bool(cfg[key].strip()), "Invalid export." + key)
    require(
        not cfg.get("audit_destination") or cfg["audit_destination"] != cfg.get("destination"),
        "Export inventory and audit destinations must differ",
    )
    require(isinstance(cfg["roles"], list), "export.roles must be a list")
    for ref in cfg["roles"]:
        mapping(ref, ["namespace", "name"], "export Role", ["namespace", "name"])
    return cfg


def export_state(engine, raw):
    """EN: Export representable assignments from a prepared snapshot without identities.
    RU: Экспортировать представимые назначения подготовленного снимка без определений учёток.

    Args:
        engine (Engine): Session prepared with export=True / Сеанс, подготовленный с export=True.
        raw (dict): Export filters / Фильтры экспорта.

    Returns:
        dict: Importable grants, sanitized audit and warnings / Импортируемые grants, аудит без секретов и предупреждения.

    Raises:
        AccessError: Invalid filters or unsupported selected assignments without allow_partial / Неверные фильтры или неподдерживаемые назначения без allow_partial.
    """
    cfg = validate_export(raw)
    inventory = {
        "k8s_configuration_grants": [],
    }
    audit, warnings = [], []
    actual = engine.actual
    def audit_entry(obj, problems):
        """EN: Record a redacted assignment snapshot and its importability.
        RU: Записать снимок назначения без секретов и признак возможности импорта.

        Args:
            obj (dict): Selected authorization object / Выбранный объект авторизации.
            problems (list[str]): Unsupported field names / Имена неподдерживаемых полей.

        Returns:
            dict: Record appended to the audit list / Запись, добавленная в список аудита.
        """
        controller = engine._is_controller(obj)
        result = {
            "source": {
                k: v for k, v in clean(obj).items() if k in ("apiVersion", "kind", "metadata")
            },
            "managed": owned(obj, engine.cfg),
            "requires_adoption": not owned(obj, engine.cfg),
            "controller_generated": controller,
            "unsupported_fields": sorted(set(problems)),
            "importable": not problems and not controller,
            "snapshot": clean(obj),
        }
        audit.append(result)
        return result

    def subject(sub):
        """EN: Preserve a subject name and require an explicit ServiceAccount namespace.
        RU: Сохранить имя субъекта и потребовать явный namespace ServiceAccount.

        Args:
            sub (dict): Observed binding subject / Субъект наблюдаемого binding.

        Returns:
            dict: Importable kind/name and optional namespace / Импортируемые kind/name и необязательный namespace.

        Raises:
            AccessError: ServiceAccount has no namespace / У ServiceAccount не указан namespace.
        """
        kind, name = sub.get("kind"), sub.get("name")
        result = {"kind": kind, "name": name}
        if kind == "ServiceAccount":
            require(sub.get("namespace"), "Cannot export ServiceAccount without namespace")
            result["namespace"] = sub["namespace"]
        return result

    for key in sorted(actual):
        obj = actual[key]
        kind, ns, name = key
        # EN: Identity definitions and their secrets never belong to assignment exports.
        # RU: Определения учёток и их секреты не включаются в экспорт назначений.
        if kind in IDENTITIES:
            continue
        backend = "deckhouse" if kind in AUTHZ else "rbac"
        if backend not in cfg["backends"]:
            continue
        if engine._is_controller(obj) and cfg["exclude_controller_generated"]:
            continue
        if cfg["mode"] == "managed" and not owned(obj, engine.cfg):
            continue
        if ns:
            if cfg["namespaces"] and ns not in cfg["namespaces"]:
                continue
        elif not cfg["include_cluster_scoped"]:
            continue
        spec = obj.get("spec", {})
        if cfg["mode"] == "scoped":
            if backend == "rbac":
                ref = obj.get("roleRef", {})
                if ref.get("kind") == "ClusterRole":
                    if ref.get("name") not in cfg["cluster_roles"]:
                        continue
                elif {"namespace": ns, "name": ref.get("name")} not in cfg["roles"]:
                    continue
            elif spec.get("accessLevel") not in cfg["access_levels"]:
                continue
        problems = unsupported(obj)
        entry = {
            "id": "export-" + hashlib.sha256(canonical(key).encode("utf-8")).hexdigest()[:16],
            "target_name": name,
            "backend": backend,
        }
        if ns:
            entry["scope"] = {"namespaces": [ns]}
        elif kind == "ClusterAuthorizationRule":
            selector = spec.get("namespaceSelector", {})
            if selector.get("labelSelector"):
                entry["scope"] = {"namespace_selector": selector["labelSelector"]}
            elif selector.get("matchAny") is True:
                entry["scope"] = {"cluster": True, "include_system_namespaces": True}
            elif not selector:
                entry["scope"] = {"cluster": True, "include_system_namespaces": False}
            else:
                problems.append("namespaceSelector")
            multi = (
                engine.authz_config.get("spec", {}).get("settings", {}).get("enableMultiTenancy")
                is True
            )
            if not multi:
                problems.append("unverified-multitenancy")
        else:
            entry["scope"] = {"cluster": True}
        subjects = obj.get("subjects", spec.get("subjects", []))
        if not subjects or any(
            s.get("kind") not in ("User", "Group", "ServiceAccount") for s in subjects
        ):
            problems.append("subjects")
        if not problems:
            entry["subjects"] = [subject(s) for s in subjects]
            if backend == "rbac":
                entry["roleRef"] = {k: obj["roleRef"][k] for k in ("kind", "name")}
            else:
                entry["accessLevel"] = spec.get("accessLevel")
                entry["options"] = {k: spec.get(k, False) for k in ("portForwarding", "allowScale")}
        record = audit_entry(obj, problems)
        if kind == "ClusterAuthorizationRule" and spec.get("namespaceSelector", {}).get(
            "labelSelector"
        ):
            record["dynamic_scope"] = True
            warnings.append(
                "CAR exported whole: namespace filters do not narrow cluster-scoped semantics"
            )
        if record["importable"]:
            inventory["k8s_configuration_grants"].append(entry)
    require(
        cfg["allow_partial"] or all(r["importable"] for r in audit),
        "Export contains unsupported access assignments; no inventory file was written. "
        "Use export.allow_partial with audit_destination only after reviewing the limitations",
    )
    validate_inventory(
        engine.cfg,
        grants=inventory["k8s_configuration_grants"],
    )
    return {
        "schema_version": 1,
        "cluster_uid": engine.cluster_uid,
        "inventory": inventory,
        "audit": audit,
        "warnings": sorted(set(warnings)),
    }
