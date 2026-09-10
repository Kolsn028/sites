from __future__ import annotations
from datetime import datetime
import discord
from discord import app_commands
from .ui import application_panel_embed,vacation_panel_embed,case_panel_embed,base_embed,activity_type_label,application_banner_file
from .views import ApplicationPanelView,VacationPanelView,CasePanelView


def admin_only():
    async def pred(i):
        if isinstance(i.user,discord.Member) and await i.client.can_manage(i.user): return True
        raise app_commands.CheckFailure
    return app_commands.check(pred)


def register_commands(bot):
    @app_commands.guild_only()
    @admin_only()
    @app_commands.describe(leader="Leader — красный, полное управление без упоминаний",
        deputy="Deputy Leader — отчёты, отдых, назначение рекрутов", ass_deputy="Ass.Deputy — отчёты, повышения, отдых, рекруты",
        recruit="Recruit- — заявки и приём", novizio="-Novizio- — роль после приёма",
        colombo="Colombo — роль всем вошедшим", vacation="Служебная роль на период отдыха")
    async def setup(i: discord.Interaction, leader: discord.Role | None = None,
                    deputy: discord.Role | None = None, ass_deputy: discord.Role | None = None,
                    recruit: discord.Role | None = None, novizio: discord.Role | None = None,
                    colombo: discord.Role | None = None, vacation: discord.Role | None = None):
        await i.response.defer(ephemeral=True, thinking=True)
        from .provisioning import provision
        try:
            embed = await provision(bot, i.guild, dict(leader_role_id=leader, dep_leader_role_id=deputy,
                high_staff_role_id=ass_deputy, recruiter_role_id=recruit, accepted_role_id=novizio,
                colombo_role_id=colombo, vacation_role_id=vacation))
            await i.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:
            await i.followup.send(str(exc), ephemeral=True)
        except discord.Forbidden:
            await i.followup.send("Проверь права бота и положение его роли. Затем повтори /setup — готовые каналы сохранятся.", ephemeral=True)

    bot.tree.command(name="setup", description="Роли Colombo, каналы и панели")(setup)
    bot.tree.command(name="setup_auto", description="Автоматическая настройка ролей и каналов Colombo")(setup)

    @bot.tree.command(name="panel_application",description="Отправить панель подачи заявки")
    @admin_only()
    async def panel_application(i:discord.Interaction,channel:discord.TextChannel):
        await i.response.defer(ephemeral=True); m=await channel.send(embed=application_panel_embed(),view=ApplicationPanelView(bot),file=application_banner_file(),allowed_mentions=discord.AllowedMentions.none()); await bot.db.set_config(i.guild.id,application_panel_channel_id=channel.id,application_panel_message_id=m.id); await i.followup.send(f"✅ {m.jump_url}",ephemeral=True)

    @bot.tree.command(name="panel_vacation",description="Отправить панель отдыха")
    @admin_only()
    async def panel_vacation(i:discord.Interaction,channel:discord.TextChannel):
        m=await channel.send(embed=vacation_panel_embed(),view=VacationPanelView(bot)); await bot.db.set_config(i.guild.id,vacation_panel_channel_id=channel.id,vacation_panel_message_id=m.id); await i.response.send_message(f"✅ {m.jump_url}",ephemeral=True)

    @bot.tree.command(name="panel_case",description="Отправить панель личных дел")
    @admin_only()
    async def panel_case(i:discord.Interaction,channel:discord.TextChannel):
        m=await channel.send(embed=case_panel_embed(),view=CasePanelView(bot)); await bot.db.set_config(i.guild.id,case_panel_channel_id=channel.id,case_panel_message_id=m.id); await i.response.send_message(f"✅ {m.jump_url}",ephemeral=True)

    @bot.tree.command(name="case_create",description="Создать/открыть личное дело участника")
    async def case_create(i:discord.Interaction,member:discord.Member):
        if not isinstance(i.user,discord.Member): return
        if i.user.id!=member.id and not await bot.is_high_staff(i.user): return await i.response.send_message("⛔ Чужое дело может создавать Recruit-, Ass.Deputy или Deputy Leader.",ephemeral=True)
        cfg = await bot.db.get_config(i.guild.id)
        accepted = cfg.get("accepted_role_id")
        if not await bot.is_family_member(member) and not await bot.can_manage(i.user):
            return await i.response.send_message("Личное дело доступно участникам семьи.", ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True); ch=await bot.ensure_personal_case(member)
        await i.followup.send(f"📁 Личное дело: {ch.mention}" if ch else "⚠️ Проверь `/setup` и права Manage Channels.",ephemeral=True)

    @bot.tree.command(name="profile",description="Карточка активности участника")
    async def profile(i:discord.Interaction,member:discord.Member|None=None):
        from .profiles import open_profile
        await open_profile(bot,i,(member or i.user).id)

    @bot.tree.command(name="activity_top",description="Топ активности участников")
    async def activity_top(i:discord.Interaction,days:app_commands.Range[int,1,90]=7):
        rows=await bot.db.activity_top(i.guild.id,days,10); medals=['🥇','🥈','🥉']; lines=[f"{medals[n] if n<3 else f'`#{n+1}`'} <@{r['member_id']}> — **{r['points']} б.** · {r['reports']} отч." for n,r in enumerate(rows)]; await i.response.send_message(embed=base_embed(f"🔥 Топ активности • {days} дн.",'\n'.join(lines) if lines else 'Пока нет подтверждённой активности.',0xE5B64B))

    @bot.tree.command(name="inactive",description="Показать участников без активности")
    async def inactive(i:discord.Interaction,days:app_commands.Range[int,1,60]=3):
        if not isinstance(i.user,discord.Member) or not await bot.is_high_staff(i.user): return await i.response.send_message("⛔ Только Recruit-, Ass.Deputy или Deputy Leader.",ephemeral=True)
        rows=await bot.inactive_members(i.guild,days); lines=[f"⚠️ {m.mention} — **{d} дн.**" for m,d,_ in rows[:30]]; await i.response.send_message(embed=base_embed(f"📉 Неактив • {days}+ дней",'\n'.join(lines) if lines else '✅ Таких участников нет.',0xD64045 if lines else 0x3BAA72),ephemeral=True)

    @bot.tree.command(name="leaderboard",description="Лидерборд рекрутеров")
    async def leaderboard(i:discord.Interaction):
        rows=await bot.db.leaderboard(i.guild.id,10); medals=['🥇','🥈','🥉']; lines=[f"{medals[n] if n<3 else f'`#{n+1}`'} <@{r['recruiter_id']}> — **{r['accepted_count']}** принято" for n,r in enumerate(rows)]; await i.response.send_message(embed=base_embed("🏆 Лидерборд рекрутеров",'\n'.join(lines) if lines else 'Пока нет данных.',0xE5B64B))

    @bot.tree.command(name="leaderboard_post",description="Создать/обновить постоянный лидерборд")
    @admin_only()
    async def leaderboard_post(i):
        await i.response.defer(ephemeral=True); m=await bot.send_or_update_leaderboard(i.guild); await i.followup.send(f"✅ {m.jump_url}" if m else "⚠️ Канал не настроен.",ephemeral=True)

    @bot.tree.command(name="vacation_status_post",description="Создать/обновить статус отпусков")
    @admin_only()
    async def vacation_status_post(i):
        await i.response.defer(ephemeral=True); m=await bot.update_vacation_status(i.guild); await i.followup.send(f"✅ {m.jump_url}" if m else "⚠️ Канал не настроен.",ephemeral=True)

    @bot.tree.command(name="inactivity_post",description="Создать/обновить контроль неактива")
    @admin_only()
    async def inactivity_post(i):
        await i.response.defer(ephemeral=True); m=await bot.update_inactivity_report(i.guild); await i.followup.send(f"✅ {m.jump_url}" if m else "⚠️ Канал не настроен.",ephemeral=True)

    @bot.tree.command(name="config_show",description="Показать конфигурацию")
    @admin_only()
    async def config_show(i):
        c=await bot.db.get_config(i.guild.id); lines=[]
        for name,key in [('Ветки заявок','applications_parent_channel_id'),('Лог заявок','applications_log_channel_id'),('Обзвон','interview_channel_id'),('Отпуска','vacation_review_channel_id'),('Статус отпусков','vacation_status_channel_id'),('Лидерборд','leaderboard_channel_id'),('Лог активности','activity_log_channel_id'),('Контроль неактива','inactivity_report_channel_id')]: lines.append(f"**{name}:** {f'<#{c.get(key)}>' if c.get(key) else '—'}")
        for name,key in [('Recruit-','recruiter_role_id'),('-Novizio-','accepted_role_id'),('main — 3 ранг','main_role_id'),('Leader','leader_role_id'),('Deputy Leader','dep_leader_role_id'),('Ass.Deputy','high_staff_role_id'),('Colombo','colombo_role_id'),('В отпуске','vacation_role_id')]: lines.append(f"**{name}:** {f'<@&{c.get(key)}>' if c.get(key) else '—'}")
        cat=i.guild.get_channel(c.get('case_category_id') or 0); lines.append(f"**Категория дел:** {cat.name if cat else '—'}"); await i.response.send_message(embed=base_embed("⚙️ Конфигурация",'\n'.join(lines)),ephemeral=True)

    @bot.tree.command(name="recruiter_assign", description="Назначить Recruit-: Ass.Deputy или Deputy Leader")
    async def recruiter_assign(i: discord.Interaction, member: discord.Member):
        if not isinstance(i.user, discord.Member) or not await bot.can_assign_recruiter(i.user):
            return await i.response.send_message("Назначают Ass.Deputy, Deputy Leader и Leader.", ephemeral=True)
        if member.bot:
            return await i.response.send_message("Выбери участника, а не бота.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        cfg = await bot.db.get_config(i.guild_id)
        role = i.guild.get_role(cfg.get('recruiter_role_id') or 0)
        if not role or role.managed or role >= i.guild.me.top_role:
            return await i.followup.send("Проверь роль Recruit- и положение роли бота.", ephemeral=True)
        await member.add_roles(role, reason=f"Colombo: назначение рекрута участником {i.user.id}")
        await i.followup.send(f"Роль Recruit- выдана {member.mention}.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name="report_event",description="Связать отчёт со сбором: Recruit- и выше")
    async def report_event(i:discord.Interaction,report_id:int,event_id:int):
        if not isinstance(i.user,discord.Member) or not await bot.is_high_staff(i.user):
            return await i.response.send_message('Только Recruit- и выше.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with bot.db.lock:
            report=await bot.db.get_activity(report_id)
            event=await bot.db._one('SELECT * FROM family_events WHERE id=? AND guild_id=?',(event_id,i.guild_id))
            if not report or report['guild_id']!=i.guild_id or not event:
                return await i.followup.send('Отчёт или сбор не найден на этом сервере.',ephemeral=True)
            participation=await bot.db._one('SELECT 1 FROM event_signups WHERE event_id=? AND member_id=?',(event_id,report['member_id']))
            if not participation:
                return await i.followup.send('Автор отчёта не записан в этот сбор.',ephemeral=True)
            await bot.db.conn.execute('UPDATE activity_submissions SET event_id=?,category=? WHERE id=?',(event_id,event['kind'],report_id))
            from .roster import audit
            await audit(bot.db,i.guild_id,i.user.id,'report_event',report_id,{'event':event_id})
            await bot.db.conn.commit()
        from .profiles import refresh_member
        await refresh_member(bot,i.guild,report['member_id'])
        await i.followup.send('Отчёт связан со сбором. Подтверждение посещения остаётся за организатором.',ephemeral=True)

    for command in bot.tree.get_commands():
        command.guild_only = True

    @bot.tree.error
    async def on_error(i,error):
        print('App command error:',repr(error)); text='⛔ Нужна роль Leader, Deputy Leader или права администратора.' if isinstance(error,app_commands.CheckFailure) else '⚠️ Произошла ошибка. Проверь права и `/setup`.'
        try:
            if i.response.is_done(): await i.followup.send(text,ephemeral=True)
            else: await i.response.send_message(text,ephemeral=True)
        except discord.DiscordException: pass

