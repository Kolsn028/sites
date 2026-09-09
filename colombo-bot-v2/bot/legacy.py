"""Migrate exact obsolete roles, retaining a role whenever access cannot be transferred."""
import discord

LEGACY = {
    'Colombo • Recruiter': 'recruiter_role_id',
    'Colombo • High Staff': 'high_staff_role_id',
    'Colombo • Family': 'accepted_role_id',
    'Colombo • Assistant Leader': 'high_staff_role_id',
    'Colombo • Dep Leader': 'dep_leader_role_id',
    'Colombo • Отдых': 'vacation_role_id',
}


def merge_overwrite(old, new):
    merged = discord.PermissionOverwrite(**dict(new))
    for name, value in old:
        current = getattr(new, name)
        if value is not None and current is not None and value != current:
            raise ValueError('конфликт прав канала')
        if current is None:
            setattr(merged, name, value)
    return merged


async def migrate_legacy(guild, roles):
    warnings = []
    if not guild.chunked:
        await guild.chunk(cache=True)
    targets = {r.id for r in roles.values()}
    for old in list(guild.roles):
        if old.name not in LEGACY or old.id in targets:
            continue
        new = roles[LEGACY[old.name]]
        if old.managed or old >= guild.me.top_role or new >= guild.me.top_role:
            warnings.append(f'Не удалена {old.name}: подними роль бота выше неё и новой роли.')
            continue
        try:
            transfers = []
            for ch in guild.channels:
                if old in ch.overwrites:
                    transfers.append((ch, merge_overwrite(ch.overwrites_for(old), ch.overwrites_for(new))))
            # Do not delete a role with general capabilities absent from the target.
            if old.permissions.value & ~new.permissions.value:
                warnings.append(f'Не удалена {old.name}: у неё есть общие права, отсутствующие у {new.name}.')
                continue
            for member in list(old.members):
                await member.add_roles(new, reason='Colombo: перенос старой роли')
            for ch, overwrite in transfers:
                await ch.set_permissions(new, overwrite=overwrite, reason='Colombo: перенос доступа')
            await old.delete(reason=f'Colombo: заменена на {new.name}')
        except (discord.DiscordException, ValueError):
            warnings.append(f'Не удалена {old.name}: не удалось полностью перенести участников или права.')
    return warnings
