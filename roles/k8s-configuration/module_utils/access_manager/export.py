"""Read-only, loss-aware export with explicit identity dependencies."""
import base64
import binascii
import hashlib
import re

from .schema import require, mapping, names, boolean, validate_inventory
from .render import AUTHZ, IDENTITIES, canonical, identity, keys, owned, clean
from .reconcile import unsupported


def validate_export(raw):
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
            "include_identities",
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
        "include_identities": True,
        "allow_partial": False,
    }
    cfg.update(raw)
    require(cfg["mode"] in ("managed", "scoped"), "Invalid export mode")
    for key in ("backends", "cluster_roles", "access_levels", "namespaces"):
        names(cfg[key], "export." + key)
    require(set(cfg["backends"]) <= {"rbac", "deckhouse"}, "Invalid export backend")
    for key in (
        "include_cluster_scoped", "exclude_controller_generated", "include_identities", "allow_partial"
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
    cfg = validate_export(raw)
    inventory = {
        "k8s_configuration_users": [],
        "k8s_configuration_groups": [],
        "k8s_configuration_grants": [],
    }
    audit, warnings, dependencies = [], [], set()
    actual = engine.actual
    users = [o for o in actual.values() if o["kind"] == "User"]
    groups = [o for o in actual.values() if o["kind"] == "Group"]
    selected_identities = {
        identity(o) for o in users + groups
        if cfg["include_identities"]
        and (cfg["mode"] == "scoped" or owned(o, engine.cfg))
        and not (cfg["exclude_controller_generated"] and engine._is_controller(o))
    }
    emails, claims = {}, {}
    for obj in users:
        emails.setdefault(obj.get("spec", {}).get("email"), []).append(obj)
    for obj in groups:
        claims.setdefault(obj.get("spec", {}).get("name"), []).append(obj)

    def audit_entry(obj, problems):
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
        kind, name = sub.get("kind"), sub.get("name")
        result = {"kind": kind, "name": name}
        if kind == "ServiceAccount":
            require(sub.get("namespace"), "Cannot export ServiceAccount without namespace")
            result.update(source="serviceaccount", namespace=sub["namespace"])
        else:
            result["source"] = "external"
            catalog = emails if kind == "User" else claims
            matches = catalog.get(name, [])
            if len(matches) == 1:
                dependencies.add(identity(matches[0]))
                result.update(source="static", name=matches[0]["metadata"]["name"])
            else:
                warnings.append(
                    "Identity origin is external or ambiguous; exact claim name preserved"
                )
        return result

    for key in sorted(actual):
        obj = actual[key]
        kind, ns, name = key
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
        # Do not emit an importable grant when any dependency cannot be represented.
        needed_before = set(dependencies)
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
        else:
            dependencies = needed_before

    # Standalone identities also belong to an inventory snapshot, even if no
    # selected authorization rule currently refers to them.
    dependencies.update(selected_identities)
    # Groups add local users transitively (nested groups are unsupported).
    for key in list(dependencies):
        obj = actual[key]
        if obj["kind"] == "Group":
            for member in obj.get("spec", {}).get("members", []):
                user_key = ("User", "", member.get("name"))
                if member.get("kind") == "User" and user_key in actual:
                    dependencies.add(user_key)
    unimportable = set()
    for key in sorted(dependencies):
        obj = actual[key]
        spec = obj.get("spec", {})
        problems = unsupported(obj)
        if obj["kind"] == "Group":
            members = [m.get("name") for m in spec.get("members", []) if m.get("kind") == "User"]
            if any(("User", "", n) not in actual for n in members):
                problems.append("unresolved-members")
            entry = {
                "name": key[2],
                "source": "static",
                "claim_name": spec.get("name"),
                "members": members,
            }
        else:
            entry = {
                "name": key[2],
                "source": "static",
                "email": spec.get("email"),
                "password_policy": "on_create",
            }
            try:
                password_hash = base64.b64decode(spec.get("password", ""), validate=True).decode("ascii")
                if not re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", password_hash):
                    raise ValueError("Not a bcrypt hash")
                entry["password_hash"] = password_hash
            except (ValueError, TypeError, UnicodeError, binascii.Error):
                problems.append("password:not-exportable-bcrypt")
        if obj.get("metadata", {}).get("annotations", {}).get(
            "user-authz.deckhouse.io/allow-authorization-rule-collision"
        ) == "true":
            entry["allow_collision"] = True
        record = audit_entry(obj, problems)
        if record["importable"]:
            inventory[
                "k8s_configuration_users" if obj["kind"] == "User" else "k8s_configuration_groups"
            ].append(entry)
        else:
            unimportable.add(key)
    # An unsupported identity makes all dependent groups/grants non-importable too.
    changed = True
    while changed:
        changed = False
        for key in dependencies:
            obj = actual[key]
            if obj["kind"] == "Group" and key not in unimportable:
                if any(
                    ("User", "", m.get("name")) in unimportable
                    for m in obj.get("spec", {}).get("members", [])
                ):
                    unimportable.add(key)
                    changed = True
    inventory["k8s_configuration_groups"] = [
        g
        for g in inventory["k8s_configuration_groups"]
        if ("Group", "", g["name"]) not in unimportable
    ]
    valid_grants = []
    for grant in inventory["k8s_configuration_grants"]:
        bad = any(
            (s["kind"], "", s["name"]) in unimportable
            for s in grant["subjects"]
            if s["source"] == "static"
        )
        if not bad:
            valid_grants.append(grant)
        else:
            for record in audit:
                if (
                    record["source"]["metadata"]["name"] == grant["target_name"]
                    and record["source"]["kind"] not in IDENTITIES
                ):
                    record["importable"] = False
                    record["unsupported_fields"].append("unsupported-identity-dependency")
    inventory["k8s_configuration_grants"] = valid_grants
    used = {
        (s["kind"], s["name"])
        for g in valid_grants
        for s in g["subjects"]
        if s["source"] == "static"
    }
    inventory["k8s_configuration_groups"] = [
        g for g in inventory["k8s_configuration_groups"]
        if ("Group", g["name"]) in used or ("Group", "", g["name"]) in selected_identities
    ]
    used.update(("User", m) for g in inventory["k8s_configuration_groups"] for m in g["members"])
    inventory["k8s_configuration_users"] = [
        u for u in inventory["k8s_configuration_users"]
        if ("User", u["name"]) in used or ("User", "", u["name"]) in selected_identities
    ]
    for record in audit:
        meta = record["source"]["metadata"]
        key = (record["source"]["kind"], meta.get("namespace", ""), meta["name"])
        if key in unimportable:
            record["importable"] = False
    require(
        cfg["allow_partial"] or all(r["importable"] for r in audit),
        "Export contains unsupported resources or identities; no inventory file was written. "
        "Use export.allow_partial with audit_destination only after reviewing the limitations",
    )
    validate_inventory(
        engine.cfg,
        inventory["k8s_configuration_users"],
        inventory["k8s_configuration_groups"],
        inventory["k8s_configuration_grants"],
    )
    return {
        "schema_version": 1,
        "cluster_uid": engine.cluster_uid,
        "inventory": inventory,
        "audit": audit,
        "warnings": sorted(set(warnings)),
    }
