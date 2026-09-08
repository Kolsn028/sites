import os
from datetime import datetime, timezone
import discord

FAMILY_NAME = os.getenv('FAMILY_NAME', 'COLOMBO FAMILY')
try:
    EMBED_COLOR = int(os.getenv('EMBED_COLOR', '0xA82D40'), 16)
except ValueError:
    EMBED_COLOR = 0xA82D40
BANNER_URL = os.getenv('BANNER_URL', '').strip()
FOOTER_TEXT = os.getenv('FOOTER_TEXT', 'COLOMBO • Семья. Уважение. Дисциплина.')


def base_embed(title, description='', color=None):
    e = discord.Embed(title=title, description=description, color=color if color is not None else EMBED_COLOR,
                      timestamp=datetime.now(timezone.utc))
    e.set_author(name=FAMILY_NAME)
    e.set_footer(text=FOOTER_TEXT)
    return e


def panel(title, description, fields, color=EMBED_COLOR):
    e = base_embed(title, description, color)
    for name, value in fields:
        e.add_field(name=name, value=value, inline=False)
    if BANNER_URL.startswith('https://'):
        e.set_image(url=BANNER_URL)
    return e


def application_panel_embed():
    return panel('ТВОЙ ПУТЬ В COLOMBO',
        'Добро пожаловать в семью.\n**Сильный состав начинается с надёжных людей.**', [
        ('01  /  ЗАПОЛНИ АНКЕТУ', 'Нажми **«Подать заявку»** и расскажи о себе, своём опыте и онлайне.'),
        ('02  /  ПОЗНАКОМЬСЯ С РЕКРУТЕРОМ', 'После отправки откроется личная ветка. Там можно задать вопросы и получить решение.'),
        ('03  /  ПРОЙДИ ОБЗВОН', 'Рекрутер сообщит время и канал для беседы. После принятия тебе откроется личное дело.'),
        ('Перед отправкой', 'Пиши честно и по делу. Срок рассмотрения зависит от занятости рекрутеров.\nТвою анкету видят приглашённые участники ветки и сотрудники с правом управления ветками.'),
    ])


def vacation_panel_embed():
    return panel('ВРЕМЯ НА ОТДЫХ', 'Нужна пауза? Предупреди руководство — сохрани порядок в составе.', [
        ('01  /  ОСТАВЬ ЗАЯВКУ', 'Укажи причину и срок: **от 1 до 60 дней**.'),
        ('02  /  ДОЖДИСЬ РЕШЕНИЯ', 'Бот создаст отдельную приватную ветку для тебя и руководства.'),
        ('03  /  ВОЗВРАЩАЙСЯ В СТРОЙ', 'После одобрения получишь роль отдыха. На этот период ты исключаешься из отчёта о неактиве.'),
    ], 0xC69B59)


def case_panel_embed():
    return panel('ТВОЁ ЛИЧНОЕ ДЕЛО', 'Вся активность участника — в одном месте.', [
        ('01  /  ОТКРОЙ ДЕЛО', 'Кнопка создаст приватный канал или откроет уже существующий.'),
        ('02  /  ДОБАВЬ ОТЧЁТ', 'Отправь скриншот или видео и выбери тип: **Капт · МП · МШ · Тренировка · Другое**.'),
        ('03  /  ПОЛУЧИ БАЛЛЫ', 'High Staff проверит отчёт. В рейтинг попадают только подтверждённые активности.'),
        ('Быстрые команды', '`/profile` — твоя статистика\n`/activity_top` — рейтинг участников'),
    ], 0x7985B5)


def activity_type_label(value):
    return {'capt':'⚔️ Капт', 'mp':'🎯 МП', 'msh':'🛡️ МШ', 'training':'🏋️ Тренировка',
            'other':'📌 Другое', 'unclassified':'❔ Не выбран'}.get(value, value)
