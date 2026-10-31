"""Read-before-write reconciliation with bounded ownership and optimistic concurrency."""
import copy
import hashlib
import json
import time
from urllib.parse import quote

from .client import APIError
from .schema import AccessError, require, mapping, names, string, boolean, validate_selector
from .render import (
    RBAC,
    KINDS,
    IDENTITIES,
    AUTHZ,
    SECTION,
    OPTIONAL,
    canonical,
    identity,
    keys,
    owned,
    controller_owned,
    clean,
    normalized,
    render,
    selector_matches,
)


def pointer(obj, path):
    value = obj
    require(isinstance(path, str) and path.startswith("/"), "JSON pointer must start with /")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, TypeError, ValueError, IndexError):
            return None
    return value


def escape(key):
    return key.replace("~", "~0").replace("/", "~1")


def unsupported(obj):
    kind = obj["kind"]
    spec = obj.get("spec", {})
    allowed = {
        "User": {"email", "password"},
        "Group": {"name", "members"},
        "AuthorizationRule": {"subjects", "accessLevel", "portForwarding", "allowScale"},
        "ClusterAuthorizationRule": {
            "subjects",
            "accessLevel",
            "portForwarding",
            "allowScale",
            "namespaceSelector",
        },
    }
    if kind in allowed:
        fields = sorted(set(spec) - allowed[kind])
        if kind == "Group" and any(m.get("kind") != "User" for m in spec.get("members", [])):
            fields.append("members:non-User")
        if kind in AUTHZ:
            if not isinstance(spec.get("subjects"), list) or not spec["subjects"]:
                fields.append("subjects")
            if kind == "ClusterAuthorizationRule" and "namespaceSelector" in spec:
                selector = spec["namespaceSelector"]
                try:
                    mapping(selector, ["matchAny", "labelSelector"], "namespaceSelector")
                    require(len(selector) == 1, "Invalid selector shape")
                    if "labelSelector" in selector:
                        validate_selector(selector["labelSelector"])
                    else:
                        require(selector.get("matchAny") is True, "Invalid matchAny")
                except AccessError:
                    fields.append("namespaceSelector")
        return fields
    return sorted(set(obj) - {"apiVersion", "kind", "metadata", "subjects", "roleRef", "status"})


def ref_matches(ref, obj, client, uid=False):
    kind, ns, name = identity(obj)
    info = client.resources[kind]
    return (
        ref.get("group") == obj["apiVersion"].split("/")[0]
        and ref.get("resource") == info["plural"]
        and ref.get("namespace", "") == ns
        and ref.get("name") == name
        and (not uid or ref.get("uid") == obj["metadata"].get("uid"))
    )


def in_scope(obj, cfg):
    ns = obj["metadata"].get("namespace")
    mg = cfg["management"]
    if ns:
        return mg["namespaces"] is None or ns in mg["namespaces"]
    return mg["include_cluster_scoped"]


def protected_namespace(ns, cfg):
    safe = cfg["safety"]
    return ns not in safe["allowed_protected_namespaces"] and (
        ns in safe["protected_namespaces"]
        or any(ns.startswith(p) for p in safe["protected_namespace_prefixes"])
    )


def patch_for(old, desired, cfg, policy="managed"):
    """Only known desired fields, plus optional authz scope fields owned by this role."""
    old, desired = normalized(old), normalized(desired)
    meta = old["metadata"]
    ops = [
        {"op": "test", "path": "/metadata/uid", "value": meta["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": meta["resourceVersion"]},
    ]
    for field in ("labels", "annotations"):
        current = meta.get(field)
        if current is None:
            ops.append(
                {"op": "add", "path": "/metadata/" + field, "value": desired["metadata"][field]}
            )
        else:
            for key, value in desired["metadata"][field].items():
                if current.get(key) != value:
                    ops.append(
                        {
                            "op": "add",
                            "path": "/metadata/%s/%s" % (field, escape(key)),
                            "value": value,
                        }
                    )
    collision = "user-authz.deckhouse.io/allow-authorization-rule-collision"
    if (
        collision in meta.get("annotations", {})
        and collision not in desired["metadata"]["annotations"]
    ):
        ops.append({"op": "remove", "path": "/metadata/annotations/" + escape(collision)})
    if "spec" in desired:
        require("spec" in old, "Existing object has no spec")
        for key, value in desired["spec"].items():
            if key == "password" and policy == "on_create":
                continue
            previous = old["spec"].get(key)
            if key == "password":
                previous = password_value(previous)
                value_compare = password_value(value)
            else:
                value_compare = value
            # CRD default values are not a meaningful update.
            if key in ("portForwarding", "allowScale") and previous is None:
                previous = False
            if previous != value_compare:
                ops.append({"op": "add", "path": "/spec/" + key, "value": value})
        if desired["kind"] in AUTHZ:
            for key in OPTIONAL:
                if key in old["spec"] and key not in desired["spec"]:
                    ops.append({"op": "remove", "path": "/spec/" + key})
    else:
        for key in ("subjects",):
            if old.get(key, []) != desired.get(key, []):
                ops.append({"op": "add", "path": "/" + key, "value": desired[key]})
    return ops if len(ops) > 2 else []


def password_value(value):
    import base64

    if isinstance(value, str) and value.startswith("$2"):
        return value
    try:
        return base64.b64decode(value, validate=True).decode("ascii")
    except (ValueError, TypeError, UnicodeError):
        return None


class Engine:
    def __init__(self, client, cfg, inventory):
        self.client, self.cfg, self.inventory = client, cfg, inventory
        self.actual, self.namespaces, self.operations = {}, {}, []
        self.warnings, self.completed = [], []
        self.profile, self.versions = {}, {"RoleBinding": RBAC, "ClusterRoleBinding": RBAC}
        self.guard_values = {}
        self.changed = False

    def _guard(self, path):
        obj = self.client.get(path)
        self.guard_values[path] = copy.deepcopy(obj)
        return obj

    def _profile(self):
        deck = self.cfg["deckhouse"]
        name = deck.get("compatibility_profile")
        require(
            name in deck["profiles"],
            "Deckhouse requires an explicitly configured compatibility profile",
        )
        p = deck["profiles"][name]
        mapping(
            p,
            [
                "deckhouse_image",
                "api_versions",
                "ready_checks",
                "authz_ready_condition",
                "password_updates",
                "mixed_backends",
                "granular_roles",
                "controller_markers",
            ],
            "compatibility profile",
            ["deckhouse_image", "api_versions", "ready_checks", "mixed_backends"],
        )
        string(p["deckhouse_image"], "deckhouse_image")
        boolean(p["mixed_backends"], "mixed_backends")
        boolean(p.get("password_updates", False), "password_updates")
        mapping(
            p["api_versions"],
            ["User", "Group", "AuthorizationRule", "ClusterAuthorizationRule"],
            "api_versions",
            ["User", "Group", "AuthorizationRule", "ClusterAuthorizationRule"],
        )
        for version in p["api_versions"].values():
            require(
                version in ("deckhouse.io/v1", "deckhouse.io/v1alpha1"),
                "Unsupported Deckhouse API version",
            )
        mapping(p["ready_checks"], ["user-authn", "user-authz"], "ready_checks")
        mapping(p.get("granular_roles", {}), p.get("granular_roles", {}), "granular_roles")
        for scopes in p.get("granular_roles", {}).values():
            names(scopes, "granular role scopes", False)
            require(set(scopes) <= {"namespace", "cluster"}, "Invalid granular role scope")
        mapping(
            p.get("controller_markers", {}),
            ["labels", "annotations", "name_prefixes"],
            "controller_markers",
        )
        for section in ("labels", "annotations"):
            markers = p.get("controller_markers", {}).get(section, {})
            require(
                isinstance(markers, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in markers.items()),
                "Controller markers must map keys to values",
            )
        names(p.get("controller_markers", {}).get("name_prefixes", []), "controller name_prefixes")
        deploy = self._guard("/apis/apps/v1/namespaces/d8-system/deployments/deckhouse")
        require(
            deploy.get("status", {}).get("observedGeneration", 0)
            >= deploy["metadata"].get("generation", 1),
            "Deckhouse Deployment has not reconciled",
        )
        require(
            deploy.get("status", {}).get("availableReplicas", 0) > 0,
            "Deckhouse Deployment is unavailable",
        )
        images = [
            c["image"]
            for c in deploy["spec"]["template"]["spec"]["containers"]
            if c["name"] == "deckhouse"
        ]
        require(
            images == [p["deckhouse_image"]],
            "Deckhouse image does not match the compatibility profile",
        )
        replicas = deploy.get("spec", {}).get("replicas", 1)
        require(
            replicas > 0
            and deploy.get("status", {}).get("updatedReplicas", 0) >= replicas
            and deploy.get("status", {}).get("readyReplicas", 0) >= replicas,
            "Deckhouse Deployment rollout is incomplete",
        )
        self.profile = p
        self.versions.update(p["api_versions"])

    def _module(self, name):
        obj = self._guard("/apis/deckhouse.io/v1alpha1/moduleconfigs/" + name)
        require(
            obj.get("spec", {}).get("enabled") is not False,
            "Required Deckhouse module is disabled: " + name,
        )
        checks = self.profile["ready_checks"].get(name)
        require(
            isinstance(checks, list) and bool(checks),
            "Profile must provide readiness probes for " + name,
        )
        for check in checks:
            mapping(
                check,
                ["path", "pointer", "equals", "minimum"],
                "readiness check",
                ["path", "pointer"],
            )
            require(
                ("equals" in check) != ("minimum" in check),
                "Readiness check needs equals or minimum",
            )
            string(check["path"], "readiness check.path")
            obj_ready = self._guard(check["path"])
            value = pointer(obj_ready, check["pointer"])
            ok = (
                value == check["equals"]
                if "equals" in check
                else (
                    type(value) in (int, float)
                    and type(check["minimum"]) in (int, float)
                    and value >= check["minimum"]
                )
            )
            require(ok, "Deckhouse readiness probe failed: " + name)
        return obj

    def prepare(self, export=False):
        c, cfg = self.client, self.cfg
        self.cluster_version = c.get("/version").get("gitVersion")
        c.get("/api")
        c.get("/apis")
        c.discover("v1", "Namespace", False)
        namespaces = c.list(c.path("Namespace"))
        self.namespaces = {o["metadata"]["name"]: o for o in namespaces}
        require(
            "kube-system" in self.namespaces
            and self.namespaces["kube-system"]["metadata"].get("uid"),
            "Cannot identify cluster using kube-system UID",
        )
        self.cluster_uid = self.namespaces["kube-system"]["metadata"]["uid"]
        for kind in ("RoleBinding", "ClusterRoleBinding"):
            c.discover(RBAC, kind, kind == "RoleBinding")
        c.discover(RBAC, "Role", True)
        c.discover(RBAC, "ClusterRole", False)
        if cfg["platform"] == "deckhouse":
            self._profile()
            self.authz_config = self._module("user-authz")
            identity_needed = export or any(
                self.inventory[k] is not None for k in ("users", "groups")
            )
            if identity_needed:
                self._module("user-authn")
            for kind in AUTHZ + (IDENTITIES if identity_needed else ()):
                c.discover(self.versions[kind], kind, kind == "AuthorizationRule")
                # Read CRD schemas: existence alone is never treated as module readiness.
                info = c.resources[kind]
                crd = self._guard(
                    "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/"
                    + info["plural"]
                    + ".deckhouse.io"
                )
                versions = crd.get("spec", {}).get("versions", [])
                v = [
                    v
                    for v in versions
                    if v.get("name") == self.versions[kind].split("/")[1] and v.get("served")
                ]
                require(
                    len(v) == 1 and v[0].get("schema", {}).get("openAPIV3Schema"),
                    "Missing served CRD schema: " + kind,
                )
                self._validate_crd_fields(kind, v[0]["schema"]["openAPIV3Schema"])
        for kind in KINDS:
            if kind in c.resources:
                for obj in c.list(c.path(kind)):
                    require(obj.get("kind", kind) == kind, "Wrong kind in API list")
                    obj["kind"] = kind
                    obj.setdefault("apiVersion", self.versions[kind])
                    key = identity(obj)
                    require(key not in self.actual, "Duplicate object in paginated API read")
                    require(
                        obj["metadata"].get("uid") and obj["metadata"].get("resourceVersion"),
                        "Object missing concurrency metadata",
                    )
                    self.actual[key] = obj
        if export:
            return
        desired, self.absent, self.policies = render(cfg, self.inventory, self.versions)
        self.desired = desired
        self._validate_desired()
        self._build_plan()
        self._validate_deletions()
        self._identity_references()
        digest_input = {
            "config": self._public_config(),
            "inventory": {
                "desired": [
                    dict(
                        clean(desired[k]),
                        managed_metadata={
                            m: desired[k]["metadata"][m] for m in ("labels", "annotations")
                        },
                    )
                    for k in sorted(desired)
                ],
                "policies": [(list(k), v) for k, v in sorted(self.policies.items())],
                "absent": sorted(self.absent),
            },
            "cluster_uid": self.cluster_uid,
            "cluster_version": self.cluster_version,
            "observed": [clean(self.actual[k]) for k in sorted(self.actual)],
            "guards": {
                p: {
                    "uid": o.get("metadata", {}).get("uid"),
                    "rv": o.get("metadata", {}).get("resourceVersion"),
                }
                for p, o in self.guard_values.items()
            },
        }
        self.digest = hashlib.sha256(canonical(digest_input).encode("utf-8")).hexdigest()
        expected = cfg.get("expected_plan_digest")
        require(not expected or expected == self.digest, "Plan digest changed; generate a new plan")
        return self.report()

    def _public_config(self):
        result = copy.deepcopy(self.cfg)
        result.pop("expected_plan_digest", None)
        result["mode"] = "dry"
        result["connection"] = {
            k: v for k, v in result["connection"].items() if k in ("context", "validate_tls")
        }
        return result

    def _validate_crd_fields(self, kind, schema):
        props = schema.get("properties", {}).get("spec", {}).get("properties", {})
        fields = {
            "User": ["email", "password"],
            "Group": ["name", "members"],
            "AuthorizationRule": ["subjects", "accessLevel", "allowScale", "portForwarding"],
            "ClusterAuthorizationRule": ["subjects", "accessLevel", "allowScale", "portForwarding"],
        }[kind]
        require(set(fields) <= set(props), "Unsupported CRD schema: " + kind)
        if kind in AUTHZ:
            self.__dict__.setdefault("level_enums", {})[kind] = props["accessLevel"].get("enum", [])
            if kind == "ClusterAuthorizationRule":
                self.selector_supported = "namespaceSelector" in props

    def _is_controller(self, obj):
        if controller_owned(obj):
            return True
        markers = self.profile.get("controller_markers", {})
        meta = obj["metadata"]
        for field in ("labels", "annotations"):
            if any(meta.get(field, {}).get(k) == v for k, v in markers.get(field, {}).items()):
                return True
        return any(meta["name"].startswith(p) for p in markers.get("name_prefixes", []))

    def _protected(self, obj):
        require(not obj["metadata"].get("deletionTimestamp"), "Object is already terminating")
        require(not self._is_controller(obj), "Refusing to modify controller-owned " + obj["kind"])
        require(
            not any(
                ref_matches(r, obj, self.client) for r in self.cfg["safety"]["protected_objects"]
            ),
            "Object is explicitly protected",
        )
        ns = obj["metadata"].get("namespace")
        require(
            not ns or not protected_namespace(ns, self.cfg), "Namespace is protected: " + (ns or "")
        )

    def _validate_desired(self):
        cfg, c = self.cfg, self.client
        for ns in cfg["management"]["namespaces"] or []:
            require(ns in self.namespaces, "Management namespace does not exist")
        backends = {
            x["backend"] for x in self.inventory["grants"] or [] if x.get("state") != "absent"
        }
        if cfg["platform"] == "deckhouse" and len(backends) > 1:
            require(
                self.profile.get("mixed_backends"),
                "Profile does not validate mixed RBAC/basic backends",
            )
            self.warnings.append("RBAC/basic migration may temporarily overlap permissions")
        if cfg["platform"] == "deckhouse":
            subject_backends = {}
            for obj in list(self.actual.values()) + list(self.desired.values()):
                if obj["kind"] in IDENTITIES or identity(obj) in self.absent:
                    continue
                backend = "deckhouse" if obj["kind"] in AUTHZ else "rbac"
                subjects = obj.get("subjects", obj.get("spec", {}).get("subjects", []))
                for sub in subjects:
                    subject_backends.setdefault(
                        (sub.get("kind"), sub.get("namespace", ""), sub.get("name")), set()
                    ).add(backend)
            if any(len(value) > 1 for value in subject_backends.values()):
                require(
                    self.profile.get("mixed_backends"),
                    "Existing grants require a validated mixed_backends profile",
                )
                self.warnings.append(
                    "A subject has grants from both RBAC and basic authorization; effective rights depend on the profile"
                )
        for key, obj in self.desired.items():
            require(in_scope(obj, cfg), "Desired object is outside management scope")
            self._protected(obj)
            kind, ns, _ = key
            require(not ns or ns in self.namespaces, "Target namespace does not exist")
            if kind in ("RoleBinding", "ClusterRoleBinding"):
                ref = obj["roleRef"]
                path = c.path(ref["kind"], ns if ref["kind"] == "Role" else None, ref["name"])
                self._guard(path)
                if cfg["platform"] == "deckhouse" and ref["name"].startswith(
                    ("d8:", "user-authz:")
                ):
                    scope = "namespace" if ns else "cluster"
                    require(
                        scope in self.profile.get("granular_roles", {}).get(ref["name"], []),
                        "Deckhouse role/scope is not approved in profile",
                    )
            if kind in AUTHZ:
                spec = obj["spec"]
                enum = self.level_enums[kind]
                require(
                    not enum or spec["accessLevel"] in enum, "accessLevel is not supported by CRD"
                )
                for sub in spec["subjects"]:
                    require(
                        sub["kind"] in ("User", "Group", "ServiceAccount"),
                        "Unsupported Deckhouse subject",
                    )
                if kind == "ClusterAuthorizationRule":
                    multi = (
                        self.authz_config.get("spec", {})
                        .get("settings", {})
                        .get("enableMultiTenancy")
                        is True
                    )
                    # All CAR scopes carry an explicit promise about namespaces.
                    require(
                        multi, "ClusterAuthorizationRule requires verified enableMultiTenancy: true"
                    )
                    if "namespaceSelector" in spec:
                        require(self.selector_supported, "CRD does not support namespaceSelector")
                        selector = spec["namespaceSelector"].get("labelSelector")
                        if selector:
                            self.warnings.append(
                                "Dynamic namespace selector can match future namespaces"
                            )
                            for name, namespace in self.namespaces.items():
                                if selector_matches(
                                    selector, namespace["metadata"].get("labels", {})
                                ):
                                    require(
                                        not protected_namespace(name, cfg),
                                        "Selector matches a protected namespace",
                                    )
                condition = self.profile.get("authz_ready_condition")
                require(
                    condition or any(check["allowed"] for check in cfg["access_checks"]),
                    "Profile without authz Ready condition requires positive access_checks",
                )
            subjects = obj.get("subjects", obj.get("spec", {}).get("subjects", []))
            for sub in subjects:
                if sub["kind"] == "ServiceAccount":
                    require(
                        sub["namespace"] in self.namespaces,
                        "ServiceAccount namespace does not exist",
                    )
                    self._guard(
                        "/api/v1/namespaces/%s/serviceaccounts/%s"
                        % (quote(sub["namespace"], safe=""), quote(sub["name"], safe=""))
                    )
            if kind == "User":
                if key not in self.actual:
                    require("password" in obj["spec"], "New local User requires password_hash")
                elif self.policies[key] == "managed":
                    require(
                        self.profile.get("password_updates") and "password" in obj["spec"],
                        "Managed password update requires password_hash and profile.password_updates",
                    )
        # Detect preexisting privilege collisions before creating or renaming identities.
        all_rules = [o for o in self.actual.values() if o["kind"] in AUTHZ]
        for key, obj in self.desired.items():
            if key[0] not in IDENTITIES:
                continue
            field = "email" if key[0] == "User" else "name"
            old = self.actual.get(key)
            if old and old.get("spec", {}).get(field) == obj["spec"][field]:
                continue
            subject = (key[0], obj["spec"][field])
            collision = any(
                any(
                    (s.get("kind"), s.get("name")) == subject
                    for s in r.get("spec", {}).get("subjects", [])
                )
                for r in all_rules
            )
            require(
                not collision
                or obj["metadata"]["annotations"].get(
                    "user-authz.deckhouse.io/allow-authorization-rule-collision"
                )
                == "true",
                "Local identity collides with an existing authorization rule; explicit allow_collision required",
            )

    def _authorise(self, old):
        self._protected(old)
        if owned(old, self.cfg):
            return
        k = keys(self.cfg)
        labels = old["metadata"].get("labels", {})
        require(
            k["owner"] not in labels and k["managed-by"] not in labels,
            "Object has another or incomplete owner",
        )
        require(
            any(ref_matches(r, old, self.client, True) for r in self.cfg["management"]["adoption"]),
            "Unmanaged object requires explicit UID-bound adoption",
        )
        require(not unsupported(old), "Cannot adopt object with unsupported fields")

    def _build_plan(self):
        for key in sorted(self.desired):
            obj, old = self.desired[key], self.actual.get(key)
            if old is None:
                self.operations.append(
                    {"action": "create", "key": key, "desired": obj, "old": None}
                )
                continue
            self._authorise(old)
            require(not unsupported(old), "Managed object contains unsupported permission fields")
            replacement = (
                key[0] in ("RoleBinding", "ClusterRoleBinding")
                and old.get("roleRef") != obj["roleRef"]
            )
            if replacement:
                require(
                    self.cfg["safety"]["allow_binding_replacement"],
                    "roleRef replacement requires allow_binding_replacement",
                )
                self.warnings.append("Binding replacement interrupts access until recreated")
                action, patch = "replace", []
            else:
                patch = patch_for(old, obj, self.cfg, self.policies.get(key, "managed"))
                action = "update" if patch else "noop"
            self.operations.append(
                {"action": action, "key": key, "desired": obj, "old": old, "patch": patch}
            )
        deletions = set(self.absent)
        if self.cfg["management"]["prune"]:
            for section, entries in self.inventory.items():
                if entries is None:
                    continue
                require(
                    entries or self.cfg["safety"]["allow_empty_desired"],
                    "Empty desired section requires allow_empty_desired for prune",
                )
                for key, obj in self.actual.items():
                    if (
                        SECTION[key[0]] == section
                        and owned(obj, self.cfg)
                        and in_scope(obj, self.cfg)
                        and key not in self.desired
                    ):
                        deletions.add(key)
        for key in sorted(deletions):
            old = self.actual.get(key)
            if old is None:
                continue
            require(in_scope(old, self.cfg), "Deletion is outside management scope")
            require(
                owned(old, self.cfg), "Unmanaged object cannot be deleted, including via adoption"
            )
            self._protected(old)
            if key[0] in IDENTITIES:
                require(
                    self.cfg["management"]["prune_identities"],
                    "Identity deletion requires prune_identities",
                )
            self.operations.append({"action": "delete", "key": key, "desired": None, "old": old})
        priority = {"User": 0, "Group": 1}
        self.operations.sort(
            key=lambda o: (
                1 if o["action"] == "delete" else 0,
                (2 if o["key"][0] == "User" else 1 if o["key"][0] == "Group" else 0)
                if o["action"] == "delete"
                else priority.get(o["key"][0], 2),
                o["key"],
            )
        )

    def _validate_deletions(self):
        count = sum(o["action"] in ("delete", "replace") for o in self.operations)
        require(
            count <= self.cfg["safety"]["max_deletions"],
            "Deletion limit exceeded (including replacements)",
        )
        for op in self.operations:
            if op["action"] == "noop":
                continue
            if op["key"][0] in AUTHZ:
                require(
                    self.cfg["deckhouse"]["basic_authz"],
                    "Managing or pruning basic authorization requires basic_authz: true",
                )
            verbs = set(self.client.resources[op["key"][0]]["verbs"])
            needed = (
                {"create"}
                if op["action"] == "create"
                else {"patch"}
                if op["action"] == "update"
                else ({"delete", "create"} if op["action"] == "replace" else {"delete"})
            )
            require(needed <= verbs, "API does not support planned operation")

    def _identity_references(self):
        final = dict(self.actual)
        for op in self.operations:
            if op["action"] == "delete":
                final.pop(op["key"], None)
            elif op["desired"]:
                final[op["key"]] = op["desired"]
        removed = [
            o["old"]
            for o in self.operations
            if o["action"] == "delete" and o["key"][0] in IDENTITIES
        ]
        # Renames can orphan old grants just as deletions can.
        for op in self.operations:
            if op["old"] and op["desired"] and op["key"][0] in IDENTITIES:
                field = "email" if op["key"][0] == "User" else "name"
                if op["old"]["spec"].get(field) != op["desired"]["spec"].get(field):
                    removed.append(op["old"])
        for obj in removed:
            kind = obj["kind"]
            effective = obj["spec"]["email" if kind == "User" else "name"]
            for other in final.values():
                subjects = other.get("subjects", other.get("spec", {}).get("subjects", []))
                require(
                    not any(s.get("kind") == kind and s.get("name") == effective for s in subjects),
                    "Identity still referenced by a remaining grant",
                )
                if kind == "Group" and other["kind"] == "User":
                    require(
                        effective not in other.get("spec", {}).get("groups", []),
                        "Identity still referenced by deprecated User.spec.groups",
                    )
                if other["kind"] == "Group":
                    require(
                        not any(
                            s.get("kind") == kind and s.get("name") == obj["metadata"]["name"]
                            for s in other.get("spec", {}).get("members", [])
                        ),
                        "Identity still referenced by a remaining group",
                    )

    def report(self):
        changes = []
        counts = {a: 0 for a in ("create", "update", "replace", "delete", "noop")}
        for op in self.operations:
            counts[op["action"]] += 1
            change = {
                "action": op["action"],
                "kind": op["key"][0],
                "namespace": op["key"][1],
                "name": op["key"][2],
                "before": clean(op["old"]),
                "after": clean(op["desired"]),
                "privilege_change": "increase"
                if op["action"] == "create"
                else "decrease"
                if op["action"] == "delete"
                else "unknown",
            }
            if op["action"] == "noop":
                change["privilege_change"] = "unknown"
            if any(p.get("path") == "/spec/password" for p in op.get("patch", [])):
                change["password_changed"] = True
            if op["action"] not in ("noop", "create", "delete"):
                before, after = clean(op["old"]), clean(op["desired"])
                reasons = []
                old_spec, new_spec = before.get("spec", {}), after.get("spec", {})
                if before.get("roleRef") != after.get("roleRef"):
                    reasons.append("role_ref_changed")
                if before.get("subjects", old_spec.get("subjects")) != after.get(
                    "subjects", new_spec.get("subjects")
                ):
                    reasons.append("subjects_changed")
                if old_spec.get("members") != new_spec.get("members"):
                    reasons.append("identity_membership_changed")
                for field in (
                    "accessLevel",
                    "portForwarding",
                    "allowScale",
                    "namespaceSelector",
                    "email",
                    "name",
                ):
                    if old_spec.get(field) != new_spec.get(field):
                        reasons.append(field + "_changed")
                change["privilege_change_reasons"] = reasons
            if op["desired"]:
                collision = "user-authz.deckhouse.io/allow-authorization-rule-collision"
                change["allow_collision"] = {
                    "before": (op["old"] or {})
                    .get("metadata", {})
                    .get("annotations", {})
                    .get(collision)
                    == "true",
                    "after": op["desired"]["metadata"].get("annotations", {}).get(collision)
                    == "true",
                }
                change["adoption"] = bool(op["old"] and not owned(op["old"], self.cfg))
            changes.append(change)
        return {
            "cluster_uid": getattr(self, "cluster_uid", None),
            "cluster_version": getattr(self, "cluster_version", None),
            "owner": self.cfg["management"]["owner"],
            "schema_version": 1,
            "profile": self.cfg["deckhouse"].get("compatibility_profile"),
            "summary": counts,
            "planned": {
                title: [
                    {k: c[k] for k in ("action", "kind", "namespace", "name")}
                    for c in changes if c["action"] in actions
                ]
                for title, actions in (
                    ("add", ("create",)),
                    ("change", ("update", "replace")),
                    ("remove", ("delete",)),
                )
            },
            "changes": changes,
            "warnings": sorted(set(self.warnings)),
            "digest": getattr(self, "digest", None),
        }

    def _same_observation(self, observed, now):
        require(
            now is not None
            and now["metadata"].get("uid") == observed["metadata"]["uid"]
            and now["metadata"].get("resourceVersion") == observed["metadata"]["resourceVersion"],
            "Object changed since plan; generate a new plan",
        )

    def _recheck(self):
        # Guards cover roles, CRDs, module settings and platform health/configuration.
        for path, old in self.guard_values.items():
            now = self.client.get(path)
            if old.get("metadata", {}).get("resourceVersion"):
                self._same_observation(old, now)
            else:
                require(now == old, "Cluster capability changed since plan")
        current_cluster = self.client.get(self.client.path("Namespace", name="kube-system"))
        require(current_cluster["metadata"]["uid"] == self.cluster_uid, "Cluster identity changed")
        # Re-list all permission sources, including unmanaged ones, before first write.
        now = {}
        for kind in KINDS:
            if kind in self.client.resources:
                for obj in self.client.list(self.client.path(kind)):
                    obj["kind"] = kind
                    now[identity(obj)] = obj
        require(set(now) == set(self.actual), "Permission objects changed since plan")
        for key, old in self.actual.items():
            self._same_observation(old, now[key])
        current_ns = self.client.list(self.client.path("Namespace"))
        old_labels = {n: o["metadata"].get("labels", {}) for n, o in self.namespaces.items()}
        require(
            {o["metadata"]["name"]: o["metadata"].get("labels", {}) for o in current_ns}
            == old_labels,
            "Namespace set or labels changed since plan",
        )

    def _delete(self, old):
        kind, ns, name = identity(old)
        path = self.client.path(kind, ns, name)
        self._same_observation(old, self.client.get(path, missing=True))
        body = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {
                "uid": old["metadata"]["uid"],
                "resourceVersion": old["metadata"]["resourceVersion"],
            },
        }
        try:
            self.client.request("DELETE", path, body)
            self.changed = True
        except AccessError as exc:
            if isinstance(exc, APIError) and exc.status < 500 and exc.status != 429:
                raise
            now = self.client.get(path, missing=True)
            if now is None:
                self.changed = True
                return
            if now["metadata"].get("uid") == old["metadata"]["uid"] and now["metadata"].get(
                "deletionTimestamp"
            ):
                self.changed = True
            else:
                raise
        deadline = time.monotonic() + self.cfg["wait_timeout_seconds"]
        while time.monotonic() < deadline:
            now = self.client.get(path, missing=True)
            if now is None:
                return
            require(
                now["metadata"].get("uid") == old["metadata"]["uid"],
                "Deleted object was recreated by another writer",
            )
            time.sleep(0.2)
        raise AccessError("Timed out waiting for deletion; finalizers are not removed")

    def _write(self, op, dry=False):
        c = self.client
        action, obj, old = op["action"], op["desired"], op["old"]
        kind, ns, name = op["key"]
        path = c.path(kind, ns, name)
        query = {"dryRun": "All"} if dry else None
        if action in ("create", "replace"):
            require(c.get(path, missing=True) is None, "Create target appeared since plan")
            try:
                result = c.request("POST", c.path(kind, ns), obj, query=query)
                if not dry:
                    self.changed = True
            except AccessError as exc:
                if dry or (isinstance(exc, APIError) and exc.status < 500 and exc.status != 429):
                    raise
                result = c.get(path, missing=True)
                if (
                    result is None
                    or not owned(result, self.cfg)
                    or patch_for(result, obj, self.cfg, "managed")
                ):
                    raise
                self.changed = True
            require(result.get("metadata", {}).get("uid"), "Write response missing UID")
            return result
        self._same_observation(old, c.get(path, missing=True))
        try:
            result = c.request("PATCH", path, op["patch"], query=query)
            if not dry:
                self.changed = True
        except AccessError as exc:
            if dry or (isinstance(exc, APIError) and exc.status < 500 and exc.status != 429):
                raise
            result = c.get(path, missing=True)
            if (
                result is None
                or result["metadata"].get("uid") != old["metadata"]["uid"]
                or patch_for(result, obj, self.cfg, self.policies.get(op["key"], "managed"))
            ):
                raise
            self.changed = True
        require(
            result.get("metadata", {}).get("uid") == old["metadata"]["uid"],
            "Update response UID changed",
        )
        return result

    def server_validate(self):
        for op in self.operations:
            if op["action"] in ("create", "update"):
                self._write(op, dry=True)
            elif op["action"] == "replace":
                self.warnings.append("Replacement cannot be fully server-validated before deletion")

    def _ready(self, obj):
        kind, ns, name = identity(obj)
        if kind not in AUTHZ:
            return
        condition = self.profile.get("authz_ready_condition")
        if not condition:
            self.warnings.append(
                "Deckhouse access is verified by configured access_checks, not object presence"
            )
            return
        deadline = time.monotonic() + self.cfg["wait_timeout_seconds"]
        while time.monotonic() < deadline:
            current = self.client.get(self.client.path(kind, ns, name))
            require(
                current["metadata"]["uid"] == obj["metadata"]["uid"],
                "Authorization object UID changed during readiness wait",
            )
            for cond in current.get("status", {}).get("conditions", []):
                generation = cond.get(
                    "observedGeneration", current.get("status", {}).get("observedGeneration", 0)
                )
                if (
                    cond.get("type") == condition
                    and cond.get("status") == "True"
                    and generation >= current["metadata"].get("generation", 1)
                ):
                    return
            time.sleep(0.2)
        raise AccessError("Deckhouse authorization resource did not become Ready")

    def _access_checks(self, positive_only=False):
        deadline = time.monotonic() + self.cfg["wait_timeout_seconds"]
        for check in self.cfg["access_checks"]:
            if positive_only and not check["allowed"]:
                continue
            while True:
                body = {
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SubjectAccessReview",
                    "spec": {k: v for k, v in check.items() if k != "allowed"},
                }
                result = self.client.request(
                    "POST", "/apis/authorization.k8s.io/v1/subjectaccessreviews", body
                )
                status = result.get("status", {})
                if not status.get("evaluationError") and status.get("allowed") is check["allowed"]:
                    break
                require(
                    time.monotonic() < deadline, "SubjectAccessReview did not match expected access"
                )
                time.sleep(0.2)

    def apply(self):
        self._recheck()
        if self.cfg["server_validation"]:
            self.server_validate()
        verified_before_prune = False
        for op in self.operations:
            if op["action"] == "delete" and not verified_before_prune:
                self._access_checks(positive_only=True)
                verified_before_prune = True
            if op["action"] == "noop":
                if op["desired"]["kind"] in AUTHZ:
                    self._ready(op["old"])
                continue
            if op["action"] in ("delete", "replace"):
                self._delete(op["old"])
            if op["action"] != "delete":
                result = self._write(op)
                # Verify all owned fields read back; waiting for controllers is separate.
                require(
                    not patch_for(
                        result, op["desired"], self.cfg, self.policies.get(op["key"], "managed")
                    ),
                    "API did not retain desired managed fields",
                )
                self._ready(result)
            self.completed.append(
                {
                    "action": op["action"],
                    "kind": op["key"][0],
                    "namespace": op["key"][1],
                    "name": op["key"][2],
                }
            )
        if self.cfg["access_checks"]:
            self._access_checks()
        return self.changed
