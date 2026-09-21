"""Explicit Colombo ranks; role position alone never grants bot permissions."""
import discord

ROLE_SPECS = {
    'leader_role_id': ('Leader', 0xE53935),
    'dep_leader_role_id': ('Deputy Leader', 0x2879E8),
    'high_staff_role_id': ('High', 0xD5AD65),
    'recruiter_role_id': ('Recruit-', 0xA82D40),
    'main_role_id': ('main', 0x8E98A6),
    'accepted_role_id': ('Test', 0x8E98A6),
    'colombo_role_id': ('Colombo', 0x777777),
    'guest_role_id': ('Guest', 0x777777),
    'vacation_role_id': ('Отдых', 0x5BAE96),
}
# Compatibility exports: existing modules can continue importing bot.roles.
from .access import (
    STAFF_KEYS, HIGH_KEYS, REPORT_KEYS, PROMOTION_KEYS, MANAGEMENT_KEYS,
    has_role, is_leader, may_recruit, may_review_reports, may_promote,
    may_manage_recruiters, may_review_vacation, is_family,
)


def named_role(guild, key):
    names = {ROLE_SPECS[key][0].casefold()}
    if key == 'high_staff_role_id':
        names.add('ass.deputy')
    matches = [r for r in guild.roles if r.name.casefold() in names and not r.managed and not r.is_default()]
    if len(matches) > 1:
        raise ValueError(f'Несколько ролей «{ROLE_SPECS[key][0]}». Выбери нужную явно в /setup.')
    return matches[0] if matches else None


def configured_roles(guild, cfg, keys):
    return [r for key in keys if (r := guild.get_role(cfg.get(key) or 0)) is not None]



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


def application_recruiters(guild, cfg):
    role = guild.get_role(cfg.get('recruiter_role_id') or 0)
    return [m for m in role.members if not m.bot and not is_leader(m, cfg)
            and not has_role(m, cfg, HIGH_KEYS)] if role else []


async def notify_recruiters(channel, guild, cfg, embed):
    return await notify_people(channel, application_recruiters(guild, cfg), embed)
