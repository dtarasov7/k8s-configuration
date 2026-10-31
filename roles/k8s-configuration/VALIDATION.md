# Проверки реализации

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
