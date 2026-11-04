# k8s-configuration

Ansible-роль для управления доступом в vanilla Kubernetes и Deckhouse через установленный `kubectl`. Поддерживает `dry`, `apply`, `export`, `matrix`, Ansible check/diff, RBAC и базовую авторизацию Deckhouse. Собственного HTTP-клиента нет; `kubernetes.core` и Kubernetes SDK не требуются.

Роль управляет только назначениями доступа существующим субъектам. Создание, изменение и удаление User/Group, смена паролей и управление составом групп исключены из роли. User/Group читаются из Deckhouse только для матрицы прав. Обычные пользователи и группы vanilla Kubernetes существуют во внешнем аутентификаторе. Роль назначает им права, но не создаёт учётные записи LDAP/OIDC, сертификаты, Namespace, Role/ClusterRole, ServiceAccount и токены.

## Файлы результатов на Ansible controller

В dry (включая alias plan), export и matrix результат сохраняется автоматически на компьютере, где запущен ansible-playbook. kubectl и чтение API остаются на выбранном target host. Для записи используется delegate_to: localhost, local connection, ansible_playbook_python и become=false; дополнительный localhost в inventory не нужен.

Переменные можно задать в inventory/group_vars:

```yaml
k8s_configuration_report_path: "{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml"
k8s_configuration_export_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml"
k8s_configuration_export_audit_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml"
k8s_configuration_matrix_output_dir: "{{ playbook_dir }}/output/{{ inventory_hostname }}"
k8s_configuration_matrix_filename: matrix.csv
k8s_configuration_matrix_bindings_filename: bindings.csv
k8s_configuration_matrix_subjects_filename: subjects.csv
```

Это значения по умолчанию. report_path и export_destination задают полный путь вместе с именем файла; matrix_output_dir — каталог, три *_filename — имена CSV. Относительные пути считаются от playbook_dir на controller, ~ раскрывается для пользователя controller. Пути файлов одного результата должны различаться. Dry report_path не может быть пустым; пустой export_audit_destination отключает только дополнительный аудит. Apply автоматически файлы не сохраняет.

Dry содержит очищенный план с «Планируем добавить/изменить/удалить». Export содержит напрямую импортируемые grants; аудит записывается отдельно. Matrix сохраняет три CSV с матрицей, источниками и членством. Новые каталоги получают 0700, файлы — 0600; существующие права каталогов сохраняются. Содержимое файлов не выводится через --diff, содержимое экспорта скрыто в stdout. В конце выводятся пути файлов на controller.

--check по-прежнему читает кластер и прогнозирует запись файлов, не создавая их. changed в read-only режимах может означать запись файлов на controller; мутаций API Kubernetes при этом нет. Повторный запуск при неизменном результате идемпотентен.

## Требования и запуск

Execution host: Python >=3.8, установленный kubectl, доступ к API и подготовленный kubeconfig. PyYAML для runtime роли на execution host не требуется. Control node: ansible-core >=2.12 с совместимой версией Python. Профили зависимостей зафиксированы в `requirements-legacy.txt` и `requirements-modern.txt`; legacy 2.12 уже EOL. Установка зависимостей выполняется отдельно от роли. RED OS не определяется через одну лишь os_family: роль не устанавливает пакеты и проверяет фактический интерпретатор.

После совместного применения `hosts:` и `--limit` должен остаться **ровно один execution host**. В `hosts:` и `--limit` допустимы имена узлов, группы, `all`, списки и шаблоны. Если итоговых узлов несколько, роль завершается ошибкой до запуска kubectl. `serial: 1` не отменяет проверку всего выбранного набора (`ansible_play_hosts_all`). Для проверки до подключения к узлам задайте `gather_facts: false`. Для каждого cluster/owner нужен последовательный CI job: кластерные изменения не транзакционны. Ключи kubeconfig и локальные TLS-файлы должны быть доступны execution host; lookup переменных выполняется на control node.

```yaml
# inventory.yml
all:
  hosts:
    access_executor:
      ansible_connection: local
      ansible_python_interpreter: /usr/bin/python3
```

```yaml
- name: Manage access
  hosts: access_executor
  gather_facts: false
  vars:
    k8s_configuration_config_mode: dry
    k8s_configuration_config_platform: vanilla
    k8s_configuration_config_connection_kubeconfig: /etc/ansible/kubeconfigs/prod.yaml
    k8s_configuration_config_connection_context: prod
    k8s_configuration_config_management_owner: platform
    k8s_configuration_config_management_namespaces:
    - development
    k8s_configuration_config_management_include_cluster_scoped: false
    k8s_configuration_grants:
    - id: developers
      backend: rbac
      subjects:
      - kind: Group
        name: oidc:developers
      roleRef:
        kind: ClusterRole
        name: edit
      scope:
        namespaces:
        - development
  roles:
  - role: k8s-configuration
```

Из корня проекта:

```bash
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i inventory.yml access.yml --check --diff
```

Режим задаётся через `k8s_configuration_config_mode`: `dry` (по умолчанию), `apply`, `export`, `matrix`.

- `dry` читает кластер и выводит **«Планируем добавить»**, **«Планируем изменить»**, **«Планируем удалить»** со списками объектов. Не требует `--check`/`--diff`, не пишет в кластер; `changed` может отражать сохранение файла результата на контроллере. Замена immutable `roleRef` попадает в изменения с `action: replace` и означает удаление/создание ресурса.
- `apply` применяет желаемое состояние. `--check` строит тот же план без записи и сообщает прогноз `changed`; `--diff` показывает очищенный before/after, в том числе вместе с `--check`.
- `export` читает фактическое состояние и сохраняет YAML с переменными роли. `--check` оставляет режим export и проверяет необходимость записи файла, не создавая его. Экспорт bcrypt-хешей скрыт из diff.

`plan` сохранён как устаревший синоним `dry`. `server_validation` используется только при настоящем apply: dry/check не отправляют даже server-side dryRun. Dry всегда сохраняет план на Ansible controller по k8s_configuration_report_path; при --check запись только прогнозируется.

Роль переименована из `k8s_access_manager`: каталог и ссылка в playbook теперь `k8s-configuration`, модуль — `k8s_configuration`, префикс всех переменных — `k8s_configuration_`. Старые имена переменных нужно заменить. Значения owner, label_domain и алгоритм имён ресурсов сохранены: переименование роли не приводит к потере владения существующими объектами. Galaxy role_name — `k8s_configuration`, поскольку Galaxy не допускает дефис в этом поле.

## Переменные роли

Настройки роли — **плоские переменные**. Например, config.schema_version → k8s_configuration_config_schema_version, connection.kubeconfig → k8s_configuration_config_connection_kubeconfig. Задача execute.yml передаёт плоские параметры прямо Python-модулю; внутренние настройки движка собираются в модуле. vars/main.yml отсутствует.

Список `k8s_configuration_grants` намеренно не имеет defaults: пропуск оставляет назначения неуправляемыми, [] — явно пустое желаемое состояние. Параметры `k8s_configuration_users` и `k8s_configuration_groups` удалены; определения учёток следует создавать вне роли. Списки правил, ссылок на объекты и членства также остаются списками объектов.

Дополнительные переменные: `k8s_configuration_no_log: true`, `k8s_configuration_report_path` (план dry на controller), `k8s_configuration_certificates: []` ({name, content}: ca_content/cert_content/key_content). Результат роли — k8s_configuration_result; export содержит только назначения; содержимое файла скрыто в выводе задач. Неизвестные поля модульного payload отклоняются.

### Выбор узла выполнения

`hosts: redos8` запускает роль и kubectl на redos8 через соединение inventory. `hosts: localhost` запускает их на Ansible controller; для явно описанного localhost задайте `ansible_connection: local`. Kubeconfig, бинарник kubectl, auth plugins и TLS-файлы относятся к выбранному узлу; файлы результатов dry/export/matrix сохраняются на Ansible controller. При become учитывайте пользователя и его окружение; роль не включает sudo автоматически.

Место выполнения можно выбирать через `--limit` (`-l`), например при `hosts: all`:

```bash
ansible-playbook -i inventory/hosts.ini playbook.yaml -l redos8
ansible-playbook -i inventory/hosts.ini playbook.yaml -l localhost
```

Для второго варианта localhost должен присутствовать в inventory с `ansible_connection: local` и попадать в исходный набор `hosts:`. Можно также использовать группу, список или `hosts: "{{ target_host }}"`: проверяется только количество итоговых узлов. Группа из одного узла проходит без `--limit`; группа из нескольких требует ограничения до одного. Если Ansible не выбрал ни одного узла, play пропускается до запуска роли. Группы по-прежнему загружают group_vars.

Вызовы выполняются аргументами без shell. GET/POST/DELETE используют `kubectl get/create/delete --raw`, обновления — `kubectl patch --type=json`. JSON передаётся через stdin. Сохраняются JSON Patch test по UID/resourceVersion и DeleteOptions.preconditions. Токены, ключи и password_hash не передаются в argv. План и границы удаления вычисляет роль; kubectl apply --prune не используется.

### Плоские настройки config

| Переменная | По умолчанию | Назначение и использование |
| --- | --- | --- |
| `k8s_configuration_config_schema_version` | `1` | Версия схемы настроек; перед выполнением роль проверяет поддерживаемое значение 1. |
| `k8s_configuration_config_mode` | `"dry"` | Режим работы: dry строит план, apply применяет изменения, export выгружает назначения, matrix формирует CSV прав; plan — устаревший синоним dry. |
| `k8s_configuration_config_platform` | `"vanilla"` | Платформа кластера: vanilla использует Kubernetes RBAC, deckhouse дополнительно включает поддержку API Deckhouse. |
| `k8s_configuration_config_connection_kubectl` | `"kubectl"` | Имя или путь к kubectl на узле выполнения; через него роль обращается к API кластера. |
| `k8s_configuration_config_connection_validate_tls` | `true` | Включает проверку TLS-сертификата API; false отключает проверку сертификата в kubectl. |
| `k8s_configuration_config_connection_timeout_seconds` | `30` | Тайм-аут обращения к API и выполнения процесса kubectl в секундах. |
| `k8s_configuration_config_connection_retries` | `2` | Число повторов GET при временных ошибках; операции записи автоматически не повторяются. |
| `k8s_configuration_config_connection_kubeconfig` | `""` | Путь к kubeconfig на узле выполнения; пустая строка оставляет стандартный выбор kubeconfig средствами kubectl. |
| `k8s_configuration_config_connection_context` | `""` | Контекст kubeconfig для подключения; пустая строка использует текущий контекст kubectl. |
| `k8s_configuration_config_connection_ca_content` | `""` | PEM-содержимое доверенного CA для API; передаётся kubectl через временный файл на узле выполнения. |
| `k8s_configuration_config_connection_cert_content` | `""` | PEM-содержимое клиентского сертификата; передаётся kubectl через временный файл на узле выполнения. |
| `k8s_configuration_config_connection_key_content` | `""` | PEM-содержимое закрытого ключа клиентского сертификата; передаётся kubectl через временный файл на узле выполнения. |
| `k8s_configuration_config_deckhouse_basic_authz` | `false` | Разрешает управление и prune базовых AuthorizationRule/ClusterAuthorizationRule Deckhouse; требуется для backend: deckhouse. |
| `k8s_configuration_config_deckhouse_api_versions_authorization_rule` | `""` | Закрепляет API-версию Deckhouse AuthorizationRule; пустая строка включает автоматический выбор доступной served-версии. |
| `k8s_configuration_config_deckhouse_api_versions_cluster_authorization_rule` | `""` | Закрепляет API-версию Deckhouse ClusterAuthorizationRule; пустая строка включает автоматический выбор доступной served-версии. |
| `k8s_configuration_config_deckhouse_ready_checks_user_authz` | `[]` | Дополнительные проверки готовности user-authz через API: список {path, pointer, equals или minimum}. |
| `k8s_configuration_config_deckhouse_authz_ready_condition` | `""` | Имя status.conditions для ожидания готовности AR/CAR после применения; пустая строка отключает эту дополнительную проверку. |
| `k8s_configuration_config_deckhouse_mixed_backends` | `false` | Разрешает совместное использование backend: rbac и backend: deckhouse в желаемых назначениях. |
| `k8s_configuration_config_deckhouse_granular_roles` | `[]` | Список {name, scopes: [namespace, cluster]} с разрешёнными областями для специальных ролей d8:* и user-authz:*. |
| `k8s_configuration_config_deckhouse_controller_markers_labels` | `[]` | Список {key, value} меток для распознавания объектов контроллеров; защищает их от изменений и позволяет исключать из экспорта. |
| `k8s_configuration_config_deckhouse_controller_markers_annotations` | `[]` | Список {key, value} аннотаций для распознавания объектов контроллеров; защищает их от изменений и позволяет исключать из экспорта. |
| `k8s_configuration_config_deckhouse_controller_markers_name_prefixes` | `[]` | Префиксы имён для распознавания объектов контроллеров; защищает их от изменений и позволяет исключать из экспорта. |
| `k8s_configuration_config_management_owner` | `"ansible-access-manager"` | Идентификатор владельца управляемых объектов; используется в метках владения и при формировании детерминированных имён. |
| `k8s_configuration_config_management_prune` | `false` | Удаляет собственные объекты, отсутствующие в явно заданных разделах желаемого состояния, с учётом ограничений безопасности. |
| `k8s_configuration_config_management_adoption` | `[]` | Список ссылок на существующие объекты с UID для явного принятия под управление; не разрешает удаление чужих объектов. |
| `k8s_configuration_config_management_label_domain` | `"access-manager.ansible.local"` | Домен служебных меток владения; используется для определения объектов, которыми управляет роль. |
| `k8s_configuration_config_management_namespaces` | `null` | Ограничивает управление указанными namespace; null не ограничивает выборку, пустой список исключает namespaced-объекты. |
| `k8s_configuration_config_management_include_cluster_scoped` | `true` | Разрешает управление кластерными объектами без namespace; false исключает такие объекты из области управления. |
| `k8s_configuration_config_safety_max_deletions` | `10` | Максимальное число удалений в одном плане, включая удаления при замене binding; превышение блокирует выполнение. |
| `k8s_configuration_config_safety_allow_empty_desired` | `false` | Разрешает prune при явно пустом разделе желаемого состояния; без разрешения очистка такого раздела блокируется. |
| `k8s_configuration_config_safety_allow_binding_replacement` | `false` | Разрешает удаление и повторное создание binding при изменении неизменяемого roleRef. |
| `k8s_configuration_config_safety_protected_namespaces` | `["kube-system", "kube-public", "kube-node-lease", "default", "loghouse"]` | Имена namespace, в которых запрещены изменения и удаления объектов, кроме явно разрешённых исключений. |
| `k8s_configuration_config_safety_protected_namespace_prefixes` | `["kube-", "d8-"]` | Префиксы защищённых namespace; блокируют изменения и удаления объектов в совпавших namespace, кроме явно разрешённых исключений. |
| `k8s_configuration_config_safety_allowed_protected_namespaces` | `[]` | Точные имена namespace, для которых снимается защита по имени или префиксу; остальные ограничения сохраняются. |
| `k8s_configuration_config_safety_protected_objects` | `[]` | Список ссылок на объекты, которые запрещено изменять и удалять; используется для защиты аварийных и служебных назначений. |
| `k8s_configuration_config_server_validation` | `false` | Включает серверную dry-run проверку перед настоящим apply; в режимах dry и Ansible check запросы проверки не отправляются. |
| `k8s_configuration_config_wait_timeout_seconds` | `60` | Предельное время ожидания в секундах при проверке результата изменений и готовности объектов Deckhouse. |
| `k8s_configuration_config_expected_plan_digest` | `""` | Ожидаемый digest плана из dry; непустое значение блокирует apply, если вычисленный план отличается. |

### Дополнительные настройки роли

| Переменная | По умолчанию | Назначение и использование |
| --- | --- | --- |
| `k8s_configuration_report_path` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml"` | Путь к YAML-плану dry на Ansible controller; обязателен и непустой, при Ansible check запись только прогнозируется. |
| `k8s_configuration_no_log` | `true` | Скрывает чувствительные аргументы и результаты задач роли в выводе Ansible; по умолчанию включён. |
| `k8s_configuration_certificates` | `[]` | Список {name, content} с готовым TLS-содержимым; name: ca_content, cert_content или key_content переопределяет соответствующий connection_*_content. |

### Назначения доступа: grants

```yaml
k8s_configuration_grants:
  - id: payments
    backend: deckhouse
    subjects:
      - kind: Group
        name: developers
    accessLevel: Editor
    options:
      allowScale: false
      portForwarding: false
    scope:
      namespaces: [payments]
```

Grant: id/backend/subjects/scope и roleRef для rbac либо accessLevel/options для deckhouse. Дополнительно state и target_name. Имена API-объектов по умолчанию детерминированы: owner/id/kind/namespace и SHA-256. target_name задаёт существующее имя при export/adoption и разрешён только для одного физического target.

subject: `{kind: User|Group, name}` либо `{kind: ServiceAccount, name, namespace}`. name передаётся буквально, включая регистр и префиксы. Для локального Deckhouse User укажите email, для Group — spec.name. Поле source в subjects удалено; экспорт использует тот же формат.

Scope: ровно один из `cluster: true`, `namespaces: [..]`, `namespace_selector: {matchLabels: .., matchExpressions: ..}`. Selector поддерживает только Deckhouse CAR и не может быть пустым. CAR cluster дополнительно требует boolean include_system_namespaces; vanilla ClusterRoleBinding не умеет исключать namespace. RoleBinding может ссылаться на Role этого namespace или ClusterRole; ClusterRoleBinding — только на ClusterRole.

Для AR уровни: User, PrivilegedUser, Editor, Admin. Для CAR дополнительно ClusterEditor, ClusterAdmin, SuperAdmin. Произвольные ClusterRole не считаются безопасной заменой accessLevel. `d8:*` и `user-authz:*` роли допускаются только в явно разрешённом profile.granular_roles scope.

`state: absent` требует id, backend и scope назначения; subjects/roleRef не нужны. Удаляются только собственные объекты, с теми же лимитами и защитами, что у prune.

### Имя пользователя Active Directory / LDAP

Для персонального назначения укажите в `subjects.name` точное имя, под которым Kubernetes видит пользователя после входа через AD/LDAP. Сохраняйте регистр и все префиксы: роль передаёт имя без преобразований. Итоговое имя зависит от настроек LDAP/Dex/OIDC; email, `DOMAIN\login` и `sAMAccountName` не являются универсальным форматом.

Выполните команду с kubeconfig нужного пользователя, прошедшего аутентификацию через AD/LDAP:

```bash
kubectl auth whoami -o yaml
```

Возьмите значение `status.userInfo.username`. Если выполнить команду с административным kubeconfig, она покажет имя администратора.

Например, если получено `ivan.petrov@example.org`, назначение чтения в namespace `development` выглядит так:

```yaml
k8s_configuration_grants:
  - id: ivan-read
    backend: rbac
    subjects:
      - kind: User
        name: 'ivan.petrov@example.org'
    roleRef:
      kind: ClusterRole
      name: view
    scope:
      namespaces: [development]
```

Пользователь должен входить через настроенный внешний провайдер; роль создаёт только назначение прав, а не учётную запись AD или объект Deckhouse User.

Источники: [kubectl auth whoami](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_auth/kubectl_auth_whoami/), [аутентификация Kubernetes](https://kubernetes.io/docs/reference/access-authn-authz/authentication/).

### Проверки Deckhouse

Роль определяет доступные served API по discovery, проверяет scope ресурса, Established CRD и схему выбранной версии, включая используемые поля AR/CAR. Пустые `k8s_configuration_config_deckhouse_api_versions_*` означают автоматический выбор; непустая строка закрепляет требуемую API-версию. Наличие CRD само по себе не доказывает готовность модуля.

Для user-authz читается Module: требуются status.phase=Ready, EnabledByModuleManager=True и IsReady=True. ModuleConfig читается при наличии; его отсутствие допустимо, spec.enabled=false блокирует запуск. HTTP 403 не считается отсутствием объекта. Состояние Module и отсутствие/версия ModuleConfig перепроверяются перед apply. [Состояния Module](https://deckhouse.io/products/kubernetes-platform/documentation/v1/architecture/module-development/run/)

Для CAR, требующих multitenancy, по-прежнему необходимо подтверждённое enableMultiTenancy=true в ModuleConfig user-authz. При отсутствии настройки роль не предполагает, что возможность доступна, и не создаёт ModuleConfig.

Отдельная переменная версии/редакции для обычного запуска не нужна: проверяются API и возможности. ready_checks_user_authz — необязательные дополнительные списки {path, pointer, equals|minimum}; выдуманный user-authz-controller не требуется.

`k8s_configuration_config_deckhouse_granular_roles` — список {name, scopes: [namespace|cluster]}; он заменяет словарь role→scopes. controller_markers_labels/annotations — списки {key, value}; name_prefixes — список строк. mixed_backends остаётся явным разрешением оператора. authz_ready_condition пуст по умолчанию: не указывайте Ready для CRD без такой condition.

```yaml
k8s_configuration_config_platform: deckhouse
k8s_configuration_config_mode: dry
k8s_configuration_config_connection_kubeconfig: /etc/ansible/dkp.yaml
k8s_configuration_config_deckhouse_basic_authz: true
k8s_configuration_config_deckhouse_granular_roles:
  - name: d8:use:role:viewer
    scopes: [namespace]
```

### Export

```yaml
k8s_configuration_config_mode: export
k8s_configuration_config_connection_kubeconfig: /etc/ansible/cluster.yaml
k8s_configuration_export_mode: scoped
k8s_configuration_export_backends:
- rbac
- deckhouse
k8s_configuration_export_cluster_roles:
- view
- edit
k8s_configuration_export_roles:
- namespace: development
  name: custom-reader
k8s_configuration_export_access_levels:
- User
- Editor
k8s_configuration_export_namespaces:
- development
k8s_configuration_export_include_cluster_scoped: false
k8s_configuration_export_exclude_controller_generated: true
k8s_configuration_export_destination: ./exports/cluster.yaml
```

Defaults export: mode managed; backends оба; cluster_roles/roles/access_levels/namespaces пусты; include_cluster_scoped true; exclude_controller_generated true; allow_partial false; destination — export.yml в каталоге результатов на controller; audit_destination по умолчанию — export-audit.yml в каталоге результатов на controller. В scoped пустые списки ролей/уровней не разрешают экспорт таких назначений: перечислите нужные роли/уровни. Для сохранения ручных изменений собственных объектов используйте managed, для новых ручных объектов — scoped с фильтрами. Пустой namespaces не ограничивает namespace. Cluster-scoped назначения включены по умолчанию; include_cluster_scoped=false их исключает. CAR экспортируется целиком, namespace-фильтр не обрезает его selector.

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
        name: readers
    roleRef:
      kind: ClusterRole
      name: view
    scope:
      namespaces: [development]
```

Файл можно без изменения содержимого подключить через `vars_files: [./exports/cluster.yaml]`, положить в group_vars либо вставить в inventory в раздел vars. `k8s_configuration_config` задаётся отдельно: kubeconfig, Deckhouse profile и owner относятся к целевой среде. Namespace, Role/ClusterRole и ServiceAccount должны существовать на целевом кластере, роль не переносит их определения.

Опциональный `audit_destination: ./exports/cluster-audit.yaml` сохраняет отдельный отчёт с UID, ownership, unsupported_fields, importable и очищенными snapshot. Аудит не попадает в импортируемый файл. По умолчанию неподдерживаемые выбранные объекты (например, additionalRoles, TTL или непредставимые зависимости) блокируют экспорт до записи файла. `allow_partial: true` явно разрешает неполный снимок для разбора вместе с аудитом; для переноса его полнота не гарантируется.

Export содержит только k8s_configuration_grants с назначениями прав. User/Group, состав групп, пароли и их хеши не экспортируются, в том числе как зависимости. Имена в subjects сохраняются буквально. Файл имеет права 0600; для импорта используются существующие namespace и Role/ClusterRole.

`target_name` сохраняет исходное имя объекта. При применении к исходному кластеру чужой/ручной объект всё ещё требует точного UID-bound management.adoption: export не меняет владение. На новом кластере отсутствующие объекты создаются без adoption. Не включайте prune с пустыми экспортированными разделами без проверки.

### Секреты

Ansible Vault или HashiCorp Vault разрешаются через переменные, алгоритм задач не зависит от источника:

```yaml
# Локальный / Ansible Vault вариант:
# Альтернатива, требует установленного lookup-плагина community.hashi_vault:
example_vault_certificate_path: ""
example_local_certs_path: ./certs/
k8s_configuration_certificates:
  - name: ca_content
    content: >-
      {{ lookup('community.hashi_vault.hashi_vault', example_vault_certificate_path + ':ca')
         if example_vault_certificate_path | length > 0
         else lookup('file', example_local_certs_path + 'ca.pem') }}
```

Аналогично можно передать cert_content/key_content или оставить пути в kubeconfig. Секретные временные файлы 0600, каталог 0700, удаляются finally. Проверки TLS выполняются в ssl.yml, запись временных файлов — в адаптере kubectl на время выполнения модуля. Внешний Vault lookup не является runtime-зависимостью самой роли.

## Безопасность и ограничения

Prune по умолчанию выключен. Чужие owner, частичные ownership labels, controller-owned и защищённые объекты не изменяются. Признаки контроллера: ownerReferences, Helm/Deckhouse labels, Helm annotations, rbac.deckhouse.io/automated и дополнительные маркеры профиля. Adoption — только точный UID, без смены чужого owner; unsupported поля блокируют захват.

GET-списки читаются полностью. Перед apply перепроверяются cluster UID, ресурсы, версии ролей/CRD/ModuleConfig/probes и метки namespace. Затем PATCH использует JSON Patch test UID/resourceVersion, DELETE — preconditions. Новые foreign labels сохраняются; subjects/members принадлежат роли целиком. При смене roleRef требуется replace opt-in с перерывом доступа. Finalizers не снимаются.

Сначала создаются и изменяются назначения, затем удаляются устаревшие назначения. При сбое последующий prune не выполняется. Создание нового назначения перед удалением старого может временно объединить права; для миграции без перекрытия используйте два отдельных запуска с отзывом сначала.

Файл dry содержит разделы add/change/remove и metadata (cluster_uid, cluster_version, owner, digest). Добавления и удаления описаны однократно без apiVersion/apiGroup и служебных metadata; в change.fields показаны только изменённые значения before/after. Замена отмечается replacement: true. adoption выводится только при принятии существующего объекта под управление. privilege_change удалён: отчёт не оценивает фактическое увеличение или уменьшение прав. После apply без изменений списки add/change/remove пусты. Для анализа разрешений используйте matrix. Диагностический результат модуля и обычный --diff сохраняют before/after; файл dry является их кратким представлением. Digest не включает секреты; секретные CI-входы фиксируйте отдельно.

Исполнителю нужны get/list выбранных ресурсов, Namespace, referenced Role/ClusterRole; create/patch/delete для apply, а также назначаемые права или bind согласно Kubernetes. Deckhouse дополнительно требует get Module, ModuleConfig и CRD; дополнительные probes могут требовать get Deployment. Матрица требует get/list User/Group. Для полноты проверки ссылок списки authorization-ресурсов читаются по всему кластеру даже при ограниченном management.namespaces. Ошибка 403 блокирует планирование. Роль не выдаёт себе cluster-admin; её binding и аварийные назначения следует включить в protected_objects.

Теги: pre-req, install, user, ssl, config. `clean` запускается только явно (`--tags clean`), завершает play; постоянные сервисы/локальные пользователи роль не создаёт, TLS-файлы, временные манифесты и отдельный discovery cache kubectl убирает модуль. Отчёты и кластерные права через clean не удаляются. Для записи report/export используйте существующий приватный каталог; copy записывает атомарно с mode 0600.

## Проверки

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i roles/k8s-configuration/examples/inventory.yml roles/k8s-configuration/examples/playbook.yml --syntax-check
```

Unit suite включает настоящий kubectl, локальный HTTPS-сервер и openssl; integration suite запускает Ansible против него. Эти тесты проверяют транспорт и упаковку, но не заменяют контроллеры Deckhouse.

Molecule default: Docker driver, предварительно подготовленный образ RED OS с Python 3.8/PyYAML и kubectl, host network, настоящий отдельный kind API. Systemd/privileged для executor не нужны. Подготовка к запуску:

```bash
mkdir -p .test-tmp/wheels
python3 -m pip download --no-deps --dest .test-tmp/wheels PyYAML==6.0.2
# Нужен kubectl, совместимый с тестовым API 1.34 (например, 1.34.3).
cp "$(command -v kubectl)" .test-tmp/wheels/kubectl
docker build -f roles/k8s-configuration/tests/execution-environment/Dockerfile -t k8s-access-manager-test-redos:7.3.6 .test-tmp/wheels
kind create cluster --name kam-role-validation --config roles/k8s-configuration/tests/integration/kind.yml --kubeconfig "$PWD/.test-tmp/kind.kubeconfig" --image kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48 --wait 120s
export KAM_TEST_KUBECONFIG="$PWD/.test-tmp/kind.kubeconfig"
export KAM_MOLECULE_IMAGE=k8s-access-manager-test-redos:7.3.6
cd roles/k8s-configuration
molecule test
```

Kubeconfig должен иметь test context `kind-kam-role-validation`. kind fixture — три control-plane узла. Molecule проверяет apply/idempotence, реальный разрешённый/запрещённый доступ, export, replace, отзыв и восстановление. Для деградации выполните из корня проекта `python3 roles/k8s-configuration/tests/degradation.py "$KAM_TEST_KUBECONFIG"`: скрипт остановит один control-plane узел, проверит роль и восстановит узел в finally. Удаление стенда: `kind delete cluster --name kam-role-validation`. Образ исполнителя можно заменить KAM_MOLECULE_IMAGE; он должен уже содержать зависимости, роль их не устанавливает.

Настоящий Deckhouse проверяется playbook `tests/integration/deckhouse.yml` с отдельным private vars-файлом и тестовым кластером. Готовый профиль для реального Deckhouse не заявляется без такого прогона. Сведения о фактически выполненных проверках находятся в `VALIDATION.md`.

## Матрица прав: mode: matrix

Режим `matrix` читает состояние кластера через kubectl и сохраняет на Ansible controller три файла: `matrix.csv`, `bindings.csv`, `subjects.csv`. Запись в API, SubjectAccessReview не выполняются. При source=cluster desired grants не читаются и не шаблонизируются. По умолчанию учитываются все RBAC bindings, включая ручные и созданные контроллерами.

```yaml
k8s_configuration_config_mode: matrix
k8s_configuration_config_platform: vanilla
k8s_configuration_config_connection_kubeconfig: /etc/ansible/cluster.yaml
k8s_configuration_config_connection_context: prod
k8s_configuration_matrix_output_dir: "{{ playbook_dir }}/output/{{ inventory_hostname }}"
k8s_configuration_matrix_source: cluster
k8s_configuration_matrix_scope: cluster
k8s_configuration_matrix_namespaces: []
k8s_configuration_matrix_include_cluster_scoped: true
k8s_configuration_matrix_subjects_users: true
k8s_configuration_matrix_subjects_groups: true
k8s_configuration_matrix_subjects_service_accounts: false
k8s_configuration_matrix_resolve_group_membership: true
k8s_configuration_matrix_memberships: []
k8s_configuration_matrix_csv_delimiter: ;
```

Все поля необязательны; defaults совпадают с примером, кроме `memberships: []`; каталог на controller по умолчанию — playbook_dir/output/inventory_hostname. Неизвестные поля отклоняются. `memberships` принимает User либо ServiceAccount с дополнительным namespace; groups и complete обязательны. `complete: true` заменяет выведенное из Deckhouse членство данного субъекта, `false` дополняет его. Стандартные группы аутентификации и ServiceAccount учитываются всегда. Это справочник для отчёта, он не меняет группы в кластере.

`matrix.csv`: первые столбцы — namespace, api_group, resource, resource_name, non_resource_url, action. Далее идут `User:<username>`, `Group:<claim>` и `ServiceAccount:<namespace>/<name>`. Пустая api_group означает core API; пустой resource_name — все имена объектов, а не буквальное `*` в resourceNames. Строки возникают из назначенных правил, с раскрытием wildcard по API discovery; содержимое рабочих объектов и Secrets не читается.

Для `action: standard` ячейка содержит восемь позиций:

| Позиция | G | L | W | C | U | P | D | X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Kubernetes verb | get | list | watch | create | update | patch | delete | deletecollection |

- Заглавная буква: субъект непосредственно указан в binding.
- Строчная: право получено через известное членство в группе, включая системные и вложенные Deckhouse группы.
- Прямое назначение имеет приоритет регистра; все источники сохраняются в bindings.csv.
- `.`: разрешение в выбранном RBAC не найдено при известном членстве.
- `?`: полного состава групп пользователя нет; положительные известные права всё равно показываются буквами.

Пример `GLWcupd.`: прямые get/list/watch, create/update/patch/delete через группу, deletecollection отсутствует. Регистр не зависит от области действия ClusterRoleBinding, агрегации ClusterRole или создания binding контроллером.

Специальные verbs (bind, escalate, impersonate, approve, use и произвольные другие) получают отдельные строки `action: <verb>` с `Y`, `y`, `.`, `?`. Строка `action: *` сохраняет право на любые специальные verbs. Wildcard ресурсов также сохраняется символически, поскольку охватывает будущие API/ресурсы. Namespace `<cluster>` означает кластерный ресурс/URL, `*` — любой namespace, `<all-scopes>` — символическое правило на все области, `<unknown>` — ресурс отсутствует в discovery и его область установить нельзя; об этом выдаётся предупреждение.

RoleBinding действует только внутри своего namespace, даже если ссылается на ClusterRole. ClusterRoleBinding раскрывается по текущим namespace и кластерным ресурсам. При `namespaces: [..]` сохраняются и назначения через ClusterRoleBinding в выбранных namespace; `include_cluster_scoped: false` убирает кластерные ресурсы и URL, сохраняя эти namespaced права. [Семантика RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

resourceNames отображаются отдельными строками; широкие права проецируются и на них. L/W на именованной строке требуют соответствующего field selector metadata.name в запросе. Ограничение по имени не даёт create для основного ресурса и deletecollection; create именованного подресурса, например pods/exec, учитывается. Наличие буквы отражает правило авторизации, а не поддержку операции конкретным HTTP endpoint.

`bindings.csv` содержит субъект, прямое/групповое происхождение, via_group, область, полные verbs, binding и role, aggregationRule и подтверждённый по owner UID источник Deckhouse. Сохраняются все цепочки, а не только источник, определивший регистр буквы. Для агрегированных ClusterRole используются фактические rules; ожидаемые будущие правила по selector не добавляются.

`subjects.csv` содержит тип/имя субъекта, известные группы, membership_complete и источники сведений. Обычные пользователи и группы собираются из bindings/справочника; полного внешнего реестра Kubernetes не предоставляет. ServiceAccount читаются из API, их канонический User-псевдоним объединяется с ServiceAccount; учитываются system:authenticated, system:serviceaccounts и system:serviceaccounts:<namespace>. Для system:anonymous используется system:unauthenticated. Внешние группы человека по умолчанию неизвестны. [Аутентификация Kubernetes](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)

При platform: deckhouse дополнительно читаются User/Group/AuthorizationRule/ClusterAuthorizationRule через обнаруженные served API: readiness модулей для matrix не проверяется. User переводится в email, Group — в spec.name; известные вложенные Group раскрываются, циклы и потерянные ссылки останавливают отчёт. `resolve_group_membership: false` отключает чтение членства из Deckhouse Group для расчёта; явный справочник memberships продолжает работать. Локальные User получают membership_complete=true после чтения полного локального состава групп; это расчёт для локальной аутентификации, а не для токена внешнего провайдера с совпадающим username. При отключённом resolve_group_membership полнота не подтверждается.

AR/CAR сохраняются в bindings.csv как `record_type: deckhouse-declaration` с исходными параметрами и текущими namespace по selector. Они сами не добавляют буквы: права вычисляются по существующему RBAC. Связь с производными bindings устанавливается только по owner UID; при отсутствии связи reconciliation=unverified, названия ресурсов не используются как доказательство. Несовпадение области/субъектов у связанных объектов помечается linked-scope-or-subject-mismatch. Даже linked-by-owner-uid подтверждает происхождение, а не полное соответствие правил декларации. Для legacy scope, который нельзя достоверно раскрыть, список namespace пуст и выводится предупреждение; исходные поля сохраняются.

Отчёт требует GET discovery (всех served API versions), list namespaces/Role/ClusterRole/RoleBinding/ClusterRoleBinding, list ServiceAccount при включённых столбцах и list четырёх Deckhouse видов для platform: deckhouse. Ошибки доступа/discovery и потерянный roleRef прерывают построение до записи файлов; существующие файлы прежнего отчёта при этом остаются. `scope: managed` фильтрует **bindings по ownership**, поэтому показывает только часть прав и явно предупреждает об этом; unowned производные bindings тоже исключаются. management.namespaces и safety не ограничивают аудит — используйте k8s_configuration_matrix_namespaces.

Новые каталоги на controller создаются с mode 0700, CSV — 0600; существующие права каталогов сохраняются; UTF-8 без BOM, LF, детерминированная сортировка, корректное CSV-экранирование и защита текстовых полей от формул электронных таблиц (начальный апостроф). Хеши паролей/токены в отчёты не включаются, содержимое CSV не показывается через --diff. Повторный запуск без изменений идемпотентен. `--check` читает кластер и прогнозирует создание/изменение файлов, не записывая их. CSV уже находятся на controller, fetch не требуется.

Матрица отражает выбранный RBAC и известное членство на момент последовательных чтений. Это не атомарный снимок и не проверка реального входа пользователя: действующий токен может содержать прежние claims. Webhook/Node/ABAC, обход авторизации через system:masters, admission и косвенное повышение привилегий не рассчитываются. SAR-проверки роль не выполняет.

### Фильтры матрицы

По умолчанию скрыты пользователи/группы `system:*`, все столбцы ServiceAccount и системные namespace. Системными считаются `kube-system`, `kube-public`, `kube-node-lease`; для Deckhouse также `d8-*`. Namespace `default` остаётся прикладным. Классификацию можно полностью переопределить через `k8s_configuration_matrix_system_namespaces` и `k8s_configuration_matrix_system_subjects`.

Все переменные ниже имеют префикс `k8s_configuration_matrix_`:

| Суффикс переменной | Default | Назначение |
| --- | --- | --- |
| `namespace_mode` | `application` | Выбирает namespace для матрицы: application исключает системные, system оставляет системные, all включает оба вида. |
| `system_namespaces` | см. выше | Имена и glob-маски системных namespace для namespace_mode; по умолчанию стандартные Kubernetes namespace и d8-* на Deckhouse. |
| `namespaces` | `[]` | Точные имена namespace для матрицы; пустой список не ограничивает выборку, отсутствующее имя вызывает ошибку. |
| `namespace_include` | `[]` | Имена и glob-маски включаемых namespace; пустой список не добавляет ограничений, остальные фильтры продолжают действовать. |
| `namespace_exclude` | `[]` | Имена и glob-маски namespace, исключаемых из матрицы после применения фильтров включения. |
| `include_system_subjects` | `false` | Включает системных пользователей и группы, распознанных по matrix_system_subjects, с учётом остальных фильтров. |
| `include_external_users` | `false` | Включает пользователей без локального Deckhouse User; для них учитываются только прямые назначения, без наследования от групп. |
| `system_subjects` | `['system:*']` | Имена и glob-маски системных пользователей и групп для фильтра include_system_subjects; по умолчанию system:*. |
| `users_include` | `[]` | Имена и glob-маски включаемых пользователей; для Deckhouse используется email, пустой список не ограничивает выборку. |
| `users_exclude` | `[]` | Имена и glob-маски исключаемых пользователей; для Deckhouse используется email. |
| `groups_include` | `[]` | Имена и glob-маски включаемых групп; для Deckhouse используется spec.name, пустой список не ограничивает выборку. |
| `groups_exclude` | `[]` | Имена и glob-маски исключаемых групп; для Deckhouse используется spec.name. |
| `subjects_service_accounts` | `false` | Включает столбцы ServiceAccount и чтение их списка из API с учётом остальных фильтров. |
| `service_accounts_include` | `[]` | Имена и glob-маски включаемых ServiceAccount в формате namespace/name; пустой список не ограничивает выборку. |
| `service_accounts_exclude` | `[]` | Имена и glob-маски исключаемых ServiceAccount в формате namespace/name. |
| `service_account_namespaces_include` | `[]` | Имена и glob-маски namespace самих ServiceAccount для отбора столбцов; пустой список не ограничивает выборку. |
| `service_account_namespaces_exclude` | `[]` | Имена и glob-маски namespace самих ServiceAccount, столбцы которых исключаются из матрицы. |
| `omit_empty_rows` | `true` | Убирает строки, где все видимые ячейки содержат только точки; строки с неизвестными правами (?) сохраняются. |
| `exclude_broad_subjects` | `true` | Исключает субъектов с wildcard по apiGroups и resources без resourceNames, а также известных наследников; внешние User проверяются только по прямым правам. |

По умолчанию `k8s_configuration_matrix_exclude_broad_subjects: true` исключает группы, пользователей и включённые ServiceAccount с широким доступом: в одном правиле есть `apiGroups: ["*"]`, `resources: ["*"]`, а `resourceNames` отсутствует или пуст. Набор verbs может быть любым, в том числе только get/list/watch. Назначение учитывается в выбранной области: ClusterRoleBinding либо RoleBinding хотя бы в одном выбранном namespace. Даже администратор одного выбранного namespace будет исключён целиком из отчёта.

Исключаются также известные локальные участники таких групп, ServiceAccount и вложенные группы; внешние User проверяются только по их прямым назначениям. Неизвестное внешнее членство не угадывается. Имена вроде cluster-admin сами по себе не являются критерием; правила с ограничением resourceNames, wildcard только в отдельной API-группе или перечислением конкретных ресурсов автоматически широкими не считаются. Это фильтр явных wildcard-назначений, а не доказательство отсутствия иных способов получить административный доступ.

Правила исключённых субъектов не создают строки матрицы: иначе при неполном членстве оставшихся пользователей эти строки сохранялись бы как `?`. У этих субъектов удаляются все их назначения из источников отчёта, включая узкие. Другие скрытые группы продолжают участвовать в наследовании. Сводка показывает `excluded_broad_subjects` и `excluded_broad_subject_names` (все обнаруженные широкие субъекты, включая уже скрытых другими фильтрами). Чтобы вернуть широкие субъекты и их строки, задайте `k8s_configuration_matrix_exclude_broad_subjects: false`; остальные фильтры сохраняют действие.

Локальные Deckhouse User и их группы читаются из Kubernetes при каждом запуске: email нормализуется в нижний регистр, учитываются Group (включая вложенность) и User.spec.groups. При resolve_group_membership=true локальное членство считается полным, не требуется справочник inventory. Чтение запрещённых/отсутствующих коллекций, циклы, потерянные ссылки и неоднозначные email/claims прерывают отчёт. При resolve_group_membership=false локальные User сохраняют неполное членство.

По умолчанию include_external_users=false: внешние User скрыты, их прямые User-правила не создают строки. Внешние группы остаются в матрице без попытки восстановить LDAP-участников. В vanilla все User относятся к внешним. Для явного аудита User bindings включите переменную; показываются только прямые права заглавными буквами и точками. Переключатель влияет только на matrix, не на apply/export. Счётчик excluded_external_users показывает число скрытых внешних User.

Glob чувствителен к регистру: `*`, `?`, `[abc]`; это не регулярное выражение. Пустой include не ограничивает выборку. Все ограничения пересекаются, exclude имеет приоритет над include. Явное включение имени не отменяет системный фильтр: для просмотра `kube-system` выберите `namespace_mode: system` либо `all`. Несовпадение glob с существующими именами допустимо и может дать пустой CSV с заголовком.

Фильтры столбцов не меняют расчёт членства: скрытые группы, включая `system:authenticated`, продолжают предоставлять унаследованные права локальным Deckhouse пользователям и ServiceAccount. Фильтр namespace ресурса независим от namespace ServiceAccount. `include_cluster_scoped` управляет кластерными ресурсами/URL отдельно от выбора namespace. `<unknown>` сохраняется с предупреждением, поскольку область отсутствующего в discovery ресурса неизвестна. Символические строки `*`/`<all-scopes>` при ограничении namespace разворачиваются только в выбранные namespace и, если разрешено, `<cluster>`.

Строки с `?` сохраняются даже без известных положительных прав. Если матрица остаётся большой из-за неполного членства, уточните `memberships`; `complete: true` допустим только для подтверждённого полного списка групп.

`subjects.csv` содержит только выбранные столбцы. RBAC-записи `bindings.csv` относятся только к выбранным субъектам и строкам; имена скрытых групп сохраняются в источниках наследования. Декларации AR/CAR отбираются по субъектам (включая группы, предоставляющие права видимым субъектам) и namespace, а `resolved_namespaces` ограничивается выборкой. Поля самой декларации сохраняют исходные параметры и не являются вычисленными правами.

Сводка содержит `filters`, `selected_namespaces`, `excluded_namespaces`, `excluded_subjects`, `omitted_empty_rows`. Счётчик субъектов относится к идентичностям, обнаруженным в области аудита; полного каталога внешних пользователей Kubernetes не предоставляет. Фильтры ограничивают отчёт, чтение discovery/RBAC остаётся кластерным. Предупреждение напоминает, что это отфильтрованный аудит.

Обычные пользователи и группы в системных namespace:

```yaml
k8s_configuration_matrix_namespace_mode: system
k8s_configuration_matrix_include_cluster_scoped: false
```

Только пользователи организации в namespace проектов:

```yaml
k8s_configuration_matrix_namespace_include: ['project-*']
k8s_configuration_matrix_namespace_exclude: ['project-archive']
k8s_configuration_matrix_users_include: ['*@example.org']
k8s_configuration_matrix_users_exclude: ['bot-*']
k8s_configuration_matrix_subjects_groups: false
```

Для полной выборки, включая системные записи, задайте `namespace_mode: all`, `include_system_subjects: true`, `include_external_users: true`, `subjects_service_accounts: true`, `omit_empty_rows: false`, `exclude_broad_subjects: false`, очистите `namespaces` и все include/exclude; оставьте `scope: cluster` и `include_cluster_scoped: true`.

### Плоские настройки export и matrix

| Переменная | По умолчанию | Назначение и использование |
| --- | --- | --- |
| `k8s_configuration_export_mode` | `"managed"` | Область экспорта: managed выбирает собственные назначения, scoped — назначения по спискам ролей и accessLevel. |
| `k8s_configuration_export_backends` | `["rbac", "deckhouse"]` | Список экспортируемых механизмов назначений: rbac и/или deckhouse. |
| `k8s_configuration_export_cluster_roles` | `[]` | Имена ClusterRole для отбора RBAC-назначений при export_mode: scoped; определения ролей не экспортируются. |
| `k8s_configuration_export_roles` | `[]` | Список {namespace, name} для отбора назначений на Role при export_mode: scoped; определения ролей не экспортируются. |
| `k8s_configuration_export_access_levels` | `[]` | Уровни accessLevel для отбора AR/CAR при export_mode: scoped. |
| `k8s_configuration_export_namespaces` | `[]` | Точные имена namespace для экспорта namespaced-назначений; пустой список не ограничивает namespace. |
| `k8s_configuration_export_include_cluster_scoped` | `true` | Включает в экспорт кластерные назначения без namespace; действует независимо от export_namespaces. |
| `k8s_configuration_export_exclude_controller_generated` | `true` | Исключает из экспорта объекты контроллеров; распознавание учитывает ownerReferences и настроенные маркеры. |
| `k8s_configuration_export_allow_partial` | `false` | Разрешает частичный экспорт при наличии непереносимых назначений; ограничения фиксируются в отдельном аудите. |
| `k8s_configuration_export_destination` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml"` | Путь к YAML с экспортируемыми назначениями на Ansible controller; относительный путь считается от playbook_dir. |
| `k8s_configuration_export_audit_destination` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml"` | Путь к отдельному YAML-аудиту экспорта на Ansible controller; пустая строка отключает сохранение аудита. |

| Переменная | По умолчанию | Назначение и использование |
| --- | --- | --- |
| `k8s_configuration_matrix_output_dir` | `"{{ playbook_dir }}/output/{{ inventory_hostname }}"` | Каталог для трёх CSV матрицы на Ansible controller; относительный путь считается от playbook_dir. |
| `k8s_configuration_matrix_scope` | `"cluster"` | Область назначений матрицы: cluster учитывает все bindings, managed — только bindings с метками владельца роли. |
| `k8s_configuration_matrix_namespaces` | `[]` | Точные имена namespace для матрицы; пустой список не ограничивает выборку, отсутствующее имя вызывает ошибку. |
| `k8s_configuration_matrix_include_cluster_scoped` | `true` | Включает строки кластерных ресурсов и URL; false сохраняет namespaced-права, в том числе полученные через ClusterRoleBinding. |
| `k8s_configuration_matrix_subjects_users` | `true` | Включает столбцы пользователей в матрицу с учётом остальных фильтров субъектов. |
| `k8s_configuration_matrix_subjects_groups` | `true` | Включает столбцы групп в матрицу; скрытые группы могут продолжать участвовать в наследовании прав. |
| `k8s_configuration_matrix_subjects_service_accounts` | `false` | Включает столбцы ServiceAccount и чтение их списка из API с учётом остальных фильтров. |
| `k8s_configuration_matrix_resolve_group_membership` | `true` | Включает чтение членства из Deckhouse Group для наследования прав; явный справочник matrix_memberships действует и при false. |
| `k8s_configuration_matrix_memberships` | `[]` | Справочник членства User/ServiceAccount в группах для отчёта: groups и complete обязательны; complete: true заменяет выведенный состав, false дополняет его. |
| `k8s_configuration_matrix_csv_delimiter` | `";"` | Односимвольный разделитель полей во всех трёх CSV матрицы; по умолчанию точка с запятой. |
| `k8s_configuration_matrix_source` | `cluster` | Источник назначений: cluster читает текущие bindings, inventory использует grants из inventory и актуальные роли из API. |
| `k8s_configuration_matrix_filename` | `"{{ 'matrix-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'matrix.csv' }}"` | Имя CSV с матрицей прав в matrix_output_dir; по умолчанию matrix.csv или matrix-inventory.csv в зависимости от matrix_source. |
| `k8s_configuration_matrix_bindings_filename` | `"{{ 'bindings-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'bindings.csv' }}"` | Имя CSV с источниками прав в matrix_output_dir; по умолчанию bindings.csv или bindings-inventory.csv в зависимости от matrix_source. |
| `k8s_configuration_matrix_subjects_filename` | `"{{ 'subjects-inventory.csv' if k8s_configuration_matrix_source == 'inventory' else 'subjects.csv' }}"` | Имя CSV со сведениями о субъектах в matrix_output_dir; по умолчанию subjects.csv или subjects-inventory.csv в зависимости от matrix_source. |
| `k8s_configuration_matrix_namespace_mode` | `application` | Выбирает namespace для матрицы: application исключает системные, system оставляет системные, all включает оба вида. |
| `k8s_configuration_matrix_system_namespaces` | `"{{ ['kube-system', 'kube-public', 'kube-node-lease'] + (['d8-*'] if k8s_configuration_config_platform == 'deckhouse' else []) }}"` | Имена и glob-маски системных namespace для namespace_mode; по умолчанию стандартные Kubernetes namespace и d8-* на Deckhouse. |
| `k8s_configuration_matrix_namespace_include` | `[]` | Имена и glob-маски включаемых namespace; пустой список не добавляет ограничений, остальные фильтры продолжают действовать. |
| `k8s_configuration_matrix_namespace_exclude` | `[]` | Имена и glob-маски namespace, исключаемых из матрицы после применения фильтров включения. |
| `k8s_configuration_matrix_include_system_subjects` | `false` | Включает системных пользователей и группы, распознанных по matrix_system_subjects, с учётом остальных фильтров. |
| `k8s_configuration_matrix_include_external_users` | `false` | Включает пользователей без локального Deckhouse User; для них учитываются только прямые назначения, без наследования от групп. |
| `k8s_configuration_matrix_system_subjects` | `['system:*']` | Имена и glob-маски системных пользователей и групп для фильтра include_system_subjects; по умолчанию system:*. |
| `k8s_configuration_matrix_users_include` | `[]` | Имена и glob-маски включаемых пользователей; для Deckhouse используется email, пустой список не ограничивает выборку. |
| `k8s_configuration_matrix_users_exclude` | `[]` | Имена и glob-маски исключаемых пользователей; для Deckhouse используется email. |
| `k8s_configuration_matrix_groups_include` | `[]` | Имена и glob-маски включаемых групп; для Deckhouse используется spec.name, пустой список не ограничивает выборку. |
| `k8s_configuration_matrix_groups_exclude` | `[]` | Имена и glob-маски исключаемых групп; для Deckhouse используется spec.name. |
| `k8s_configuration_matrix_service_accounts_include` | `[]` | Имена и glob-маски включаемых ServiceAccount в формате namespace/name; пустой список не ограничивает выборку. |
| `k8s_configuration_matrix_service_accounts_exclude` | `[]` | Имена и glob-маски исключаемых ServiceAccount в формате namespace/name. |
| `k8s_configuration_matrix_service_account_namespaces_include` | `[]` | Имена и glob-маски namespace самих ServiceAccount для отбора столбцов; пустой список не ограничивает выборку. |
| `k8s_configuration_matrix_service_account_namespaces_exclude` | `[]` | Имена и glob-маски namespace самих ServiceAccount, столбцы которых исключаются из матрицы. |
| `k8s_configuration_matrix_omit_empty_rows` | `true` | Убирает строки, где все видимые ячейки содержат только точки; строки с неизвестными правами (?) сохраняются. |
| `k8s_configuration_matrix_exclude_broad_subjects` | `true` | Исключает субъектов с wildcard по apiGroups и resources без resourceNames, а также известных наследников; внешние User проверяются только по прямым правам. |


Имена CSV:

- `k8s_configuration_matrix_filename`: `matrix.csv`.
- `k8s_configuration_matrix_bindings_filename`: `bindings.csv`.
- `k8s_configuration_matrix_subjects_filename`: `subjects.csv`.

Boolean-переключатели matrix принимают значения YAML и CLI key=value: например, `-e k8s_configuration_matrix_include_external_users=true`. Роль преобразует строковое значение в boolean перед проверкой схемы. Альтернативный формат extra-vars с типизированным JSON: `-e '{"k8s_configuration_matrix_include_external_users": true}'`.

Для внешних User при включённом `include_external_users` рассчитываются только прямые назначения: заглавные буквы и точки, без наследования и `?`. Точка означает отсутствие прямого назначения, а не отсутствие доступа через группы. Локальность определяется совпадением имени субъекта с нормализованным `spec.email` прочитанного Deckhouse User. В vanilla все User внешние. В `subjects.csv` поле `rights_basis` равно `direct_only` для внешних User и `direct_and_groups` для остальных субъектов. `membership_complete` по-прежнему описывает полноту сведений о группах, а не режим расчёта. Даже явно переданные memberships не включают наследование для внешнего User. В bindings.csv для такого User сохраняются только его прямые источники; широкие группы не исключают его столбец через наследование.


Проверки access_checks удалены из роли: apply и prune не выполняют SubjectAccessReview. Для просмотра фактических прав с учётом содержимого ролей используйте matrix. Дополнительные проверки bindings после apply не добавлялись.

Миграция subjects: удалите source. Для прежних static-ссылок замените name локального User на его email, а имя Group — на spec.name; прежние external/serviceaccount имена остаются прежними. Управление локальными User/Group удалено; определения учёток нужно создавать вне роли.

Экспорт inventory использует компактный YAML: каждый subject записан в фигурных скобках, roleRef и scope — в одну строку. Схема переменных сохраняется, файл непосредственно импортируется как inventory.

Переменные example_* в примере lookup принадлежат inventory, не являются параметрами роли и объявляются в самом примере. Роль получает готовые значения через k8s_configuration_certificates и connection_*_content.

Предупреждение о смешанных назначениях указывает субъекта и конкретные RBAC/Deckhouse-объекты; посторонние субъекты кластера в предупреждение не включаются.

### Матрица по назначениям inventory

```yaml
k8s_configuration_config_mode: matrix
k8s_configuration_matrix_source: inventory
```

source=cluster (по умолчанию) читает текущие bindings. source=inventory использует только k8s_configuration_grants и актуальные rules Role/ClusterRole из API: назначения, уже существующие в кластере, не читаются и не добавляются. Требуются явно заданные grants; [] означает пустой набор. Поддерживаются RoleBinding по namespaces, ClusterRoleBinding и state: absent (исключается). Несуществующие namespace/роли прерывают отчёт до записи файлов. Правила агрегированных ClusterRole берутся в текущем состоянии.

Локальные User/Group и их членство читаются из Deckhouse, определения учёток из inventory не принимаются. Сохраняются обычные фильтры, маски, прямые права внешних User и наследование локальных пользователей. Для столбцов внешних User включите k8s_configuration_matrix_include_external_users. Источник виден в summary.source, subjects.csv (inventory-binding) и bindings.csv (record_type=inventory-rbac).

Файлы по умолчанию: matrix-inventory.csv, bindings-inventory.csv, subjects-inventory.csv на контроллере, отдельно от текущей матрицы. Их имена по-прежнему переопределяются через matrix_filename/matrix_bindings_filename/matrix_subjects_filename.

Это права только от описанных назначений, а не полный эффективный доступ после apply: прочие bindings исключены, prune/adoption/ограничения удаления и допустимость применения не проверяются. Для проверки плана применения используйте dry. Будущее изменение агрегированных ролей/токенов не прогнозируется. GET-only; --check не пишет CSV.

На первом этапе source=inventory поддерживает только backend: rbac, в том числе на Deckhouse. Для backend: deckhouse (AR/CAR) роль завершает работу с ошибкой: accessLevel не является прямой ссылкой на роль, права производных bindings зависят от контроллера. Для таких назначений используйте source=cluster после apply; виртуальные разрешения AR/CAR не подставляются.
