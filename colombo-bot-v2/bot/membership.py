"""Separate guest onboarding from family membership and application access."""
import discord
from .roles import application_recruiters


def membership_roles(guild, cfg):
    roles = [guild.get_role(cfg.get(k) or 0) for k in
             ('guest_role_id', 'colombo_role_id', 'accepted_role_id')]
    if any(r is None or r.managed or r.is_default() or r >= guild.me.top_role for r in roles):
        raise ValueError('В /setup выбери Guest, Colombo и Test; подними роль бота выше них.')
    if len({r.id for r in roles}) != 3:
        raise ValueError('Guest, Colombo и Test должны быть разными ролями.')
    return roles


async def accept_member(member, cfg, reason):
    guest, family, test = membership_roles(member.guild, cfg)
    # Grant access first; failed Guest removal leaves the application retryable.
    await member.add_roles(family, test, reason=reason)
    if member.get_role(guest.id):
        await member.remove_roles(guest, reason=reason)


async def repair_members(bot, guild, roles):
    cfg = {k: r.id for k, r in roles.items()}
    guest, family, test = membership_roles(guild, cfg)
    main = roles['main_role_id']
    count = 0
    for member in guild.members:
        if member.bot or not any(member.get_role(r.id) for r in (test, main, family)):
            continue
        # An approved leave intentionally removes family roles until restoration.
        if member.get_role(roles['vacation_role_id'].id) or await bot.db.pending_vacation_for_member(guild.id, member.id):
            continue
        changed = False
        if not member.get_role(family.id):
            await member.add_roles(family, reason='Colombo: восстановление семейного доступа Test/main')
            changed = True
        if member.get_role(guest.id):
            await member.remove_roles(guest, reason='Colombo: Guest только для непринятых участников')
            changed = True
        count += changed
    return count


async def secure_application_parent(parent):
    # Manage Threads bypasses private-thread membership. Deny it in this parent,
    # including role-specific allows; Discord Administrator remains a bypass.
    ow = dict(parent.overwrites)
    for target in [parent.guild.default_role, *ow]:
        if target.id == parent.guild.me.id:
            continue
        perm = ow.get(target, discord.PermissionOverwrite())
        perm.manage_threads = False
        ow[target] = perm
    perm = ow.get(parent.guild.me, discord.PermissionOverwrite())
    perm.manage_threads = True
    perm.create_private_threads = True
    ow[parent.guild.me] = perm
    await parent.edit(overwrites=ow, reason='Colombo: приватность заявок по ответственному')


async def sync_application_members(bot, thread, app):
    cfg = await bot.db.get_config(thread.guild.id)
    allowed = {app['applicant_id'], bot.user.id}
    if app.get('assigned_to'):
        allowed.add(app['assigned_to'])
    else:
        allowed.update(m.id for m in application_recruiters(thread.guild, cfg))
    for current in await thread.fetch_members():
        if current.id not in allowed:
            await thread.remove_user(discord.Object(id=current.id))
    for uid in allowed - {bot.user.id}:
        await thread.add_user(discord.Object(id=uid))
