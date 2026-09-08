from __future__ import annotations
from datetime import datetime
import discord
from discord import app_commands
from .ui import application_panel_embed,vacation_panel_embed,case_panel_embed,base_embed,activity_type_label
from .views import ApplicationPanelView,VacationPanelView,CasePanelView


def admin_only():
    async def pred(i):
        if isinstance(i.user,discord.Member) and i.user.guild_permissions.administrator: return True
        raise app_commands.CheckFailure
    return app_commands.check(pred)


def register_commands(bot):
    @bot.tree.command(name="setup_auto", description="Создать каналы, роли и панели Colombo автоматически")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @admin_only()
    async def setup_auto(i: discord.Interaction, recruiter: discord.Role | None = None,
                         high_staff: discord.Role | None = None, family: discord.Role | None = None,
                         assistant: discord.Role | None = None, deputy: discord.Role | None = None,
                         vacation: discord.Role | None = None):
        await i.response.defer(ephemeral=True, thinking=True)
        from .provisioning import provision
        try:
            embed = await provision(bot, i.guild, dict(recruiter_role_id=recruiter,
                high_staff_role_id=high_staff, accepted_role_id=family,
                assistant_leader_role_id=assistant, dep_leader_role_id=deputy, vacation_role_id=vacation))
            await i.followup.send(embed=embed, ephemeral=True)
        except ValueError as exc:
            await i.followup.send(str(exc), ephemeral=True)
        except discord.Forbidden:
            await i.followup.send("Не хватает прав в одном из каналов. Проверь права и положение роли бота; затем повтори `/setup_auto`. Уже созданные разделы сохранятся.", ephemeral=True)


    @bot.tree.command(name="setup",description="Полная настройка Colombo Bot")
    @admin_only()
    async def setup(i:discord.Interaction,
        applications_parent:discord.TextChannel, applications_log:discord.TextChannel,
        recruiter_role:discord.Role, interview_text:discord.TextChannel, interview_voice:discord.VoiceChannel,
        accepted_role:discord.Role, vacation_review:discord.TextChannel, vacation_status:discord.TextChannel,
        assistant_leader_role:discord.Role, dep_leader_role:discord.Role, vacation_role:discord.Role,
        leaderboard_channel:discord.TextChannel, case_category:discord.CategoryChannel,
        high_staff_role:discord.Role, activity_log:discord.TextChannel, inactivity_report:discord.TextChannel):
        await bot.db.set_config(i.guild.id,
            applications_parent_channel_id=applications_parent.id, applications_log_channel_id=applications_log.id,
            recruiter_role_id=recruiter_role.id, interview_channel_id=interview_text.id, interview_voice_channel_id=interview_voice.id,
            accepted_role_id=accepted_role.id, vacation_review_channel_id=vacation_review.id, vacation_status_channel_id=vacation_status.id,
            assistant_leader_role_id=assistant_leader_role.id, dep_leader_role_id=dep_leader_role.id, vacation_role_id=vacation_role.id,
            leaderboard_channel_id=leaderboard_channel.id, case_category_id=case_category.id, high_staff_role_id=high_staff_role.id,
            activity_log_channel_id=activity_log.id, inactivity_report_channel_id=inactivity_report.id)
        await i.response.send_message(embed=base_embed("✅ Система настроена",f"Заявки: {applications_parent.mention} → {applications_log.mention}\nРекрутеры: {recruiter_role.mention}\nОбзвон: {interview_text.mention} / {interview_voice.mention}\nОтпуска: {vacation_review.mention} → {vacation_status.mention}\nЛичные дела: **{case_category.name}**\nHigh Staff: {high_staff_role.mention}\nЛог активности: {activity_log.mention}\nКонтроль неактива: {inactivity_report.mention}",0x3BAA72),ephemeral=True)

    @bot.tree.command(name="panel_application",description="Отправить панель подачи заявки")
    @admin_only()
    async def panel_application(i:discord.Interaction,channel:discord.TextChannel):
        m=await channel.send(embed=application_panel_embed(),view=ApplicationPanelView(bot)); await bot.db.set_config(i.guild.id,application_panel_channel_id=channel.id,application_panel_message_id=m.id); await i.response.send_message(f"✅ {m.jump_url}",ephemeral=True)

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
        if i.user.id!=member.id and not await bot.is_high_staff(i.user): return await i.response.send_message("⛔ Чужое дело может создавать только High Staff.",ephemeral=True)
        cfg = await bot.db.get_config(i.guild.id)
        accepted = cfg.get("accepted_role_id")
        if accepted and not member.get_role(accepted) and not i.user.guild_permissions.administrator:
            return await i.response.send_message("Личное дело доступно участникам семьи.", ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True); ch=await bot.ensure_personal_case(member)
        await i.followup.send(f"📁 Личное дело: {ch.mention}" if ch else "⚠️ Проверь `/setup` и права Manage Channels.",ephemeral=True)

    @bot.tree.command(name="profile",description="Карточка активности участника")
    async def profile(i:discord.Interaction,member:discord.Member|None=None):
        member=member or i.user; r30,last=await bot.db.member_activity_stats(i.guild.id,member.id,30); rall,_=await bot.db.member_activity_stats(i.guild.id,member.id,None)
        p30=sum(x['points'] for x in r30); n30=sum(x['count'] for x in r30); pall=sum(x['points'] for x in rall); nall=sum(x['count'] for x in rall)
        details='\n'.join(f"{activity_type_label(x['category'])}: **{x['count']}** · {x['points']} б." for x in r30) or "Нет подтверждённых отчётов за 30 дней."
        last_text=datetime.fromisoformat(last['created_at']).strftime('%d.%m.%Y %H:%M') if last else 'нет'; case=await bot.db.get_case_by_member(i.guild.id,member.id); case_text=f"<#{case['channel_id']}>" if case else 'не создано'
        e=base_embed(f"📊 Профиль активности • {member.display_name}",f"Участник: {member.mention}\nЛичное дело: {case_text}\nПоследняя активность: **{last_text}**",0x6E56CF); e.set_thumbnail(url=member.display_avatar.url); e.add_field(name="Последние 30 дней",value=f"**{n30}** отчётов · **{p30}** баллов\n\n{details}",inline=False); e.add_field(name="За всё время",value=f"**{nall}** отчётов · **{pall}** баллов",inline=False); await i.response.send_message(embed=e)

    @bot.tree.command(name="activity_top",description="Топ активности участников")
    async def activity_top(i:discord.Interaction,days:app_commands.Range[int,1,90]=7):
        rows=await bot.db.activity_top(i.guild.id,days,10); medals=['🥇','🥈','🥉']; lines=[f"{medals[n] if n<3 else f'`#{n+1}`'} <@{r['member_id']}> — **{r['points']} б.** · {r['reports']} отч." for n,r in enumerate(rows)]; await i.response.send_message(embed=base_embed(f"🔥 Топ активности • {days} дн.",'\n'.join(lines) if lines else 'Пока нет подтверждённой активности.',0xE5B64B))

    @bot.tree.command(name="inactive",description="Показать участников без активности")
    async def inactive(i:discord.Interaction,days:app_commands.Range[int,1,60]=3):
        if not isinstance(i.user,discord.Member) or not await bot.is_high_staff(i.user): return await i.response.send_message("⛔ Только High Staff.",ephemeral=True)
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
        for name,key in [('Рекрутеры','recruiter_role_id'),('Принятые','accepted_role_id'),('High Staff','high_staff_role_id'),('Assistant GP Leader','assistant_leader_role_id'),('Dep Leader','dep_leader_role_id'),('В отпуске','vacation_role_id')]: lines.append(f"**{name}:** {f'<@&{c.get(key)}>' if c.get(key) else '—'}")
        cat=i.guild.get_channel(c.get('case_category_id') or 0); lines.append(f"**Категория дел:** {cat.name if cat else '—'}"); await i.response.send_message(embed=base_embed("⚙️ Конфигурация",'\n'.join(lines)),ephemeral=True)

    for command in bot.tree.get_commands():
        command.guild_only = True

    @bot.tree.error
    async def on_error(i,error):
        print('App command error:',repr(error)); text='⛔ Нужны права администратора.' if isinstance(error,app_commands.CheckFailure) else '⚠️ Произошла ошибка. Проверь права и `/setup`.'
        try:
            if i.response.is_done(): await i.followup.send(text,ephemeral=True)
            else: await i.response.send_message(text,ephemeral=True)
        except discord.DiscordException: pass

