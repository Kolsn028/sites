"""Repeatable server setup. Existing configured channels are never deleted."""
import discord
from .ui import base_embed, application_panel_embed, vacation_panel_embed, case_panel_embed
from .views import ApplicationPanelView, VacationPanelView, CasePanelView

from .roles import ROLE_SPECS, named_role, HIGH_KEYS
from .ui import application_banner_file
from .legacy import migrate_legacy
from .events import EVENTS, EventPanelView, event_panel
from .progression import ContractPanelView, PromotionPanelView, contract_panel_embed, promotion_panel_embed

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
        warnings = []
        candidates = {}
        for key, (name, color) in ROLE_SPECS.items():
            saved = guild.get_role(cfg.get(key) or 0)
            # Retain explicit choices after migration, otherwise resolve the requested hierarchy.
            role = selected.get(key) or (saved if cfg.get('role_schema_version') == 2 else None) or named_role(guild, key)
            if role and (role.is_default() or role.managed):
                raise ValueError('Выбери обычные роли сервера, не @everyone и не роли интеграций.')
            if role and key in ('main_role_id', 'accepted_role_id', 'colombo_role_id', 'vacation_role_id') and role >= me.top_role:
                raise ValueError(f'Подними роль бота выше роли «{role.name}».')
            candidates[key] = role
        ids = [r.id for r in candidates.values() if r]
        if len(ids) != len(set(ids)):
            raise ValueError('Каждой должности нужна отдельная роль. Leader и Recruit- нельзя назначить одной ролью.')
        for key, (name, color) in ROLE_SPECS.items():
            role = candidates[key]
            if role is None:
                role = await guild.create_role(name=name, colour=discord.Colour(color),
                                               permissions=discord.Permissions.none(), reason='Colombo: настройка')
            elif key in ('leader_role_id', 'dep_leader_role_id'):
                if role < me.top_role:
                    role = await role.edit(colour=discord.Colour(color), reason='Colombo: цвет ранга')
                elif role.colour.value != color:
                    warnings.append(f'Цвет {name} не изменён: роль выше бота.')
            roles[key] = role
            await bot.db.set_config(guild.id, **{key: role.id})
        await bot.db.set_config(guild.id, role_schema_version=2)
        warnings.extend(await migrate_legacy(guild, roles))
        ranked = [roles[k] for k in ROLE_SPECS if k != 'vacation_role_id']
        if all(r < me.top_role for r in ranked):
            positions = sorted([r.position for r in ranked], reverse=True)
            if len(set(positions)) == len(positions):
                await guild.edit_role_positions(positions=dict(zip(ranked, positions)), reason='Colombo: порядок рангов')


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
        leader = roles['leader_role_id']
        high = roles['high_staff_role_id']
        deputy = roles['dep_leader_role_id']
        leaders = [leader, deputy, high]
        staff = [*leaders, recruiter]
        family = [roles['accepted_role_id'], roles['main_role_id'], *staff]
        specs = [
            ('events_category_id', 'COLOMBO • ПЛЮСЫ МП', family, []),
            ('recruitment_category_id', 'COLOMBO • НАБОР', [guild.default_role], []),
            ('family_category_id', 'COLOMBO • СОСТАВ', family, []),
            ('management_category_id', 'COLOMBO • УПРАВЛЕНИЕ', staff, []),
            ('case_category_id', 'COLOMBO • ЛИЧНЫЕ ДЕЛА', staff, staff),
        ]
        cats = {}
        for key, name, audience, reviewers in specs:
            channel = guild.get_channel(cfg.get(key) or 0)
            if not isinstance(channel, discord.CategoryChannel):
                matches = [c for c in guild.categories if c.name == name]
                if len(matches) > 1:
                    raise ValueError(f'Несколько категорий {name}: сначала убери неоднозначность.')
                channel = matches[0] if matches else None
            if not isinstance(channel, discord.CategoryChannel):
                channel = await guild.create_category(name, overwrites=overwrites(audience, reviewers=reviewers), reason='Colombo: настройка')
                await bot.db.set_config(guild.id, **{key: channel.id})
            await bot.db.set_config(guild.id, **{key: channel.id})
            if channel.name == name:
                await channel.edit(overwrites=overwrites(audience, reviewers=reviewers), reason='Colombo: обновление доступа')
            cats[key] = channel

        channels = {}
        async def channel(key, name, cat, audience, reviewers=(), voice=False):
            ch = guild.get_channel(cfg.get(key) or 0)
            cls = discord.VoiceChannel if voice else discord.TextChannel
            if not isinstance(ch, cls):
                matches = [c for c in guild.channels if isinstance(c, cls) and
                           ((voice and c.name in ((name, 'Обзвон • Colombo') if key == 'interview_voice_channel_id' else (name,)) and c.category_id == cats[cat].id) or
                            (not voice and c.topic == f'Colombo • {key} • управляется ботом'))]
                if len(matches) > 1:
                    raise ValueError(f'Несколько каналов {name}: проверь дубликаты.')
                ch = matches[0] if matches else None
            if not isinstance(ch, cls):
                method = guild.create_voice_channel if voice else guild.create_text_channel
                kw = {} if voice else {'topic': f'Colombo • {key} • управляется ботом'}
                ch = await method(name, category=cats[cat], overwrites=overwrites(audience, reviewers=reviewers),
                                  reason='Colombo: настройка', **kw)
                await bot.db.set_config(guild.id, **{key: ch.id})
            elif not voice and ch.topic == f'Colombo • {key} • управляется ботом':
                await ch.edit(overwrites=overwrites(audience, reviewers=reviewers), reason='Colombo: обновление ролей')
            await bot.db.set_config(guild.id, **{key: ch.id})
            if key == 'interview_voice_channel_id' and ch.name == 'Обзвон • Colombo':
                await ch.edit(name='Обзвон 1 • Colombo', reason='Colombo: три канала обзвона')
            channels[key] = ch
            return ch

        await channel('application_panel_channel_id', '📩・заявка-в-семью', 'recruitment_category_id', [guild.default_role])
        await channel('applications_parent_channel_id', '📋・заявки-рекрутам', 'recruitment_category_id', [guild.default_role], staff)
        await channel('interview_channel_id', '📞・вызов-на-обзвон', 'recruitment_category_id', [guild.default_role])
        # Keep the original first channel; add two more without duplicating it on repeated setup.
        await channel('interview_voice_channel_id', 'Обзвон 1 • Colombo', 'recruitment_category_id', [guild.default_role], voice=True)
        await channel('interview_voice_2_id', 'Обзвон 2 • Colombo', 'recruitment_category_id', [guild.default_role], voice=True)
        await channel('interview_voice_3_id', 'Обзвон 3 • Colombo', 'recruitment_category_id', [guild.default_role], voice=True)
        await channel('case_panel_channel_id', '📁・личное-дело', 'family_category_id', family)
        await channel('vacation_panel_channel_id', '🌴・заявка-на-отдых', 'family_category_id', family)
        await channel('vacation_review_channel_id', '🗂・рассмотрение-отдыха', 'family_category_id', family, leaders)
        await channel('vacation_status_channel_id', '🗓・кто-в-отдыхе', 'family_category_id', family)
        await channel('leaderboard_channel_id', '🏆・рейтинг-рекрутеров', 'management_category_id', staff)
        await channel('applications_log_channel_id', '📥・журнал-заявок', 'management_category_id', staff)
        await channel('activity_log_channel_id', '📊・журнал-активности', 'management_category_id', staff)
        await channel('inactivity_report_channel_id', '📉・контроль-неактива', 'management_category_id', staff)

        await channel('contract_panel_channel_id', '🟠・активация-контрактов', 'family_category_id', family, staff)
        await channel('promotion_panel_channel_id', '😎・система-повышения', 'family_category_id', family, staff)

        for kind, (emoji, name, color) in EVENTS.items():
            await channel(f'{kind}_panel_channel_id', f'{emoji}・{name}', 'events_category_id', family)

        panels = [('application', application_panel_embed, ApplicationPanelView),
                  ('vacation', vacation_panel_embed, VacationPanelView),
                  ('case', case_panel_embed, CasePanelView),
                  ('contract', contract_panel_embed, ContractPanelView),
                  ('promotion', promotion_panel_embed, PromotionPanelView)]
        panels += [(kind, lambda k=kind: event_panel(k), EventPanelView) for kind in EVENTS]
        cfg = await bot.db.get_config(guild.id)
        for kind, make_embed, view in panels:
            ch = channels[f'{kind}_panel_channel_id']
            embed = make_embed()
            if bot.user and kind != 'application':
                embed.set_thumbnail(url=bot.user.display_avatar.url)
            message = None
            mid = cfg.get(f'{kind}_panel_message_id')
            if mid:
                try:
                    message = await ch.fetch_message(mid)
                except discord.NotFound:
                    pass
            if not message:
                custom_id = 'colombo:event:open' if kind in EVENTS else f'colombo:{kind}:open'
                async for old in ch.history(limit=100):
                    if old.author.id == bot.user.id and any(getattr(child, 'custom_id', None) == custom_id
                        for row in old.components for child in getattr(row, 'children', [])):
                        message = old
                        break
            if message and message.author.id == bot.user.id:
                kwargs = {'attachments': [application_banner_file()]} if kind == 'application' else {}
                await message.edit(embed=embed, view=view(bot), allowed_mentions=discord.AllowedMentions.none(), **kwargs)
            else:
                kwargs = {'file': application_banner_file()} if kind == 'application' else {}
                message = await ch.send(embed=embed, view=view(bot), allowed_mentions=discord.AllowedMentions.none(), **kwargs)
            await bot.db.set_config(guild.id, **{f'{kind}_panel_message_id': message.id})
        await bot.send_or_update_leaderboard(guild)
        await bot.update_vacation_status(guild)
        await bot.update_inactivity_report(guild)
        if not guild.chunked:
            await guild.chunk(cache=True)
        # Refresh staff access to existing personal cases without mentioning their owners.
        for case in cats['case_category_id'].text_channels:
            topic = case.topic or ''
            if not topic.startswith('Личное дело • owner='):
                continue
            raw_id = topic.partition('owner=')[2]
            if not raw_id.isdigit():
                continue
            owner = guild.get_member(int(raw_id))
            ow = overwrites(staff, write=True)
            if owner:
                ow[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                    read_message_history=True, attach_files=True, embed_links=True)
            await case.edit(overwrites=ow, reason='Colombo: доступ руководства к личному делу')
        # Existing open contract threads also need the newly authorized recruiters.
        contract_parent = channels['contract_panel_channel_id']
        for thread in guild.threads:
            if thread.parent_id in (contract_parent.id, channels['promotion_panel_channel_id'].id):
                for member in recruiter.members:
                    if not member.bot:
                        await thread.add_user(member)
        base_role = roles['colombo_role_id']
        for member in guild.members:
            if not member.bot and not member.get_role(base_role.id):
                try:
                    await member.add_roles(base_role, reason='Colombo: базовая роль участника')
                except discord.Forbidden:
                    warnings.append('Не всем участникам удалось выдать Colombo: проверь права бота.')
                    break
        # main is the next family rank, with exactly Novizio's permissions.
        fresh_roles = {r.id: r for r in await guild.fetch_roles()}
        novice = fresh_roles.get(roles['accepted_role_id'].id, roles['accepted_role_id'])
        main = fresh_roles.get(roles['main_role_id'].id, roles['main_role_id'])
        await main.edit(permissions=novice.permissions, colour=novice.colour,
                        reason='Colombo: main имеет права Novizio')
        if main.position <= novice.position:
            await main.edit(position=novice.position + 1, reason='Colombo: main выше Novizio')
        for ch in guild.channels:
            if novice in ch.overwrites:
                ow = dict(ch.overwrites)
                ow[main] = ch.overwrites_for(novice)
                await ch.edit(overwrites=ow, reason='Colombo: равный доступ main и Novizio')
        result = base_embed('Сервер готов • Colombo', 'Разделы и панели настроены. Повторный запуск обновляет эту структуру.')
        result.add_field(name='Начало работы', value='\n'.join(channels[f'{kind}_panel_channel_id'].mention for kind in ('application', 'vacation', 'case')), inline=False)
        result.add_field(name='Роли', value='\n'.join(f'{name}: {roles[key].mention}' for key, (name, _) in ROLE_SPECS.items()), inline=False)
        result.add_field(name='Следующий шаг', value='Выдай роли нужным участникам. Чтобы использовать свои роли, повтори `/setup` и выбери их в параметрах. Права каналов, созданных ботом, обновляются автоматически. Права подключённых вручную каналов проверь отдельно.', inline=False)
        if warnings:
            result.add_field(name='Проверь', value='\n'.join(warnings)[:1024], inline=False)
        await bot.db.set_config(guild.id, server_layout_version=8)
        return result
