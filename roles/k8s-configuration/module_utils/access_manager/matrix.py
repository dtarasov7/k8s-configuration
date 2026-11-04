"""EN: Build GET-only RBAC matrices from cluster or inventory assignments.
RU: Строить RBAC-матрицы по кластеру или inventory, выполняя только GET.
"""
import csv
from fnmatch import fnmatchcase
import io
import json

from .render import RBAC, owned, render, selector_matches
from .schema import AccessError, boolean, mapping, names, require, string, validate_inventory, validate_selector


VERBS = ("get", "list", "watch", "create", "update", "patch", "delete", "deletecollection")
LETTERS = "GLWCUPDX"
ROW_FIELDS = ("namespace", "api_group", "resource", "resource_name", "non_resource_url", "action")
DEFAULTS = {
    "source": "cluster",
    "output_dir": "./k8s-access-matrix",
    "scope": "cluster",
    "namespaces": [],
    "include_cluster_scoped": True,
    "subjects": {"users": True, "groups": True, "service_accounts": False},
    "namespace_mode": "application",
    "system_namespaces": ["kube-system", "kube-public", "kube-node-lease"],
    "namespace_include": [],
    "namespace_exclude": [],
    "include_system_subjects": False,
    "include_external_users": False,
    "system_subjects": ["system:*"],
    "users_include": [], "users_exclude": [],
    "groups_include": [], "groups_exclude": [],
    "service_accounts_include": [], "service_accounts_exclude": [],
    "service_account_namespaces_include": [], "service_account_namespaces_exclude": [],
    "omit_empty_rows": True,
    "exclude_broad_subjects": True,
    "resolve_group_membership": True,
    "memberships": [],
    "csv": {"delimiter": ";"},
}


def list_field(obj, field):
    value = obj.get(field)
    require(value is None or isinstance(value, list), "Invalid matrix list field: " + field)
    return value or []


def validate_matrix(raw):
    """EN: Validate matrix source, filters, membership hints and CSV options.
    RU: Проверить источник матрицы, фильтры, сведения о членстве и параметры CSV.

    Args:
        raw (dict): Matrix options / Параметры матрицы.

    Returns:
        dict: Options with validated defaults / Параметры с проверенными значениями по умолчанию.

    Raises:
        AccessError: Unknown field, invalid filter/source or duplicate membership / Неизвестное поле, неверный фильтр/источник или повтор членства.
    """
    mapping(raw, DEFAULTS, "matrix")
    cfg = dict(DEFAULTS, **raw)
    string(cfg["output_dir"], "matrix.output_dir")
    require(cfg["source"] in ("cluster", "inventory"), "Invalid matrix.source; use cluster or inventory")
    require(cfg["scope"] in ("cluster", "managed"), "Invalid matrix.scope")
    names(cfg["namespaces"], "matrix.namespaces")
    require(cfg["namespace_mode"] in ("application", "all", "system"), "Invalid matrix.namespace_mode")
    for key in ("system_namespaces", "namespace_include", "namespace_exclude", "system_subjects",
                "users_include", "users_exclude", "groups_include", "groups_exclude",
                "service_accounts_include", "service_accounts_exclude",
                "service_account_namespaces_include", "service_account_namespaces_exclude"):
        names(cfg[key], "matrix." + key)
    for key in ("include_cluster_scoped", "resolve_group_membership", "include_system_subjects", "include_external_users", "omit_empty_rows",
                "exclude_broad_subjects"):
        boolean(cfg[key], "matrix." + key)
    mapping(cfg["subjects"], DEFAULTS["subjects"], "matrix.subjects")
    cfg["subjects"] = dict(DEFAULTS["subjects"], **cfg["subjects"])
    for value in cfg["subjects"].values():
        boolean(value, "matrix.subjects")
    require(any(cfg["subjects"].values()), "Select at least one matrix subject type")
    mapping(cfg["csv"], ["delimiter"], "matrix.csv")
    cfg["csv"] = dict(DEFAULTS["csv"], **cfg["csv"])
    require(cfg["csv"]["delimiter"] in (";", ",", "\t"), "Invalid matrix CSV delimiter")
    require(isinstance(cfg["memberships"], list), "matrix.memberships must be a list")
    seen = set()
    for member in cfg["memberships"]:
        mapping(member, ["kind", "name", "namespace", "groups", "complete"], "matrix membership",
                ["kind", "name", "groups", "complete"])
        require(member["kind"] in ("User", "ServiceAccount"), "Invalid membership kind")
        key = subject_key(member)
        require(key not in seen, "Duplicate matrix membership")
        seen.add(key)
        names(member["groups"], "membership.groups")
        boolean(member["complete"], "membership.complete")
        require(member.get("namespace") is None or member["kind"] == "ServiceAccount",
                "Only ServiceAccount membership accepts namespace")
    return cfg


def subject_key(subject, namespace=""):
    """EN: Canonicalize a subject, merging ServiceAccount User aliases.
    RU: Нормализовать субъекта с объединением User-псевдонимов ServiceAccount.

    Args:
        subject (dict): User, Group or ServiceAccount / User, Group или ServiceAccount.
        namespace (str): Binding namespace fallback for ServiceAccount / Namespace binding как запасное значение для ServiceAccount.

    Returns:
        tuple[str, str, str]: Kind, namespace and effective name / Kind, namespace и фактическое имя.

    Raises:
        AccessError: Unknown kind, empty name or missing ServiceAccount namespace / Неизвестный kind, пустое имя или отсутствующий namespace ServiceAccount.
    """
    kind, name = subject.get("kind"), subject.get("name")
    require(kind in ("User", "Group", "ServiceAccount"), "Unsupported matrix subject kind")
    string(name, "matrix subject name")
    if kind == "User" and name.startswith("system:serviceaccount:"):
        parts = name.split(":")
        if len(parts) == 4 and all(parts[2:]):
            return ("ServiceAccount", parts[2], parts[3])
    ns = (subject.get("namespace") or namespace) if kind == "ServiceAccount" else ""
    require(kind != "ServiceAccount" or bool(ns), "ServiceAccount subject requires namespace")
    return (kind, ns, name)


def label(subject):
    kind, ns, name = subject
    return "%s:%s%s" % (kind, ns + "/" if ns else "", name)


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csv_text(header, rows, delimiter):
    """EN: Write deterministic CSV with spreadsheet formula protection.
    RU: Сформировать детерминированный CSV с защитой от формул электронных таблиц.

    Args:
        header (list[str]): Column names / Имена столбцов.
        rows (Iterable): Cell rows / Строки ячеек.
        delimiter (str): Validated one-character separator / Проверенный односимвольный разделитель.

    Returns:
        str: CSV with LF line endings / CSV с переводами строк LF.
    """
    def safe(value):
        value = str(value)
        # Quoting alone does not prevent spreadsheet formula evaluation.
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
            return "'" + value
        return value

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow([safe(v) for v in header])
    for row in rows:
        writer.writerow([safe(v) for v in row])
    return stream.getvalue()


class Matrix:
    """EN: Calculate RBAC masks and provenance without writing to Kubernetes.
    RU: Вычислять RBAC-маски и происхождение прав без записи в Kubernetes.
    """
    def __init__(self, client, config, options, grants=None):
        """EN: Validate options and accept desired grants only for inventory source.
        RU: Проверить параметры и принять целевые grants только для источника inventory.

        Args:
            client (Client): Read-only API adapter usage / Адаптер API, используемый только для чтения.
            config (dict): Validated role settings / Проверенные настройки роли.
            options (dict): Matrix source and filters / Источник матрицы и фильтры.
            grants (list[dict] | None): Required inventory assignments; [] is empty / Обязательные назначения inventory; [] задаёт пустой набор.

        Returns:
            None: Initializes report state / Инициализирует состояние отчёта.

        Raises:
            AccessError: Invalid options, missing grants or native Deckhouse forecast / Неверные параметры, нет grants или запрошен прогноз native Deckhouse.
        """
        self.client, self.config, self.cfg = client, config, validate_matrix(options)
        # Deckhouse system namespace defaults also apply to direct module callers.
        if "system_namespaces" not in options and config["platform"] == "deckhouse":
            self.cfg["system_namespaces"] = self.cfg["system_namespaces"] + ["d8-*"]
        self.catalog, self.apis, self.objects = {}, {}, {}
        self.subjects, self.parents, self.permissions = {}, {}, []
        self.declarations, self.warnings = [], set()
        self.inventory = None
        if self.cfg["source"] == "inventory":
            require(grants is not None, "Inventory matrix requires k8s_configuration_grants; use [] for an empty assignment set")
            require(isinstance(grants, list), "Inventory matrix grants must be a list")
            # EN: accessLevel is not roleRef; future controller RBAC cannot be invented.
            # RU: accessLevel не является roleRef; будущий RBAC контроллера нельзя угадывать.
            require(not any(isinstance(grant, dict) and grant.get("backend") == "deckhouse"
                            and grant.get("state", "present") != "absent" for grant in grants),
                    "Inventory matrix supports backend: rbac only; Deckhouse AR/CAR permissions require controller-generated RBAC. Use source: cluster after apply or reference an existing Role/ClusterRole")
            self.inventory = validate_inventory(config, grants=grants)

    def read(self):
        """EN: Read discovery, roles and source-specific assignments plus live identities.
        RU: Прочитать discovery, роли, назначения выбранного источника и текущие учётки.

        Returns:
            None: Populates resource catalog, namespaces and objects / Заполняет каталог ресурсов, namespace и объекты.

        Raises:
            AccessError: Incomplete/forbidden reads or missing namespace filters / Неполное/запрещённое чтение или отсутствующие namespace из фильтра.
        """
        c = self.client
        self.version = c.get("/version").get("gitVersion", "")
        groups = c.get("/apis").get("groups", [])
        versions = ["v1"]
        for group in groups:
            preferred = group.get("preferredVersion", {}).get("groupVersion")
            versions.extend([preferred] if preferred else [])
            versions.extend(v["groupVersion"] for v in group.get("versions", []))
        # Include older served versions: a kind/subresource may not exist in the preferred one.
        # RU: Preferred-версия может не содержать kind или подресурс из другой served-версии.
        for version in dict.fromkeys(versions):
            group = version.split("/")[0] if "/" in version else ""
            base = ("/apis/" if group else "/api/") + version
            doc = c.get(base)
            require(isinstance(doc.get("resources"), list), "Incomplete matrix API discovery")
            for resource in doc["resources"]:
                name = resource["name"]
                key = (group, name)
                scope = resource["namespaced"]
                require(key not in self.catalog or self.catalog[key] == scope,
                        "Inconsistent resource scope in API discovery")
                self.catalog[key] = scope
                self.apis.setdefault((group, resource.get("kind"), name), base)
        self.namespaces = {
            obj["metadata"]["name"]: obj for obj in self.collection("", "Namespace", "namespaces")
        }
        missing = sorted(set(self.cfg["namespaces"]) - set(self.namespaces))
        require(not missing, "Unknown matrix namespace(s): %s. Use matrix.namespaces: [] to remove the exact-name filter; other matrix filters still apply"
                % ", ".join(missing))
        self.selected_namespaces = sorted(ns for ns in self.namespaces if self.namespace_selected(ns))
        self.namespace_filtered = bool(self.cfg["namespaces"] or self.cfg["namespace_include"]
                                       or self.cfg["namespace_exclude"] or self.cfg["namespace_mode"] != "all")
        for kind, plural in (("Role", "roles"), ("ClusterRole", "clusterroles"),
                             ("RoleBinding", "rolebindings"), ("ClusterRoleBinding", "clusterrolebindings")):
            self.objects[kind] = ([] if self.inventory is not None and kind.endswith("Binding")
                                  else self.collection(RBAC.split("/")[0], kind, plural))
        if self.cfg["subjects"]["service_accounts"]:
            for obj in self.collection("", "ServiceAccount", "serviceaccounts"):
                self.add_subject(subject_key(dict(obj["metadata"], kind="ServiceAccount")), "serviceaccount")
        if self.config["platform"] == "deckhouse":
            for kind, plural in (("User", "users"), ("Group", "groups"),
                                 ("AuthorizationRule", "authorizationrules"),
                                 ("ClusterAuthorizationRule", "clusterauthorizationrules")):
                self.objects[kind] = ([] if self.inventory is not None and kind.endswith("AuthorizationRule")
                                      else self.collection("deckhouse.io", kind, plural))
        if self.inventory is not None:
            self.inventory_bindings()

    def inventory_bindings(self):
        """EN: Render present RBAC grants and resolve roles from the live snapshot.
        RU: Сформировать присутствующие RBAC-назначения и найти роли в живом снимке.

        Returns:
            None: Adds synthetic bindings; no API writes or live-binding reads / Добавляет модельные bindings; без записи API и чтения живых bindings.

        Raises:
            AccessError: Referenced role/namespace is absent or targets collide / Нет указанной роли/namespace или цели совпадают.
        """
        present = dict(self.inventory, grants=[grant for grant in self.inventory["grants"]
                                               if grant.get("state", "present") != "absent"])
        desired, _ = render(self.config, present,
                               {"RoleBinding": RBAC, "ClusterRoleBinding": RBAC})
        roles = {(obj["kind"], obj["metadata"].get("namespace", ""), obj["metadata"]["name"])
                 for kind in ("Role", "ClusterRole") for obj in self.objects[kind]}
        for obj in desired.values():
            ns = obj["metadata"].get("namespace", "")
            require(not ns or ns in self.namespaces, "Inventory matrix namespace does not exist: " + ns)
            ref = obj["roleRef"]
            require((ref["kind"], ns if ref["kind"] == "Role" else "", ref["name"]) in roles,
                    "Inventory matrix role does not exist: " + ref["kind"] + "/" + ref["name"])
            self.objects[obj["kind"]].append(obj)
        self.warnings.add("Inventory assignments only: other cluster bindings are excluded; this is not a complete effective-access forecast after apply")
        self.warnings.add("Prune, adoption, deletion guards and controller convergence are not evaluated; state: absent assignments are omitted")

    @staticmethod
    def matches(value, patterns):
        return any(fnmatchcase(value, pattern) for pattern in patterns)

    def namespace_selected(self, ns):
        """EN: Intersect namespace system classification and explicit filters.
        RU: Пересечь системную классификацию namespace с явными фильтрами.

        Args:
            ns (str): Existing namespace / Существующий namespace.

        Returns:
            bool: Whether the namespace is selected / Выбран ли namespace.
        """
        system = self.matches(ns, self.cfg["system_namespaces"])
        return ((self.cfg["namespace_mode"] == "all" or
                 system == (self.cfg["namespace_mode"] == "system"))
                and (not self.cfg["namespaces"] or ns in self.cfg["namespaces"])
                and self.pattern_selected(ns, "namespace"))

    def pattern_selected(self, value, prefix):
        include, exclude = self.cfg[prefix + "_include"], self.cfg[prefix + "_exclude"]
        return (not include or self.matches(value, include)) and not self.matches(value, exclude)

    def direct_only(self, key):
        """EN: Identify User columns that must exclude all group inheritance.
        RU: Определить User-столбцы, исключающие любое наследование из групп.

        Args:
            key (tuple): Registered subject key / Ключ зарегистрированного субъекта.

        Returns:
            bool: True for Users without a local Deckhouse User source / True для User без локального источника Deckhouse User.
        """
        return key[0] == "User" and "deckhouse-user" not in self.subjects[key]["sources"]

    def subject_selected(self, key):
        """EN: Apply subject type, system and include/exclude filters.
        RU: Применить фильтры типа, системности и включения/исключения субъектов.

        Args:
            key (tuple): Registered subject key / Ключ зарегистрированного субъекта.

        Returns:
            bool: Whether a subject column is visible / Отображается ли столбец субъекта.
        """
        kind, ns, name = key
        category = {"User": "users", "Group": "groups", "ServiceAccount": "service_accounts"}[kind]
        if not self.cfg["subjects"][category]:
            return False
        if kind == "ServiceAccount":
            return (self.pattern_selected(ns + "/" + name, category)
                    and self.pattern_selected(ns, "service_account_namespaces"))
        if kind == "User" and not self.cfg["include_external_users"] and "deckhouse-user" not in self.subjects[key]["sources"]:
            return False
        return ((self.cfg["include_system_subjects"] or not self.matches(name, self.cfg["system_subjects"]))
                and self.pattern_selected(name, category))

    def collection(self, group, kind, plural):
        """EN: Read a complete discovered collection and fill omitted kind fields.
        RU: Прочитать полную обнаруженную коллекцию и заполнить пропущенный kind.

        Args:
            group (str): API group; empty for core / Группа API; пустая для core.
            kind (str): Expected kind / Ожидаемый kind.
            plural (str): Discovered collection name / Обнаруженное имя коллекции.

        Returns:
            list[dict]: Collection objects with kind populated / Объекты коллекции с заполненным kind.

        Raises:
            AccessError: API resource is absent, unreadable or returns a conflicting kind / Ресурс API отсутствует, недоступен или вернул другой kind.
        """
        base = self.apis.get((group, kind, plural))
        require(base, "Required matrix API resource is not available: " + kind)
        items = self.client.list(base + "/" + plural)
        for obj in items:
            # List items may omit TypeMeta; the collection's discovered kind is authoritative.
            require(obj.get("kind") in (None, "", kind), "Wrong kind in matrix API collection: " + kind)
            obj["kind"] = kind
        return items

    def add_subject(self, key, source):
        """EN: Register a subject and its standard authentication groups once.
        RU: Однократно зарегистрировать субъекта и стандартные группы аутентификации.

        Args:
            key (tuple): Canonical subject key / Нормализованный ключ субъекта.
            source (str): Provenance marker / Признак происхождения.

        Returns:
            None: Merges provenance into the subject registry / Объединяет сведения о происхождении в реестре субъектов.
        """
        if key not in self.subjects:
            kind, ns, name = key
            groups = set()
            if kind != "Group":
                groups.add("system:unauthenticated" if name == "system:anonymous" else "system:authenticated")
            if kind == "ServiceAccount":
                groups.update(("system:serviceaccounts", "system:serviceaccounts:" + ns))
            self.subjects[key] = {
                "groups": groups, "sources": set(),
                "complete": kind != "User" or name == "system:anonymous",
            }
        self.subjects[key]["sources"].add(source)

    def identities(self):
        """EN: Resolve live local membership, nested groups and optional explicit hints.
        RU: Разрешить текущее локальное членство, вложенные группы и явные сведения.

        Returns:
            None: Updates membership and completeness in subjects / Обновляет членство и его полноту в subjects.

        Raises:
            AccessError: Ambiguous claims, missing members or group cycles / Неоднозначные claims, отсутствующие участники или циклы групп.
        """
        users = {o["metadata"]["name"]: o["spec"]["email"].lower() for o in self.objects.get("User", [])}
        require(len(set(users.values())) == len(users), "Ambiguous local Deckhouse User emails prevent complete membership")
        groups = {o["metadata"]["name"]: o["spec"]["name"] for o in self.objects.get("Group", [])}
        require(len(set(groups.values())) == len(groups), "Ambiguous Deckhouse Group claims prevent complete membership")
        for obj in self.objects.get("User", []):
            key = ("User", "", users[obj["metadata"]["name"]])
            self.add_subject(key, "deckhouse-user")
            if self.cfg["resolve_group_membership"]:
                legacy_groups = list_field(obj["spec"], "groups")
                names(legacy_groups, "Deckhouse User.spec.groups")
                self.subjects[key]["groups"].update(legacy_groups)
                # EN: Completeness applies to local authentication, not an external token with the same name.
                # RU: Полнота относится к локальному входу, не к внешнему токену с тем же именем.
                self.subjects[key]["complete"] = True
        for group in self.objects.get("Group", []):
            claim = groups[group["metadata"]["name"]]
            self.add_subject(("Group", "", claim), "deckhouse-group")
            if not self.cfg["resolve_group_membership"]:
                continue
            for member in list_field(group["spec"], "members"):
                kind, name = member.get("kind"), member.get("name")
                refs = users if kind == "User" else groups if kind == "Group" else {}
                require(name in refs, "Unresolved Deckhouse Group member in matrix")
                key = subject_key({"kind": kind, "name": refs[name]})
                self.add_subject(key, "deckhouse-group-member")
                if kind == "Group":
                    self.parents.setdefault(refs[name], set()).add(claim)
                else:
                    self.subjects[key]["groups"].add(claim)
        # Validate cycles even when no current user belongs to the affected group.
        def expand(group, visiting):
            require(group not in visiting, "Cyclic Deckhouse Group membership")
            result = set(self.parents.get(group, set()))
            for parent in list(result):
                result.update(expand(parent, visiting | {group}))
            return result

        closure = {group: expand(group, set()) for group in self.parents}
        for member in self.cfg["memberships"]:
            key = subject_key(member)
            self.add_subject(key, "explicit-membership")
            # An explicit complete list overrides inferred Deckhouse membership,
            # while standard authentication/SA groups always remain applicable.
            if member["complete"]:
                self.subjects[key]["groups"].difference_update(groups.values())
            self.subjects[key]["groups"].update(member["groups"])
            self.subjects[key]["complete"] = member["complete"]
        for key, info in list(self.subjects.items()):
            if key[0] == "Group":
                info["groups"].update(closure.get(key[2], set()))
            else:
                for group in list(info["groups"]):
                    info["groups"].update(closure.get(group, set()))
            for group in info["groups"]:
                self.add_subject(("Group", "", group), "membership")

    def bindings(self):
        """EN: Expand bindings into rules and retain Deckhouse declarations as audit data.
        RU: Развернуть bindings в правила, сохраняя декларации Deckhouse только для аудита.

        Returns:
            None: Populates permissions, subjects and declaration provenance / Заполняет permissions, subjects и происхождение деклараций.

        Raises:
            AccessError: Dangling roleRef or invalid policy rule / Неразрешённый roleRef или неверное правило политики.
        """
        roles = {(o["kind"], o["metadata"].get("namespace", ""), o["metadata"]["name"]): o
                 for kind in ("Role", "ClusterRole") for o in self.objects[kind]}
        declarations = {
            o["metadata"].get("uid"): o for kind in ("AuthorizationRule", "ClusterAuthorizationRule")
            for o in self.objects.get(kind, []) if o["metadata"].get("uid")
        }
        linked = {}
        for kind in ("RoleBinding", "ClusterRoleBinding"):
            for binding in self.objects[kind]:
                ns = binding["metadata"].get("namespace", "")
                if self.cfg["scope"] == "managed" and not owned(binding, self.config):
                    continue
                if ns and self.cfg["namespaces"] and ns not in self.cfg["namespaces"]:
                    continue
                ref = binding["roleRef"]
                require(ref.get("apiGroup") == RBAC.split("/")[0], "Unsupported matrix roleRef API group")
                require(ref["kind"] in (("Role", "ClusterRole") if ns else ("ClusterRole",)),
                        "Invalid matrix roleRef kind")
                role = roles.get((ref["kind"], ns if ref["kind"] == "Role" else "", ref["name"]))
                require(role is not None, "Dangling roleRef prevents a complete matrix")
                origins = []
                # EN: Only owner UID links prove provenance; matching names do not.
                # RU: Происхождение подтверждается owner UID, а не совпадением имён.
                for owner in list_field(binding["metadata"], "ownerReferences"):
                    declaration = declarations.get(owner.get("uid"))
                    if declaration:
                        origins.append("%s/%s/%s" % (declaration["kind"],
                                       declaration["metadata"].get("namespace", ""),
                                       declaration["metadata"]["name"]))
                        linked.setdefault(owner["uid"], []).append(binding)
                for subject in list_field(binding, "subjects"):
                    key = subject_key(subject, ns)
                    self.add_subject(key, "inventory-binding" if self.inventory is not None else "rbac-binding")
                    for raw_rule in list_field(role, "rules"):
                        rule = dict(raw_rule)
                        for field in ("verbs", "apiGroups", "resources", "resourceNames", "nonResourceURLs"):
                            rule[field] = list_field(raw_rule, field)
                            require(all(isinstance(v, str) for v in rule[field]),
                                    "Invalid matrix policy rule field: " + field)
                        require(bool(rule["verbs"]), "Matrix policy rule has no verbs")
                        self.permissions.append({
                            "subject": key, "namespace": ns, "rule": rule,
                            "binding": binding, "role": role, "origins": sorted(origins),
                        })
        for kind in ("AuthorizationRule", "ClusterAuthorizationRule"):
            for obj in self.objects.get(kind, []):
                if self.cfg["scope"] == "managed" and not owned(obj, self.config):
                    continue
                ns = obj["metadata"].get("namespace", "")
                if ns and self.cfg["namespaces"] and ns not in self.cfg["namespaces"]:
                    continue
                spec = obj["spec"]
                selector = spec.get("namespaceSelector")
                if selector and (not isinstance(selector, dict)
                                 or set(selector) not in ({"labelSelector"}, {"matchAny"})):
                    selector = None
                    self.warnings.add("Unsupported Deckhouse namespace selector; see bindings.csv declarations")
                if selector and "labelSelector" in selector:
                    try:
                        # An empty Kubernetes LabelSelector matches every namespace.
                        if selector["labelSelector"]:
                            validate_selector(selector["labelSelector"])
                    except AccessError:
                        selector = None
                        self.warnings.add("Unsupported Deckhouse namespace selector; see bindings.csv declarations")
                if ns:
                    selected = [ns]
                elif "limitNamespaces" in spec or "allowAccessToSystemNamespaces" in spec:
                    selected = []
                    self.warnings.add("Legacy Deckhouse namespace scope is not expanded; see original declaration")
                elif selector and "labelSelector" in selector:
                    selected = sorted(n for n, o in self.namespaces.items()
                                      if selector_matches(selector["labelSelector"], o["metadata"].get("labels", {})))
                elif (selector and selector.get("matchAny") is True) or not spec.get("namespaceSelector"):
                    selected = sorted(self.namespaces)
                else:
                    selected = []
                    self.warnings.add("Unsupported Deckhouse namespace selector; see bindings.csv declarations")
                state = "linked-by-owner-uid" if obj["metadata"].get("uid") in linked else "unverified"
                if state == "unverified":
                    self.warnings.add("Deckhouse declarations cannot be verified against generated RBAC without owner UID links")
                for subject in list_field(spec, "subjects"):
                    self.add_subject(subject_key(subject, ns), "deckhouse-declaration")
                expected = {subject_key(s, ns) for s in list_field(spec, "subjects")}
                for binding in linked.get(obj["metadata"].get("uid"), []):
                    binding_ns = binding["metadata"].get("namespace", "")
                    subjects = {subject_key(s, binding_ns) for s in list_field(binding, "subjects")}
                    if not subjects <= expected or (selected and binding_ns and binding_ns not in selected):
                        state = "linked-scope-or-subject-mismatch"
                        self.warnings.add("Deckhouse declaration differs from linked RBAC scope/subjects; inspect bindings.csv")
                # Never export the whole User or Group object (may contain passwords).
                self.declarations.append({
                    "record_type": "deckhouse-declaration", "binding_kind": kind,
                    "binding_namespace": ns, "binding_name": obj["metadata"]["name"],
                    "declaration": compact({k: v for k, v in spec.items() if k in (
                        "subjects", "accessLevel", "namespaceSelector", "limitNamespaces",
                        "allowAccessToSystemNamespaces", "portForwarding", "allowScale",
                    )}), "resolved_namespaces": compact(selected),
                    "reconciliation": state, "_subjects": expected,
                })

    @staticmethod
    def resource_matches(pattern, resource):
        return pattern == "*" or pattern == resource or (
            "/" in resource and pattern == "*/" + resource.split("/", 1)[1]
        )

    def scopes(self, permission, group, resource):
        """EN: Resolve resource scope without guessing absent discovery entries.
        RU: Определить область ресурса без догадок при его отсутствии в discovery.

        Args:
            permission (dict): Binding rule and namespace / Правило binding и namespace.
            group (str): API group / Группа API.
            resource (str): Resource or subresource pattern / Шаблон ресурса или подресурса.

        Returns:
            list[str]: Selected scopes, including symbolic or <unknown> markers / Выбранные области, включая символические маркеры или <unknown>.
        """
        ns = permission["namespace"]
        scoped = self.catalog.get((group, resource))
        if ns:
            return [ns] if scoped is not False and ns in self.selected_namespaces else []
        if scoped is False:
            return ["<cluster>"] if self.cfg["include_cluster_scoped"] else []
        if scoped is True:
            return self.selected_namespaces + ([] if self.namespace_filtered else ["*"])
        if "*" in (group, resource) or resource.startswith("*/"):
            return (self.selected_namespaces + (["<cluster>"] if self.cfg["include_cluster_scoped"] else [])
                    if self.namespace_filtered else ["<all-scopes>" if self.cfg["include_cluster_scoped"] else "*"])
        self.warnings.add("Rules reference resources absent from discovery; their scope is <unknown>")
        return ["<unknown>"]

    def broad_subjects(self):
        """EN: Find wildcard principals and inheriting local subjects to exclude.
        RU: Найти исключаемых субъектов с wildcard-правами и локальных наследников.

        Returns:
            set[tuple]: Broad subject keys; external Users use direct grants only / Ключи широких субъектов; для внешних User учитываются только прямые права.
        """
        if not self.cfg["exclude_broad_subjects"]:
            return set()
        direct = set()
        for permission in self.permissions:
            rule, ns = permission["rule"], permission["namespace"]
            if ("*" in rule["apiGroups"] and "*" in rule["resources"] and not rule["resourceNames"]
                    and (ns in self.selected_namespaces if ns else
                         bool(self.selected_namespaces) or self.cfg["include_cluster_scoped"])):
                direct.add(permission["subject"])
        groups = {key[2] for key in direct if key[0] == "Group"}
        return direct | {key for key, info in self.subjects.items() if not self.direct_only(key) and groups & info["groups"]}

    def rows(self, permissions):
        """EN: Expand rule targets into sorted concrete and symbolic matrix rows.
        RU: Развернуть цели правил в отсортированные конкретные и символические строки матрицы.

        Args:
            permissions (list[dict]): Selected assignment rules / Выбранные правила назначений.

        Returns:
            list[tuple]: Scope/group/resource/name/URL/action rows / Строки области/группы/ресурса/имени/URL/действия.
        """
        rows = set()
        for permission in permissions:
            rule = permission["rule"]
            actions = (["standard"] if set(VERBS) & set(rule["verbs"]) or "*" in rule["verbs"] else [])
            actions += sorted(set(rule["verbs"]) - set(VERBS))
            for pattern_group in rule.get("apiGroups", []):
                for pattern_resource in rule.get("resources", []):
                    targets = {(g, r) for g, r in self.catalog
                               if pattern_group in ("*", g) and self.resource_matches(pattern_resource, r)}
                    # Keep symbolic wildcards/future resources as well as concrete discovery rows.
                    # RU: Символический wildcard сохраняет смысл доступа и к будущим API-ресурсам.
                    targets.add((pattern_group, pattern_resource))
                    for group, resource in targets:
                        for ns in self.scopes(permission, group, resource):
                            for name in rule.get("resourceNames") or [""]:
                                for action in actions:
                                    rows.add((ns, group, resource, name, "", action))
            if not permission["namespace"] and self.cfg["include_cluster_scoped"]:
                for url in rule.get("nonResourceURLs", []):
                    for action in actions:
                        rows.add(("<cluster>", "", "", "", url, action))
        return sorted(rows)

    def matching_verbs(self, permission, row):
        """EN: Match a rule to a row while respecting resourceNames restrictions.
        RU: Сопоставить правило строке с учётом ограничений resourceNames.

        Args:
            permission (dict): Assignment rule / Правило назначения.
            row (tuple): Matrix target and action / Цель и действие строки матрицы.

        Returns:
            set[str]: Granted verbs for this row / Разрешённые verbs для строки.
        """
        ns, group, resource, name, url, action = row
        rule = permission["rule"]
        if permission["namespace"] and permission["namespace"] != ns:
            return set()
        if url:
            if permission["namespace"] or not any(
                p == url or p.endswith("*") and url.startswith(p[:-1]) for p in rule.get("nonResourceURLs", [])
            ):
                return set()
        else:
            if not any(p in ("*", group) for p in rule.get("apiGroups", [])) or not any(
                self.resource_matches(p, resource) for p in rule.get("resources", [])
            ):
                return set()
            if rule.get("resourceNames") and name not in rule["resourceNames"]:
                return set()
        verbs = set(VERBS) if action == "standard" else {action}
        if "*" not in rule["verbs"]:
            verbs.intersection_update(rule["verbs"])
        if rule.get("resourceNames"):
            # EN: A name constraint cannot authorize collection deletion or unnamed creation.
            # RU: Ограничение по имени не разрешает удаление коллекции или создание без известного имени.
            verbs.discard("deletecollection")
            if "/" not in resource:
                verbs.discard("create")
        return verbs

    def candidates(self, permission, index, urls):
        """EN: Use the row index to avoid scanning every namespace/resource pair.
        RU: Использовать индекс строк вместо перебора всех пар namespace/ресурс.

        Args:
            permission (dict): Assignment rule / Правило назначения.
            index (dict): Rows grouped by API resource and scope / Строки по API-ресурсу и области.
            urls (list[tuple]): Non-resource URL rows / Строки URL вне ресурсов.

        Yields:
            tuple: A potentially matching row, still requiring verb checks / Возможная подходящая строка, требующая проверки verbs.
        """
        keys = set()
        rule, ns = permission["rule"], permission["namespace"]
        for group in rule.get("apiGroups", []):
            for resource in rule.get("resources", []):
                if group != "*" and resource != "*" and not resource.startswith("*/"):
                    if (group, resource) in index:
                        keys.add((group, resource))
                else:
                    keys.update((g, r) for g, r in index
                                if group in ("*", g) and self.resource_matches(resource, r))
        for key in sorted(keys):
            scopes = index[key]
            for scope in ([ns] if ns else sorted(scopes)):
                yield from scopes.get(scope, [])
        if not ns and rule.get("nonResourceURLs"):
            yield from urls

    def report(self):
        """EN: Read selected sources and calculate filtered masks with provenance.
        RU: Прочитать выбранные источники и вычислить отфильтрованные маски с происхождением.

        Returns:
            dict: Three CSV strings, summary and limitations / Три CSV-строки, сводка и ограничения.

        Raises:
            AccessError: Required reads, discovery, roles or membership cannot be resolved / Нельзя прочитать или разрешить discovery, роли либо членство.
        """
        self.read()
        self.bindings()
        self.identities()
        broad = self.broad_subjects()
        external = {key for key, info in self.subjects.items()
                    if key[0] == "User" and "deckhouse-user" not in info["sources"]}
        selected = sorted(key for key in self.subjects if self.subject_selected(key) and key not in broad)
        # Excluded wildcard principals must not seed rows, even when other users have
        # incomplete memberships: otherwise those rows survive as question marks.
        # RU: Исключённые широкие назначения не должны создавать строки, остающиеся только из-за «?».
        permissions = [p for p in self.permissions if p["subject"] not in broad
                       and (self.cfg["include_external_users"] or p["subject"] not in external)]
        rows = self.rows(permissions)
        index, urls = {}, []
        for row in rows:
            if row[4]:
                urls.append(row)
            else:
                index.setdefault((row[1], row[2]), {}).setdefault(row[0], []).append(row)
        # Sparse accumulation retains every source while direct grants win casing.
        cells, audit = {}, []
        for permission in permissions:
            targets = [(key, key != permission["subject"]) for key in selected if (
                key == permission["subject"] or permission["subject"][0] == "Group"
                and not self.direct_only(key)
                and permission["subject"][2] in self.subjects[key]["groups"]
            )]
            if not targets:
                continue
            binding, role = permission["binding"], permission["role"]
            for row in self.candidates(permission, index, urls):
                verbs = self.matching_verbs(permission, row)
                if not verbs:
                    continue
                for key, inherited in targets:
                    granted = cells.setdefault((row, key), {})
                    for verb in verbs:
                        granted[verb] = max(granted.get(verb, 0), 1 if inherited else 2)
                    audit.append(dict(zip(ROW_FIELDS, row),
                                      record_type="inventory-rbac" if self.inventory is not None else "rbac", subject=label(key),
                                      via_group=permission["subject"][2] if inherited else "",
                                      origin="inherited" if inherited else "direct",
                                      verbs=",".join(sorted(verbs)), binding_kind=binding["kind"],
                                      binding_namespace=binding["metadata"].get("namespace", ""),
                                      binding_name=binding["metadata"]["name"], role_kind=role["kind"],
                                      role_namespace=role["metadata"].get("namespace", ""),
                                      role_name=role["metadata"]["name"],
                                      aggregation=compact(role.get("aggregationRule", {})),
                                      deckhouse_origins=compact(permission["origins"])))
        matrix_rows = []
        for row in rows:
            masks = []
            for key in selected:
                grants = cells.get((row, key), {})
                letters = zip(VERBS, LETTERS) if row[-1] == "standard" else [(row[-1], "Y")]
                masks.append("".join(letter if grants.get(verb) == 2 else letter.lower() if grants.get(verb) == 1
                                     else "." if self.direct_only(key) or self.subjects[key]["complete"] else "?"
                                     for verb, letter in letters))
            # Unknown membership is meaningful and must never be treated as denial.
            # RU: Неизвестное членство локального User не равно запрету; внешние User показывают только прямые права.
            if not self.cfg["omit_empty_rows"] or any(set(mask) - {"."} for mask in masks):
                matrix_rows.append(list(row) + masks)
        subject_fields = ["subject", "kind", "namespace", "name", "groups", "membership_complete", "sources", "rights_basis"]
        subject_rows = [[label(key), *key, compact(sorted(self.subjects[key]["groups"])),
                         str(self.subjects[key]["complete"]).lower(), compact(sorted(self.subjects[key]["sources"])),
                         "direct_only" if self.direct_only(key) else "direct_and_groups"]
                        for key in selected]
        if any(not self.direct_only(key) and not self.subjects[key]["complete"] for key in selected):
            self.warnings.add("User group membership is incomplete; unknown positions are '?' rather than denials")
        if external & set(selected):
            self.warnings.add("External User columns show direct grants only; dots mean no direct grant, group access is not evaluated")
        if external and not self.cfg["include_external_users"]:
            self.warnings.add("External User columns and direct User bindings are excluded; external groups are shown without member inference")
        if self.cfg["scope"] == "managed":
            self.warnings.add("Managed scope includes only owned RBAC bindings; other grants, including unowned generated bindings, are excluded")
        relevant = set(selected)
        relevant.update(("Group", "", group) for key in selected if not self.direct_only(key)
                        for group in self.subjects[key]["groups"])
        for declaration in self.declarations:
            if not declaration["_subjects"] & relevant:
                continue
            ns = declaration["binding_namespace"]
            if ns and ns not in self.selected_namespaces:
                continue
            declaration["resolved_namespaces"] = compact([
                ns for ns in json.loads(declaration["resolved_namespaces"]) if ns in self.selected_namespaces
            ])
            audit.append(declaration)
        audit_fields = ["record_type", "subject", "origin", "via_group"] + list(ROW_FIELDS) + [
            "verbs", "binding_kind", "binding_namespace", "binding_name", "role_kind", "role_namespace",
            "role_name", "aggregation", "deckhouse_origins", "declaration", "resolved_namespaces", "reconciliation",
        ]
        audit_rows = sorted(set(tuple(record.get(k, "") for k in audit_fields) for record in audit))
        if self.namespace_filtered or len(selected) != len(self.subjects) or len(matrix_rows) != len(rows):
            self.warnings.add("Filtered report: inspect summary.filters and exclusion counts before treating it as a full audit")
        delimiter = self.cfg["csv"]["delimiter"]
        return {
            "files": {
                "matrix.csv": csv_text(list(ROW_FIELDS) + [label(key) for key in selected], matrix_rows, delimiter),
                "bindings.csv": csv_text(audit_fields, audit_rows, delimiter),
                "subjects.csv": csv_text(subject_fields, subject_rows, delimiter),
            },
            "summary": {"subjects": len(selected), "rows": len(matrix_rows), "sources": len(audit_rows),
                        "source": self.cfg["source"],
                        "scope": self.cfg["scope"], "cluster_version": self.version,
                        "output_dir": self.cfg["output_dir"], "mask": LETTERS,
                        "excluded_namespaces": len(self.namespaces) - len(self.selected_namespaces),
                        "excluded_subjects": len(self.subjects) - len(selected),
                        "excluded_external_users": 0 if self.cfg["include_external_users"] else len(external),
                        "excluded_broad_subjects": len(broad),
                        "excluded_broad_subject_names": sorted(label(key) for key in broad),
                        "omitted_empty_rows": len(rows) - len(matrix_rows),
                        "selected_namespaces": self.selected_namespaces,
                        "filters": {k: v for k, v in self.cfg.items()
                                    if k not in ("output_dir", "csv", "memberships", "resolve_group_membership")}},
            "warnings": sorted(self.warnings) + [
                "RBAC snapshot only: webhook/Node/ABAC, system:masters bypass, admission and indirect escalation are not evaluated",
                "Collections are read sequentially; the report is not an atomic cluster snapshot",
            ],
        }
