"""Application decisions: authorization, role changes, then one atomic result.

UI callbacks may hold their existing recruiter_decision lock. This service uses
its own lock so callers outside a view also serialize approval/rejection safely.
It never sends messages; a failed notification cannot undo a recorded decision.
"""
import discord
from ..access import may_decide_application
from ..membership import accept_member


class ApplicationDecisionError(ValueError):
    """A request cannot be decided; safe to show this message to staff."""


async def decide(bot, guild, actor, thread_id, *, accepted, reason=None, expected_id=None):
    if actor.guild.id != guild.id:
        raise ApplicationDecisionError('Участник находится на другом сервере.')
    async with bot.operation_locks[('application_action', guild.id, thread_id)]:
        app = await bot.db.get_application_by_thread(guild.id, thread_id)
        if not app or (expected_id is not None and app['id'] != expected_id):
            raise ApplicationDecisionError('Заявка изменилась. Открой её заново.')
        if app['status'] not in ('pending', 'interview'):
            raise ApplicationDecisionError('Заявка уже закрыта.')
        cfg = await bot.db.get_config(guild.id)
        if not may_decide_application(actor, cfg, app):
            raise ApplicationDecisionError('Решение принимает ответственный рекрутер или руководитель с правом управления заявкой.')
        if not accepted and len((reason or '').strip()) < 3:
            raise ApplicationDecisionError('Напиши причину отказа не короче трёх символов.')
        if accepted:
            applicant = guild.get_member(app['applicant_id'])
            if not applicant:
                raise ApplicationDecisionError('Участник вышел с сервера. Решение не сохранено.')
            try:
                await accept_member(applicant, cfg, f"Заявка #{app['id']}: принят в Colombo")
            except (discord.DiscordException, ValueError) as exc:
                raise ApplicationDecisionError(
                    'Не удалось завершить выдачу Colombo + Test и снятие Guest. '
                    'Проверь роли и права бота, затем повтори приём. ' + str(exc)) from exc
        status = 'accepted' if accepted else 'rejected'
        saved = await bot.db.record_application_decision(
            app['id'], guild.id, actor.id, status, bot.now_iso(), reason)
        if not saved:
            raise ApplicationDecisionError('Решение уже сохранено.')
        return {**app, 'status': status, 'handled_by': actor.id, 'rejection_reason': reason}
