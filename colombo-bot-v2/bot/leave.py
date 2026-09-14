"""Resumable leave transitions. Persist snapshots before touching Discord roles."""
import json
import discord
from .roles import HIGH_KEYS, configured_roles, notify_assistants
from .interactions import SafeModal, SafeView, private_thread
from .ui import base_embed


def removable_roles(member, cfg):
    guild = member.guild
    recruit = guild.get_role(cfg.get('recruiter_role_id') or 0)
    if not recruit:
        raise ValueError('Не настроена роль Recruit-.')
    protected = {cfg.get(k) for k in HIGH_KEYS + ('accepted_role_id', 'vacation_role_id')}
    return [r for r in member.roles if not r.is_default() and not r.managed
            and r.id not in protected and r <= recruit]


async def begin_leave(bot, guild, vac):
    member = await guild.fetch_member(vac['member_id'])
    cfg = await bot.db.get_config(guild.id)
    if vac.get('role_snapshot') is None:
        leave = guild.get_role(cfg.get('vacation_role_id') or 0)
        if not leave or leave.managed or leave.is_default() or leave >= guild.me.top_role:
            raise ValueError('Проверь роль Отдых и подними роль бота выше неё.')
        # Persist the exact leave role before Discord writes, so retries and a
        # later /setup change cannot remove a different role on return.
        marker = {'mode': 'role_only', 'leave_role_id': leave.id}
        await bot.db.update_vacation(vac['id'], role_snapshot=json.dumps(marker),
            added_novice=0, status='applying', updated_at=bot.now_iso())
        vac = await bot.db.get_vacation(vac['id'])
    snapshot = json.loads(vac['role_snapshot'])
    role_id = snapshot['leave_role_id'] if isinstance(snapshot, dict) and snapshot.get('mode') == 'role_only' else cfg.get('vacation_role_id')
    leave = guild.get_role(role_id or 0)
    if not leave or leave.managed or leave.is_default() or leave >= guild.me.top_role:
        raise ValueError('Проверь роль Отдых и подними роль бота выше неё.')
    # Legacy snapshots are retained for eventual restoration; never remove
    # additional roles, even when retrying an old partially approved leave.
    await member.add_roles(leave, reason='Colombo: одобрен отдых')
    await bot.db.update_vacation(vac['id'], status='approved', updated_at=bot.now_iso())


async def restore_leave(bot, guild, vac):
    if vac.get('role_snapshot') is None:
        raise ValueError('Снимок ролей отсутствует. Руководству нужно вручную проверить ранее снятые роли; они не будут угаданы.')
    member = await guild.fetch_member(vac['member_id'])
    cfg = await bot.db.get_config(guild.id)
    snapshot = json.loads(vac['role_snapshot'])
    if isinstance(snapshot, dict):
        if snapshot.get('mode') != 'role_only':
            raise ValueError('Неизвестный формат отпуска. Нужна проверка руководства.')
        leave = guild.get_role(snapshot['leave_role_id'])
        if leave and (leave.managed or leave.is_default() or leave >= guild.me.top_role):
            raise ValueError('Проверь положение роли бота относительно Отдых.')
        await bot.db.update_vacation(vac['id'], status='restoring', updated_at=bot.now_iso())
        if leave:
            await member.remove_roles(leave, reason='Colombo: возвращение из отпуска одобрено')
        await bot.db.update_vacation(vac['id'], status='returned', updated_at=bot.now_iso())
        return
    saved_roles=[]
    for saved in json.loads(vac['role_snapshot']):
        role=guild.get_role(saved['id'])
        if not role:
            raise ValueError(f"Роль «{saved['name']}» удалена. Нужна ручная проверка руководства; восстановление не закрыто.")
        if role.managed or role >= guild.me.top_role or role.permissions.value != saved['permissions'] or role.id in {cfg.get(k) for k in HIGH_KEYS}:
            raise ValueError(f'Права или положение роли {role.name} изменились. Нужна ручная проверка перед возвратом.')
        saved_roles.append(role)
    leave=guild.get_role(cfg.get('vacation_role_id') or 0)
    novice=guild.get_role(cfg.get('accepted_role_id') or 0)
    cleanup=[r for r in [leave, novice if vac['added_novice'] else None] if r]
    if any(r >= guild.me.top_role for r in cleanup): raise ValueError('Проверь положение роли бота.')
    await bot.db.update_vacation(vac['id'],status='restoring',updated_at=bot.now_iso())
    for role in saved_roles:
        await member.add_roles(role,reason='Colombo: восстановление сохранённых ролей')
    for role in cleanup:
        await member.remove_roles(role,reason='Colombo: возвращение из отпуска одобрено')
    await bot.db.update_vacation(vac['id'],status='returned',updated_at=bot.now_iso())


class ReturnModal(SafeModal,title='Восстановление после отдыха'):
    reason=discord.ui.TextInput(label='Причина возвращения',max_length=500,style=discord.TextStyle.paragraph)
    comment=discord.ui.TextInput(label='Комментарий',max_length=700,style=discord.TextStyle.paragraph)
    def __init__(self,bot):super().__init__();self.bot=bot
    async def on_submit(self,i):
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('leave',i.guild_id,i.user.id)]:
            vac=await self.bot.db.pending_vacation_for_member(i.guild_id,i.user.id)
            if not vac or vac['status']!='approved':
                return await i.followup.send('Нет одобренного отпуска или заявка на возврат уже рассматривается.',ephemeral=True)
            cfg=await self.bot.db.get_config(i.guild_id)
            parent=i.guild.get_channel(cfg.get('vacation_review_channel_id') or 0)
            if not isinstance(parent,discord.TextChannel):raise ValueError('Канал отдыха не настроен.')
            thread=await private_thread(parent,i.user,configured_roles(i.guild,cfg,HIGH_KEYS),f'восстановление-{vac["id"]}')
            try:
                e=base_embed('↩️ Возвращение в состав',f'Участник: {i.user.mention}\n\n**Причина**\n{self.reason}\n\n**Комментарий**\n{self.comment}',0xD5AD65)
                msg=await thread.send(embed=e,view=ReturnDecisionView(self.bot),allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                await thread.delete(reason='Не удалось создать заявку восстановления');raise
            await self.bot.db.update_vacation(vac['id'],status='return_pending',return_reason=str(self.reason),
                return_comment=str(self.comment),return_thread_id=thread.id,return_message_id=msg.id,updated_at=self.bot.now_iso())
            await notify_assistants(thread,i.guild,cfg,base_embed('Нужна проверка восстановления',f'Заявка по отпуску #{vac["id"]}'))
            await i.followup.send(f'Заявка отправлена: {thread.mention}',ephemeral=True)


class ReturnDecisionView(SafeView):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    async def decide(self,i,approve):
        if not isinstance(i.user,discord.Member) or not await self.bot.can_review_vacation(i.user):
            return await i.response.send_message('Восстановление одобряет Ass.Deputy и выше.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        vac=await self.bot.db._one('SELECT * FROM vacations WHERE guild_id=? AND return_thread_id=? AND return_message_id=?',
                                  (i.guild_id,i.channel_id,i.message.id))
        if not vac:return await i.followup.send('Заявка не найдена.',ephemeral=True)
        async with self.bot.operation_locks[('leave',i.guild_id,vac['member_id'])]:
            vac=await self.bot.db.get_vacation(vac['id'])
            if vac['status'] not in ('return_pending','restoring'):
                return await i.followup.send('Решение уже принято.',ephemeral=True)
            if vac['status']=='restoring' and not approve:
                return await i.followup.send('Возврат ролей уже начат. Заверши восстановление.',ephemeral=True)
            if approve:await restore_leave(self.bot,i.guild,vac)
            else:await self.bot.db.update_vacation(vac['id'],status='approved',updated_at=self.bot.now_iso())
            await i.message.edit(embed=base_embed('✅ Восстановлен' if approve else '❌ Восстановление отклонено',
                f"Участник: <@{vac['member_id']}>\nРешение: {i.user.mention}\n"+
                ('Возвращение одобрено, роль отдыха снята.' if approve else 'Отдых продолжается. Можно подать новую заявку.'),0x3BAA72 if approve else 0xD64045),view=None,allowed_mentions=discord.AllowedMentions.none())
            await self.bot.update_vacation_status(i.guild)
            await i.followup.send('Решение сохранено.',ephemeral=True)
            await i.channel.edit(archived=True,locked=True)
    @discord.ui.button(label='Одобрить возвращение',style=discord.ButtonStyle.success,custom_id='colombo:return:approve')
    async def approve(self,i,_):await self.decide(i,True)
    @discord.ui.button(label='Отклонить',style=discord.ButtonStyle.danger,custom_id='colombo:return:reject')
    async def reject(self,i,_):await self.decide(i,False)
