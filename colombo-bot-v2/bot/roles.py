"""Explicit Colombo ranks; role position alone never grants bot permissions."""
import discord

ROLE_SPECS = {
    'leader_role_id': ('Leader', 0xE53935),
    'dep_leader_role_id': ('Deputy Leader', 0x2879E8),
    'high_staff_role_id': ('Ass.Deputy', 0xD5AD65),
    'recruiter_role_id': ('Recruit-', 0xA82D40),
    'accepted_role_id': ('-Novizio-', 0x8E98A6),
    'colombo_role_id': ('Colombo', 0x777777),
    'vacation_role_id': ('Отдых', 0x5BAE96),
}
STAFF_KEYS = ('leader_role_id', 'dep_leader_role_id', 'high_staff_role_id', 'recruiter_role_id')
HIGH_KEYS = STAFF_KEYS[:3]
REPORT_KEYS = ('leader_role_id', 'high_staff_role_id')


def named_role(guild, key):
    matches = [r for r in guild.roles if r.name == ROLE_SPECS[key][0] and not r.managed and not r.is_default()]
    if len(matches) > 1:
        raise ValueError(f'Несколько ролей «{ROLE_SPECS[key][0]}». Выбери нужную явно в /setup.')
    return matches[0] if matches else None


def configured_roles(guild, cfg, keys):
    return [r for key in keys if (r := guild.get_role(cfg.get(key) or 0)) is not None]


def has_role(member, cfg, keys):
    return any(cfg.get(k) and member.get_role(cfg[k]) for k in keys)


def is_leader(member, cfg):
    return member.id == member.guild.owner_id or has_role(member, cfg, ('leader_role_id',))


def may_recruit(member, cfg):
    return is_leader(member, cfg) or has_role(member, cfg, STAFF_KEYS) or member.guild_permissions.administrator


def may_review_reports(member, cfg):
    if is_leader(member, cfg):
        return True
    # Deputy is deliberately excluded, even if carrying a junior role or Administrator.
    if has_role(member, cfg, ('dep_leader_role_id',)):
        return False
    return has_role(member, cfg, ('high_staff_role_id',)) or member.guild_permissions.administrator


def is_family(member, cfg):
    return may_recruit(member, cfg) or has_role(member, cfg, ('accepted_role_id',))


async def notify_recruiters(channel, guild, cfg, embed):
    """Mention people individually: a Recruit role ping could also notify the Leader."""
    role = guild.get_role(cfg.get('recruiter_role_id') or 0)
    recruits = [m for m in role.members if not m.bot and not is_leader(m, cfg)
                and not has_role(m, cfg, ('dep_leader_role_id',))] if role else []
    batches = [recruits[i:i + 40] for i in range(0, len(recruits), 40)] or [[]]
    first = None
    for index, group in enumerate(batches):
        message = await channel.send(content=' '.join(m.mention for m in group) or None,
            embed=embed if index == 0 else None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=group, replied_user=False))
        first = first or message
    return first
