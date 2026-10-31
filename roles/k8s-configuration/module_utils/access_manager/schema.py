"""Strict input validation. No API writes or credential-bearing errors."""
import copy
import re


class AccessError(Exception):
    """An intentionally public, credential-free diagnostic."""


def require(condition, message):
    if not condition:
        raise AccessError(message)


def mapping(value, allowed, where, required=()):
    require(isinstance(value, dict), "%s must be a mapping" % where)
    require(not set(value) - set(allowed), "%s has unsupported fields" % where)
    require(set(required) <= set(value), "%s is missing required fields" % where)
    return value


def string(value, where):
    require(isinstance(value, str) and bool(value.strip()), "%s must be a nonempty string" % where)
    return value


def names(value, where, empty=True):
    require(isinstance(value, list), "%s must be a list" % where)
    require(empty or bool(value), "%s must not be empty" % where)
    for item in value:
        string(item, where)
    require(len(set(value)) == len(value), "%s contains duplicates" % where)
    return value


def boolean(value, where):
    require(type(value) is bool, "%s must be a boolean" % where)


def integer(value, where, minimum=0, maximum=100000):
    require(
        type(value) is int and minimum <= value <= maximum,
        "%s must be an integer in %d..%d" % (where, minimum, maximum),
    )


def path_name(value, where):
    string(value, where)
    require(
        value not in (".", "..") and not any(c in value for c in ("/", "%")),
        where + " must be a valid Kubernetes path-segment name",
    )


def dns(value, where):
    string(value, where)
    require(
        len(value) <= 253 and re.fullmatch(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", value),
        "%s must be a DNS-compatible name" % where,
    )
    require(
        all(
            len(p) <= 63 and re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", p)
            for p in value.split(".")
        ),
        "%s has an invalid DNS label" % where,
    )


DEFAULTS = {
    "schema_version": 1,
    "mode": "dry",
    "platform": "vanilla",
    "connection": {"validate_tls": True, "timeout_seconds": 30, "retries": 2},
    "deckhouse": {"basic_authz": False, "profiles": {}},
    "management": {
        "owner": "ansible-access-manager",
        "prune": False,
        "prune_identities": False,
        "adoption": [],
        "label_domain": "access-manager.ansible.local",
        "namespaces": None,
        "include_cluster_scoped": True,
    },
    "safety": {
        "max_deletions": 10,
        "allow_empty_desired": False,
        "allow_binding_replacement": False,
        "protected_namespaces": [
            "kube-system",
            "kube-public",
            "kube-node-lease",
            "default",
            "loghouse",
        ],
        "protected_namespace_prefixes": ["kube-", "d8-"],
        "allowed_protected_namespaces": [],
        "protected_objects": [],
    },
    "server_validation": False,
    "wait_timeout_seconds": 60,
    "access_checks": [],
}


def object_ref(value, where, uid=False):
    mapping(
        value,
        ["group", "resource", "namespace", "name", "uid"],
        where,
        ["group", "resource", "name"] + (["uid"] if uid else []),
    )
    require(isinstance(value["group"], str), where + ".group must be a string")
    for key in ("resource", "name"):
        string(value[key], where + "." + key)
    if uid:
        string(value["uid"], where + ".uid")


def validate_config(raw):
    mapping(raw, list(DEFAULTS) + ["expected_plan_digest"], "config")
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key in ("connection", "deckhouse", "management", "safety"):
            allowed = {
                "connection": [
                    "kubeconfig",
                    "context",
                    "validate_tls",
                    "timeout_seconds",
                    "retries",
                    "ca_content",
                    "cert_content",
                    "key_content",
                ],
                "deckhouse": ["basic_authz", "compatibility_profile", "profiles"],
                "management": list(DEFAULTS["management"]),
                "safety": list(DEFAULTS["safety"]),
            }[key]
            mapping(value, allowed, key)
            cfg[key].update(value)
        else:
            cfg[key] = value
    require(
        type(cfg["schema_version"]) is int and cfg["schema_version"] == 1,
        "Only schema_version 1 is supported",
    )
    # Keep existing inventories working; dry is the public name of this mode.
    if cfg["mode"] == "plan":
        cfg["mode"] = "dry"
    require(cfg["mode"] in ("dry", "apply", "export"), "Invalid mode")
    require(cfg["platform"] in ("vanilla", "deckhouse"), "Invalid platform")
    string(cfg["connection"].get("kubeconfig"), "connection.kubeconfig")
    for key in ("validate_tls",):
        boolean(cfg["connection"][key], "connection." + key)
    integer(cfg["connection"]["timeout_seconds"], "timeout_seconds", 1, 3600)
    integer(cfg["connection"]["retries"], "retries", 0, 5)
    integer(cfg["wait_timeout_seconds"], "wait_timeout_seconds", 1, 3600)
    boolean(cfg["server_validation"], "server_validation")
    mg = cfg["management"]
    require(
        isinstance(mg["owner"], str)
        and len(mg["owner"]) <= 63
        and re.fullmatch(r"[a-zA-Z0-9](?:[-_.a-zA-Z0-9]*[a-zA-Z0-9])?", mg["owner"]),
        "Invalid management.owner",
    )
    dns(mg["label_domain"], "management.label_domain")
    for key in ("prune", "prune_identities", "include_cluster_scoped"):
        boolean(mg[key], "management." + key)
    if mg["namespaces"] is not None:
        names(mg["namespaces"], "management.namespaces")
    require(isinstance(mg["adoption"], list), "adoption must be a list")
    for ref in mg["adoption"]:
        object_ref(ref, "adoption", True)
    safe = cfg["safety"]
    integer(safe["max_deletions"], "safety.max_deletions")
    for key in ("allow_empty_desired", "allow_binding_replacement"):
        boolean(safe[key], "safety." + key)
    for key in (
        "protected_namespaces",
        "protected_namespace_prefixes",
        "allowed_protected_namespaces",
    ):
        names(safe[key], "safety." + key)
    require(isinstance(safe["protected_objects"], list), "protected_objects must be a list")
    for ref in safe["protected_objects"]:
        object_ref(ref, "protected_objects")
    boolean(cfg["deckhouse"]["basic_authz"], "deckhouse.basic_authz")
    mapping(cfg["deckhouse"]["profiles"], cfg["deckhouse"]["profiles"], "deckhouse.profiles")
    require(isinstance(cfg["access_checks"], list), "access_checks must be a list")
    for check in cfg["access_checks"]:
        mapping(
            check,
            ["user", "groups", "resourceAttributes", "allowed"],
            "access_check",
            ["user", "resourceAttributes", "allowed"],
        )
        string(check["user"], "access_check.user")
        names(check.get("groups", []), "access_check.groups")
        boolean(check["allowed"], "access_check.allowed")
        mapping(
            check["resourceAttributes"],
            ["namespace", "verb", "group", "version", "resource", "subresource", "name"],
            "resourceAttributes",
            ["verb", "resource"],
        )
        for v in check["resourceAttributes"].values():
            require(isinstance(v, str), "resourceAttributes values must be strings")
    return cfg


def validate_selector(selector):
    mapping(selector, ["matchLabels", "matchExpressions"], "namespace_selector")
    require(
        bool(selector.get("matchLabels")) or bool(selector.get("matchExpressions")),
        "Empty selector is forbidden",
    )
    if "matchLabels" in selector:
        require(isinstance(selector["matchLabels"], dict), "matchLabels must be a mapping")
        for k, v in selector["matchLabels"].items():
            string(k, "matchLabels key")
            require(isinstance(v, str), "matchLabels values must be strings")
    if "matchExpressions" in selector:
        require(isinstance(selector["matchExpressions"], list), "matchExpressions must be a list")
        for expr in selector["matchExpressions"]:
            mapping(expr, ["key", "operator", "values"], "matchExpression", ["key", "operator"])
            string(expr["key"], "matchExpression.key")
            require(
                expr["operator"] in ("In", "NotIn", "Exists", "DoesNotExist"),
                "Invalid selector operator",
            )
            names(expr.get("values", []), "matchExpression.values")
            if expr["operator"] in ("In", "NotIn"):
                require(bool(expr.get("values")), "In/NotIn requires values")
            else:
                require(not expr.get("values"), "Exists/DoesNotExist forbids values")


def validate_inventory(cfg, users=None, groups=None, grants=None):
    sections = {"users": users, "groups": groups, "grants": grants}
    result = {}
    for section, entries in sections.items():
        require(
            entries is None or isinstance(entries, list), section + " must be a list or omitted"
        )
        result[section] = copy.deepcopy(entries)
        seen = set()
        for entry in entries or []:
            fields = {
                "users": [
                    "name",
                    "source",
                    "email",
                    "password_hash",
                    "password_policy",
                    "state",
                    "allow_collision",
                ],
                "groups": ["name", "source", "claim_name", "members", "state", "allow_collision"],
                "grants": [
                    "id",
                    "backend",
                    "subjects",
                    "roleRef",
                    "scope",
                    "accessLevel",
                    "options",
                    "state",
                    "target_name",
                ],
            }[section]
            mapping(entry, fields, section)
            ident = entry.get("id" if section == "grants" else "name")
            dns(ident, section + " identifier")
            require(ident not in seen, "Duplicate identifier in " + section)
            seen.add(ident)
            require(entry.get("state", "present") in ("present", "absent"), "Invalid state")
            absent = entry.get("state") == "absent"
            if section != "grants":
                require(cfg["platform"] == "deckhouse", "Local identities require Deckhouse")
                require(entry.get("source") == "static", "Local identities require source: static")
                boolean(entry.get("allow_collision", False), "allow_collision")
                if absent:
                    continue
            if section == "users":
                email = string(entry.get("email"), "user.email")
                require(email == email.lower() and "@" in email, "Local email must be lowercase")
                require(
                    entry.get("password_policy", "on_create") in ("on_create", "managed"),
                    "Invalid password_policy",
                )
                if entry.get("password_hash") is not None:
                    require(
                        isinstance(entry["password_hash"], str)
                        and re.fullmatch(
                            r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", entry["password_hash"]
                        ),
                        "password_hash must be a raw bcrypt hash",
                    )
            elif section == "groups":
                string(entry.get("claim_name"), "group.claim_name")
                names(entry.get("members"), "group.members")
            else:
                require(entry.get("backend") in ("rbac", "deckhouse"), "Invalid backend")
                if entry["backend"] == "deckhouse":
                    require(
                        cfg["platform"] == "deckhouse" and cfg["deckhouse"]["basic_authz"],
                        "Basic Deckhouse backend is not enabled",
                    )
                scope = mapping(
                    entry.get("scope"),
                    ["cluster", "namespaces", "namespace_selector", "include_system_namespaces"],
                    "scope",
                )
                require(
                    sum(k in scope for k in ("cluster", "namespaces", "namespace_selector")) == 1,
                    "scope requires exactly one variant",
                )
                if "cluster" in scope:
                    require(scope["cluster"] is True, "scope.cluster must be true")
                    if entry["backend"] == "deckhouse":
                        boolean(
                            scope.get("include_system_namespaces"),
                            "scope.include_system_namespaces",
                        )
                if "namespaces" in scope:
                    names(scope["namespaces"], "scope.namespaces", False)
                    for ns in scope["namespaces"]:
                        dns(ns, "namespace")
                if "namespace_selector" in scope:
                    require(
                        entry["backend"] == "deckhouse", "RBAC does not support namespace_selector"
                    )
                    validate_selector(scope["namespace_selector"])
                if "include_system_namespaces" in scope:
                    require(
                        entry["backend"] == "deckhouse" and scope.get("cluster") is True,
                        "include_system_namespaces requires a Deckhouse cluster scope",
                    )
                if "target_name" in entry:
                    if entry["backend"] == "rbac":
                        path_name(entry["target_name"], "target_name")
                    else:
                        dns(entry["target_name"], "target_name")
                    require(
                        len(scope.get("namespaces", [])) <= 1,
                        "target_name requires a single target",
                    )
                if absent:
                    continue
                subs = entry.get("subjects")
                require(isinstance(subs, list) and bool(subs), "subjects must not be empty")
                for sub in subs:
                    mapping(
                        sub,
                        ["kind", "source", "name", "namespace"],
                        "subject",
                        ["kind", "source", "name"],
                    )
                    string(sub["name"], "subject.name")
                    require(
                        sub["kind"] in ("User", "Group", "ServiceAccount"), "Invalid subject kind"
                    )
                    if sub["kind"] == "ServiceAccount":
                        require(
                            sub["source"] == "serviceaccount",
                            "ServiceAccount source must be serviceaccount",
                        )
                        dns(sub.get("namespace"), "ServiceAccount namespace")
                        dns(sub["name"], "ServiceAccount name")
                    else:
                        require(
                            sub["source"] in ("static", "external") and "namespace" not in sub,
                            "Invalid User/Group subject",
                        )
                if entry["backend"] == "rbac":
                    require(
                        not set(entry) & {"accessLevel", "options"},
                        "RBAC cannot use accessLevel/options",
                    )
                    ref = mapping(
                        entry.get("roleRef"), ["kind", "name"], "roleRef", ["kind", "name"]
                    )
                    path_name(ref["name"], "roleRef.name")
                    require(ref["kind"] in ("Role", "ClusterRole"), "Invalid roleRef.kind")
                    require(
                        ref["kind"] != "Role" or "namespaces" in scope,
                        "Role requires namespace scope",
                    )
                else:
                    require("roleRef" not in entry, "Deckhouse cannot use roleRef")
                    levels = ["User", "PrivilegedUser", "Editor", "Admin"]
                    if "namespaces" not in scope:
                        levels += ["ClusterEditor", "ClusterAdmin", "SuperAdmin"]
                    require(entry.get("accessLevel") in levels, "Invalid accessLevel for scope")
                    mapping(entry.get("options", {}), ["allowScale", "portForwarding"], "options")
                    for v in entry.get("options", {}).values():
                        boolean(v, "option")
    for section, field in [("users", "email"), ("groups", "claim_name")]:
        values = [x[field] for x in result[section] or [] if x.get("state") != "absent"]
        require(len(values) == len(set(values)), "Duplicate identity in " + section)
    user_names = {x["name"] for x in result["users"] or [] if x.get("state") != "absent"}
    for group in result["groups"] or []:
        if group.get("state") != "absent":
            require(
                set(group["members"]) <= user_names,
                "Group member must reference a present inventory User",
            )
    return result
