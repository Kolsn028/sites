import os
from pathlib import Path
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


def application_banner_file():
    return discord.File(Path(__file__).resolve().parent.parent / 'assets' / 'colombo-banner.png', filename='colombo-banner.png')


def application_panel_embed():
    e = base_embed('Вступить в COLOMBO',
        'Заполни короткую анкету — рекрутер рассмотрит её в приватной ветке.\n'
        'После принятия получишь роль **-Novizio-**.\n\n'
        '**Готов? Нажми «Подать заявку».**')
    e.set_image(url='attachment://colombo-banner.png')
    return e


def vacation_panel_embed():
    return panel('ВРЕМЯ НА ОТДЫХ', 'Нужна пауза? Предупреди руководство — сохрани порядок в составе.', [
        ('01  /  ОСТАВЬ ЗАЯВКУ', 'Укажи причину и срок: **от 1 до 60 дней**.'),
        ('02  /  ДОЖДИСЬ РЕШЕНИЯ', 'Бот создаст отдельную приватную ветку для тебя и руководства.'),
        ('03  /  ВОЗВРАЩАЙСЯ В СТРОЙ', 'Роли до Recruit- включительно временно снимаются, -Novizio- и старшие роли остаются. Для возврата нажми «Вернуться из отпуска»: причина и комментарий, затем одобрение Ass.Deputy и выше.'),
    ], 0xC69B59)


def case_panel_embed():
    return panel('ТВОЁ ЛИЧНОЕ ДЕЛО', 'Вся активность участника — в одном месте.', [
        ('01  /  ОТКРОЙ ДЕЛО', 'Кнопка создаст приватный канал или откроет уже существующий.'),
        ('02  /  ДОБАВЬ ОТЧЁТ', 'Отправь скриншот или видео и выбери тип: **Капт · MCL · VZM · VZZ · Контракт · Другое**.'),
        ('03  /  ОТКРОЙ КАРТОЧКУ', 'Разделы MCL, VZM, VZZ, капты и контракты. Фильтры по неделе, месяцу и всему времени; история со ссылками на источники. Посещения подтверждает создатель МП или Leader / Deputy Leader.'),
        ('Быстрые команды', '`/profile` — твоя статистика\n`/activity_top` — рейтинг участников'),
    ], 0x7985B5)


def activity_type_label(value):
    return {'capt':'⚔️ Капт', 'mp':'🎯 МП', 'msh':'🛡️ МШ', 'training':'🏋️ Тренировка',
            'mcl':'🟥 MCL', 'vzm':'🟩 VZM', 'vzz':'🟦 VZZ', 'contract':'🟠 Контракт', 'other':'📌 Другое', 'unclassified':'❔ Не выбран'}.get(value, value)
