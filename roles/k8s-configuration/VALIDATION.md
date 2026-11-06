# Проверки реализации

## README, примеры и удаление задач user/clean — 6 ноября 2026 года

- PASS: 6 тестов test_flat_settings.py; проверка шаблонизации настроек включает новый examples/deckhouse и все его 9 сценариев.
- PASS: syntax-check examples/playbook.yml с examples/inventory.ini и examples/deckhouse/playbook.yml с inventory/hosts.ini. Относительный путь новой роли разрешается без ANSIBLE_ROLES_PATH.
- PASS: baseline → повторный apply → OpenLDAP → точечный отзыв → cleanup на FakeAPI; User/Group и определения Role/ClusterRole сохранены, собственные bindings удалены.
- PASS: --list-tags показывает always/config/install/pre-req/ssl, без user/clean.
- PASS: все 83 defaults имеют пояснения в обеих таблицах README; английские описания не содержат кириллицы. Примеры YAML, синтаксис shell-команд, INI-блоки, UTF-8/LF проверены.
- Реальный кластер не использовался; настройки примера и манифесты к нему не применялись.

## Удаление управления User/Group — 3 ноября 2026 года

Роль управляет только назначениями доступа. Удалены входные параметры users/groups, формирование и изменение User/Group, пароли, состав групп, удаление identities и связанные настройки. Чтение User/Group сохранено в матрице прав. Предыдущие записи ниже описывают исторические проверки прежнего интерфейса.

- PASS: 123 unit-теста (5.255 s), включая сохранность существующих User/Group с метками прежнего владельца при apply/idempotence/prune/export и отсутствие удалённых параметров в argument_spec.
- PASS: 36 интеграционных тестов через Ansible/kubectl и локальный HTTPS API (179.630 s): назначения, dry/apply/check/diff, export, cluster/inventory matrix и сохранность User/Group.
- PASS: syntax-check examples/playbook.yml; разбор Python AST и YAML, совпадение комментариев всех 83 defaults с описаниями в README.
- Настоящий кластер Deckhouse в этом прогоне не использовался.

## Проверка версии 2.9.0 — 3 ноября 2026 года

Удалён vars/main.yml. Плоские аргументы передаются из execute.yml в модуль; типы и внутренние пути заданы в settings.py. Удалены expected_image/manual_dkp_deckhouse_image, проверка образа и rollout Deployment Deckhouse. Проверки Module и API/CRD сохранены.

- PASS: 127 unit-тестов, включая шаблонизацию обоих inventory и всех сценариев, boolean CLI strings, отсутствие старых аргументов модуля, сохранение None/пустых списков и приоритет TLS content.
- PASS: полный интеграционный набор test_ansible_https.py — 29 тестов через настоящий Ansible/kubectl и локальный HTTPS API (187.617 s). Проверены apply/idempotence, dry, export, cluster/inventory matrix, check/diff, секреты и файлы на controller.
- При первом интеграционном прогоне выявлено преждевременное вычисление прямых Jinja-переменных users/groups в общей задаче. Исправлено условным lookup vars; обе упавшие проверки отдельно и полный повторный прогон прошли.
- PASS: syntax-check обоих ручных playbook; UTF-8/LF, Python/YAML для 95 файлов, YAML блока DOCUMENTATION модуля.

Реальные кластеры и Molecule не запускались.

## Проверка версии 2.8.1 — 3 ноября 2026 года

Добавлены EN/RU docstring и поясняющие комментарии к Python-коду роли и сложным Jinja-выражениям. Изменения ограничены документацией: module/class/function docstring, Python/YAML comments, CHANGELOG и этот отчёт.

- PASS: AST каждого из 9 Python-файлов после удаления docstring полностью совпадает с AST до правок; Python 3.8 syntax и UTF-8/LF проверены.
- PASS: 109 EN/RU docstring; все 8 классов документированы. Основные функции описывают типы параметров, возвращаемые значения/побочные эффекты и ожидаемые ошибки. Пояснения охватывают защиту секретов, контекст kubectl, отсутствие повторов записи, lost-response recovery, UID/resourceVersion, pagination, wildcard/unknown scope, membership и inventory matrix.
- PASS: полный unit suite — 125 тестов.
- PASS: syntax-check обоих manual playbook.

Runtime-изменений нет; integration/Molecule и реальные кластеры повторно не запускались. Контрольный AST сохранён только во временном каталоге .test-tmp.


## Проверка версии 2.8.0 — 3 ноября 2026 года

Добавлен k8s_configuration_matrix_source=cluster/inventory. По выбору пользователя inventory означает только назначения из grants, без сохранённых сторонних bindings. Inventory-режим не читает RoleBinding/ClusterRoleBinding и AR/CAR; использует текущие rules Role/ClusterRole и живое локальное Deckhouse-членство. Desired users/groups и парольные lookup не оцениваются. State absent пропускается. Не прогнозируются prune/adoption, применимость изменений, другие bindings и будущие изменения контроллеров. Native backend deckhouse явно отклоняется; поддерживается RBAC на обеих платформах.

- PASS: полный unit suite — 125 тестов. Новые 4 теста: запрет чтения bindings, изменение матрицы вслед за live rules, Role/ClusterRole scopes, absent/пустой набор, ошибки отсутствующих inputs/roles/ns, отказ AR/CAR, живое локальное членство.
- PASS: 10 интеграционных matrix-тестов через настоящий Ansible/kubectl и локальный HTTPS API. Новый inventory-сценарий проходит при запрете GET bindings, не вычисляет undefined users/groups, сохраняет три *-inventory.csv, учитывает только inventory Group, идемпотентен; --check не пишет файлы, ошибка missing role не оставляет CSV. Все API-вызовы GET. Cluster matrix сохраняет прежнее поведение.
- PASS: syntax-check обоих matrix-inventory.yml сценариев; UTF-8/LF, Python 3.8/YAML 89 файлов и Markdown YAML.

Реальные dkp/k3s и Molecule не запускались.


## Проверка версии 2.7.0 — 3 ноября 2026 года

Файл dry преобразуется из очищенного внутреннего плана в add/change/remove и metadata. Стандартный --diff продолжает использовать before/after. Убраны privilege_change/reasons, false adoption и неизменённый allow_collision. Сохранены реальные adoption/collision transitions, password_changed без значения и replacement. Сравнение игнорирует порядок subjects/members и CRD-default false. Mixed-предупреждения перечисляют релевантного субъекта и конкретные RBAC/Deckhouse-объекты; проверки допустимости смешанных backend сохранены.

- PASS: полный unit suite — 121 тест. Новые 7 тестов покрывают пустой план, смешанный add/update/delete, изменение только subjects, замену roleRef, adoption, collision без паролей, порядок списков/CRD defaults и конкретные mixed-предупреждения.
- PASS: 4 integration dry-теста через настоящий Ansible/kubectl и локальный HTTPS API. Дополнительно PASS: стандартный apply --diff с sanitization/no_log и запись результатов на controller при недоступном target connection. После нормализации сравнения повторно PASS: dry_file_contains_only_operations_and_changed_fields.
- PASS: syntax-check обоих manual playbook; UTF-8/LF и Python 3.8/YAML 86 файлов, README YAML-примеры.

Реальные кластеры и Molecule не запускались. Алгоритм применения назначений и digest не менялись; изменено представление отчёта и текст предупреждений.


## Проверка версии 2.6.1 — 3 ноября 2026 года

Аудит defaults/vars/tasks/модульного кода, обоих ручных inventory и всех сценариев выявил четыре лишних объявления: k8s_configuration_export_include_identities в vanilla inventory и k8s_configuration_hashi_vault_path, k8s_configuration_hashi_vault_path_password, k8s_configuration_local_certs_path в defaults. Все удалены. Пути для lookup-примеров README переименованы в example_* и определены внутри примера. Остальные 88 defaults имеют ссылки в runtime-файлах; неизвестных параметров роли и вспомогательных manual_* объявлений без использования в обоих стендах не осталось. manual_dkp_deckhouse_image сохранена: через expected_image она участвует в необязательной проверке образа.

- PASS: 114 unit-тестов, включая 4 test_flat_settings: ссылки на defaults, неизвестные role-параметры и шаблонизация/валидация всех ручных inventory/scenarios.
- PASS: syntax-check manual-test и manual-test-dkp playbook.
- PASS: UTF-8/LF, Python 3.8/YAML изменённых исходников, YAML-примеры README RU/EN.

Изменения не затрагивают runtime-алгоритмы; integration suite повторно не запускался. Реальные кластеры не использовались.


## Проверка версии 2.6.0 — 3 ноября 2026 года

По явному выбору пользователя экспорт ограничен назначениями без возможности включения identities. Удалены include_identities из схемы/defaults/private vars/ручного inventory, экспорт локальных User/Group и хешей, сопоставление зависимостей. Сохранились компактное форматирование, буквальные subjects, фильтрация grants, аудит неподдерживаемых полей и валидация импортируемого списка grants. Функции apply/matrix не менялись.

- PASS: полный unit suite — 113 тестов. Неподдерживаемые поля локального User не блокируют экспорт его назначений; inventory/audit не содержат identities и bcrypt.
- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/integration -p test_ansible_https.py -k export -v` — 5 тестов настоящего Ansible/kubectl с локальным HTTPS API. Проверены компактный экспорт и импорт только назначений, отсутствие самостоятельных User/Group и хешей, --check, отказ при неподдерживаемых полях authorization rule.
- PASS: syntax-check Deckhouse manual playbook; UTF-8/LF, YAML и Python 3.8 syntax.

Реальный dkp и Molecule не запускались.


## Проверка версии 2.5.1 — 3 ноября 2026 года

Ручные inventory используют компактные subjects/roleRef/scope. В Deckhouse baseline добавлен cluster-node-readers: ClusterRoleBinding на существующую dkp-access-node-reader. Экспорт по умолчанию содержит только grants; include_identities=false исключает и самостоятельные identities, и зависимости назначений. Полный перенос identities сохранён по явному include_identities=true. Контроллерный YAML-фильтр формирует компактный, напрямую импортируемый файл.

- PASS: полный unit suite — 113 тестов; компактные поля, безопасное quoting, YAML round trip, cluster-grant, apply/noop/cleanup и экспорт.
- Integration: полный прогон — 25 PASS из 26; прежний тест неподдерживаемой identity ожидал ошибку обычного экспорта. Тест переведён на явный include_identities=true и повторён отдельно: PASS. Все 26 проверок прошли в совокупности. Новый тест подтверждает только grants, компактные строки, отсутствие хеша, импорт на другой API fixture и повторное применение без изменений.
- PASS: syntax-check обоих ручных playbook; 85 Python/YAML файлов и Markdown YAML-примеры проверены на UTF-8/LF и синтаксис Python 3.8/YAML.

Новые манифесты не потребовались: ClusterRole чтения nodes уже есть в fixtures. Пользовательское назначение group-readers-2 сохранено. Реальный dkp и Molecule не запускались.


## Проверка версии 2.5.0 — 3 ноября 2026 года

Поле source удалено из subjects: схема принимает kind/name и namespace для ServiceAccount, render передаёт имена буквально, export сохраняет фактические email/claims. Разделы управления локальными identities сохранены; соответствующие зависимости экспорта сопоставляются по фактическому имени субъекта. Ручные inventory/scenarios и Molecule обновлены.

- PASS: полный unit suite — 112 тестов. Проверены буквальное имя с регистром, экспорт без source и повторное применение, локальные email/claims, ServiceAccount и зависимости экспорта.
- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/integration -p test_ansible_https.py -v` — 25 тестов через настоящий Ansible/kubectl и локальный HTTPS API, включая перенос экспорта, apply/noop, dry и matrix.
- PASS: syntax-check обоих ручных playbook; UTF-8/LF, YAML/Python 3.8 для 83 файлов и YAML-примеры README/design.

Пользовательское назначение group-readers-2 сохранено. Реальный dkp и Molecule не запускались.


## Проверка версии 2.4.0 — 3 ноября 2026 года

Удалены access_checks из defaults, private payload, схемы и аргументов модуля, SAR после apply и перед prune, требование положительной проверки для профиля Deckhouse без Ready condition. Удалены соответствующие списки из manual-test и manual-test-dkp; explicit-scope.yml удалён как сценарий только с SAR. Дополнительные проверки bindings после apply не добавлялись.

- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/unit -q` — 111 тестов. Покрыты prune без SAR и apply/noop Deckhouse с отсутствующим authz_ready_condition.
- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/integration -p test_ansible_https.py -v` — 25 тестов через настоящий Ansible/kubectl и локальный HTTPS API. Проверены apply/noop без SAR, dry, export, matrix и управление только назначениями в ручном стенде.
- PASS: syntax-check playbook обоих ручных стендов; 83 YAML/Python файла проверены на UTF-8/LF и синтаксис YAML/Python 3.8.

Существующее пользовательское назначение group-readers-2 сохранено; тест получает число bindings из текущего inventory. Локальному HTTPS fixture требовалось разрешение сетевой изоляции sandbox. Реальный dkp и Molecule не запускались. Отдельный SAR в live_smoke остаётся тестом вне роли и автоматически при apply не выполняется.


## Проверка версии 2.3.3 — 3 ноября 2026 года

- PASS: полный unit suite — 110 тестов. Проверены пустой changes после apply и смешанный план с create/update/delete плюс неизменённый объект: noop учитывается только в summary.
- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/integration -p test_ansible_https.py -k dry_after_apply -v` — настоящий Ansible apply, затем dry с тем же inventory. Сохранённый файл содержит пустые changes/planned, summary.noop=1, без before/after; dry выполняет только GET.
- PASS: Python 3.8 syntax, UTF-8/LF изменённых исходников.

Локальный HTTPS fixture запущен с разрешением сетевого sandbox. Реальный dkp не использовался.


## Проверка версии 2.3.2 — 3 ноября 2026 года

Внешние User в matrix рассчитываются только по прямым назначениям. Локальные Deckhouse User определяются по прочитанным объектам User/email и сохраняют наследование. subjects.csv содержит rights_basis; фильтр широких субъектов и bindings.csv согласованы с режимом расчёта.

- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/unit -q` — 110 тестов. Новая проверка обеих платформ подтверждает заглавные буквы/точки внешних User, отсутствие наследования system:authenticated/явных memberships, только прямые источники, специальные verbs и удаление пустых строк. Сохраняется наследование локальных User, вложенных групп и ServiceAccount.
- PASS: `python3 -m unittest discover -s roles/k8s-configuration/tests/integration -p test_ansible_https.py -k matrix -v` — 8 тестов через настоящий Ansible/kubectl и локальный HTTPS API. Проверены CLI true/false, права внешних User, rights_basis, прямые источники, живая локальная принадлежность, фильтры, идемпотентность и --check. API получает только GET.
- PASS: syntax-check manual-test-dkp/playbook.yaml со сценарием matrix и CLI include_external_users=true; UTF-8/LF и Python 3.8 syntax изменённых исходников.

Локальному HTTPS fixture требовался запуск вне сетевой изоляции sandbox. Для syntax-check ANSIBLE_LOCAL_TEMP направлен в .test-tmp проекта. Реальный dkp, live smoke и Molecule не запускались.


## Проверка версии 2.3.1 — 3 ноября 2026 года

Исправлена передача строковых true/false из CLI extra-vars в строгую схему matrix. Девять boolean-переключателей нормализуются фильтром Ansible bool на границе публичных переменных и модульного payload.

- PASS: 3 test_flat_settings проверки, включая true/false строки каждого из девяти переключателей и шаблонизацию всех ручных inventory/scenarios.
- PASS: 8 интеграционных matrix-тестов через настоящий Ansible/kubectl с локальным HTTPS fixture. Новый тест передаёт именно -e k8s_configuration_matrix_include_external_users=true и false: внешний User появляется/исчезает, явное get сохраняется как G, группа остаётся, все обращения GET.
- PASS: syntax-check Deckhouse playbook со сценарием matrix и исходным CLI key=value; UTF-8/LF, YAML/Markdown YAML и Python 3.8 syntax изменённых исходников.

Реальный dkp, Molecule и полный integration suite не запускались: изменение ограничено передачей boolean-настроек matrix.

## Проверка версии 2.3.0 — 3 ноября 2026 года

Удалены статические справочники членства из обоих ручных стендов. Matrix вычисляет полное членство локальных Deckhouse User из текущих объектов Kubernetes (Group/вложенные связи и legacy User.spec.groups); внешние User по умолчанию исключены, внешние группы представлены без попытки восстановить участников. include_external_users=true явно возвращает User-аудит с неизвестным внешним членством. При отключённом resolve_group_membership локальная полнота не подтверждается.

- PASS: 108 unit-тестов, включая 40 matrix-проверок. Покрыты локальная полнота без inventory dictionary, legacy groups, отсутствие локальных групп, nested groups, режим без resolution, неоднозначные local emails и внешний group-only default без строк прямых User grants.
- PASS: 30 интеграционных тестов (23 packaged Ansible/HTTPS и 7 выбора узла). Новый тест читает живые Group через настоящий Ansible/kubectl: локальный пользователь получает g.......; после ручного удаления участника из Group — ........; LDAP-группа видима, внешний User и его прямые secret-строки исключены, все запросы GET.
- PASS: новый manual fixture тест подтверждает актуальность после переноса локального участника между группами без изменения inventory.
- PASS: syntax-check обоих ручных playbook со сценарием matrix; шаблонизация inventory/scenarios; UTF-8/LF, YAML/Markdown YAML и Python 3.8 syntax 91 исходного файла.

Реальный dkp/Dex/LDAP, Molecule и деградация не запускались; свободно около 720 MiB. Локальная полнота относится к локальной аутентификации Deckhouse, а не к произвольным внешним токенам с совпадающим username. Сопоставление групп по точным claim-именам сверено с официальной документацией Kubernetes authentication и Deckhouse user-authn usage.

## Проверка версии 2.2.3 — 2 ноября 2026 года

Изменены только данные ручного стенда matrix: явный complete-справочник для 16 локальных fixtures users, переопределяемый через manual_dkp_matrix_memberships. Полнота не приписывается произвольным пользователям кластера.

- PASS: 4 проверки test_manual_dkp, включая соответствие membership манифестам, унаследованные glw..... для alice, точки auditor без доступа и GLW????? для неизвестного внешнего пользователя.
- PASS: 2 проверки test_flat_settings: схема и шаблонизация ручных inventory/scenarios.

Проверка на реальном dkp и полный integration suite не запускались; runtime роли не менялся.

## Проверка версии 2.2.2 — 2 ноября 2026 года

Перестроен только manual-test-dkp: fixtures создают локальные User/Group и дополнительные роли, inventory управляет external claims и привязками. Пароль 16 локальных пользователей — публичное тестовое значение 12121212, сохранённое как Base64 от bcrypt; все хеши проверены crypt.crypt. Runtime роли не менялся.

- PASS: 104 unit-теста, включая 3 новых проверки ручного Deckhouse-стенда. Все 18 сценариев оставляют users/groups неуправляемыми, prune_identities=false и не используют static subjects/password lookup. Проверены baseline (16 RoleBinding), идемпотентность, изменение группы привязки, cleanup без изменения User/Group/Role/ClusterRole и план 6 native AuthorizationRule.
- PASS: новая интеграционная проверка test_manual_dkp_assigns_rights_without_managing_fixture_identities_or_roles через настоящий Ansible/kubectl с HTTPS fixture: apply --check только GET; apply создаёт 16 RoleBinding для локальных и LDAP claims, сохраняет fixture identities/roles; повтор changed=0, хеши отсутствуют в stdout. Полный integration suite в этом прогоне не повторялся: runtime роли не менялся; предыдущие 28 тестов относятся к 2.2.1.
- PASS: syntax-check ручного Deckhouse playbook; шаблонизация inventory/scenarios без частных файлов паролей; UTF-8/LF, YAML/Markdown YAML и Python 3.8 syntax для 91 исходного файла роли и ручных стендов. Пользовательские output/private исключены из статической проверки.

Реальные dkp/Dex/LDAP, Molecule и деградация не запускались. SAR в fixture получает заранее заданные ответы и не подтверждает эффективные права настоящего кластера. User/Group manifests сверены с официальными CRD Deckhouse v1.73.4 (modules/150-user-authn/crds/user.yaml, group.yaml).

## Проверка версии 2.2.1 — 2 ноября 2026 года

Matrix по умолчанию исключает субъектов с явными wildcard apiGroups/resources без resourceNames и их известных участников. Набор verbs не влияет на классификацию; широкое назначение должно действовать в выбранной области. Правила исключённых субъектов не создают строки CSV. Переменная exclude_broad_subjects=false возвращает прежнюю выборку.

- PASS: 101 unit-тест (Python 3.8.20), включая 37 matrix-проверок: администраторы и широкий read-only, прямые пользователи, известные участники и вложенные Deckhouse группы, scoped RoleBinding, сохранение ограничений resourceNames и конкретных API-групп, восстановление фильтра false и удаление лишних строк при неполном членстве других пользователей.
- PASS: 28 интеграционных тестов (21 packaged Ansible/HTTPS и 7 выбора узла). Новая проверка читает CSV на controller: широкие группы и известный участник скрыты, у обычного пользователя только строка pods, отключение переменной возвращает столбцы и wildcard-строки; все обращения к Kubernetes GET.
- PASS: проверка шаблонизации обоих inventory и сценариев после обновления; syntax-check обоих manual-test playbook, UTF-8/LF, YAML/Markdown YAML и Python 3.8 syntax для 93 файлов.

Настоящий Deckhouse, Molecule и деградация в этом прогоне не запускались; свободного места около 759 MiB. Неизвестное внешнее членство и административные права без явных wildcard этим фильтром не классифицируются.

## Проверка версии 2.2.0 — 2 ноября 2026 года

Реализован первый этап фильтрации matrix: application/system/all, системная классификация, glob include/exclude субъектов и namespace, ServiceAccount выключены по умолчанию, удаление строк только с точками. Расчёт наследования сохраняет скрытые группы, неизвестные ячейки не удаляются.

- PASS: 97 unit-тестов (Python 3.8.20), включая 33 matrix-проверки. Новые проверки охватывают системные defaults vanilla/Deckhouse, независимость фильтров namespace и субъектов, пересечение точных имён/glob, приоритет exclude, наследование через скрытые системные и обычные группы, ServiceAccount name/namespace, неизвестное членство, пустую выборку и отбор AR/CAR деклараций.
- PASS: 27 интеграционных тестов (20 Ansible/HTTPS и 7 выбора target host). Новая проверка передаёт плоские фильтры через настоящий Ansible/kubectl и читает CSV с controller: доступ alice к kube-system через скрытую system:authenticated, исключённый bob, только GET.
- PASS: syntax-check обоих ручных playbook со сценарием matrix; UTF-8/LF, Python 3.8 syntax, YAML и YAML-примеры Markdown для 93 файлов роли и ручных стендов.

Настоящий Deckhouse, Molecule и деградация в этом прогоне не запускались; свободно около 764 MiB. HTTPS fixture проверяет клиент и расчёт RBAC, но не контроллеры Deckhouse/Dex.

## Проверка версии 2.1.0 — 2 ноября 2026 года

Удалена проверка устаревших словарей. Результаты dry/export/matrix сохраняются на Ansible controller через локальное соединение без become; пути и имена файлов задаются плоскими переменными inventory.

- PASS: 89 unit-тестов (Python 3.8.20).
- PASS: 26 интеграционных тестов (19 Ansible/HTTPS и 7 выбора target host). Проверены недоступное SSH-соединение target при записи на controller, отключение target become/Python для записи, относительные пути, сохранение прав существующего каталога, права файлов 0600, имена CSV из inventory, check и идемпотентность.
- PASS: syntax-check обоих manual-test playbook со сценарием matrix; UTF-8/LF, YAML, YAML-примеры Markdown и синтаксис Python 3.8 для 93 файлов роли и ручных стендов.

Настоящий Deckhouse и Molecule в этом прогоне не запускались; свободного места около 768 MiB. Интеграционные проверки используют локальный HTTPS API fixture и настоящий kubectl.

## Проверка версии 2.0.0 — 2 ноября 2026 года

Публичные настройки роли переведены на плоские переменные. Предметные списки users/groups/grants и формат CSV не изменены. Обновлены оба manual-test inventory/scenarios, examples, Molecule, README RU/EN и дизайн.

- PASS: 89 unit-тестов (Python 3.8.20), включая Module Ready без ModuleConfig и image pin, discovery served API, Established/served/schema CRD, блокировку выключенного/неготового модуля и появившихся после plan настроек.
- PASS: 24 интеграционных теста (ansible-core 2.13.13, настоящий kubectl 1.36.1, локальный HTTPS fixture): 17 packaged Ansible + 7 выбора execution host. Включены dry/apply/export/matrix, check/diff, idempotence, export/import и отсутствие хешей/токенов в stdout.
- PASS: отдельные проверки нового плоского интерфейса: override owner, шаблонизированный числовой max_deletions, отказ для старого config-словаря до обращения к API; apply/idempotence/export при готовых Module и отсутствующих ModuleConfig/Deployment deckhouse без pin образа.
- PASS: 34 набора настроек ручных стендов (две baseline и 32 сценария): настоящий шаблонизатор Ansible, тип int для safety.max_deletions из argument_spec, проверка схем config/export/matrix. Для adoption использован dummy UID, реальные пароли не читались.
- PASS: syntax-check обоих manual-test и основного examples/playbook.yml (с ANSIBLE_ROLES_PATH=roles); UTF-8/LF, YAML, YAML-примеры Markdown и синтаксис Python 3.8.

Для HTTPS unit fixture потребовалось разрешение loopback socket; повторный полный прогон прошёл. Molecule/настоящий кластер/деградация этой версии не запускались: на диске около 768 MiB свободного места (99% занято), новый kind-стенд не создавался. Ранее пользователь предоставил успешный matrix-лог настоящего dkp (174 субъекта, 14046 строк, 158052 записи источников); он относится к версии до перехода на плоские настройки, содержимое CSV агентом не проверено.

Обязательное чтение настроек user-authz заменено проверкой Module phase=Ready, EnabledByModuleManager=True, IsReady=True. ModuleConfig может отсутствовать; spec.enabled=false и HTTP 403 блокируют reconcile. CAR multitenancy по-прежнему требует явно подтверждённого enableMultiTenancy=true. Источник контракта Module: https://deckhouse.io/products/kubernetes-platform/documentation/v1/architecture/module-development/run/.

## Проверка версии 1.3.1 — 2 ноября 2026 года

После ручного запуска matrix на dkp выявлена недостаточная диагностика непредвиденного исключения. Воспроизведены и исправлены два дефекта обработки API: элементы List без kind (KeyError при построении индекса ролей) и пустые nullable списки rules/subjects/members/PolicyRule (TypeError при итерации). Исходный лог пользователя скрывал тип и место исключения, поэтому точная причина именно того запуска на dkp не установлена.

- PASS: 84 unit-теста, включая 25 проверок matrix. Добавлены эквивалентность отчёта без kind/apiVersion, null optional lists, пустой состав Deckhouse Group и безопасная диагностика исключений.
- PASS: четыре packaged Ansible/kubectl HTTPS проверки matrix: check/idempotence, Deckhouse scenario без TypeMeta и с rules: null, Forbidden и непредвиденный TypeError с файлом/строкой без traceback, токенов/хешей и записи CSV при ошибке.
- PASS: Python 3.8 syntax и UTF-8/LF изменённых файлов.

Непредвиденные ошибки теперь содержат только класс исключения и файл/строку кода. Текст исключения, traceback с исходниками/locals и объекты API не выводятся. Реальный dkp, Molecule и полный integration suite в этом дополнительном прогоне не запускались.

## Проверка версии 1.3.0 — 2 ноября 2026 года

Исправление после ручного запуска: прежний scenarios/matrix.yml требовал dkp-access-dev/dkp-access-stage и останавливался до создания оснастки. Теперь сценарий по умолчанию охватывает все существующие namespace; необязательный фильтр задаётся manual_dkp_matrix_namespaces. Диагностика роли перечисляет отсутствующие имена. PASS: 21 unit-тест матрицы, packaged Ansible/kubectl с настоящим файлом сценария на HTTPS fixture без тестовых namespace, syntax-check сценария, UTF-8/LF и Python 3.8 syntax. Настоящий dkp в этой проверке не использовался.

Добавлен GET-only режим matrix. Проверки выполнены на Python 3.8.20, ansible-core 2.13.13, настоящем kubectl 1.36.1 с локальным HTTPS API fixture.

- PASS: 79 unit-тестов, включая 20 новых проверок matrix: прямые/групповые маски, приоритет прямого назначения, неполное членство, стандартные группы ServiceAccount и anonymous, resourceNames/field-selector semantics, wildcard API/resources/verbs, подресурсы, nonResourceURLs, специальные действия, агрегация, namespace/ownership filters, пагинация, CSV quoting/formula protection, потерянный roleRef/Forbidden, Deckhouse email/claim/nested groups, циклы/потерянные ссылки, AR/CAR declarations, UID links и дрейф области/субъектов.
- PASS: 21 интеграционный тест роли (14 packaged Ansible HTTPS + 7 выбора execution host). Регрессия dry/apply/export, check/diff, idempotence, export/import, ошибки API и защита секретов.
- PASS: три новые packaged matrix-проверки, повторно выполненные после финальных изменений расчёта. Настоящий Ansible/kubectl: только GET, корректные CSV и права 0700/0600, --check не создаёт каталог/файлы, повторный запуск changed=0, Undefined desired-password variable не вычисляется, Deckhouse audit не требует Deployment/profile readiness, хеши/токены не попадают в stdout/CSV, Forbidden останавливает запись отчётов.
- PASS: syntax-check обоих ручных playbook с scenarios/matrix.yml, YAML/UTF-8/LF и Python 3.8 syntax.
- PASS: дополнительный расчёт на in-memory fixture: 1200 bindings, 60 namespace, 121 субъект, 240 строк матрицы и 9600 строк источников за ~0.28 s; все вызовы GET. Это не замер сетевого API. Отбор строк индексируется по ресурсу/namespace.

Molecule/live Kubernetes/деградация для 1.3.0 НЕ ЗАПУСКАЛИСЬ: на разделе workspace осталось около 783 MiB (99% занято), новый kind-стенд не разворачивался. В tests/live_smoke.py добавлены проверки прямой/групповой CSV-маски для будущего Molecule-прогона; они пока не подтверждены на настоящем API. Реальный Deckhouse/Dex, controller reconciliation и внешний IdP этим fixture не проверяются. Проверка фактических операций через SAR не входит в первый этап matrix.

Воспроизведение:

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
```

## Проверка версии 1.2.1 — 1 ноября 2026 года

Проверка execution host использует встроенный Ansible assert и ansible_play_hosts_all: учитывается итоговый набор hosts после --limit, а не исходный селектор или текущая serial-партия. Группы, all, списки и шаблоны разрешены при одном выбранном узле.

- PASS: 18 интеграционных тестов, ansible-core 2.13.13 / Python 3.8.20, настоящий kubectl 1.36.1 и локальный HTTPS API fixture.
- PASS: 7 тестов выбора узла (с дополнительными subTest): singleton group, all/group/list/pattern с --limit, localhost через -l, шаблонизированный hosts, serial: 1, запрет нескольких итоговых узлов, обязательная проверка при --tags config.
- PASS: dry/apply/export, check/diff, идемпотентность, экспорт/import, PATCH/DELETE preconditions и скрытие секретов в packaged Ansible suite.
- PASS: syntax-check ручного и основного примеров; UTF-8/LF, YAML и Python 3.8 syntax.

Транспорт Kubernetes в этой версии не менялся. Unit/Molecule/деградация повторно не запускались; предыдущие результаты и ограничения ниже относятся к версии 1.2.0. Собственный action plugin проверки селектора удалён. В manual-test восстановлен hosts: access_test, поддерживается -l redos8.


## Проверка версии 1.2.0 — 1 ноября 2026 года

Транспорт роли переведён на установленный kubectl. Собственная реализация HTTPS/TLS и разбора kubeconfig удалена. Python сохраняет планирование, экспорт и защитные проверки.

| Проверка | Результат |
| --- | --- |
| Unit/HTTPS transport | PASS: 59 тестов, Python 3.8.20, настоящий kubectl 1.36.1 |
| Packaged Ansible integration | PASS: 16 тестов, ansible-core 2.13.13 / Python 3.8.20, настоящий kubectl 1.36.1 |
| Выбор execution host | PASS: точное имя, localhost, имя из переменной; отказ для групп с одним/несколькими узлами, all, шаблонов, списков, --limit, serial: 1 и --tags config |
| Kubeconfig/context | PASS: явный context с другими credentials, фиксация current-context, отсутствие изменений kubeconfig, exec credential plugin, tokenFile rotation |
| Безопасные операции | PASS: JSON Patch test UID/resourceVersion, server-side dry-run, DeleteOptions.preconditions, имена с двоеточием, скрытие ошибок с секретами |
| Dry/apply/export, check/diff | PASS: только чтение в dry/check/export, apply/idempotence, экспорт/import, Deckhouse hashes скрыты в выводе |
| Syntax-check | PASS: examples/playbook.yml и manual-test/playbook.yaml |
| Molecule / настоящий Kubernetes | PASS: destroy/create/prepare/converge/idempotence/verify/destroy; RED OS 7.3.6, Python 3.8.20, kubectl/API 1.34.3, одноузловой kind |
| Три control-plane узла / деградация | НЕ ПРОВЕРЕНО для 1.2.0: трёхузловой стенд заполнил диск (ENOSPC); удалён, использован одноузловой стенд |
| Настоящий Deckhouse | НЕ ПРОВЕРЕНО; API fixtures не заменяют контроллеры |
| ansible-core 2.12 / 2.19, ansible-lint | Для 1.2.0 не повторялись; результаты ниже относятся к предыдущему транспорту |

Проверка Molecule дополнительно включает реальный JSON Patch с server-side dry-run для имени с двоеточием, повторный apply без изменений, replacement, отзыв/возврат доступа и положительные/отрицательные SubjectAccessReview. Тесты invalid target останавливаются до запуска kubectl. Проверка именованного remote inventory host в HTTPS suite использует local transport вместо SSH; Molecule выполняет роль в отдельном Docker execution host. Реальный SSH/redos8/k3s в этом прогоне не использовался.

Все текстовые изменения проверены как UTF-8/LF, YAML разобран, Python соответствует синтаксису 3.8. Воспроизведение HTTPS-тестов требует установленного kubectl, openssl, PyYAML для тестовой оснастки, Ansible и разрешённых loopback sockets.


## Проверка версии 1.1.0 — 24 октября 2026 года

Проверена переименованная роль `k8s-configuration`. Git metadata в workspace недоступна.

| Проверка | Результат |
| --- | --- |
| Unit/HTTPS transport | PASS: 56 тестов, Python 3.8.20 |
| Packaged Ansible HTTPS integration | PASS: 9 тестов, ansible-core 2.13.13 / Python 3.8.20 |
| Стандартный check/diff | PASS: apply --check, apply --diff с default no_log, dry с/без --check, export --check |
| Прямой импорт export | PASS: YAML через vars_files на новом API-стенде; повторный apply changed=false |
| Ручные изменения | PASS: scoped export ручного RoleBinding; перенос subjects и target_name |
| Deckhouse identities | PASS на HTTPS fixture: самостоятельные User/Group, bcrypt в файле 0600 без маскирования и без вывода в stdout/diff |
| Неполный export | PASS: отказ до записи файла с публичной безопасной причиной |
| ansible-playbook --syntax-check | PASS: переименованная роль в examples/playbook.yml |
| ansible-lint 25.9.2 | PASS: 0 нарушений; Python 3.12 / ansible-core 2.19.3 |
| molecule test | PASS: destroy/create/prepare/converge/idempotence/verify/destroy |
| Настоящий Kubernetes | PASS: kind 0.31.0, Kubernetes 1.34.3, три control-plane узла |
| Execution environment | PASS: RED OS 7.3.6 / Python 3.8.20 |
| Отказ control-plane узла | PASS: API/RBAC lifecycle при остановленном control-plane2; узел восстановлен |
| YAML, UTF-8/LF, Python 3.8 AST | PASS |

Ключевые изменения проверены фактическим запуском Ansible, а не только вызовами Python Engine. Dry не отправляет mutating-запросы даже при server_validation=true. Export --check остаётся export и не создаёт файл. Неподдерживаемый snapshot не выдаётся за полный; аудит сохраняется отдельно. Имя роли и префикс переменных обновлены во всех исполняемых примерах и тестах; ownership domain/owner defaults и имена ресурсов сохранены.

Прогоны core 2.12/2.19 с полным набором новых интеграционных сценариев не повторялись: ниже сохранены результаты исходной версии 1.0.0. Линтер core 2.19 подтверждает статические проверки, а не весь новый runtime-контракт. Реальный Deckhouse по-прежнему требует отдельного стенда; fixtures не заменяют его контроллеры.

## История проверки версии 1.0.0 — 23 октября 2026 года

Проверялась исходная роль в текущем workspace; Git metadata недоступна, идентификатор коммита не фиксировался.

| Проверка | Результат |
| --- | --- |
| Unit/HTTPS transport | PASS: 53 теста, Python 3.8.20 |
| Ansible HTTPS integration | PASS: 3 теста, ansible-core 2.13.13 / Python 3.8.20 |
| Legacy integration | PASS: те же 3 теста, изолированный ansible-core 2.12.10 / Python 3.8.20 |
| Modern integration | PASS: те же 3 теста, ansible-core 2.19.3 / Python 3.12 в Docker |
| ansible-playbook --syntax-check | PASS: examples/playbook.yml |
| ansible-lint 25.9.2 | PASS: 0 нарушений; Python 3.12 / ansible-core 2.19.3 |
| YAML, UTF-8/LF, Python 3.8 AST | PASS для исходных файлов роли |
| molecule test | PASS: create, prepare, converge, idempotence, verify, destroy |
| Реальный Kubernetes | PASS: kind 0.31.0, Kubernetes 1.34.3, три control-plane узла |
| Execution environment | PASS: RED OS 7.3.6, Python 3.8.20, PyYAML 6.0.2 |
| Отказ одного control-plane узла | PASS: остановлен kam-role-validation-control-plane2; API, RBAC lifecycle и проверки доступа продолжили работать; узел восстановлен в finally |
| RBAC target_name с двоеточием | PASS: создание/удаление на настоящем API, export/import в unit suite |
| Настоящий Deckhouse | НЕ ЗАПУСКАЛОСЬ: отдельный стенд, точная версия/редакция и kubeconfig не предоставлены |

## Что проверено

- Read-only plan/check/export, фактическое применение, повторный apply без изменений.
- API discovery, полная пагинация, ошибка повторяющегося continue token.
- Проверка CA/hostname, tokenFile rotation, запрет redirect, приватные TLS-файлы и очистка.
- Чужое владение, UID-bound adoption, controller markers, защищённые namespace/объекты, ограниченная область prune и пустой desired.
- Immutable roleRef replacement и включение replace в лимит удалений.
- Гонка после последнего GET: JSON Patch test и DELETE preconditions останавливают запись.
- Потерянный ответ успешного POST/PATCH проверяется чтением, без повторной записи.
- Явный HTTP 409 не считается успешной записью; частичный apply не продолжает prune.
- Положительные access_checks перед stale-prune и отрицательные проверки доступа после apply.
- Deckhouse User/Group, AR/CAR, локальные/внешние claims, пароль on_create/managed, disabled module при наличии CRD, multi-tenancy и несовместимый profile — на stateful API fixture.
- Export/import сохраняет имена и selectors; неподдерживаемые поля и зависимости помечаются непригодными для автоматического импорта.
- Пароли, bearer token и ключи отсутствуют в выводе. Имя context не маскирует одноимённый namespace.

Линтер использует `.ansible-lint`: только name[casing] исключено из-за обязательного префикса имени файла в задачах. Установленная community.docker 2.7.3 и локальный module_utils вызывают диагностические сообщения внутреннего ArgsRule о пропущенной introspection; это не нарушения роли. Реальный разбор аргументов и упаковка module_utils дополнительно проверены запуском Ansible на трёх версиях core.

## Воспроизведение

Из корня проекта:

```bash
python3 -m unittest discover -s roles/k8s-configuration/tests/unit -v
python3 -m unittest discover -s roles/k8s-configuration/tests/integration -v
ANSIBLE_ROLES_PATH=./roles ansible-playbook -i roles/k8s-configuration/examples/inventory.yml roles/k8s-configuration/examples/playbook.yml --syntax-check
ansible-lint --offline -c roles/k8s-configuration/.ansible-lint roles/k8s-configuration
```

HTTPS suite требует openssl и разрешённых loopback sockets. Зависимости control node устанавливаются отдельно; для проверки разных профилей следует использовать соответствующий executable ansible-playbook и его Python environment.

Инструкции подготовки RED OS execution image, kind-кластера и переменных Molecule приведены в README.md. Проверка деградации запускается из корня проекта:

```bash
python3 roles/k8s-configuration/tests/degradation.py "$KAM_TEST_KUBECONFIG"
```

Скрипты live_smoke.py и degradation.py предназначены только для тестового контекста kind-kam-role-validation; не используйте их против рабочих кластеров. Molecule удаляет собственный executor, отдельный kind-кластер удаляется отдельно.

## Граница подтверждённой совместимости

Встроенные Deckhouse fixtures проверяют поведение клиента и планировщика, но не контроллеры, admission webhooks, аутентификацию Dex или фактическую комбинацию CAR/RBAC конкретного выпуска. Production-профиль Deckhouse нужно отдельно зафиксировать и проверить через `tests/integration/deckhouse.yml` с минимум положительным и отрицательным access_checks.

Проверка modern control node и проверка RED OS execution host выполнены раздельно; комбинация core 2.19 → RED OS через удалённое соединение в этом прогоне не проверялась. Роль не заявляет непрерывную поддержку всех промежуточных выпусков Ansible или всех редакций Deckhouse.
