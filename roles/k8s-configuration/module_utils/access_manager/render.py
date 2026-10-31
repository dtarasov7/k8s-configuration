"""Pure rendering and canonical, redacted projections."""
import base64
import copy
import hashlib
import json

from .schema import require

RBAC = "rbac.authorization.k8s.io/v1"
KINDS = (
    "RoleBinding",
    "ClusterRoleBinding",
    "AuthorizationRule",
    "ClusterAuthorizationRule",
    "User",
    "Group",
)
IDENTITIES = ("User", "Group")
AUTHZ = ("AuthorizationRule", "ClusterAuthorizationRule")
SECTION = {k: ("users" if k == "User" else "groups" if k == "Group" else "grants") for k in KINDS}
OPTIONAL = ("namespaceSelector", "allowAccessToSystemNamespaces", "limitNamespaces")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sorted_items(items):
    return sorted(items, key=canonical)


def identity(obj):
    meta = obj["metadata"]
    return (obj["kind"], meta.get("namespace", ""), meta["name"])


def keys(cfg):
    domain = cfg["management"]["label_domain"]
    return {
        k: domain + "/" + k
        for k in ("owner", "managed-by", "grant-id", "section", "schema-version")
    }


def owned(obj, cfg):
    labels = obj.get("metadata", {}).get("labels", {})
    k = keys(cfg)
    return (
        labels.get(k["owner"]) == cfg["management"]["owner"]
        and labels.get(k["managed-by"]) == "ansible"
    )


def controller_owned(obj):
    meta = obj.get("metadata", {})
    if meta.get("ownerReferences"):
        return True
    labels = meta.get("labels", {})
    annotations = meta.get("annotations", {})
    if labels.get("rbac.deckhouse.io/automated") == "true":
        return True
    if labels.get("app.kubernetes.io/managed-by", "").lower() in ("helm", "deckhouse"):
        return True
    if any(k.startswith(("meta.helm.sh/", "heritage")) for k in annotations):
        return True
    return any(k.startswith(("user-authz.deckhouse.io/", "heritage")) for k in labels)


def resource_ref(obj):
    version = obj["apiVersion"]
    kind, ns, name = identity(obj)
    return {
        "group": version.split("/")[0] if "/" in version else "",
        "kind": kind,
        "namespace": ns,
        "name": name,
        "uid": obj.get("metadata", {}).get("uid"),
    }


def generated_name(cfg, grant, kind, ns):
    raw = "\0".join([cfg["management"]["owner"], grant["id"], kind, ns])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return "am-" + grant["id"][:46].rstrip("-.") + "-" + digest


def make(cfg, version, kind, name, ns, section, grant_id=None):
    k = keys(cfg)
    meta = {
        "name": name,
        "labels": {
            k["owner"]: cfg["management"]["owner"],
            k["managed-by"]: "ansible",
            k["section"]: section,
        },
        "annotations": {k["schema-version"]: "1"},
    }
    if grant_id:
        meta["annotations"][k["grant-id"]] = grant_id
    if ns:
        meta["namespace"] = ns
    return {"apiVersion": version, "kind": kind, "metadata": meta}


def render(cfg, inventory, versions):
    users = {x["name"]: x for x in inventory["users"] or [] if x.get("state") != "absent"}
    groups = {x["name"]: x for x in inventory["groups"] or [] if x.get("state") != "absent"}
    local = {("User", x["email"]) for x in users.values()} | {
        ("Group", x["claim_name"]) for x in groups.values()
    }
    desired, absent, policies = {}, set(), {}

    def add(obj, is_absent=False):
        key = identity(obj)
        require(key not in desired and key not in absent, "Two entries render the same API object")
        if is_absent:
            absent.add(key)
        else:
            desired[key] = obj

    for section, kind in [("users", "User"), ("groups", "Group")]:
        for entry in inventory[section] or []:
            obj = make(cfg, versions[kind], kind, entry["name"], "", section)
            if entry.get("allow_collision"):
                obj["metadata"]["annotations"][
                    "user-authz.deckhouse.io/allow-authorization-rule-collision"
                ] = "true"
            if entry.get("state") == "absent":
                add(obj, True)
                continue
            if kind == "User":
                obj["spec"] = {"email": entry["email"]}
                if entry.get("password_hash"):
                    obj["spec"]["password"] = base64.b64encode(
                        entry["password_hash"].encode("ascii")
                    ).decode("ascii")
                policies[identity(obj)] = entry.get("password_policy", "on_create")
            else:
                obj["spec"] = {
                    "name": entry["claim_name"],
                    "members": [{"kind": "User", "name": n} for n in sorted(entry["members"])],
                }
            add(obj)
    for grant in inventory["grants"] or []:
        basic = grant["backend"] == "deckhouse"
        scope = grant["scope"]
        namespaces = scope.get("namespaces", [""])
        kind = (
            ("AuthorizationRule" if basic else "RoleBinding")
            if "namespaces" in scope
            else ("ClusterAuthorizationRule" if basic else "ClusterRoleBinding")
        )
        subjects = []
        for sub in grant.get("subjects", []):
            actual = {k: v for k, v in sub.items() if k != "source"}
            if sub["source"] == "static":
                catalog = users if sub["kind"] == "User" else groups
                require(
                    sub["name"] in catalog, "Static subject must reference a present local identity"
                )
                actual["name"] = catalog[sub["name"]][
                    "email" if sub["kind"] == "User" else "claim_name"
                ]
            elif sub["source"] == "external":
                require(
                    (sub["kind"], sub["name"]) not in local, "Local/external identity collision"
                )
            if not basic and sub["kind"] != "ServiceAccount":
                actual["apiGroup"] = "rbac.authorization.k8s.io"
            subjects.append(actual)
        require(
            len({canonical(s) for s in subjects}) == len(subjects), "Duplicate effective subjects"
        )
        for ns in namespaces:
            name = grant.get("target_name") or generated_name(cfg, grant, kind, ns)
            obj = make(cfg, versions[kind], kind, name, ns, "grants", grant["id"])
            if grant.get("state") == "absent":
                add(obj, True)
                continue
            if basic:
                obj["spec"] = {
                    "subjects": sorted_items(subjects),
                    "accessLevel": grant["accessLevel"],
                    "portForwarding": grant.get("options", {}).get("portForwarding", False),
                    "allowScale": grant.get("options", {}).get("allowScale", False),
                }
                if "namespace_selector" in scope:
                    obj["spec"]["namespaceSelector"] = {
                        "labelSelector": copy.deepcopy(scope["namespace_selector"])
                    }
                elif scope.get("cluster") and scope["include_system_namespaces"]:
                    obj["spec"]["namespaceSelector"] = {"matchAny": True}
            else:
                obj["subjects"] = sorted_items(subjects)
                obj["roleRef"] = dict(grant["roleRef"], apiGroup="rbac.authorization.k8s.io")
            add(obj)
    return desired, absent, policies


def clean(obj):
    """Allowlist public fields; never expose passwords, arbitrary annotations or status."""
    if obj is None:
        return None
    result = {k: copy.deepcopy(obj[k]) for k in ("apiVersion", "kind") if k in obj}
    meta = obj.get("metadata", {})
    result["metadata"] = {
        k: meta[k] for k in ("name", "namespace", "uid", "resourceVersion") if k in meta
    }
    for k in ("subjects", "roleRef"):
        if k in obj:
            result[k] = copy.deepcopy(obj[k])
    if "spec" in obj:
        allowed = [
            "subjects",
            "accessLevel",
            "portForwarding",
            "allowScale",
            "namespaceSelector",
            "allowAccessToSystemNamespaces",
            "limitNamespaces",
            "additionalRoles",
        ]
        if obj.get("kind") == "User":
            allowed = ["email", "ttl", "groups", "userID"]
        elif obj.get("kind") == "Group":
            allowed = ["name", "members"]
        result["spec"] = {k: copy.deepcopy(v) for k, v in obj["spec"].items() if k in allowed}
    return result


def normalized(obj):
    result = copy.deepcopy(obj)

    def subjects(items, rbac=False):
        for item in items:
            if item.get("kind") == "ServiceAccount":
                if item.get("apiGroup") == "":
                    item.pop("apiGroup")
            elif item.get("kind") in ("User", "Group"):
                if item.get("namespace") == "":
                    item.pop("namespace")
                if rbac:
                    item.setdefault("apiGroup", "rbac.authorization.k8s.io")
                elif item.get("apiGroup") in ("", "rbac.authorization.k8s.io"):
                    item.pop("apiGroup")
        return sorted_items(items)

    if "subjects" in result:
        result["subjects"] = subjects(result["subjects"], rbac=True)
    if "spec" in result:
        if "subjects" in result["spec"]:
            result["spec"]["subjects"] = subjects(result["spec"]["subjects"])
        if "members" in result["spec"]:
            result["spec"]["members"] = sorted_items(result["spec"]["members"])
    return result


def selector_matches(selector, labels):
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for expr in selector.get("matchExpressions", []):
        key, op, values = expr["key"], expr["operator"], expr.get("values", [])
        if op == "In" and (key not in labels or labels[key] not in values):
            return False
        if op == "NotIn" and key in labels and labels[key] in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True
