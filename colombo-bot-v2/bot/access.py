"""Permission policy only; no Discord messages, SQL or role mutations."""

STAFF_KEYS = ('leader_role_id', 'dep_leader_role_id', 'high_staff_role_id', 'recruiter_role_id')
HIGH_KEYS = STAFF_KEYS[:3]
REPORT_KEYS = STAFF_KEYS
PROMOTION_KEYS = STAFF_KEYS
MANAGEMENT_KEYS = HIGH_KEYS


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
    return is_leader(member, cfg) or has_role(member, cfg, STAFF_KEYS + ('accepted_role_id', 'main_role_id', 'colombo_role_id'))


# Tier review deliberately has no owner/admin/senior-role bypass.
TIER_GUILD_ID = 1503854540116721747
TIERCHECK_ROLE_ID = 1549336543527960636


def may_review_tiers(member, guild_id):
    return guild_id == TIER_GUILD_ID and bool(member.get_role(TIERCHECK_ROLE_ID))


def may_manage_events(member, cfg):
    return may_manage_recruiters(member, cfg)


def may_view_profiles(member, cfg):
    return may_manage_recruiters(member, cfg)


def may_confirm_attendance(member, cfg, event):
    return is_leader(member, cfg) or bool(has_role(member, cfg, ('dep_leader_role_id',))) or (
        member.id == event['creator_id'] and bool(has_role(member, cfg, HIGH_KEYS)))


def may_use_legacy_admin(member, cfg):
    # Preserve existing command/assignment override; do not silently expand High.
    return is_leader(member, cfg) or has_role(member, cfg, ('dep_leader_role_id',)) or member.guild_permissions.administrator


def may_decide_application(member, cfg, application):
    return may_recruit(member, cfg) and bool(application.get('assigned_to')) and (
        application['assigned_to'] == member.id or may_use_legacy_admin(member, cfg))


def may_setup(member, cfg, resolve_role):
    if may_manage_recruiters(member, cfg):
        return True
    if not cfg.get('role_schema_version'):
        return any((role := resolve_role(member.guild, key)) and member.get_role(role.id)
                   for key in HIGH_KEYS)
    return False
