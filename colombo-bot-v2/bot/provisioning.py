"""Repeatable server setup. Existing configured channels are never deleted."""
import discord
from .ui import base_embed, application_panel_embed, vacation_panel_embed, case_panel_embed
from .views import ApplicationPanelView, VacationPanelView, CasePanelView

ROLE_SPECS = {
    'recruiter_role_id': ('Colombo • Recruiter', 0xBA3444),
    'high_staff_role_id': ('Colombo • High Staff', 0xD5AD65),
    'accepted_role_id': ('Colombo • Family', 0x8E98A6),
    'assistant_leader_role_id': ('Colombo • Assistant Leader', 0xC78B54),
    'dep_leader_role_id': ('Colombo • Dep Leader', 0xBC7650),
    'vacation_role_id': ('Colombo • Отдых', 0x5BAE96),
}

async def provision(bot, guild, selected):
    async with bot.operation_locks[('setup', guild.id)]:
        me = guild.me
        required = ('manage_channels', 'manage_roles', 'create_private_threads', 'manage_threads',
                    'send_messages', 'send_messages_in_threads', 'embed_links', 'read_message_history')
        missing = [p for p in required if not getattr(me.guild_permissions, p)]
        if missing:
            raise ValueError('Боту не хватает прав: ' + ', '.join(missing))
        cfg = await bot.db.get_config(guild.id)
        roles = {}
        for key, (name, color) in ROLE_SPECS.items():
            role = selected.get(key) or guild.get_role(cfg.get(key) or 0)
            if role and (role.is_default() or role.managed):
                raise ValueError('Выбери обычные роли сервера, не @everyone и не роли интеграций.')
            if role and key in ('accepted_role_id', 'vacation_role_id') and role >= me.top_role:
                raise ValueError(f'Подними роль бота выше роли «{role.name}».')
            if role is None:
                # Reuse only a role previously created by this bot's setup, via saved ID.
                role = await guild.create_role(name=name, colour=discord.Colour(color),
                                               permissions=discord.Permissions.none(), reason='Colombo: настройка')
            roles[key] = role
            await bot.db.set_config(guild.id, **{key: role.id})

        def overwrites(audience, write=False, reviewers=()):
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                      attach_files=True, read_message_history=True, manage_channels=True, manage_threads=True,
                      create_private_threads=True, send_messages_in_threads=True)}
            for role in audience:
                ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=write,
                    read_message_history=True, send_messages_in_threads=True, attach_files=True,
                    create_public_threads=False, create_private_threads=False)
            for role in reviewers:
                ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                    read_message_history=True, send_messages_in_threads=True, attach_files=True,
                    manage_threads=True)
            return ow

        recruiter = roles['recruiter_role_id']
        high = roles['high_staff_role_id']
        leaders = [roles['assistant_leader_role_id'], roles['dep_leader_role_id']]
        family = [roles['accepted_role_id'], high, recruiter, *leaders]
        specs = [
            ('recruitment_category_id', 'COLOMBO • НАБОР', [guild.default_role], []),
            ('family_category_id', 'COLOMBO • СОСТАВ', family, []),
            ('management_category_id', 'COLOMBO • УПРАВЛЕНИЕ', [high, recruiter, *leaders], []),
            ('case_category_id', 'COLOMBO • ЛИЧНЫЕ ДЕЛА', [high], [high]),
        ]
        cats = {}
        for key, name, audience, reviewers in specs:
            channel = guild.get_channel(cfg.get(key) or 0)
            if not isinstance(channel, discord.CategoryChannel):
                channel = await guild.create_category(name, overwrites=overwrites(audience, reviewers=reviewers), reason='Colombo: настройка')
                await bot.db.set_config(guild.id, **{key: channel.id})
            cats[key] = channel

        channels = {}
        async def channel(key, name, cat, audience, reviewers=(), voice=False):
            ch = guild.get_channel(cfg.get(key) or 0)
            cls = discord.VoiceChannel if voice else discord.TextChannel
            if not isinstance(ch, cls):
                method = guild.create_voice_channel if voice else guild.create_text_channel
                kw = {} if voice else {'topic': f'Colombo • {key} • управляется ботом'}
                ch = await method(name, category=cats[cat], overwrites=overwrites(audience, reviewers=reviewers),
                                  reason='Colombo: настройка', **kw)
                await bot.db.set_config(guild.id, **{key: ch.id})
            elif not voice and ch.topic == f'Colombo • {key} • управляется ботом':
                await ch.edit(overwrites=overwrites(audience, reviewers=reviewers), reason='Colombo: обновление ролей')
            channels[key] = ch
            return ch

        await channel('application_panel_channel_id', '📩・заявка-в-семью', 'recruitment_category_id', [guild.default_role])
        await channel('applications_parent_channel_id', '📋・заявки-рекрутам', 'recruitment_category_id', [guild.default_role], [recruiter, high])
        await channel('interview_channel_id', '📞・вызов-на-обзвон', 'recruitment_category_id', [guild.default_role])
        await channel('interview_voice_channel_id', 'Обзвон • Colombo', 'recruitment_category_id', [guild.default_role], voice=True)
        await channel('case_panel_channel_id', '📁・личное-дело', 'family_category_id', family)
        await channel('vacation_panel_channel_id', '🌴・заявка-на-отдых', 'family_category_id', family)
        await channel('vacation_review_channel_id', '🗂・рассмотрение-отдыха', 'family_category_id', family, leaders)
        await channel('vacation_status_channel_id', '🗓・кто-в-отдыхе', 'family_category_id', family)
        await channel('leaderboard_channel_id', '🏆・рейтинг-рекрутеров', 'management_category_id', [recruiter, high, *leaders])
        await channel('applications_log_channel_id', '📥・журнал-заявок', 'management_category_id', [recruiter, high])
        await channel('activity_log_channel_id', '📊・журнал-активности', 'management_category_id', [high])
        await channel('inactivity_report_channel_id', '📉・контроль-неактива', 'management_category_id', [high])

        panels = [('application', application_panel_embed, ApplicationPanelView),
                  ('vacation', vacation_panel_embed, VacationPanelView),
                  ('case', case_panel_embed, CasePanelView)]
        cfg = await bot.db.get_config(guild.id)
        for kind, make_embed, view in panels:
            ch = channels[f'{kind}_panel_channel_id']
            embed = make_embed()
            if bot.user:
                embed.set_thumbnail(url=bot.user.display_avatar.url)
            message = None
            mid = cfg.get(f'{kind}_panel_message_id')
            if mid:
                try:
                    message = await ch.fetch_message(mid)
                except discord.NotFound:
                    pass
            if message and message.author.id == bot.user.id:
                await message.edit(embed=embed, view=view(bot))
            else:
                message = await ch.send(embed=embed, view=view(bot))
            await bot.db.set_config(guild.id, **{f'{kind}_panel_message_id': message.id})
        await bot.send_or_update_leaderboard(guild)
        await bot.update_vacation_status(guild)
        await bot.update_inactivity_report(guild)
        result = base_embed('Сервер готов • Colombo', 'Разделы и панели настроены. Повторный запуск обновляет эту структуру.')
        result.add_field(name='Начало работы', value='\n'.join(channels[f'{kind}_panel_channel_id'].mention for kind in ('application', 'vacation', 'case')), inline=False)
        result.add_field(name='Роли', value='\n'.join(f'{name}: {roles[key].mention}' for key, (name, _) in ROLE_SPECS.items()), inline=False)
        result.add_field(name='Следующий шаг', value='Выдай роли нужным участникам. Чтобы использовать свои роли, повтори `/setup_auto` и выбери их в параметрах. Права каналов, созданных ботом, обновляются автоматически. Права подключённых вручную каналов проверь отдельно.', inline=False)
        return result
