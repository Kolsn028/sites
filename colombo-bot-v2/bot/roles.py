"""Explicit Colombo ranks; role position alone never grants bot permissions."""
import discord

ROLE_SPECS = {
    'leader_role_id': ('Leader', 0xE53935),
    'dep_leader_role_id': ('Deputy Leader', 0x2879E8),
    'high_staff_role_id': ('Ass.Deputy', 0xD5AD65),
    'recruiter_role_id': ('Recruit-', 0xA82D40),
    'main_role_id': ('main', 0x8E98A6),
    'accepted_role_id': ('-Novizio-', 0x8E98A6),
    'colombo_role_id': ('Colombo', 0x777777),
    'vacation_role_id': ('Отдых', 0x5BAE96),
}
STAFF_KEYS = ('leader_role_id', 'dep_leader_role_id', 'high_staff_role_id', 'recruiter_role_id')
HIGH_KEYS = STAFF_KEYS[:3]
REPORT_KEYS = STAFF_KEYS
PROMOTION_KEYS = STAFF_KEYS
MANAGEMENT_KEYS = HIGH_KEYS


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
    return is_leader(member, cfg) or bool(has_role(member, cfg, STAFF_KEYS))


def may_review_reports(member, cfg):
    return is_leader(member, cfg) or bool(has_role(member, cfg, REPORT_KEYS))


def may_promote(member, cfg):
    return is_leader(member, cfg) or bool(has_role(member, cfg, PROMOTION_KEYS))


def may_manage_recruiters(member, cfg):
    return is_leader(member, cfg) or bool(has_role(member, cfg, MANAGEMENT_KEYS))


def may_review_vacation(member, cfg):
    return is_leader(member, cfg) or bool(has_role(member, cfg, MANAGEMENT_KEYS))


def is_family(member, cfg):
    return is_leader(member, cfg) or has_role(member, cfg, STAFF_KEYS + ('accepted_role_id', 'main_role_id'))


def assistant_mentions(guild, cfg):
    role = guild.get_role(cfg.get('high_staff_role_id') or 0)
    people = [m for m in role.members if not m.bot and not is_leader(m, cfg)
              and not has_role(m, cfg, ('dep_leader_role_id',))] if role else []
    return people


async def notify_assistants(channel, guild, cfg, embed):
    return await notify_people(channel, assistant_mentions(guild, cfg), embed)


async def notify_people(channel, people, embed):
    batches = [people[i:i+40] for i in range(0, len(people), 40)] or [[]]
    first = None
    for index, group in enumerate(batches):
        message = await channel.send(content=' '.join(m.mention for m in group) or None,
            embed=embed if index == 0 else None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=group, replied_user=False))
        first = first or message
    return first


async def notify_recruiters(channel, guild, cfg, embed):
    role = guild.get_role(cfg.get('recruiter_role_id') or 0)
    people = [m for m in role.members if not m.bot and not is_leader(m, cfg)
              and not has_role(m, cfg, ('dep_leader_role_id',))] if role else []
    return await notify_people(channel, people, embed)
