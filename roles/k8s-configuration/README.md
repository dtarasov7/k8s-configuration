# k8s-configuration

Ansible-роль для управления доступом в vanilla Kubernetes и Deckhouse через HTTPS REST API. Поддерживает `dry`, `apply`, `export`, Ansible check/diff, локальные Deckhouse User/Group, RBAC и базовую авторизацию Deckhouse. `kubernetes.core`, SDK и kubectl во время работы роли не используются.

Обычные пользователи и группы vanilla Kubernetes существуют во внешнем аутентификаторе. Роль назначает им права, но не создаёт учётные записи LDAP/OIDC, сертификаты, Namespace, Role/ClusterRole, ServiceAccount и токены.

## Требования и запуск

Execution host: Python >=3.8, PyYAML, доступ к API и подготовленный kubeconfig. Control node: ansible-core >=2.12 с совместимой версией Python. Профили зависимостей зафиксированы в `requirements-legacy.txt` и `requirements-modern.txt`; legacy 2.12 уже EOL. Установка зависимостей выполняется отдельно от роли. RED OS не определяется через одну лишь os_family: роль не устанавливает пакеты и проверяет фактический интерпретатор.

Play должен содержать **один** execution host. Для каждого cluster/owner нужен последовательный CI job: кластерные изменения не транзакционны. Ключи kubeconfig и локальные TLS-файлы должны быть доступны execution host; lookup переменных выполняется на control node.

```yaml
# inventory.yml
all:
  hosts:
    access_executor:
      ansible_connection: local
      ansible_python_interpreter: /usr/bin/python3
```

```yaml
# access.yml
- name: Manage access
  hosts: access_executor
  gather_facts: false
  vars:
    k8s_configuration_config:
      mode: dry
      platform: vanilla
      connection:
        kubeconfig: /etc/ansible/kubeconfigs/prod.yaml
        context: prod
      management:
        owner: platform
        namespaces: [development]
        include_cluster_scoped: false
    k8s_configuration_grants:
      - id: developers
        backend: rbac
        subjects:
          - kind: Group
            source: external
            name: oidc:developers
        roleRef:
          kind: ClusterRole
          name: edit
        scope:
          namespaces: [development]
  roles:
    - role: k8s-configuration
```

Из корня проекта:

```bash
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml --check --diff
```

Режим задаётся через `k8s_configuration_config.mode`: `dry` (по умолчанию), `apply`, `export`.

- `dry` читает кластер и выводит **«Планируем добавить»**, **«Планируем изменить»**, **«Планируем удалить»** со списками объектов. Не требует `--check`/`--diff`, не пишет в кластер и возвращает `changed: false`. Замена immutable `roleRef` попадает в изменения с `action: replace` и означает удаление/создание ресурса.
- `apply` применяет желаемое состояние. `--check` строит тот же план без записи и сообщает прогноз `changed`; `--diff` показывает очищенный before/after, в том числе вместе с `--check`.
- `export` читает фактическое состояние и сохраняет YAML с переменными роли. `--check` оставляет режим export и проверяет необходимость записи файла, не создавая его. Экспорт bcrypt-хешей скрыт из diff.

`plan` сохранён как устаревший синоним `dry`. `server_validation` используется только при настоящем apply: dry/check не отправляют даже server-side dryRun. Явно заданный report_path сохраняет локальный отчёт; при `--check` действует обычная проверка записи Ansible copy.

Роль переименована из `k8s_access_manager`: каталог и ссылка в playbook теперь `k8s-configuration`, модуль — `k8s_configuration`, префикс всех переменных — `k8s_configuration_`. Старые имена переменных нужно заменить. Значения owner, label_domain и алгоритм имён ресурсов сохранены: переименование роли не приводит к потере владения существующими объектами. Galaxy role_name — `k8s_configuration`, поскольку Galaxy не допускает дефис в этом поле.

## Переменные роли

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `k8s_configuration_config` | См. defaults | Основная конфигурация ниже |
| `k8s_configuration_users` | Не определена | Локальные Deckhouse User |
| `k8s_configuration_groups` | Не определена | Локальные Deckhouse Group |
| `k8s_configuration_grants` | Не определена | Назначения прав |
| `k8s_configuration_export` | `{destination: ./k8s-configuration-export.yml}` | Фильтры экспорта ниже |
| `k8s_configuration_report_path` | `""` | Явный путь отчёта на execution host, родительский каталог уже должен существовать |
| `k8s_configuration_no_log` | `true` | Скрывает полный результат; при --diff выводится безопасный diff; export скрыт всегда |
| `k8s_configuration_certificates` | `[]` | Список `{name, content}`, имена: ca_content/cert_content/key_content; временные файлы удаляет API-клиент |
| `k8s_configuration_hashi_vault_path` | `""` | Необязательный путь для lookup в пользовательских переменных |
| `k8s_configuration_hashi_vault_path_password` | `""` | Аналогичный путь к секретам паролей |
| `k8s_configuration_local_certs_path` | `./certs/` | Базовый путь для локальных lookup в пользовательских переменных |
| `k8s_configuration_result` | Результат задачи | Зарегистрированные plan/exported/completed, changed |

Пропущенный users/groups/grants не управляется. `[]` — явно пустое desired state; удаление stale-ресурсов дополнительно требует prune и allow_empty_desired. Настройки config рекурсивно дополняются внутренними безопасными defaults, а не зависят от Ansible hash_behaviour. Неизвестные поля отвергаются.

### config

| Поле | Default / допустимые значения |
| --- | --- |
| schema_version | `1` |
| mode | `dry`, `apply`, `export` |
| platform | `vanilla`, `deckhouse` |
| connection.kubeconfig | Обязательный путь к одному kubeconfig |
| connection.context | current-context, если не задан |
| connection.validate_tls | `true`; insecure kubeconfig требует явного false |
| connection.timeout_seconds | `30`, 1..3600 |
| connection.retries | `2`, 0..5, для GET при временных ошибках |
| connection.ca_content/cert_content/key_content | PEM вместо файлов kubeconfig |
| management.owner | `ansible-access-manager`, значение Kubernetes label |
| management.label_domain | `access-manager.ansible.local`, фиксируется до первого apply |
| management.prune | `false` |
| management.prune_identities | `false`, требуется и для explicit absent User/Group |
| management.adoption | `[]`, точные `{group, resource, namespace?, name, uid}` |
| management.namespaces | `null`: все namespace; список ограничивает изменение и prune |
| management.include_cluster_scoped | `true`; false запрещает управление cluster-scoped ресурсами, включая User/Group |
| safety.max_deletions | `10`, включает удаление внутри replace |
| safety.allow_empty_desired | `false` |
| safety.allow_binding_replacement | `false` |
| safety.protected_namespaces | kube-system, kube-public, kube-node-lease, default, loghouse |
| safety.protected_namespace_prefixes | kube-, d8- |
| safety.allowed_protected_namespaces | `[]`, точные исключения |
| safety.protected_objects | `[]`, точные `{group, resource, namespace?, name}` |
| deckhouse.basic_authz | `false` |
| deckhouse.compatibility_profile | Имя профиля в deckhouse.profiles, обязательно для Deckhouse |
| deckhouse.profiles | `{}`, см. ниже |
| server_validation | `false`; разрешает dryRun=All POST/PATCH перед apply; в dry/check не используется |
| wait_timeout_seconds | `60`, ожидание удаления, Ready и доступа |
| expected_plan_digest | Не задан; расхождение с текущим планом блокирует запуск |
| access_checks | `[]`, проверки SubjectAccessReview после apply, см. ниже |

Ownership использует label-domain `/owner`, `/managed-by`, `/section` и annotations `/grant-id`, `/schema-version`. Значение managed-by — `ansible`. Смена label_domain/owner требует отдельной миграции, иначе прежние объекты считаются чужими. Метки не защищают от администратора, который может их подделать.

Клиент поддерживает bearer token, tokenFile (перечитывается при запросе), certificate/key и data-поля. Относительные пути разрешаются от kubeconfig. Не поддерживаются exec/auth-provider, refresh OIDC, basic auth, impersonation, proxy-url, tls-server-name, extensions и объединение KUBECONFIG. Redirect запрещён; ошибки API не включают серверное тело. TLS verify включён по умолчанию.

### users, groups, grants

```yaml
k8s_configuration_users:
  - name: jane
    source: static
    email: jane@example.org
    password_hash: "{{ vault_jane_bcrypt }}"
    password_policy: on_create
    allow_collision: false
k8s_configuration_groups:
  - name: developers
    source: static
    claim_name: developers
    members: [jane]
    allow_collision: false
k8s_configuration_grants:
  - id: payments
    backend: deckhouse
    subjects:
      - kind: Group
        source: static
        name: developers
    accessLevel: Editor
    options:
      allowScale: false
      portForwarding: false
    scope:
      namespaces: [payments]
```

User: name/source/email, необязательные password_hash/password_policy/allow_collision/state. Email lowercase, password_hash — raw bcrypt. Для нового User хеш обязателен. on_create сохраняет пароль существующего User, managed обновляет при наличии хеша и `profile.password_updates: true`. UserOperation, 2FA, TTL, reset/revoke сессий не реализуются.

Group: name/source/claim_name/members, необязательные allow_collision/state. members — список имён present User из того же inventory, полный управляемый состав. Вложенные группы не поддерживаются. allow_collision добавляет конкретной identity аннотацию `user-authz.deckhouse.io/allow-authorization-rule-collision: "true"`; автоматически она не выставляется.

Grant: id/backend/subjects/scope и roleRef для rbac либо accessLevel/options для deckhouse. Дополнительно state и target_name. Имена API-объектов по умолчанию детерминированы: owner/id/kind/namespace и SHA-256. target_name задаёт существующее имя при export/adoption и разрешён только для одного физического target.

subject: `{kind: User|Group, source: external|static, name}` либо `{kind: ServiceAccount, source: serviceaccount, name, namespace}`. Static User превращается в email, Group — в claim_name. External использует точную строку после всех преобразований аутентификатора. source не является частью Kubernetes subject и не разделяет совпадающие конечные имена.

Scope: ровно один из `cluster: true`, `namespaces: [..]`, `namespace_selector: {matchLabels: .., matchExpressions: ..}`. Selector поддерживает только Deckhouse CAR и не может быть пустым. CAR cluster дополнительно требует boolean include_system_namespaces; vanilla ClusterRoleBinding не умеет исключать namespace. RoleBinding может ссылаться на Role этого namespace или ClusterRole; ClusterRoleBinding — только на ClusterRole.

Для AR уровни: User, PrivilegedUser, Editor, Admin. Для CAR дополнительно ClusterEditor, ClusterAdmin, SuperAdmin. Произвольные ClusterRole не считаются безопасной заменой accessLevel. `d8:*` и `user-authz:*` роли допускаются только в явно разрешённом profile.granular_roles scope.

`state: absent` требует идентификатор, source у identity, backend/scope у grant; subjects/roleRef/пароль не нужны. Удаляются только собственные объекты, с теми же лимитами и защитами, что у prune.

### Deckhouse profile

Готовых production-профилей в роли нет: в проекте не указаны версия и редакция реального Deckhouse. Профиль задаёт оператор после тестирования на стенде. Это явный контракт совместимости, не автоматическое подтверждение поддержки.

```yaml
k8s_configuration_config:
  platform: deckhouse
  mode: dry
  connection:
    kubeconfig: /etc/ansible/dkp.yaml
  deckhouse:
    basic_authz: true
    compatibility_profile: my-tested-dkp
    profiles:
      my-tested-dkp:
        deckhouse_image: registry.example.org/deckhouse/ee:v1.78.0
        api_versions:
          User: deckhouse.io/v1
          Group: deckhouse.io/v1alpha1
          AuthorizationRule: deckhouse.io/v1alpha1
          ClusterAuthorizationRule: deckhouse.io/v1
        mixed_backends: false
        password_updates: false
        authz_ready_condition: Ready
        ready_checks:
          user-authn:
            - path: /apis/apps/v1/namespaces/d8-user-authn/deployments/dex
              pointer: /status/availableReplicas
              minimum: 1
          user-authz:
            - path: /apis/apps/v1/namespaces/d8-user-authz/deployments/user-authz-controller
              pointer: /status/availableReplicas
              minimum: 1
        granular_roles:
          d8:use:role:viewer: [namespace]
        controller_markers:
          labels:
            rbac.deckhouse.io/automated: "true"
          annotations: {}
          name_prefixes: []
```

Пути выше — пример для версии с отдельным контроллером, их нужно сверить с установленным выпуском. Обязательные поля профиля: deckhouse_image, api_versions всех четырёх CR, mixed_backends, ready_checks. В каждом probe: path, JSON pointer и ровно одно из equals/minimum. authz_ready_condition опционален; без него для basic grants обязательны положительные access_checks. password_updates по умолчанию false; granular_roles и дополнительные controller_markers по умолчанию пустые.

Проверяются точный образ и готовность Deployment deckhouse, ModuleConfig, probes, discovery и served CRD schema. На Deckhouse всегда проверяется user-authz; для users/groups/export — также user-authn. Явно отключённый модуль блокирует запуск даже при сохранившихся CRD. Отсутствующие ModuleConfig/CRD и ошибки чтения завершают запуск. CAR требует подтверждённого `enableMultiTenancy: true` даже при общекластерном scope; это намеренно консервативное ограничение первой реализации.

Selector сохраняется динамическим, совпадение с защищённым namespace сейчас запрещается. Изменение меток в будущем может расширить доступ; для строгой изоляции используйте список namespace. Включение системных namespace в cluster scope — явное решение include_system_namespaces: true.

Проверки доступа после apply:

```yaml
access_checks:
  - user: jane@example.org
    groups: [developers]
    resourceAttributes:
      namespace: payments
      verb: list
      resource: pods
    allowed: true
  - user: jane@example.org
    groups: [developers]
    resourceAttributes:
      namespace: restricted
      verb: get
      resource: secrets
    allowed: false
```

Это поля config. Для SubjectAccessReview нужны отдельные права исполнителя; группы задаются явно, API не делает lookup членства IdP. Положительные проверки дополнительно выполняются перед stale-prune; полный набор — после применения. Проверки выполняются и при apply без изменений. Plan/check их не отправляет, поскольку SAR использует POST.

### Export

```yaml
k8s_configuration_config:
  mode: export
  connection:
    kubeconfig: /etc/ansible/cluster.yaml
k8s_configuration_export:
  mode: scoped
  backends: [rbac, deckhouse]
  cluster_roles: [view, edit]
  roles:
    - namespace: development
      name: custom-reader
  access_levels: [User, Editor]
  namespaces: [development]
  include_cluster_scoped: false
  exclude_controller_generated: true
  destination: ./exports/cluster.yaml
```

Defaults export: mode managed; backends оба; cluster_roles/roles/access_levels/namespaces пусты; include_cluster_scoped true; exclude_controller_generated true; include_identities true; allow_partial false; destination `./k8s-configuration-export.yml`; audit_destination не задан. В scoped пустые списки ролей/уровней не разрешают экспорт таких назначений: перечислите нужные роли/уровни. Для сохранения ручных изменений собственных объектов используйте managed, для новых ручных объектов — scoped с фильтрами. Пустой namespaces не ограничивает namespace. Cluster-scoped назначения включены по умолчанию; include_cluster_scoped=false их исключает. CAR экспортируется целиком, namespace-фильтр не обрезает его selector.

В `destination` записываются непосредственно три переменные — без служебной обёртки:

```yaml
k8s_configuration_users: []
k8s_configuration_groups: []
k8s_configuration_grants:
  - id: export-0123456789abcdef
    target_name: existing-readers
    backend: rbac
    subjects:
      - kind: Group
        source: external
        name: readers
    roleRef:
      kind: ClusterRole
      name: view
    scope:
      namespaces: [development]
```

Файл можно без изменения содержимого подключить через `vars_files: [./exports/cluster.yaml]`, положить в group_vars либо вставить в inventory в раздел vars. `k8s_configuration_config` задаётся отдельно: kubeconfig, Deckhouse profile и owner относятся к целевой среде. Namespace, Role/ClusterRole и ServiceAccount должны существовать на целевом кластере, роль не переносит их определения.

Опциональный `audit_destination: ./exports/cluster-audit.yaml` сохраняет отдельный отчёт с UID, ownership, unsupported_fields, importable и очищенными snapshot. Аудит не попадает в импортируемый файл. По умолчанию неподдерживаемые выбранные объекты (например, additionalRoles, TTL или непредставимые зависимости) блокируют экспорт до записи файла. `allow_partial: true` явно разрешает неполный снимок для разбора вместе с аудитом; для переноса его полнота не гарантируется.

User/Group включаются и без назначений, если попадают в область managed/scoped и include_identities=true; необходимые зависимости grants включаются всегда. Экспорт локального User сохраняет bcrypt из spec.password как raw `password_hash`, чтобы пользователь мог быть создан в другом кластере без добавления пароля. Хеши не выводятся в консоль, audit или diff. Файлы имеют права 0600; каталог должен существовать. Для хранения в Git файл с хешами предварительно зашифруйте Ansible Vault. Токены, ключи kubeconfig и сессии не экспортируются.

`target_name` сохраняет исходное имя объекта. При применении к исходному кластеру чужой/ручной объект всё ещё требует точного UID-bound management.adoption: export не меняет владение. На новом кластере отсутствующие объекты создаются без adoption. Не включайте prune с пустыми экспортированными разделами без проверки.

### Секреты

Ansible Vault или HashiCorp Vault разрешаются через переменные, алгоритм задач не зависит от источника:

```yaml
# Локальный / Ansible Vault вариант:
vault_jane_bcrypt: "{{ lookup('file', 'private/jane.bcrypt') | trim }}"
# Альтернатива, требует установленного lookup-плагина community.hashi_vault:
# vault_jane_bcrypt: "{{ lookup('community.hashi_vault.hashi_vault', k8s_configuration_hashi_vault_path_password + ':jane') }}"
k8s_configuration_hashi_vault_path_password: secret=team/data/k8s-users
k8s_configuration_hashi_vault_path: ""
k8s_configuration_certificates:
  - name: ca_content
    content: >-
      {{ lookup('community.hashi_vault.hashi_vault', k8s_configuration_hashi_vault_path + ':ca')
         if k8s_configuration_hashi_vault_path | length > 0
         else lookup('file', k8s_configuration_local_certs_path + 'ca.pem') }}
```

Аналогично можно передать cert_content/key_content или оставить пути в kubeconfig. Секретные временные файлы 0600, каталог 0700, удаляются finally. Проверки TLS выполняются в ssl.yml, запись временных файлов — в API-клиенте только на время соединения. Внешний Vault lookup не является runtime-зависимостью самой роли.

## Безопасность и ограничения

Prune по умолчанию выключен. Чужие owner, частичные ownership labels, controller-owned и защищённые объекты не изменяются. Признаки контроллера: ownerReferences, Helm/Deckhouse labels, Helm annotations, rbac.deckhouse.io/automated и дополнительные маркеры профиля. Adoption — только точный UID, без смены чужого owner; unsupported поля блокируют захват.

GET-списки читаются полностью. Перед apply перепроверяются cluster UID, ресурсы, версии ролей/CRD/ModuleConfig/probes и метки namespace. Затем PATCH использует JSON Patch test UID/resourceVersion, DELETE — preconditions. Новые foreign labels сохраняются; subjects/members принадлежат роли целиком. При смене roleRef требуется replace opt-in с перерывом доступа. Finalizers не снимаются.

Порядок: User → Group → grants → stale grants → groups → users. При сбое последующий prune не выполняется. Создание нового назначения перед удалением старого может временно объединить права; для миграции без перекрытия используйте два отдельных запуска с отзывом сначала. Удаление identity блокируется оставшимися API-ссылками; токены/IdP-сессии роль не отзывает.

Отчёт содержит before/after, summary, digest, completed/pending при сбое. privilege_change консервативен: create increase, delete decrease, остальные unknown. Он не доказывает отсутствие повышения прав. Изменения password помечаются без значения. Digest не включает секреты, но включает безопасное desired state, политики, наблюдаемые версии и config; секретные CI-входы фиксируйте отдельно. Dry-run не проверяет фактическую работу контроллера; replace полностью dry-run проверить нельзя.

Исполнителю нужны get/list выбранных ресурсов, Namespace, referenced Role/ClusterRole; create/patch/delete для apply, а также назначаемые права или bind согласно Kubernetes. Deckhouse дополнительно требует get Deployment, ModuleConfig и CRD; export identities — get/list User/Group. Для полноты проверки ссылок списки authorization-ресурсов читаются по всему кластеру даже при ограниченном management.namespaces. Ошибка 403 блокирует планирование. Роль не выдаёт себе cluster-admin; её binding и аварийные назначения следует включить в protected_objects.

Теги: pre-req, install, user, ssl, config. `clean` запускается только явно (`--tags clean`), завершает play; постоянные сервисы/локальные пользователи роль не создаёт, TLS временные файлы убирает клиент. Отчёты и кластерные права через clean не удаляются. Для записи report/export используйте существующий приватный каталог; copy записывает атомарно с mode 0600.

## Проверки

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i roles/k8s-configuration/examples/inventory.yml roles/k8s-configuration/examples/playbook.yml --syntax-check
```

Unit suite включает локальный HTTPS-сервер и openssl; integration suite запускает Ansible против него. Эти тесты проверяют транспорт и упаковку, но не заменяют контроллеры Deckhouse.

Molecule default: Docker driver, предварительно подготовленный образ RED OS с Python 3.8/PyYAML, host network, настоящий отдельный kind API. Systemd/privileged для executor не нужны. Подготовка к запуску:

```bash
mkdir -p .test-tmp/wheels
python3 -m pip download --no-deps --dest .test-tmp/wheels PyYAML==6.0.2
docker build -f roles/k8s-configuration/tests/execution-environment/Dockerfile -t k8s-access-manager-test-redos:7.3.6 .test-tmp/wheels
kind create cluster --name kam-role-validation --config roles/k8s-configuration/tests/integration/kind.yml --kubeconfig "$PWD/.test-tmp/kind.kubeconfig" --image kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48 --wait 120s
export KAM_TEST_KUBECONFIG="$PWD/.test-tmp/kind.kubeconfig"
export KAM_MOLECULE_IMAGE=k8s-access-manager-test-redos:7.3.6
cd roles/k8s-configuration
molecule test
```

Kubeconfig должен иметь test context `kind-kam-role-validation`. kind fixture — три control-plane узла. Molecule проверяет apply/idempotence, реальный разрешённый/запрещённый доступ, export, replace, отзыв и восстановление. Для деградации выполните из корня проекта `python3 roles/k8s-configuration/tests/degradation.py "$KAM_TEST_KUBECONFIG"`: скрипт остановит один control-plane узел, проверит роль и восстановит узел в finally. Удаление стенда: `kind delete cluster --name kam-role-validation`. Образ исполнителя можно заменить KAM_MOLECULE_IMAGE; он должен уже содержать зависимости, роль их не устанавливает.

Настоящий Deckhouse проверяется playbook `tests/integration/deckhouse.yml` с отдельным private vars-файлом, тестовым кластером и минимум положительным/отрицательным access_checks. Готовый профиль для реального Deckhouse не заявляется без такого прогона. Сведения о фактически выполненных проверках находятся в `VALIDATION.md`.
