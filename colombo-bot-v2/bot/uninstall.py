"""Owner-authorized uninstall, restricted to an explicitly reviewed manifest."""
import asyncio
import json
import os
from pathlib import Path

import discord
from aiohttp import web
from .database import Database
from .discord_backup import DiscordBackups
from .roles import ROLE_SPECS
from .services.ranks import TIER_ROLES
from .access import TIERCHECK_ROLE_ID


def select_configured(config, channels, roles):
    channel_ids = {value for key, value in config.items() if isinstance(value, int)
                   and (key.endswith('_channel_id') or key.endswith('_category_id') or key in ('interview_voice_2_id','interview_voice_3_id'))}
    role_ids = {value for key, value in config.items() if isinstance(value, int) and key.endswith('_role_id')}
    return ({c.id for c in channels if c.id in channel_ids},
            {r.id for r in roles if r.id in role_ids and not r.managed and not r.is_default()})


class Uninstaller(discord.Client):
    async def setup_hook(self):
        self.started = False
        self.db = Database(os.getenv('DATABASE_PATH', 'data/colombo-v9.db'))
        await self.db.connect()
        self.backups = DiscordBackups(self)
        await self.backups.restore()
        async def health(_): return web.json_response({'mode':'uninstall'})
        app=web.Application();app.router.add_get('/health',health)
        self.health_runner=web.AppRunner(app);await self.health_runner.setup()
        await web.TCPSite(self.health_runner,'0.0.0.0',int(os.getenv('PORT','8080'))).start()

    async def on_ready(self):
        if self.started: return
        self.started=True
        try:
            guild=self.get_guild(int(os.environ['COLOMBO_UNINSTALL_GUILD_ID']))
            if guild is None:
                print('UNINSTALL_TARGET_ABSENT',flush=True);return
            mode=os.environ['COLOMBO_UNINSTALL_MODE']
            if mode == 'inventory':
                await self.inventory(guild)
            elif mode == 'delete':
                await self.remove(guild)
        except Exception as exc:
            print(f'UNINSTALL_FAILED {type(exc).__name__}: {exc}',flush=True)

    async def inventory(self,guild):
        config=await self.db.get_config(guild.id)
        channels=await guild.fetch_channels();roles=await guild.fetch_roles()
        channel_ids,role_ids=select_configured(config,channels,roles)
        # Audit provenance catches old bot-created objects missing from current config.
        for action,ids in ((discord.AuditLogAction.channel_create,channel_ids),(discord.AuditLogAction.role_create,role_ids)):
            try:
                async for entry in guild.audit_logs(limit=None,action=action,user=self.user):
                    if entry.target: ids.add(entry.target.id)
            except discord.Forbidden:
                print('UNINSTALL_AUDIT_UNAVAILABLE',flush=True)
        role_ids.update(TIER_ROLES.values());role_ids.add(TIERCHECK_ROLE_ID)
        for channel in channels:
            topic=getattr(channel,'topic',None) or ''
            if topic in [self.backups.topic(guild.id,k) for k in ('backup','logs')] or topic.startswith(f'Colombo • ') and topic.endswith(' • управляется ботом'):
                channel_ids.add(channel.id)
            if topic in {f'colombo:tier:{t}:{self.user.id}:{guild.id}' for t in TIER_ROLES}:channel_ids.add(channel.id)
        for row in await self.db._all('SELECT channel_id FROM personal_cases WHERE guild_id=?',(guild.id,)):
            channel_ids.add(row['channel_id'])
        manifest={'guild_id':guild.id,'bot_id':self.user.id,
                  'channels':[{'id':c.id,'name':c.name,'category':isinstance(c,discord.CategoryChannel),'backup':getattr(c,'topic',None)==self.backups.topic(guild.id,'backup')} for c in channels if c.id in channel_ids],
                  'roles':[{'id':r.id,'name':r.name,'editable':r<guild.me.top_role} for r in roles if r.id in role_ids and not r.managed and not r.is_default()]}
        print('UNINSTALL_MANIFEST '+json.dumps(manifest,ensure_ascii=False),flush=True)

    async def remove(self,guild):
        manifest=json.loads(os.environ['COLOMBO_UNINSTALL_MANIFEST'])
        if manifest['guild_id']!=guild.id or manifest['bot_id']!=self.user.id:
            raise ValueError('Manifest target mismatch')
        channels={c.id:c for c in await guild.fetch_channels()}
        failures=[]
        # Parents delete their threads/messages. Keep recovery data until other work finishes.
        planned=sorted(manifest['channels'],key=lambda x:(x['backup'],x['category']))
        for item in planned:
            channel=channels.get(item['id'])
            if channel is None:continue
            if isinstance(channel,discord.CategoryChannel):
                remaining=await guild.fetch_channels()
                if any(getattr(c,'category_id',None)==channel.id for c in remaining):
                    failures.append({'channel':channel.id,'reason':'contains surviving channels'});continue
            try:
                await channel.delete(reason='Owner requested complete Colombo removal')
                print(f'UNINSTALL_CHANNEL_DELETED {channel.id}',flush=True)
            except discord.HTTPException as exc:failures.append({'channel':channel.id,'status':exc.status})
        # Retry empty categories after the backup channel is removed.
        for item in manifest['channels']:
            if not item['category']:continue
            remaining=await guild.fetch_channels();channel=next((c for c in remaining if c.id==item['id']),None)
            if channel and not any(getattr(c,'category_id',None)==channel.id for c in remaining):
                try:await channel.delete(reason='Owner requested complete Colombo removal')
                except discord.HTTPException:pass
        roles={r.id:r for r in await guild.fetch_roles()}
        for item in manifest['roles']:
            role=roles.get(item['id'])
            if role is None:continue
            if role.managed or role.is_default() or role>=guild.me.top_role:
                failures.append({'role':role.id,'name':role.name,'reason':'Discord hierarchy or managed role'});continue
            try:
                await role.delete(reason='Owner requested complete Colombo removal')
                print(f'UNINSTALL_ROLE_DELETED {role.id}',flush=True)
            except discord.HTTPException as exc:failures.append({'role':role.id,'name':role.name,'status':exc.status})
        channels_left={c.id for c in await guild.fetch_channels()}
        roles_left={r.id for r in await guild.fetch_roles()}
        summary={'channels_remaining':[c for c in manifest['channels'] if c['id'] in channels_left],
                 'roles_remaining':[r for r in manifest['roles'] if r['id'] in roles_left]}
        print('UNINSTALL_RESULT '+json.dumps(summary,ensure_ascii=False),flush=True)
        await guild.leave()
        print(f'UNINSTALL_LEFT_GUILD {guild.id}',flush=True)
        await self.db.close()
        for suffix in ('','-wal','-shm'):
            Path(str(self.db.path)+suffix).unlink(missing_ok=True)
        print('UNINSTALL_LOCAL_DATA_REMOVED',flush=True)

    async def close(self):
        if hasattr(self,'db'):await self.db.close()
        if hasattr(self,'health_runner'):await self.health_runner.cleanup()
        await super().close()


def run(token):
    Uninstaller(intents=discord.Intents.default()).run(token)
