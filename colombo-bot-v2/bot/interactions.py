import functools
import logging
import discord

log = logging.getLogger(__name__)

async def report_error(interaction, error):
    log.error('Discord interaction failed', exc_info=(type(error), error, error.__traceback__))
    if isinstance(error, discord.Forbidden):
        message = 'Не хватает прав. Нужны просмотр канала, отправка сообщений, создание приватных веток и управление ветками. Проверь также положение роли бота.'
    elif isinstance(error, ValueError):
        message = str(error)
    else:
        message = 'Не удалось завершить действие. Администратор может проверить журнал бота и настройки `/setup_auto`.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction, error):
        await report_error(interaction, error)

class SafeView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


def serialized(kind, by_user=False):
    def decorate(func):
        @functools.wraps(func)
        async def wrapped(self, interaction, *args, **kwargs):
            target = interaction.user.id if by_user else interaction.channel_id
            async with self.bot.operation_locks[(kind, interaction.guild_id, target)]:
                return await func(self, interaction, *args, **kwargs)
        return wrapped
    return decorate

async def private_thread(parent, member, roles, name):
    """No public anchor: application text stays inside the private thread."""
    perms = parent.permissions_for(parent.guild.me)
    required = ('view_channel', 'send_messages', 'create_private_threads', 'manage_threads',
                'send_messages_in_threads', 'read_message_history', 'embed_links')
    if any(not getattr(perms, key) for key in required):
        raise ValueError('Проверь права бота в канале заявок: просмотр, сообщения, Embed Links, история, создание приватных веток и управление ветками.')
    if not parent.permissions_for(member).view_channel:
        raise ValueError('У участника нет доступа к родительскому каналу заявок. Администратор должен открыть просмотр этого канала; сами заявки останутся в приватных ветках.')
    if not parent.guild.chunked:
        await parent.guild.chunk(cache=True)
    thread = await parent.create_thread(name=name[:100], type=discord.ChannelType.private_thread,
                                       invitable=False, auto_archive_duration=1440, reason='Colombo: приватная заявка')
    try:
        await thread.add_user(member)
        reviewers = {m.id: m for role in roles if role for m in role.members if not m.bot}
        for reviewer in reviewers.values():
            if reviewer.id != member.id:
                await thread.add_user(reviewer)
    except Exception:
        # Only remove the empty thread from this failed attempt.
        await thread.delete(reason='Colombo: не удалось добавить участников')
        raise
    return thread
