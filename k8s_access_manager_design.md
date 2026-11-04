# Ansible-роль k8s-configuration: возможности и проект реализации

> Актуальное ограничение: роль управляет только назначениями доступа. Описанные ниже создание, изменение и удаление User/Group, пароли, состав групп, параметры users/groups, password_updates и prune_identities удалены. Чтение User/Group сохранено только для матрицы. Актуальный интерфейс — roles/k8s-configuration/README.md.

Статус: проект реализован в `roles/k8s-configuration/`; актуальный пользовательский контракт описан в README роли. Основание: `project.md`. Дата проверки документации: 23 октября 2026 года.

## 1. Назначение и границы

Роль декларативно управляет назначениями прав через Kubernetes REST API в vanilla Kubernetes и Deckhouse. Для Deckhouse дополнительно управляет локальными идентичностями User/Group. Один inventory может содержать назначения стандартного RBAC и базовой модели Deckhouse; backend выбирается отдельно для каждого назначения.

Результат работы — проверяемый план, применение изменений или экспорт существующих настроек. Роль использует установленный kubectl; kubernetes.core, Kubernetes SDK и установка агентов на узлах кластера не требуются.

В vanilla Kubernetes обычные пользователи и группы не являются API-объектами: роль только ссылается на идентичности, которые предоставляет настроенная аутентификация. Запись группы в inventory не создаёт членство в OIDC/LDAP и не добавляет группу в сертификат. Это принципиальное ограничение обещания «управлять пользователями» в исходном документе. [Kubernetes: authentication](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)

| Возможность первой версии | Vanilla | Deckhouse |
| --- | --- | --- |
| RoleBinding / ClusterRoleBinding к существующим ролям | Да | Да |
| Ссылки на внешних User/Group | Да | Да |
| Создание локальных User/Group и изменение членства | Нет | Через user-authn |
| AuthorizationRule / ClusterAuthorizationRule | Нет | Через user-authz, базовая модель |
| Назначение существующих гранулярных ролей Deckhouse | Нет | Через backend `rbac` |
| Dry, apply, export, контроль владения и удаления | Да | Да |
| Matrix: CSV текущего RBAC, источники и известное членство | Да | Да, включая декларации AR/CAR |
| Динамический namespace selector | Нет в первой версии | Для ClusterAuthorizationRule при подтверждённой поддержке |

В первую версию не входят: управление AD/LDAP/OIDC-провайдерами, выпуск сертификатов пользователей, настройка API server, установка модулей Deckhouse, создание Namespace, Role/ClusterRole, ServiceAccount и токенов, ProjectRoleBinding, управление 2FA/сессиями. Существующий ServiceAccount можно использовать как субъект назначения. Изменение прав в приложениях, например Grafana, также находится вне области роли.

## 2. Исправления исходной проработки

| Положение project.md | Решение в проекте |
| --- | --- |
| «Ansible 2.12–3.12» | Не использовать как диапазон совместимости: различать пакет Ansible, ansible-core и Python; см. раздел 3 |
| Общие users/groups для двух платформ | Явно разделить внешние ссылки и локальные Deckhouse-идентичности |
| `users[].groups` и самостоятельные groups | Единственный источник членства — `groups[].members`; исключить противоречия двух списков |
| Для Deckhouse достаточно обнаружить CRD | Проверять API, схему, состояние модулей и необходимые настройки; CRD может оставаться после отключения модуля |
| Единственный переключатель basic/granular | Не запрещать их сосуществование; отдельно проверять доступность basic backend |
| Все изменения выполняются PATCH | Смена неизменяемого `roleRef` — операция replace |
| `prune: true` в примере по умолчанию | По умолчанию false, отдельно разрешать удаление идентичностей |
| Любой кластерный scope может исключать системные namespace | В RBAC это не реализуется ClusterRoleBinding; в Deckhouse нужны проверенные ограничения |
| Export готов к обратному импорту | Гарантировать это только для поддерживаемого подмножества; неподдерживаемое экспортировать как аудит |
| Права двух backend всегда складываются | Для vanilla RBAC — да; в Deckhouse учитывать версию и webhook |

`roleRef` у binding неизменяем; RoleBinding может ссылаться на Role своего namespace или ClusterRole, ClusterRoleBinding — только на ClusterRole. RBAC разрешения аддитивны, запретов в правилах нет. [Kubernetes: RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

В changelog Deckhouse описано изменение совместной работы CAR и независимого RBAC: ранее webhook мог запрещать доступ вне CAR даже при наличии binding. Поэтому упоминание «1.76.5» из исходника не принимается как достаточная граница совместимости: нужен проверенный профиль конкретного выпуска и интеграционный тест смешанных назначений. [Deckhouse: changelog 1.76](https://github.com/deckhouse/deckhouse/blob/main/CHANGELOG/CHANGELOG-v1.76.md)

## 3. Среда исполнения

Предлагаются два явно разделённых профиля:

| Профиль | Control node | Узел исполнения модуля |
| --- | --- | --- |
| Legacy для исходных ограничений | ansible-core 2.12, Python 3.8 | Тот же узел либо RED OS 7.3 с Python 3.8 |
| Предпочтительный при сохранении Python 3.8 на RED OS | ansible-core 2.19, Python 3.11–3.13 | RED OS 7.3, Python 3.8, отдельный execution host |

Это целевые профили тестирования, а не заявление о уже проверенной совместимости. При `connection: local` Python control node и интерпретатор модуля должны удовлетворять выбранному профилю; современный ansible-core нельзя просто запускать под Python 3.8. В матрице Ansible версия 2.19 поддерживает Python 3.8 на target, а 2.20 требует там минимум 3.9. Ветка 2.12 уже EOL. [Матрица Ansible](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html)

Для кода модуля сохраняется синтаксис Python 3.8. Перед реализацией фиксируются patch-версии ansible-core, Python и kubectl для каждого профиля. PyYAML нужен тестовой оснастке, но не runtime роли. RED OS проверяется фактическим запуском, а не предположением о совместимости с RHEL. Системные пакеты и Python роль автоматически не обновляет.

Один запуск обслуживает один кластер и одного владельца конфигурации. После совместного применения hosts и --limit требуется ровно один execution host с доступом к API; localhost означает controller. Группы, all, списки и шаблоны допустимы, если итоговый набор содержит один узел. Несколько узлов блокируются до запуска kubectl; serial не обходит проверку ansible_play_hosts_all. Kubeconfig и auth plugins относятся к выбранному узлу; файлы dry/export/matrix — к Ansible controller; запуск роли на каждом control-plane узле не нужен. Параллельные apply для одного owner/cluster запрещаются сериализацией CI.

## 4. Контракт inventory

Публичные переменные имеют префикс `k8s_configuration_`. Настройки являются плоскими переменными: k8s_configuration_config_schema_version, k8s_configuration_config_mode, k8s_configuration_config_connection_kubeconfig, k8s_configuration_export_destination и k8s_configuration_matrix_output_dir. Users/groups/grants остаются предметными списками объектов. Плоские аргументы передаются непосредственно модулю; внутренние настройки движка собираются в Python.

Пример желаемой конфигурации Deckhouse:

```yaml
k8s_configuration_config_schema_version: 1
k8s_configuration_config_mode: dry
k8s_configuration_config_platform: deckhouse
k8s_configuration_config_connection_kubeconfig: /etc/ansible/kubeconfigs/dkp-prod.yaml
k8s_configuration_config_connection_context: dkp-prod
k8s_configuration_config_connection_validate_tls: true
k8s_configuration_config_connection_timeout_seconds: 30
k8s_configuration_config_deckhouse_basic_authz: true
k8s_configuration_config_management_owner: platform-team
k8s_configuration_config_management_prune: false
k8s_configuration_config_management_prune_identities: false
k8s_configuration_config_management_adoption: []
k8s_configuration_config_safety_max_deletions: 10
k8s_configuration_config_safety_allow_empty_desired: false
k8s_configuration_config_safety_allow_binding_replacement: false
k8s_configuration_config_safety_protected_namespaces:
- kube-system
- kube-public
- kube-node-lease
- default
- loghouse
k8s_configuration_config_safety_protected_namespace_prefixes:
- kube-
- d8-
k8s_configuration_config_safety_allowed_protected_namespaces: []
k8s_configuration_users:
- name: ivanov
  source: static
  email: ivanov@example.org
  password_hash: '{{ vault_ivanov_bcrypt }}'
  password_policy: on_create
k8s_configuration_groups:
- name: developers
  source: static
  claim_name: developers
  members:
  - ivanov
k8s_configuration_grants:
- id: developers-edit
  backend: rbac
  subjects:
  - kind: Group
    name: developers
  roleRef:
    kind: ClusterRole
    name: edit
  scope:
    namespaces:
    - application-dev
    - application-test
- id: payments-admin
  backend: deckhouse
  subjects:
  - kind: Group
    name: K8S-Payments-Admins
  accessLevel: Admin
  scope:
    namespaces:
    - payments-prod
  options:
    portForwarding: true
    allowScale: false
- id: review-reader
  backend: deckhouse
  subjects:
  - kind: User
    name: ivanov@example.org
  accessLevel: User
  scope:
    namespace_selector:
      matchLabels:
        environment: review
  options:
    portForwarding: false
    allowScale: false
```

Именованные публичные compatibility profiles заменены плоскими настройками возможностей Deckhouse. Served API обнаруживаются автоматически либо закрепляются отдельными API pins. Проверяются scope и Established CRD со схемой нужной версии. Проверки образа и Deployment Deckhouse не выполняются. Готовность берётся из Module (phase Ready, EnabledByModuleManager=True, IsReady=True), а ModuleConfig читается при наличии. Отсутствие ModuleConfig не блокирует обычные назначения; CAR multitenancy требует явно подтверждённого enableMultiTenancy=true. Предпосылки перепроверяются перед apply.

Для vanilla используются `platform: vanilla`, пустые users/groups и grants с `backend: rbac`. Для внешних субъектов `name` содержит точную строку после преобразований аутентификатора, включая настроенные префиксы. Роль не проверяет наличие пользователя в каталоге. Пустой каталог пользователей не означает отсутствие допустимых внешних субъектов.

### Правила схемы

- `id` уникален; поля неизвестного назначения отвергаются, а не игнорируются.
- `subjects` — непустой список. Поддерживаются User, Group, ServiceAccount; для последнего обязателен namespace.
- Имена subjects передаются буквально: локальный User указывается по email, Group — по claim_name/spec.name. Поле source в subjects не используется.
- Email локального пользователя задаётся в lowercase. Внешние имена не нормализуются произвольно. Проверяются коллизии фактических имён между локальными и внешними субъектами.
- `scope` содержит ровно один вариант: `cluster: true`, непустой список `namespaces` либо непустой `namespace_selector`. Пустой selector запрещён как неявный доступ ко всем namespace.
- `roleRef` разрешён только для rbac, `accessLevel/options` — только для deckhouse. Для Role проверяется существование в каждом namespace назначения.
- Namespace должны существовать. Роль не создаёт их и не изменяет метки.
- `state` по умолчанию present; `state: absent` задаёт явное удаление конкретного объекта в области владения. Для absent-grant сохраняются backend и scope для однозначного вычисления имён.
- Пропущенный раздел grants/users/groups означает «не управлять этим разделом»; явно заданный пустой список означает пустое desired state. При prune пустой desired требует `allow_empty_desired: true`.
- Управление членством группы авторитетное: список members полностью заменяет управляемое членство. Вложенные локальные группы в первой версии не поддерживаются.

## 5. Преобразование в Kubernetes-ресурсы

| Backend и scope | Объект и поля |
| --- | --- |
| rbac + cluster | Один ClusterRoleBinding, `roleRef` и `subjects` |
| rbac + namespaces | По RoleBinding на namespace |
| deckhouse + namespaces | По AuthorizationRule на namespace; `spec.subjects`, `spec.accessLevel`, `spec.portForwarding`, `spec.allowScale` |
| deckhouse + cluster | Один ClusterAuthorizationRule |
| deckhouse + namespace_selector | Один ClusterAuthorizationRule, selector в `spec.namespaceSelector.labelSelector` |
| static User | User: `spec.email`, `spec.password` при создании/явном управлении паролем |
| static Group | Group: `spec.name`, `spec.members` со ссылками на metadata.name пользователей |

Для basic backend AR допускает User, PrivilegedUser, Editor, Admin; CAR дополнительно ClusterEditor, ClusterAdmin, SuperAdmin. Selector может включать системные namespace; `matchAny` включает все. Namespace selector имеет приоритет над устаревшими limitNamespaces/allowAccessToSystemNamespaces. Проверять допустимость полей по установленной схеме. [Deckhouse: CR user-authz](https://deckhouse.io/modules/user-authz/cr.html)

API-версии AR v1alpha1 и CAR v1 — кандидаты профиля, а не универсальные константы. Для User документация описывает v1 и v1alpha1, для Group — v1alpha1. `User.spec.groups` устарел; членство следует задавать через Group. [Deckhouse: CR user-authn](https://deckhouse.io/modules/user-authn/cr.html)

Имена grants генерируются детерминированно из owner, grant id, kind и namespace: читаемый префикс плюс короткий SHA-256 с проверкой коллизий. Длина ограничивается требованиями ресурса; изменение списка namespace не переименовывает сохранившиеся объекты. User/Group используют явные имена inventory. Сортировка subjects/members и namespace делает diff стабильным.

### Системные namespace и динамические ограничения

Предлагаемый контракт для CAR с `scope.cluster`: обязательное поле `include_system_namespaces`. Значение false разрешается только в профиле, где подтверждено исключение системных namespace; true переводится в проверенную для профиля конфигурацию доступа ко всем namespace. При невозможности представить требование — ошибка. Для rbac это поле запрещено: ClusterRoleBinding не умеет исключать namespace.

Для namespace_selector роль не добавляет молча дополнительные условия. Если выбранные сейчас namespace пересекаются с защищёнными, требуется явное исключение в allowed_protected_namespaces. Проверка текущего набора не гарантирует безопасность будущих изменений labels: динамический selector должен отмечаться в плане как потенциальное расширение области доступа. Строгая изоляция требует явного списка namespace и отдельного контроля их меток.

В Deckhouse namespace-ограничения CAR требуют работающего multi-tenancy. Наличие CRD недостаточно; если режим выключен или его нельзя проверить, ограниченный CAR запрещается. Нельзя обещать изоляцию кластерных административных полномочий одним selector. [Deckhouse: FAQ](https://deckhouse.io/modules/user-authz/latest/faq.html)

Гранулярные роли назначаются обычными bindings через rbac. Список их имён и допустимый scope берётся из проверенного профиля: существование ClusterRole само по себе не означает допустимость ClusterRoleBinding для неё. Роль не переводит уровни Editor/Admin в гранулярные роли автоматически. [Deckhouse: использование user-authz](https://deckhouse.io/modules/user-authz/usage.html)

## 6. Dry, apply, export и matrix

### Plan

По умолчанию выполняются только чтение API и локальные вычисления. `apply` с Ansible `--check` выполняет тот же plan, без операций записи. Ansible `--diff` получает только очищенные различия.

План включает cluster identity, owner, версию схемы/профиля, create/update/delete/replace/noop, причины конфликтов и блокировок, прежний и новый scope, количество физических объектов. Удаления внутри replace входят в общий лимит. Производные объекты Deckhouse в список изменений не включаются.

Dry показывает операции с назначениями и изменение полей. Классификация privilege_change не используется: создание или удаление binding само по себе не доказывает изменение фактических прав.

Опциональный `server_validation` использует запросы с `dryRun=All`, когда поддерживаются API/admission. Он используется только перед настоящим apply; в dry/check даже эти POST/PATCH не выполняются. Проверка ресурса в ещё не существующей цепочке зависимостей может быть неполной. Серверная dry-run проверяет API/admission, но не будущую работу контроллера. [Kubernetes: API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)

### Apply

1. Проверить схему inventory, соединение, совместимость, конфликты владения и весь план до первой записи.
2. Зафиксировать наблюдаемые UID/resourceVersion и отпечаток конфигурации кластера. Перепроверить предпосылки непосредственно перед изменением.
3. Создать/обновить User, затем Group, затем первичные назначения. Обработку паролей выполнять отдельно от публичного отчёта.
4. Выполнить разрешённые замены. Смена roleRef по умолчанию блокируется; при `allow_binding_replacement: true` использовать delete → дождаться удаления → create, отражая возможный перерыв доступа.
5. После успешного создания/обновления выполнить stale-prune назначений, затем изменения/удаления зависимых групп и пользователей. При state: absent identity сначала удалить её управляемые назначения и ссылки членства.
6. Дождаться наблюдаемого результата с timeout. Для Deckhouse применять доступные в профиле readiness/status-проверки; при их отсутствии проверять доступ отдельно и не подменять это наличием CR.
7. Вернуть выполненные и невыполненные операции, changed и ошибки. При частичном сбое остановиться, не выполнять дальнейший prune. Повторный запуск должен сходиться к desired state.

Операции нескольких ресурсов не транзакционны. Автоматического «отката всего» нет: он может восстановить отозванные права. Миграция backend по умолчанию создаёт новое назначение перед удалением старого и отмечает временное перекрытие. Для сценария, где перекрытие запрещено, применять явную двухэтапную миграцию с отзывом доступа сначала.

Обычный apply пересчитывает план. Для CI можно передать expected_plan_digest: он включает несекретное desired state, идентификатор кластера и наблюдаемые версии затрагиваемых объектов; любое расхождение требует нового плана. Значения секретов и их обычные хеши в публичный digest/отчёт не включаются; артефакт секретных входов CI фиксируется отдельно.

### Export

Режимы config.mode: `dry` (самостоятельный план), `apply`, `export`, `matrix`; `plan` остаётся совместимым синонимом dry. Dry читает кластер и выводит «Планируем добавить», «Планируем изменить», «Планируем удалить». Он не зависит от Ansible CLI-флагов. Apply --check прогнозирует изменения; --diff показывает очищенный before/after. Export --check читает фактическое состояние и проверяет запись файла, сохраняя режим export.

```yaml
k8s_configuration_export_mode: scoped
k8s_configuration_export_backends:
- rbac
- deckhouse
k8s_configuration_export_cluster_roles:
- view
- edit
- platform-reader
k8s_configuration_export_roles:
- namespace: application-dev
  name: application-developer
k8s_configuration_export_access_levels:
- User
- Editor
k8s_configuration_export_namespaces:
- application-dev
- application-test
k8s_configuration_export_include_cluster_scoped: false
k8s_configuration_export_exclude_controller_generated: true
k8s_configuration_export_allow_partial: false
k8s_configuration_export_destination: ./exports/dkp-prod.yaml
k8s_configuration_export_audit_destination: ./exports/dkp-prod-audit.yaml
```

Managed выбирает ресурсы данного owner, включая ручные изменения. Scoped выбирает и ручные объекты по явным фильтрам. Фильтры действуют совместно; CAR экспортируется целиком с selector, namespace-фильтр не обрезает его смысл.

В destination сохранять непосредственно `k8s_configuration_users`, `k8s_configuration_groups`, `k8s_configuration_grants`, без обёртки inventory. Файл подключается через vars_files/group_vars или вставляется в vars inventory без правок. Плоские настройки соединения и возможностей Deckhouse задают отдельно для целевого кластера. Audit с UID/ownership/unsupported_fields хранится отдельно и не импортируется.

Export содержит только k8s_configuration_grants с назначениями прав. User/Group, состав групп, пароли и их хеши не экспортируются, в том числе как зависимости. Имена в subjects сохраняются буквально. Файл имеет права 0600; для импорта используются существующие namespace и Role/ClusterRole.

Неподдерживаемые поля/зависимости блокируют экспорт по умолчанию; allow_partial явно разрешает неполный снимок для аудита. Сохранять target_name для исходных имён. На исходном кластере unowned объекты требуют отдельного UID-bound adoption; export не захватывает владение. На целевом должны существовать Namespace и роли/ServiceAccount, на которые ссылаются grants; их определения эта роль не переносит.

### Файлы dry/export/matrix

Результаты этих режимов сохраняются на Ansible controller через delegate_to: localhost, local connection и become=false, с Python контроллера. Настройка localhost в inventory не требуется. kubectl продолжает работать на выбранном target host.

Плоские переменные: k8s_configuration_report_path — полный путь плана dry; k8s_configuration_export_destination и k8s_configuration_export_audit_destination — inventory и аудит; k8s_configuration_matrix_output_dir — каталог CSV, а matrix_filename, matrix_bindings_filename, matrix_subjects_filename с префиксом k8s_configuration_ задают имена. По умолчанию все результаты находятся в playbook_dir/output/inventory_hostname: dry.yml, export.yml, export-audit.yml, matrix.csv, bindings.csv, subjects.csv. Относительные пути считаются от playbook_dir на controller. Нужные каталоги создаются, новые получают 0700; файлы 0600. --check не записывает файлы, --diff не показывает их содержимое. changed может означать локальную запись результатов без изменений API. Дополнительная проверка наличия старых словарей удалена.

### Matrix — первый этап аудита

Реализован самостоятельный config.mode: matrix; он читает кластер через установленный kubectl и сохраняет matrix.csv, bindings.csv, subjects.csv. Desired state/пароли не шаблонизируются. Публичные переменные k8s_configuration_matrix_* задают output_dir, scope (cluster по умолчанию либо managed), namespaces, include_cluster_scoped, subjects, resolve_group_membership, memberships и csv.delimiter. Полный контракт и пример: [README роли](roles/k8s-configuration/README.md).

Строка: namespace/API group/resource/resourceNames либо nonResourceURL; столбец: User/Group/ServiceAccount. Маска GLWCUPDX соответствует get/list/watch/create/update/patch/delete/deletecollection; заглавная буква — прямой binding, строчная — известная группа, точка — отсутствие разрешения в выбранном RBAC при известном членстве, ? — неизвестная позиция из-за неполного членства. Прямое назначение выигрывает регистр, все цепочки сохраняются. Специальные verbs имеют отдельные строки Y/y/./?; wildcard сохраняется символически и раскрывается по discovery. Агрегация использует существующие rules, широкий grant проецируется на строки именованных объектов. RoleBinding не даёт cluster-scoped права.

По умолчанию читается весь RBAC, включая ручные и производные назначения. Managed фильтрует ownership bindings и предупреждает о неполноте. Все необходимые коллекции/discovery должны быть прочитаны: ошибки останавливают отчёт до файлов. В Deckhouse используются обнаруженные served API без требования readiness/image pin: User/email, Group/claim и известное вложенное членство, AR/CAR как декларации и selector scopes. Декларации не создают виртуальных разрешений. Связи с производным RBAC подтверждаются только owner UID; при отсутствии связи reconciliation=unverified. Никакое имя binding само по себе не доказывает происхождение/сходимость.

CSV UTF-8/LF, каталог 0700, файлы 0600, без хешей/токенов и без содержимого в --diff; --check не пишет файлы. Matrix выполняет только GET: SAR и операции записи в Kubernetes отсутствуют. Это не полный расчёт webhook/Node/ABAC, bypass system:masters, admission, действующих токенов и косвенного повышения прав.

## 7. Владение, удаление и защита от конфликтов

Объект идентифицируется по API group/resource, namespace, name; наблюдаемая incarnation — по UID. Предлагаемые метки: `access-manager.example.org/owner`, `access-manager.example.org/managed-by`; аннотации содержат grant id и schema version. Домен является примером, перед реализацией заменяется организационным и фиксируется. Метки не являются защитой от администратора кластера.

Правила обязательны независимо от режима:

- Объект с другим owner, без ownership или с признаками управления контроллером не изменяется.
- Признаки производного ресурса: ownerReferences, известные метки/аннотации Deckhouse и сведения проверенного профиля. Одного отсутствия ownerReferences недостаточно для adoption.
- Adoption допускается только по точному списку group/resource/namespace/name/uid, после проверки diff. Глобальное adopt_existing: true не поддерживается.
- Prune рассматривает только собственные первичные ресурсы в явно управляемых разделах и namespace. Ограниченный запуск не удаляет объекты за пределами области запуска.
- Ошибка discovery, 403, неполная пагинация, недоступный backend или ошибка любого обязательного чтения блокирует apply/prune. Это не «пустой список существующих объектов».
- Explicit absent и prune подчиняются одним ограничениям владения, лимитов и защищённых объектов. Удаление User/Group дополнительно требует prune_identities: true, включая explicit absent.
- Удаление identity блокируется, если остаются ссылки в доступных для проверки чужих назначениях или группах. При недостаточных правах проверки — ошибка. Даже полная проверка API не доказывает отсутствие внешних IdP-ссылок.
- DELETE содержит UID/resourceVersion preconditions; объект с изменившейся версией требует нового плана. При timeout проверить результат GET перед повтором. Finalizers не удалять принудительно.
- Поддерживать список защищённых объектов, включая binding исполнителя и аварийный доступ; полномочия исполнителя не включать в desired inventory этой же роли.

Коллизии локальных и внешних имён важны даже при разных source: Kubernetes видит конечную строку identity. Аннотация `user-authz.deckhouse.io/allow-authorization-rule-collision` разрешается только явно для конкретной локальной identity. Порядок User → Group → grants уменьшает конфликты первого запуска, но не заменяет проверку существующих правил. [Deckhouse: локальная аутентификация](https://deckhouse.io/modules/user-authn/usage.html)

Удаление User/Group или изменение членства не гарантирует немедленную инвалидизацию уже выданного токена. Срочный отзыв доступа требует удаления соответствующих назначений и учёта остальных источников прав; роль не обещает отзывать сессии IdP.

## 8. Устройство реализации

Предлагается один собственный Ansible-модуль и небольшое ядро без зависимостей от Kubernetes SDK. Не разбивать код на десятки файлов до появления реальной необходимости.

```text
roles/k8s-configuration/
  defaults/main.yml
  meta/main.yml
  handlers/main.yml
  tasks/
    main.yml
    pre-req.yml
    install.yml
    user.yml
    ssl.yml
    config.yml
    clean.yml
  library/k8s_configuration.py
  module_utils/access_manager/
    client.py
    schema.py
    render.py
    reconcile.py
    export.py
  templates/
  molecule/default/{molecule.yml,converge.yml,verify.yml}
  tests/unit/
  tests/integration/
  README.md
  README-en.md
  CHANGELOG.md
  CHANGELOG-en.md
```

Структура следует локальному шаблону роли; перечисленные пути сейчас не создаются. Имена задач начинаются с имени файла, переменные используют префикс роли. Системный пользователь, systemd и logrotate для API-клиента не нужны. Служебные файлы шаблона не должны устанавливать сервисы ради структуры.

`pre-req` выполняет проверки; `install` — проверку заранее подготовленных зависимостей и необходимых каталогов; `user` не создаёт Linux-пользователей; `ssl` готовит явно переданные локальные TLS-файлы, если это требуется; `config` вызывает модуль. `clean` с тегами never/clean удаляет только созданные ролью локальные артефакты и завершает play согласно шаблону. Удаление кластерных прав выполняется через обычный план absent/prune, а не отдельный обход проверок в clean. В plan/check подготовка каталогов и сертификатов не должна выполнять записи.

| Компонент | Ответственность |
| --- | --- |
| library | argument_spec, check mode, no_log-параметры, единый формат результата |
| client | kubeconfig, TLS/HTTP, discovery, пагинация, ошибки и ограниченные retry |
| schema | валидация inventory, нормализация identity, проверка возможностей |
| render | RBAC, Deckhouse authz и identity; чистые функции без HTTP |
| reconcile | ownership, diff, план, зависимости, preconditions, apply |
| export | фильтры, обратное преобразование, приватный inventory и отдельный audit |

### API-клиент

Базовый транспорт — установленный kubectl. Python сохраняет валидацию, desired state, планирование, экспорт и ограничения удаления. Собственного HTTP/TLS-клиента нет. Вызовы выполняются argv без shell, тела запросов и JSON Patch передаются через stdin. GET/POST/DELETE выполняются через kubectl --raw, PATCH — kubectl patch --type=json с минимальным versioned manifest. JSON Patch test UID/resourceVersion и DeleteOptions.preconditions сохраняются.

Kubeconfig и аутентификацию, включая exec credential plugins, обрабатывает kubectl. Путь задаётся через connection.kubeconfig, бинарник — connection.kubectl (default kubectl). Явный context либо однократно прочитанный current-context передаётся каждой команде без изменения kubeconfig. Auth plugins должны быть установлены на execution host и работать без интерактивного ввода. Допустим HTTPS, проверка TLS включена по умолчанию. timeout_seconds ограничивает запрос и процесс. Секреты не попадают в argv; необработанные stdout/stderr не возвращаются. TLS-файлы, временные манифесты и discovery cache — в каталоге 0700, файлы 0600, удаление в finally. Версия kubectl должна быть в пределах одной minor-версии от API server.

Discovery определяет plural, scope и served versions. По умолчанию выбирается обслуживаемая версия с нужным видом ресурса; API pin позволяет явно закрепить её. Схема соответствующей версии CRD и состояние Established обязательны; отсутствие схемы блокирует запуск. Состояние Module проверяется отдельно: discovery не подтверждает готовность контроллера. ModuleConfig читается при наличии, а 403 не трактуется как отсутствие настроек.

```text
GET    /version
GET    /api, /apis, /apis/{group}/{version}
GET    /apis/rbac.authorization.k8s.io/v1/rolebindings
GET    /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings
POST   /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings
PATCH  /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings/{name}
DELETE /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings/{name}
```

Первый путь rolebindings — чтение по всем namespace; создавать namespaced объект через него нельзя. Для Deckhouse пути строятся из discovery аналогично.

Для обновлений предлагается JSON Patch с test resourceVersion/UID и точечными изменениями управляемых полей. Subject/member списки принадлежат роли целиком. Чужие labels/annotations и поля spec сохраняются, но неизвестные поля, влияющие на права, блокируют adoption. Удаление ранее управляемого optional-поля должно быть явным действием diff. ResourceVersion не участвует в семантическом сравнении, но участвует в защите записи.

GET-списки обходятся до конца через limit/continue. Retry с backoff разрешён для временных сетевых ошибок, 429 и выбранных 5xx; 401/403/422 завершают операцию. При неопределённом результате POST сначала GET детерминированного имени и проверка ownership/desired, при PATCH/DELETE — проверка состояния. Конфликт конкурентной записи останавливает применение устаревшего плана, а не вызывает force-update.

### Полномочия исполнителя

Нужны discovery и get/list управляемых ресурсов, Namespace, referenced Role/ClusterRole; для apply — create/patch/delete только выбранных видов. В Deckhouse дополнительно read Module/CRD и чтение ModuleConfig при наличии; дополнительные Deployment-пробы — по явным настройкам. Право создавать binding само по себе недостаточно: Kubernetes проверяет права назначающего либо специальное bind. Не выдавать cluster-admin автоматически. [Kubernetes: ограничения назначения прав](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

### Секреты и отчёты

Пароли передаются уже подготовленным bcrypt-хешем; контракт password_hash принимает raw bcrypt, адаптер кодирует его в формат выбранного API. Соль/хеш не генерируются заново на каждом apply. `on_create` оставляет пароль существующего User без изменений; `managed` требует явно управляемого значения и проверки поведения целевой версии при смене пароля. UserOperation/принудительный reset в первую версию не входят.

Секреты разрешаются в переменных из Ansible Vault, внешнего secret store/HashiCorp Vault либо локальных файлов; lookup не встраивается в tasks или Python-клиент. HashiCorp lookup — необязательная зависимость окружения control node. TLS также принимает локальные пути или заранее разрешённое содержимое. Смена источника не меняет алгоритм роли.

Не выводить password/hash, Authorization headers, client keys, полный kubeconfig, секретные тела API и traceback с ними. Чувствительные аргументы модуля помечаются no_log, diff очищается до возврата Ansible. Отдельный публичный отчёт содержит только безопасные поля. Экспорт и отчёты по умолчанию 0600; записи файлов атомарные. Ошибки не подавлять пустым except/pass.

## 9. Проверка и критерии приёмки будущей роли

Документ не является результатом тестирования реализации. При разработке требуются следующие проверки:

| Уровень | Обязательные сценарии |
| --- | --- |
| Unit | схема, неизвестные поля, разрешение static/external, имена, selectors, canonical diff, secret redaction |
| API-клиент | TLS CA/hostname, tokenFile, относительные пути, пагинация, timeout после успешной записи, 403/409/422/429, concurrent update |
| Ownership | чужой объект, controller-owned без ownerReferences, adoption с неверным UID, пустое desired, выход за scope, лимит удалений |
| Vanilla integration | создание/изменение/отзыв bindings, roleRef replace, Role scope, повторный apply без изменений |
| Deckhouse integration | User/Group, AR/CAR, версии API, disabled module с сохранившимся CRD, multi-tenancy, смешанный RBAC/CAR, коллизии |
| Export | несколько subjects, selector без разворачивания, unsupported_fields, отсутствующие пароли, import/adoption без дублирования |
| Отказоустойчивость | обрыв API, частичный apply, перезапуск, недоступный контроллер; prune не продолжается после ошибки |
| Доступ | положительные и отрицательные запросы для конкретных identities, в разрешённых и запрещённых namespace |

Molecule использует Docker driver для execution environment, включая доступный RED OS 7.3-совместимый образ. Vanilla API поднимается отдельной тестовой оснасткой kind/k3s; runtime роли и тестовая оснастка используют kubectl совместимой версии. Deckhouse проверяется на настоящем выделенном стенде: установка одних CRD не тестирует контроллер/webhook. Для проверки деградации API нужен многоузловой стенд, но роль сама кластер не разворачивает. Systemd/privileged-контейнер не требуется, если в сценарии нет соответствующей зависимости.

Критерии готовности:

1. Во всех режимах кластера обращения проходят только через API, без kubernetes.core.
2. Dry/check/export не изменяют кластер; dry не выполняет mutating HTTP-запросы. Export по умолчанию включает собственные cluster-scoped назначения.
3. Повторный apply возвращает changed: false при неизменном desired state и отсутствии drift.
4. Чужие/производные ресурсы сохраняются; гонка UID/resourceVersion не приводит к перезаписи.
5. Реальный доступ соответствует ожиданиям, включая отрицательные тесты и задержки reconciliation.
6. Секреты отсутствуют в публичном выводе, diff и плане. Экспорт локального Deckhouse User содержит bcrypt только в приватном импортируемом файле, без вывода в audit/консоль.
7. Проходят unit/integration, `ansible-playbook --syntax-check`, `ansible-lint`, `molecule test` для утверждённых профилей.
8. README/CHANGELOG подготовлены на русском и английском, документированы все параметры, теги, inventory и сценарии тестирования.

## 10. Порядок реализации и оставшиеся вводные

Порядок: зафиксировать схему и fixtures → реализовать read-only client/discovery → renderer/plan и ownership → RBAC apply → Deckhouse identity/basic authz → export/adoption → интеграционные проверки и документация. Первый работающий срез — vanilla RBAC dry/apply без prune; удаление включать после тестов ограничений владения.

До объявления production-поддержки необходимо получить три набора вводных:

- Точные версии Kubernetes/Deckhouse, редакции, состояние user-authn/user-authz и multi-tenancy; по ним фиксируется профиль, включая coexistence-тест.
- Где обязателен Python 3.8: control node или только RED OS execution host; какой из профилей Ansible должен поддерживаться.
- Фактические username/group claims и префиксы, способ API-аутентификации исполнителя, границы owner и перечень защищённых назначений.

До получения этих данных архитектуру и unit-тесты можно разрабатывать, но нельзя заявлять подтверждённую совместимость с конкретным кластером. Проверенные веб-страницы Deckhouse помечены как документация невыпущенной версии; приведённые сведения требуют сопоставления с документацией установленного релиза и его API. Исходный `project.md` сохранён без изменений.

## Фильтры matrix (этап 1)

По умолчанию скрыты пользователи/группы `system:*`, все столбцы ServiceAccount и системные namespace. Системными считаются `kube-system`, `kube-public`, `kube-node-lease`; для Deckhouse также `d8-*`. Namespace `default` остаётся прикладным. Классификацию можно полностью переопределить через `k8s_configuration_matrix_system_namespaces` и `k8s_configuration_matrix_system_subjects`.

Все переменные ниже имеют префикс `k8s_configuration_matrix_`:

| Суффикс переменной | Default | Назначение |
| --- | --- | --- |
| `namespace_mode` | `application` | `application`, `system` или `all` |
| `system_namespaces` | см. выше | Имена/glob системных namespace |
| `namespaces` | `[]` | Точные имена namespace; отсутствующее имя вызывает ошибку |
| `namespace_include`, `namespace_exclude` | `[]` | Имена/glob namespace |
| `include_system_subjects` | `false` | Показывать также системных пользователей/группы |
| `include_external_users` | `false` | Включить User без локального Deckhouse User; по умолчанию внешние идентичности показываются только группами |
| `system_subjects` | `['system:*']` | Имена/glob системных пользователей/групп |
| `users_include`, `users_exclude` | `[]` | Имена/glob пользователей; для Deckhouse — email |
| `groups_include`, `groups_exclude` | `[]` | Имена/glob групп; для Deckhouse — claim `spec.name` |
| `subjects_service_accounts` | `false` | Показывать ServiceAccount |
| `service_accounts_include`, `service_accounts_exclude` | `[]` | Имена/glob в формате `namespace/name` |
| `service_account_namespaces_include`, `service_account_namespaces_exclude` | `[]` | Имена/glob namespace самих ServiceAccount |
| `omit_empty_rows` | `true` | Убирать строки, где все видимые ячейки содержат только точки |
| `exclude_broad_subjects` | `true` | Исключать широкие wildcard-назначения и известных участников групп |

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


Для внешних User при включённом `include_external_users` рассчитываются только прямые назначения: заглавные буквы и точки, без наследования и `?`. Точка означает отсутствие прямого назначения, а не отсутствие доступа через группы. Локальность определяется совпадением имени субъекта с нормализованным `spec.email` прочитанного Deckhouse User. В vanilla все User внешние. В `subjects.csv` поле `rights_basis` равно `direct_only` для внешних User и `direct_and_groups` для остальных субъектов. `membership_complete` по-прежнему описывает полноту сведений о группах, а не режим расчёта. Даже явно переданные memberships не включают наследование для внешнего User. В bindings.csv для такого User сохраняются только его прямые источники; широкие группы не исключают его столбец через наследование.

Файл dry содержит разделы add/change/remove и metadata (cluster_uid, cluster_version, owner, digest). Добавления и удаления описаны однократно без apiVersion/apiGroup и служебных metadata; в change.fields показаны только изменённые значения before/after. Замена отмечается replacement: true. adoption выводится только при принятии существующего объекта под управление; allow_collision — только при изменении аннотации Deckhouse. privilege_change удалён: отчёт не оценивает фактическое увеличение или уменьшение прав. После apply без изменений списки add/change/remove пусты. Для анализа разрешений используйте matrix. Диагностический результат модуля и обычный --diff сохраняют before/after; файл dry является их кратким представлением.

Проверки access_checks удалены из роли: apply и prune не выполняют SubjectAccessReview. Для просмотра фактических прав с учётом содержимого ролей используйте matrix. Дополнительные проверки bindings после apply не добавлялись.

Экспорт inventory использует компактный YAML: каждый subject записан в фигурных скобках, roleRef и scope — в одну строку. Схема переменных сохраняется, файл непосредственно импортируется как inventory.

### Матрица по назначениям inventory

```yaml
k8s_configuration_config_mode: matrix
k8s_configuration_matrix_source: inventory
```

source=cluster (по умолчанию) читает текущие bindings. source=inventory использует только k8s_configuration_grants и актуальные rules Role/ClusterRole из API: назначения, уже существующие в кластере, не читаются и не добавляются. Требуются явно заданные grants; [] означает пустой набор. Поддерживаются RoleBinding по namespaces, ClusterRoleBinding и state: absent (исключается). Несуществующие namespace/роли прерывают отчёт до записи файлов. Правила агрегированных ClusterRole берутся в текущем состоянии.

Локальные User/Group и их членство читаются из Deckhouse, параметры k8s_configuration_users/groups и пароли не вычисляются. Сохраняются обычные фильтры, маски, прямые права внешних User и наследование локальных пользователей. Для столбцов внешних User включите k8s_configuration_matrix_include_external_users. Источник виден в summary.source, subjects.csv (inventory-binding) и bindings.csv (record_type=inventory-rbac).

Файлы по умолчанию: matrix-inventory.csv, bindings-inventory.csv, subjects-inventory.csv на контроллере, отдельно от текущей матрицы. Их имена по-прежнему переопределяются через matrix_filename/matrix_bindings_filename/matrix_subjects_filename.

Это права только от описанных назначений, а не полный эффективный доступ после apply: прочие bindings исключены, prune/adoption/ограничения удаления и допустимость применения не проверяются. Для проверки плана применения используйте dry. Новые User/Group из inventory и будущее изменение агрегированных ролей/токенов не прогнозируются. GET-only; --check не пишет CSV.

На первом этапе source=inventory поддерживает только backend: rbac, в том числе на Deckhouse. Для backend: deckhouse (AR/CAR) роль завершает работу с ошибкой: accessLevel не является прямой ссылкой на роль, права производных bindings зависят от контроллера. Для таких назначений используйте source=cluster после apply; виртуальные разрешения AR/CAR не подставляются.
