# История изменений

## 1.1.0

- Роль переименована в k8s-configuration, переменные и модуль используют k8s_configuration_. Ownership и имена ресурсов сохранены.
- Добавлен самостоятельный dry с тремя сводками; plan сохранён как синоним. Исправлен стандартный diff и export --check.
- Файл export содержит переменные inventory без обёртки, audit сохраняется отдельно. Поддержан перенос самостоятельных User/Group с bcrypt без вывода хешей в консоль.
- Неподдерживаемые выбранные объекты блокируют экспорт по умолчанию; неполный снимок требует allow_partial.


## 1.0.0 — 2026-10-23

- Добавлена Ansible-роль с собственным HTTPS API-клиентом для vanilla Kubernetes и Deckhouse.
- Реализованы plan/apply/export, check/diff, строгая схема, ownership/adoption, ограниченный prune и защита конкурентных записей.
- Добавлены локальные User/Group, базовые AuthorizationRule/ClusterAuthorizationRule и явные профили Deckhouse.
- Добавлены unit/HTTPS integration, Molecule на RED OS с настоящим kind API и сценарий отказа control-plane узла.
- Production-профиль Deckhouse требует проверки на целевой версии; поставляемые тестовые API fixtures не подтверждают работу реального контроллера.
