# Карта проекта

Пути относительно `colombo-bot-v2/`. Читайте только строки, относящиеся к задаче.

| Задача | Код | Основные тесты в tests/ |
|---|---|---|
| Запуск, события Discord, завершение | main.py, bot/core.py | test_workflows.py |
| Команды и setup | bot/commands.py, bot/provisioning.py | test_setup_access.py, test_main_rank.py |
| Роли, права, адресаты уведомлений | bot/access.py, bot/roles.py, bot/membership.py | test_roles.py, test_membership.py |
| Заявки в семью, рекрутеры | bot/forms/applications.py, bot/services/applications.py, bot/recruiting.py, bot/enhancements.py | test_recruiting.py, test_enhancements.py |
| Отдых и возвращение | bot/services/leave.py, bot/leave.py, bot/forms/vacations.py | test_leave_role_only.py |
| Классификация и проверка активности | bot/forms/activities.py | test_forms_compatibility.py, test_workflows.py |
| Контракты и повышения | bot/progression.py, bot/services/ranks.py | test_progression.py |
| Тиры, tiercheck, доступ к веткам | bot/tiers.py | test_tiers.py |
| МП: карточки, основной и запасной состав | bot/events.py, bot/roster.py | test_events.py |
| Личные дела и панели управления | bot/profiles.py, bot/forms/cases.py, bot/dashboard.py | test_dashboard.py |
| SQLite, схема, миграции | bot/database.py, bot/repositories/, bot/schema_v9.py, bot/migration_v9.py | test_upgrade_v9.py |
| Резервные копии и логи Discord | bot/discord_backup.py | test_discord_backup.py |
| Разовое восстановление статистики | bot/recovery_september.py | test_recovery_september.py |
| Обновление сообщений, объединение запросов | bot/performance.py | test_performance.py |
| Общие обработчики и оформление | bot/interactions.py, bot/ui.py | test_workflows.py |
| Перенос старых ролей | bot/legacy.py | test_upgrade_v9.py |

Тесты в таблице — отправная точка, а не обещание полного покрытия модуля.

## Формы и кнопки

`bot/forms/` разделён по функциям: applications, vacations, cases, activities. Общие вспомогательные функции находятся в shared.py. `bot/views.py` оставлен как слой совместимости импортов; новую логику добавляйте в соответствующий модуль forms. Старые custom_id проверяются в tests/test_forms_compatibility.py.

## Границы слоёв

- forms и модули интерфейса: ввод, ответы, карточки; SQL сюда не добавлять.
- services: решения и изменения ролей без кнопок и embed. Приём и отказ используют services/applications.py; отпуск — services/leave.py; Main и тиры — services/ranks.py.
- access.py: правила допуска. roles.py сохраняет прежние импорты, описание ролей и уведомления. Tiercheck и старые административные исключения прописаны отдельно.
- repositories: именованные методы Database по направлениям. Блокировки и транзакции записи находятся здесь; не оборачивать эти методы повторно в db.lock. Существующие транзакции roster и резервного копирования остаются в своих модулях.
- database.py сохраняет публичный Database и схему; миграция данных для этого разделения не нужна.

Сценарии приёма и восстановления после ошибок: tests/test_application_scenarios.py. Карта прав: tests/test_access_policy.py. Сценарии данных и изоляция серверов: tests/test_repository_scenarios.py.

## Связи, которые важно сохранить

- main.py создаёт Database и ColomboBot, регистрирует команды и запускает подключение. core.py управляет жизненным циклом.
- Команды и Discord-компоненты вызывают обработчики функций; права проверяются на стороне бота. Для тиров действует отдельное правило tiercheck.
- SQLite — рабочее состояние. discord_backup.py сохраняет проверяемые снимки в Discord и восстанавливает данные при отсутствии конфигурации сервера. Обычные сообщения логов не являются источником восстановления.
- Существующие сообщения используют persistent views и custom_id. Переименование обработчика не должно ломать уже опубликованные кнопки.
- performance.py объединяет обновления панелей и пропускает неизменившиеся сообщения. Не обходите этот механизм без причины.

Подробности: [тиры](TIERS.md), [хранение](DISCORD_STORAGE.md), [частота сохранений](QUIET_LOGGING.md). Исторические инструкции требуют сверки с текущим кодом.
