"""EN: Plan bounded changes and apply them with ownership and concurrency guards.
RU: Планировать ограниченные изменения и применять их с защитой владения и конкурентного доступа.
"""
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
    """EN: Resolve a JSON pointer and return None for an absent path.
    RU: Разрешить JSON pointer и вернуть None при отсутствии пути.

    Args:
        obj (dict | list): JSON response / JSON-ответ.
        path (str): JSON pointer / JSON pointer.

    Returns:
        Any | None: Located value or absence / Найденное значение или отсутствие.
    """
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
    """EN: Find permission-affecting fields outside the supported resource schema.
    RU: Найти влияющие на права поля вне поддерживаемой схемы ресурса.

    Args:
        obj (dict): API authorization object / Объект авторизации из API.

    Returns:
        list[str]: Unsupported field names; [] means representable / Имена неподдерживаемых полей; [] означает представимость.
    """
    kind = obj["kind"]
    spec = obj.get("spec", {})
    allowed = {
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
    """EN: Match an object reference against discovery metadata and optional UID.
    RU: Сопоставить ссылку с данными discovery и необязательным UID.

    Args:
        ref (dict): Configured resource reference / Настроенная ссылка на ресурс.
        obj (dict): Observed object / Наблюдаемый объект.
        client (Client): Discovery resource registry / Реестр ресурсов discovery.
        uid (bool): Require matching UID / Требовать совпадения UID.

    Returns:
        bool: Whether every requested reference component matches / Совпали ли все запрошенные компоненты ссылки.
    """
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
    """EN: Check the configured namespace and cluster-scope management boundary.
    RU: Проверить границы управления namespace и кластерными объектами.

    Args:
        obj (dict): Candidate object / Проверяемый объект.
        cfg (dict): Management settings / Настройки управления.

    Returns:
        bool: Whether the object lies within the boundary / Находится ли объект в пределах управления.
    """
    ns = obj["metadata"].get("namespace")
    mg = cfg["management"]
    if ns:
        return mg["namespaces"] is None or ns in mg["namespaces"]
    return mg["include_cluster_scoped"]


def protected_namespace(ns, cfg):
    """EN: Apply explicit namespace exceptions before protected names and prefixes.
    RU: Применить исключения namespace перед защищёнными именами и префиксами.

    Args:
        ns (str): Namespace name / Имя namespace.
        cfg (dict): Safety settings / Настройки защиты.

    Returns:
        bool: Whether changes are forbidden in this namespace / Запрещены ли изменения в namespace.
    """
    safe = cfg["safety"]
    return ns not in safe["allowed_protected_namespaces"] and (
        ns in safe["protected_namespaces"]
        or any(ns.startswith(p) for p in safe["protected_namespace_prefixes"])
    )


def patch_for(old, desired, cfg):
    """EN: Build guarded JSON Patch operations for managed fields only.
    RU: Сформировать JSON Patch с проверками версии только для управляемых полей.

    Args:
        old (dict): Observed object with UID/resourceVersion / Наблюдаемый объект с UID/resourceVersion.
        desired (dict): Rendered target object / Сформированный целевой объект.
        cfg (dict): Role settings / Настройки роли.

    Returns:
        list[dict]: JSON Patch; [] when no field changes / JSON Patch; [] при отсутствии изменений полей.

    Raises:
        AccessError: Existing managed object lacks required structure / У управляемого объекта отсутствует нужная структура.
    """
    old, desired = normalized(old), normalized(desired)
    meta = old["metadata"]
    # EN: UID binds the incarnation; resourceVersion rejects concurrent edits.
    # RU: UID фиксирует экземпляр объекта, resourceVersion защищает от конкурентной правки.
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
    if "spec" in desired:
        require("spec" in old, "Existing object has no spec")
        for key, value in desired["spec"].items():
            previous = old["spec"].get(key)
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


class Engine:
    """EN: Reconcile an owned inventory snapshot without granting inferred permissions.
    RU: Согласовывать управляемый inventory со снимком без вычисления виртуальных разрешений.
    """
    def __init__(self, client, cfg, inventory):
        """EN: Initialize a reconciliation session without API requests.
        RU: Инициализировать сеанс согласования без запросов API.

        Args:
            client (Client): kubectl-backed API adapter / Адаптер API через kubectl.
            cfg (dict): Validated settings / Проверенные настройки.
            inventory (dict): Validated grants / Проверенные назначения.

        Returns:
            None: Initializes snapshot, plan and completion state / Инициализирует снимок, план и состояние выполнения.
        """
        self.client, self.cfg, self.inventory = client, cfg, inventory
        self.actual, self.namespaces, self.operations = {}, {}, []
        self.warnings, self.completed = [], []
        self.profile, self.versions = {}, {"RoleBinding": RBAC, "ClusterRoleBinding": RBAC}
        self.guard_values = {}
        self.changed = False

    def _guard(self, path, missing=False):
        """EN: Read and retain a prerequisite for the pre-write recheck.
        RU: Прочитать и сохранить предпосылку для перепроверки перед записью.

        Args:
            path (str): Prerequisite API path / Путь предпосылки в API.
            missing (bool): Allow HTTP 404 / Разрешить HTTP 404.

        Returns:
            dict | None: Observed prerequisite / Наблюдаемая предпосылка.

        Raises:
            AccessError: Prerequisite cannot be read / Предпосылка не может быть прочитана.
        """
        obj = self.client.get(path, missing=missing)
        self.guard_values[path] = copy.deepcopy(obj)
        return obj

    def _discover_deckhouse(self, kind, namespaced, groups=("deckhouse.io",)):
        """EN: Select a served API version for a required Deckhouse kind.
        RU: Выбрать обслуживаемую версию API нужного kind Deckhouse.

        Args:
            kind (str): Required kind / Нужный kind.
            namespaced (bool): Expected scope / Ожидаемая область.
            groups (tuple[str]): Accepted API groups / Допустимые группы API.

        Returns:
            str: Served API version registered in the client / Обслуживаемая версия API, зарегистрированная в клиенте.

        Raises:
            AccessError: No suitable readable API resource / Нет подходящего читаемого API-ресурса.
        """
        for group in self.api_groups:
            if group.get("name") not in groups:
                continue
            versions = [group.get("preferredVersion", {}).get("groupVersion")]
            versions += [v["groupVersion"] for v in group.get("versions", [])]
            for version in dict.fromkeys(v for v in versions if v):
                doc = self.client.get("/apis/" + version)
                if any(r.get("kind") == kind and "/" not in r.get("name", "")
                       for r in doc.get("resources", [])):
                    self.client.discover(version, kind, namespaced)
                    return version
        raise AccessError("Required Deckhouse API is not served: " + kind)

    def _profile(self):
        """EN: Validate Deckhouse compatibility settings.
        RU: Проверить настройки совместимости Deckhouse.

        Returns:
            None: Sets profile and selected API versions / Задаёт профиль и выбранные версии API.

        Raises:
            AccessError: Invalid compatibility settings / Неверные настройки совместимости.
        """
        deck = self.cfg["deckhouse"]
        name = deck.get("compatibility_profile")
        require(not name or name in deck["profiles"], "Unknown Deckhouse compatibility profile")
        p = dict(api_versions={}, ready_checks={}, mixed_backends=False)
        p.update(deck["profiles"].get(name, {}))
        mapping(
            p,
            [
                "api_versions",
                "ready_checks",
                "authz_ready_condition",
                "mixed_backends",
                "granular_roles",
                "controller_markers",
            ],
            "compatibility profile",
            ["api_versions", "ready_checks", "mixed_backends"],
        )
        boolean(p["mixed_backends"], "mixed_backends")
        mapping(
            p["api_versions"],
            ["AuthorizationRule", "ClusterAuthorizationRule"],
            "api_versions",
        )
        for version in p["api_versions"].values():
            require(
                version in ("deckhouse.io/v1", "deckhouse.io/v1alpha1"),
                "Unsupported Deckhouse API version",
            )
        mapping(p["ready_checks"], ["user-authz"], "ready_checks")
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
        self.profile = p
        self.versions.update(p["api_versions"])

    def _module(self, name):
        """EN: Validate Module readiness and optional ModuleConfig/probes.
        RU: Проверить готовность Module и необязательные ModuleConfig/пробы.

        Args:
            name (str): user-authz module / Модуль user-authz.

        Returns:
            dict: ModuleConfig, or {} when absent / ModuleConfig либо {} при отсутствии.

        Raises:
            AccessError: Disabled/unready module, forbidden read or failed probe / Модуль выключен/не готов, чтение запрещено или проба не пройдена.
        """
        if "Module" not in self.client.resources:
            self._discover_deckhouse("Module", False, ("deckhouse.io", "modules.deckhouse.io"))
        module = self._guard(self.client.path("Module", name=name), missing=True)
        require(module is not None, "Required Deckhouse Module does not exist: " + name)
        status = module.get("status") or {}
        conditions = {c.get("type"): c.get("status") for c in status.get("conditions") or []}
        require(
            conditions.get("EnabledByModuleManager") == "True",
            "Required Deckhouse module is disabled: " + name,
        )
        require(
            status.get("phase") == "Ready" and conditions.get("IsReady") == "True",
            "Required Deckhouse module is not ready: " + name,
        )
        if "ModuleConfig" not in self.client.resources:
            self._discover_deckhouse("ModuleConfig", False)
        obj = self._guard(self.client.path("ModuleConfig", name=name), missing=True) or {}
        require((obj.get("spec") or {}).get("enabled") is not False,
                "Required Deckhouse module is disabled in ModuleConfig: " + name)
        checks = self.profile["ready_checks"].get(name, [])
        require(isinstance(checks, list), "Readiness probes must be a list: " + name)
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
        """EN: Read a complete snapshot and optionally construct a guarded plan.
        RU: Прочитать полный снимок и при необходимости построить защищённый план.

        Args:
            export (bool): Read snapshot only without rendering desired inventory / Только прочитать снимок без формирования desired inventory.

        Returns:
            dict | None: Sanitized plan, or None for export / План без секретов либо None для экспорта.

        Raises:
            AccessError: Incomplete reads, invalid targets or mismatched expected digest / Неполное чтение, недопустимые цели или несовпадение ожидаемого digest.
        """
        c, cfg = self.client, self.cfg
        self.cluster_version = c.get("/version").get("gitVersion")
        c.get("/api")
        self.api_groups = c.get("/apis").get("groups", [])
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
            for kind in AUTHZ:
                if kind in self.versions:
                    c.discover(self.versions[kind], kind, kind == "AuthorizationRule")
                else:
                    self.versions[kind] = self._discover_deckhouse(kind, kind == "AuthorizationRule")
                # Read CRD schemas: existence alone is never treated as module readiness.
                info = c.resources[kind]
                crd = self._guard(
                    "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/"
                    + info["plural"]
                    + ".deckhouse.io"
                )
                versions = crd.get("spec", {}).get("versions", [])
                conditions = {v.get("type"): v.get("status")
                              for v in (crd.get("status") or {}).get("conditions") or []}
                require(conditions.get("Established") == "True" and conditions.get("NamesAccepted") != "False",
                        "Deckhouse CRD is not established: " + kind)
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
        desired, self.absent = render(cfg, self.inventory, self.versions)
        self.desired = desired
        self._validate_desired()
        self._build_plan()
        self._validate_deletions()
        # EN: Hash only public projections; never add passwords or TLS material here.
        # RU: В digest входят только публичные представления, без паролей и TLS-данных.
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
                "absent": sorted(self.absent),
            },
            "cluster_uid": self.cluster_uid,
            "cluster_version": self.cluster_version,
            "observed": [clean(self.actual[k]) for k in sorted(self.actual)],
            "guards": {
                p: {
                    "uid": (o or {}).get("metadata", {}).get("uid"),
                    "rv": (o or {}).get("metadata", {}).get("resourceVersion"),
                }
                for p, o in self.guard_values.items()
            },
        }
        self.digest = hashlib.sha256(canonical(digest_input).encode("utf-8")).hexdigest()
        expected = cfg.get("expected_plan_digest")
        require(not expected or expected == self.digest, "Plan digest changed; generate a new plan")
        return self.report()

    def _public_config(self):
        """EN: Copy configuration for digest calculation without connection credentials.
        RU: Скопировать конфигурацию для digest без учётных данных подключения.

        Returns:
            dict: Mode-normalized configuration projection / Представление конфигурации с нормализованным режимом.
        """
        result = copy.deepcopy(self.cfg)
        result.pop("expected_plan_digest", None)
        result["mode"] = "dry"
        result["connection"] = {
            k: v for k, v in result["connection"].items() if k in ("context", "validate_tls")
        }
        return result

    def _validate_crd_fields(self, kind, schema):
        """EN: Check whether the served CRD schema can represent managed fields.
        RU: Проверить, представляет ли обслуживаемая схема CRD управляемые поля.

        Args:
            kind (str): Deckhouse resource kind / Kind ресурса Deckhouse.
            schema (dict): Served OpenAPI schema / Обслуживаемая OpenAPI-схема.

        Returns:
            None: Records supported selector capability / Фиксирует поддержку селектора.

        Raises:
            AccessError: Required fields or supported semantics are absent / Нет обязательных полей или поддерживаемой семантики.
        """
        props = schema.get("properties", {}).get("spec", {}).get("properties", {})
        fields = {
            "AuthorizationRule": ["subjects", "accessLevel", "allowScale", "portForwarding"],
            "ClusterAuthorizationRule": ["subjects", "accessLevel", "allowScale", "portForwarding"],
        }[kind]
        require(set(fields) <= set(props), "Unsupported CRD schema: " + kind)
        if kind in AUTHZ:
            self.__dict__.setdefault("level_enums", {})[kind] = props["accessLevel"].get("enum", [])
            if kind == "ClusterAuthorizationRule":
                self.selector_supported = "namespaceSelector" in props

    def _is_controller(self, obj):
        """EN: Combine standard and profile-specific controller ownership markers.
        RU: Объединить стандартные и профильные признаки владения контроллером.

        Args:
            obj (dict): Observed resource / Наблюдаемый ресурс.

        Returns:
            bool: Whether a controller owns the resource / Управляется ли ресурс контроллером.
        """
        if controller_owned(obj):
            return True
        markers = self.profile.get("controller_markers", {})
        meta = obj["metadata"]
        for field in ("labels", "annotations"):
            if any(meta.get(field, {}).get(k) == v for k, v in markers.get(field, {}).items()):
                return True
        return any(meta["name"].startswith(p) for p in markers.get("name_prefixes", []))

    def _protected(self, obj):
        """EN: Reject terminating, controller-owned or explicitly protected objects.
        RU: Отклонить удаляемые, контроллерные или явно защищённые объекты.

        Args:
            obj (dict): Candidate write/delete target / Цель записи или удаления.

        Returns:
            None: Validation only / Только проверка.

        Raises:
            AccessError: Object or namespace is protected / Объект или namespace защищён.
        """
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
        """EN: Validate target scope, references and platform-specific constraints.
        RU: Проверить область целей, ссылки и ограничения платформы.

        Returns:
            None: Collects prerequisite guards and explanatory warnings / Собирает предпосылки и поясняющие предупреждения.

        Raises:
            AccessError: Unsupported, protected or incompatible assignments / Неподдерживаемые, защищённые или несовместимые назначения.
        """
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
        if cfg["platform"] == "deckhouse":
            subject_backends = {}
            for obj in list(self.actual.values()) + list(self.desired.values()):
                if identity(obj) in self.absent:
                    continue
                backend = "deckhouse" if obj["kind"] in AUTHZ else "rbac"
                subjects = obj.get("subjects", obj.get("spec", {}).get("subjects", []))
                for sub in subjects:
                    subject_backends.setdefault(
                        (sub.get("kind"), sub.get("namespace", ""), sub.get("name")), {}
                    ).setdefault(backend, set()).add("/".join(part for part in identity(obj) if part))
            if any(len(value) > 1 for value in subject_backends.values()):
                require(
                    self.profile.get("mixed_backends"),
                    "Existing grants require a validated mixed_backends profile",
                )
                relevant = {subject_key for obj in self.desired.values()
                            for subject in obj.get("subjects", obj.get("spec", {}).get("subjects", []))
                            for subject_key in [(subject.get("kind"), subject.get("namespace", ""), subject.get("name"))]}
                for subject, sources in sorted(subject_backends.items()):
                    if len(sources) > 1 and subject in relevant:
                        self.warnings.append(
                            "Mixed authorization for %s: RBAC=[%s]; Deckhouse=[%s]"
                            % ("/".join(part for part in subject if part),
                               ", ".join(sorted(sources["rbac"])),
                               ", ".join(sorted(sources["deckhouse"])))
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
                    settings = (self.authz_config.get("spec") or {}).get("settings") or {}
                    multi = settings.get("enableMultiTenancy") is True
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

    def _authorise(self, old):
        """EN: Require role ownership or explicit UID-bound adoption before mutation.
        RU: Потребовать принадлежность роли или явное принятие по UID перед изменением.

        Args:
            old (dict): Existing target object / Существующий целевой объект.

        Returns:
            None: Validation only / Только проверка.

        Raises:
            AccessError: Protected object, conflicting owner or missing adoption / Защищённый объект, чужой владелец или отсутствие adoption.
        """
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
        """EN: Build ordered create/update/replace/delete/noop operations.
        RU: Построить упорядоченные операции create/update/replace/delete/noop.

        Returns:
            None: Populates operations and replacement warnings / Заполняет operations и предупреждения о замене.

        Raises:
            AccessError: Unsafe replacement, prune or ownership violation / Небезопасная замена, prune или нарушение принадлежности.
        """
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
                patch = patch_for(old, obj, self.cfg)
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
            self.operations.append({"action": "delete", "key": key, "desired": None, "old": old})
        self.operations.sort(key=lambda o: (o["action"] == "delete", o["key"]))

    def _validate_deletions(self):
        """EN: Enforce deletion limits and advertised API operation support.
        RU: Проверить лимиты удаления и поддержку операций в API.

        Returns:
            None: Validation only / Только проверка.

        Raises:
            AccessError: Limit exceeded or unsupported planned operation / Превышен лимит или запланированная операция не поддерживается.
        """
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

    def report(self):
        """EN: Return redacted operation details and summary for module diagnostics.
        RU: Вернуть детали операций без секретов и сводку для диагностики модуля.

        Returns:
            dict: Counts, operations, concise lists, warnings and digest / Счётчики, операции, краткие списки, предупреждения и digest.
        """
        changes = []
        counts = {a: 0 for a in ("create", "update", "replace", "delete", "noop")}
        for op in self.operations:
            counts[op["action"]] += 1
            if op["action"] == "noop":
                continue
            change = {
                "action": op["action"],
                "kind": op["key"][0],
                "namespace": op["key"][1],
                "name": op["key"][2],
                "before": clean(op["old"]),
                "after": clean(op["desired"]),
            }
            if op["desired"]:
                if op["old"] and not owned(op["old"], self.cfg):
                    change["adoption"] = True
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
        """EN: Require an unchanged object incarnation and resource version.
        RU: Потребовать неизменность экземпляра объекта и его версии.

        Args:
            observed (dict): Snapshot object / Объект из снимка.
            now (dict | None): Current object / Текущий объект.

        Returns:
            None: Validation only / Только проверка.

        Raises:
            AccessError: Object disappeared, was replaced or changed / Объект исчез, заменён или изменён.
        """
        require(
            now is not None
            and now["metadata"].get("uid") == observed["metadata"]["uid"]
            and now["metadata"].get("resourceVersion") == observed["metadata"]["resourceVersion"],
            "Object changed since plan; generate a new plan",
        )

    def _recheck(self):
        """EN: Verify prerequisites and permission snapshots before the first write.
        RU: Перепроверить предпосылки и снимок назначений перед первой записью.

        Returns:
            None: No Kubernetes mutations / Без изменений в Kubernetes.

        Raises:
            AccessError: Cluster identity, guards, objects or namespace labels changed / Изменились кластер, предпосылки, объекты или метки namespace.
        """
        # Guards cover roles, CRDs, module settings and platform health/configuration.
        for path, old in self.guard_values.items():
            now = self.client.get(path, missing=old is None)
            if old is None:
                require(now is None, "Module settings appeared since plan; generate a new plan")
            elif old.get("metadata", {}).get("resourceVersion"):
                self._same_observation(old, now)
            else:
                require(now == old, "Cluster capability changed since plan")
        current_cluster = self.client.get(self.client.path("Namespace", name="kube-system"))
        require(current_cluster["metadata"]["uid"] == self.cluster_uid, "Cluster identity changed")
        # Re-list all permission sources, including unmanaged ones, before first write.
        # RU: Чужие назначения тоже влияют на согласованность снимка перед первой записью.
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
        """EN: Delete with UID/version preconditions and wait without removing finalizers.
        RU: Удалить с условиями UID/версии и дождаться завершения без снятия finalizers.

        Args:
            old (dict): Snapshot object to delete / Удаляемый объект из снимка.

        Returns:
            None: Marks changed once deletion is observed or accepted / Устанавливает changed при принятом или наблюдаемом удалении.

        Raises:
            AccessError: Concurrent recreation, API failure or timeout / Конкурентное пересоздание, ошибка API или таймаут.
        """
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
            # EN: A lost DELETE response is resolved by observation, not another DELETE.
            # RU: Потерянный ответ DELETE уточняется чтением, без повторного удаления.
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
        """EN: Create or patch once and recover ambiguous responses by reading back.
        RU: Однократно создать или изменить объект и уточнить неоднозначный ответ чтением.

        Args:
            op (dict): Planned create/update/replace operation / Запланированная операция create/update/replace.
            dry (bool): Use server-side dryRun without setting changed / Использовать серверный dryRun без установки changed.

        Returns:
            dict: Verified write response or recovered object / Проверенный ответ записи или найденный объект.

        Raises:
            AccessError: Concurrent mutation, failed write or inconclusive recovery / Конкурентное изменение, ошибка записи или неоднозначный результат чтения.
        """
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
                # EN: Confirm the owned desired object before accepting an ambiguous POST.
                # RU: Неоднозначный POST считается успешным только при совпадении целевого объекта.
                result = c.get(path, missing=True)
                if (
                    result is None
                    or not owned(result, self.cfg)
                    or patch_for(result, obj, self.cfg)
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
            # EN: Recheck UID and remaining patch instead of repeating the write.
            # RU: Проверяем UID и остаток patch вместо повторной записи.
            result = c.get(path, missing=True)
            if (
                result is None
                or result["metadata"].get("uid") != old["metadata"]["uid"]
                or patch_for(result, obj, self.cfg)
            ):
                raise
            self.changed = True
        require(
            result.get("metadata", {}).get("uid") == old["metadata"]["uid"],
            "Update response UID changed",
        )
        return result

    def server_validate(self):
        """EN: Submit supported planned writes with server-side dryRun.
        RU: Отправить поддерживаемые записи плана с серверным dryRun.

        Returns:
            None: Adds a warning for incomplete replacement validation / Добавляет предупреждение о неполной проверке замены.

        Raises:
            AccessError: Server rejects a planned write / Сервер отклоняет планируемую запись.
        """
        for op in self.operations:
            if op["action"] in ("create", "update"):
                self._write(op, dry=True)
            elif op["action"] == "replace":
                self.warnings.append("Replacement cannot be fully server-validated before deletion")

    def _ready(self, obj):
        """EN: Wait for a configured authorization Ready condition and generation.
        RU: Дождаться настроенного условия Ready и поколения ресурса авторизации.

        Args:
            obj (dict): Written or unchanged authorization object / Записанный или неизменённый объект авторизации.

        Returns:
            None: Returns immediately if no condition is configured / Возвращается сразу, если условие не настроено.

        Raises:
            AccessError: UID changed, read failed or readiness timed out / Изменился UID, ошибка чтения или таймаут готовности.
        """
        kind, ns, name = identity(obj)
        if kind not in AUTHZ:
            return
        condition = self.profile.get("authz_ready_condition")
        if not condition:
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

    def apply(self):
        """EN: Recheck the prepared snapshot and apply ordered operations.
        RU: Перепроверить подготовленный снимок и выполнить операции по порядку.

        Returns:
            bool: Whether this session changed Kubernetes objects / Изменял ли сеанс объекты Kubernetes.

        Raises:
            AccessError: Precondition, API or convergence failure; earlier writes remain / Ошибка предпосылок, API или сходимости; предыдущие записи сохраняются.
        """
        self._recheck()
        if self.cfg["server_validation"]:
            self.server_validate()
        for op in self.operations:
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
                        result, op["desired"], self.cfg
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
        return self.changed
