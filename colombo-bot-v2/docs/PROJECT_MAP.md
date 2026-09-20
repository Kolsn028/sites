# Карта проекта

Пути относительно `colombo-bot-v2/`. Читайте только строки, относящиеся к задаче.

| Задача | Код | Основные тесты в tests/ |
|---|---|---|
| Запуск, события Discord, завершение | main.py, bot/core.py | test_workflows.py |
| Команды и setup | bot/commands.py, bot/provisioning.py | test_setup_access.py, test_main_rank.py |
| Роли, права, адресаты уведомлений | bot/roles.py, bot/membership.py | test_roles.py, test_membership.py |
| Заявки в семью, рекрутеры | bot/views.py, bot/recruiting.py, bot/enhancements.py | test_recruiting.py, test_enhancements.py |
| Отдых и возвращение | bot/leave.py, bot/views.py | test_leave_role_only.py |
| Контракты и повышения | bot/progression.py | test_progression.py |
| Тиры, tiercheck, доступ к веткам | bot/tiers.py | test_tiers.py |
| МП: карточки, основной и запасной состав | bot/events.py, bot/roster.py | test_events.py |
| Личные дела и панели управления | bot/profiles.py, bot/dashboard.py | test_dashboard.py |
| SQLite, схема, миграции | bot/database.py, bot/schema_v9.py, bot/migration_v9.py | test_upgrade_v9.py |
| Резервные копии и логи Discord | bot/discord_backup.py | test_discord_backup.py |
| Разовое восстановление статистики | bot/recovery_september.py | test_recovery_september.py |
| Обновление сообщений, объединение запросов | bot/performance.py | test_performance.py |
| Общие обработчики и оформление | bot/interactions.py, bot/ui.py | test_workflows.py |
| Перенос старых ролей | bot/legacy.py | test_upgrade_v9.py |

Тесты в таблице — отправная точка, а не обещание полного покрытия модуля.

## Связи, которые важно сохранить

- main.py создаёт Database и ColomboBot, регистрирует команды и запускает подключение. core.py управляет жизненным циклом.
- Команды и Discord-компоненты вызывают обработчики функций; права проверяются на стороне бота. Для тиров действует отдельное правило tiercheck.
- SQLite — рабочее состояние. discord_backup.py сохраняет проверяемые снимки в Discord и восстанавливает данные при отсутствии конфигурации сервера. Обычные сообщения логов не являются источником восстановления.
- Существующие сообщения используют persistent views и custom_id. Переименование обработчика не должно ломать уже опубликованные кнопки.
- performance.py объединяет обновления панелей и пропускает неизменившиеся сообщения. Не обходите этот механизм без причины.

Подробности: [тиры](TIERS.md), [хранение](DISCORD_STORAGE.md), [частота сохранений](QUIET_LOGGING.md). Исторические инструкции требуют сверки с текущим кодом.
