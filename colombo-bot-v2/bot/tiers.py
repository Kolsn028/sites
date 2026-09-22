"""Compatibility imports; tier implementation lives in tier_system."""
from .tier_system.common import (
    GUILD_ID, TIERCHECK_ROLE_ID, TIER_ROLES, KINDS,
    can_review, panel, tier_channel_topic, tier_from_channel,
)
from .tier_system.applications import TierModal, TierPanelView
from .tier_system.review import TierDecision, TierReviewView
from .tier_system.channels import install
from .tier_system.reviewers import sync_reviewers, _sync_reviewers
from .services.ranks import award_tier
