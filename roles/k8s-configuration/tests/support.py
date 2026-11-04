"""Stateful Kubernetes API fixture. Not a replacement for a live Deckhouse test."""
import copy
import sys
from pathlib import Path
from urllib.parse import quote

ROLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROLE / "module_utils"))
from access_manager.client import Client, APIError
from access_manager.render import RBAC, identity
from access_manager.schema import AccessError, validate_config, validate_inventory
from access_manager.reconcile import Engine

HASH = "$2b$12$" + "a" * 53
INFO = {
    "Namespace": ("v1", "namespaces", False),
    "ServiceAccount": ("v1", "serviceaccounts", True),
    "Role": (RBAC, "roles", True),
    "ClusterRole": (RBAC, "clusterroles", False),
    "RoleBinding": (RBAC, "rolebindings", True),
    "ClusterRoleBinding": (RBAC, "clusterrolebindings", False),
    "User": ("deckhouse.io/v1", "users", False),
    "Group": ("deckhouse.io/v1alpha1", "groups", False),
    "AuthorizationRule": ("deckhouse.io/v1alpha1", "authorizationrules", True),
    "ClusterAuthorizationRule": ("deckhouse.io/v1", "clusterauthorizationrules", False),
    "Module": ("deckhouse.io/v1alpha1", "modules", False),
    "ModuleConfig": ("deckhouse.io/v1alpha1", "moduleconfigs", False),
}
VERBS = ["get", "list", "create", "patch", "delete"]


def flat_settings(value, prefix):
    """Translate test payloads into the public flat Ansible interface."""
    value = copy.deepcopy(value)
    if prefix == "k8s_configuration_config":
        deck = value.get("deckhouse", {})
        profile = deck.pop("profiles", {}).get(deck.pop("compatibility_profile", None), {})
        api_names = {"User": "user", "Group": "group", "AuthorizationRule": "authorization_rule",
                     "ClusterAuthorizationRule": "cluster_authorization_rule"}
        if "api_versions" in profile:
            profile["api_versions"] = {api_names[k]: v for k, v in profile["api_versions"].items()}
        if "granular_roles" in profile:
            profile["granular_roles"] = [{"name": name, "scopes": scopes}
                                         for name, scopes in profile["granular_roles"].items()]
        for key in ("labels", "annotations"):
            if key in profile.get("controller_markers", {}):
                profile["controller_markers"][key] = [{"key": k, "value": v}
                                                     for k, v in profile["controller_markers"][key].items()]
        deck.update(profile)
        if "deckhouse" in value:
            value["deckhouse"] = deck
    result = {}
    for key, item in value.items():
        name = prefix + "_" + key.replace("-", "_")
        if isinstance(item, dict):
            result.update(flat_settings(item, name))
        else:
            result[name] = item
    return result


def config(deckhouse=False, **extra):
    cfg = {"connection": {"kubeconfig": "/unused"}, "management": {"owner": "test"}}
    if deckhouse:
        probe = {
            "path": "/apis/apps/v1/namespaces/d8-user-authz/deployments/user-authz-controller",
            "pointer": "/status/availableReplicas",
            "minimum": 1,
        }
        cfg.update(
            platform="deckhouse",
            deckhouse={
                "basic_authz": True,
                "compatibility_profile": "fixture",
                "profiles": {
                    "fixture": {
                        "api_versions": {
                            k: INFO[k][0]
                            for k in (
                                "AuthorizationRule",
                                "ClusterAuthorizationRule",
                            )
                        },
                        "mixed_backends": True,
                        "authz_ready_condition": "Ready",
                        "ready_checks": {
                            "user-authz": [probe],
                        },
                        "granular_roles": {"d8:use:role:viewer": ["namespace"]},
                    }
                },
            },
        )
    for k, v in extra.items():
        if isinstance(v, dict) and k in cfg:
            cfg[k].update(v)
        else:
            cfg[k] = v
    return validate_config(cfg)


def grant(name="readers", **kw):
    result = {
        "id": name,
        "backend": "rbac",
        "subjects": [{"kind": "Group", "name": "readers"}],
        "roleRef": {"kind": "ClusterRole", "name": "view"},
        "scope": {"namespaces": ["dev"]},
    }
    result.update(kw)
    return result


class FakeAPI(Client):
    def __init__(self):
        self.resources = {}
        self.objects = {}
        self.calls = []
        self.serial = 0
        self.fail = None
        self.access_allowed = True
        self.page_size = 500
        for ns in ("kube-system", "dev", "test", "d8-user-authz", "d8-user-authn"):
            self.store(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": ns,
                        "labels": {
                            "kubernetes.io/metadata.name": ns,
                            "env": "review" if ns in ("dev", "test") else "system",
                        },
                    },
                }
            )
        for role in ("view", "edit", "cluster-admin", "d8:use:role:viewer"):
            self.store(
                {"apiVersion": RBAC, "kind": "ClusterRole", "metadata": {"name": role}, "rules": []}
            )
        self.store(
            {
                "apiVersion": RBAC,
                "kind": "Role",
                "metadata": {"name": "local", "namespace": "dev"},
                "rules": [],
            }
        )
        for module in ("user-authz", "user-authn"):
            self.store({
                "apiVersion": "deckhouse.io/v1alpha1", "kind": "Module",
                "metadata": {"name": module},
                "status": {"phase": "Ready", "conditions": [
                    {"type": "EnabledByModuleManager", "status": "True"},
                    {"type": "IsReady", "status": "True"},
                ]},
            })
            self.objects["/apis/deckhouse.io/v1alpha1/moduleconfigs/" + module] = {
                "metadata": {"uid": module, "resourceVersion": "1"},
                "spec": {"enabled": True, "settings": {"enableMultiTenancy": True}},
            }
        for ns, name in [
            ("d8-system", "deckhouse"),
            ("d8-user-authz", "user-authz-controller"),
            ("d8-user-authn", "dex"),
        ]:
            self.objects["/apis/apps/v1/namespaces/%s/deployments/%s" % (ns, name)] = {
                "metadata": {"uid": name, "generation": 1, "resourceVersion": "1"},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"name": "deckhouse", "image": "registry.invalid/deckhouse:v1.78.0"}
                            ]
                        }
                    }
                },
                "status": {
                    "observedGeneration": 1,
                    "availableReplicas": 1,
                    "updatedReplicas": 1,
                    "readyReplicas": 1,
                },
            }
        fields = {
            "User": ["email", "password"],
            "Group": ["name", "members"],
            "AuthorizationRule": ["subjects", "accessLevel", "allowScale", "portForwarding"],
            "ClusterAuthorizationRule": [
                "subjects",
                "accessLevel",
                "allowScale",
                "portForwarding",
                "namespaceSelector",
            ],
        }
        for kind, fs in fields.items():
            version, plural, _ = INFO[kind]
            self.objects[
                "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/"
                + plural
                + ".deckhouse.io"
            ] = {
                "metadata": {"uid": plural, "resourceVersion": "1"},
                "status": {"conditions": [{"type": "Established", "status": "True"}]},
                "spec": {
                    "versions": [
                        {
                            "name": version.split("/")[1],
                            "served": True,
                            "schema": {
                                "openAPIV3Schema": {
                                    "properties": {"spec": {"properties": {k: {} for k in fs}}}
                                }
                            },
                        }
                    ]
                },
            }

    def object_path(self, obj):
        version, plural, scoped = INFO[obj["kind"]]
        path = "/api/" + version if "/" not in version else "/apis/" + version
        ns = obj["metadata"].get("namespace")
        if ns:
            path += "/namespaces/" + ns
        return path + "/" + plural + "/" + quote(obj["metadata"]["name"], safe="")

    def store(self, obj):
        obj = copy.deepcopy(obj)
        self.serial += 1
        obj["metadata"].setdefault("uid", "uid-" + str(self.serial))
        obj["metadata"]["resourceVersion"] = str(self.serial)
        obj["metadata"].setdefault("generation", 1)
        if obj["kind"] in ("AuthorizationRule", "ClusterAuthorizationRule"):
            obj["status"] = {
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "True",
                        "observedGeneration": obj["metadata"]["generation"],
                    }
                ]
            }
        self.objects[self.object_path(obj)] = obj
        return copy.deepcopy(obj)

    def request(self, method, path, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body), query))
        if self.fail:
            self.fail(method, path, body)
        if method == "GET":
            if path == "/version":
                return {"gitVersion": "v1.30.0"}
            if path in ("/api", "/apis"):
                if path == "/api":
                    return {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]}
                groups = {}
                for version, _, _ in INFO.values():
                    if "/" in version:
                        group, v = version.split("/")
                        groups.setdefault(group, {})[v] = {"groupVersion": version, "version": v}
                return {
                    "kind": "APIGroupList", "apiVersion": "v1",
                    "groups": [
                        {"name": g, "versions": list(vs.values()),
                         "preferredVersion": list(vs.values())[0]}
                        for g, vs in groups.items()
                    ],
                }
            resources = [
                {"kind": k, "name": v[1], "namespaced": v[2], "verbs": VERBS}
                for k, v in INFO.items()
                if path == ("/api/" + v[0] if "/" not in v[0] else "/apis/" + v[0])
            ]
            if resources:
                return {"kind": "APIResourceList", "apiVersion": "v1",
                        "groupVersion": path.split("/", 2)[-1], "resources": resources}
            if path in self.objects:
                return copy.deepcopy(self.objects[path])
            collection = []
            known = False
            for kind, (version, plural, scoped) in INFO.items():
                base = "/api/" + version if "/" not in version else "/apis/" + version
                if (
                    path == base + "/" + plural
                    or path.startswith(base + "/namespaces/")
                    and path.endswith("/" + plural)
                ):
                    known = True
                    collection = [
                        copy.deepcopy(o)
                        for p, o in self.objects.items()
                        if o.get("kind") == kind
                        and (path == base + "/" + plural or p.rsplit("/", 1)[0] == path)
                    ]
                    break
            if known:
                offset = int((query or {}).get("continue", 0))
                end = offset + min(self.page_size, int((query or {}).get("limit", 500)))
                return {
                    "items": collection[offset:end],
                    "metadata": {"continue": str(end) if end < len(collection) else ""},
                }
            raise APIError("GET", 404)
        if path == "/apis/authorization.k8s.io/v1/subjectaccessreviews":
            return {"status": {"allowed": self.access_allowed}}
        dry = (query or {}).get("dryRun") == "All"
        if method == "POST":
            obj = copy.deepcopy(body)
            target = self.object_path(obj)
            if target in self.objects:
                raise APIError("POST", 409)
            if dry:
                obj["metadata"].update(uid="dry-run", resourceVersion="0")
                return obj
            return self.store(obj)
        old = self.objects.get(path)
        if old is None:
            raise APIError(method, 404)
        if method == "PATCH":
            obj = copy.deepcopy(old)
            for op in body:
                parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"][1:].split("/")]
                parent = obj
                for part in parts[:-1]:
                    parent = parent[part]
                key = parts[-1]
                if op["op"] == "test":
                    if parent.get(key) != op["value"]:
                        raise APIError("PATCH", 422)
                elif op["op"] == "remove":
                    del parent[key]
                else:
                    parent[key] = op["value"]
            if dry:
                return obj
            obj["metadata"]["generation"] += 1
            return self.store(obj)
        if method == "DELETE":
            pre = body["preconditions"]
            if pre != {k: old["metadata"][k] for k in ("uid", "resourceVersion")}:
                raise APIError("DELETE", 409)
            if not dry:
                del self.objects[path]
            return {"kind": "Status", "status": "Success"}
        raise APIError(method, 405)


def engine(api=None, cfg=None, grants=None):
    api, cfg = api or FakeAPI(), cfg or config()
    inventory = validate_inventory(cfg, grants=grants)
    e = Engine(api, cfg, inventory)
    e.prepare()
    return e


def render_settings(variables):
    """Render the real task arguments and apply Ansible's module type validation."""
    import yaml
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar
    from ansible.executor.task_executor import remove_omit
    from ansible.module_utils.common.arg_spec import ArgumentSpecValidator
    from access_manager.settings import argument_spec, build_settings

    variables = dict(variables, omit="__OMIT__")
    arguments = yaml.safe_load((ROLE / "tasks/execute.yml").read_text())[0]["k8s_configuration"]
    arguments = {k: v for k, v in arguments.items() if k not in ("users", "groups", "grants")}
    params = remove_omit(Templar(loader=DataLoader(), variables=variables).template(arguments), "__OMIT__")
    result = ArgumentSpecValidator(argument_spec()).validate(params)
    if result.error_messages:
        raise AssertionError(result.error_messages)
    return build_settings(result.validated_parameters)
