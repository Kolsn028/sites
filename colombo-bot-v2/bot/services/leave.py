"""Resumable vacation role transitions; no UI or notification calls."""
import json
from ..access import HIGH_KEYS


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

