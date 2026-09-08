from __future__ import annotations
import os, re
from datetime import date, datetime, timezone
from aiohttp import web
import discord
from discord.ext import commands, tasks
from .ui import base_embed

MEDIA_EXTS=(".png",".jpg",".jpeg",".webp",".gif",".mp4",".mov")

def safe_case_name(name,user_id):
    clean=re.sub(r"[^0-9A-Za-zА-Яа-яЁё _.-]+","",name).strip()
    clean=re.sub(r"\s+","-",clean).lower()
    return f"дело-{(clean or str(user_id))[:70]}"[:95]

class ColomboBot(commands.Bot):
    def __init__(self,*args,db,**kwargs):
        super().__init__(*args,**kwargs); self.db=db; self.health_runner=None

    def now_iso(self): return datetime.now(timezone.utc).isoformat()

    async def setup_hook(self):
        await self.db.connect()
        from .views import ApplicationPanelView,RecruiterActionView,VacationPanelView,VacationDecisionView,CasePanelView,ActivityClassifyView,ActivityReviewView
        for view in (ApplicationPanelView(self),RecruiterActionView(self),VacationPanelView(self),VacationDecisionView(self),CasePanelView(self),ActivityClassifyView(self),ActivityReviewView(self)):
            self.add_view(view)
        gid=int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None
        try:
            if gid:
                g=discord.Object(id=gid); self.tree.copy_global_to(guild=g); await self.tree.sync(guild=g)
            else: await self.tree.sync()
        except Exception as e: print("Slash sync error:",e)
        await self._start_health(); self.housekeeping.start()

    async def _start_health(self):
        async def health(_): return web.json_response({"ok":True,"guilds":len(self.guilds)})
        app=web.Application(); app.router.add_get("/",health); app.router.add_get("/health",health)
        runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,"0.0.0.0",int(os.getenv("PORT","8080"))).start(); self.health_runner=runner

    async def close(self):
        if self.housekeeping.is_running(): self.housekeeping.cancel()
        if self.health_runner: await self.health_runner.cleanup()
        await self.db.close(); await super().close()

    async def on_ready(self): print(f"✅ {self.user} online | guilds={len(self.guilds)}")

    async def is_recruiter(self,m):
        c=await self.db.get_config(m.guild.id); rid=c.get("recruiter_role_id")
        return bool(m.guild_permissions.administrator or (rid and m.get_role(rid)))

    async def is_high_staff(self,m):
        c=await self.db.get_config(m.guild.id); rid=c.get("high_staff_role_id")
        return bool(m.guild_permissions.administrator or (rid and m.get_role(rid)))

    async def can_review_vacation(self,m):
        c=await self.db.get_config(m.guild.id); ids={c.get("assistant_leader_role_id"),c.get("dep_leader_role_id")}
        return m.guild_permissions.administrator or any(r and m.get_role(r) for r in ids)

    def activity_points(self,cat):
        return {"capt":int(os.getenv("CAPT_POINTS","3")),"mp":int(os.getenv("MP_POINTS","2")),"msh":int(os.getenv("MSH_POINTS","2")),"training":int(os.getenv("TRAINING_POINTS","1")),"other":int(os.getenv("OTHER_POINTS","1"))}.get(cat,0)

    async def ensure_personal_case(self,member):
        ex=await self.db.get_case_by_member(member.guild.id,member.id)
        if ex:
            ch=member.guild.get_channel(ex["channel_id"])
            if isinstance(ch,discord.TextChannel): return ch
        c=await self.db.get_config(member.guild.id); cat=member.guild.get_channel(c.get("case_category_id") or 0); high=member.guild.get_role(c.get("high_staff_role_id") or 0)
        if not isinstance(cat,discord.CategoryChannel) or not high: return None
        ow={member.guild.default_role:discord.PermissionOverwrite(view_channel=False),member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True),high:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True,manage_messages=True)}
        if member.guild.me: ow[member.guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True,manage_messages=True,attach_files=True,embed_links=True)
        ch=await member.guild.create_text_channel(name=safe_case_name(member.display_name,member.id),category=cat,overwrites=ow,topic=f"Личное дело • owner={member.id}",reason=f"Личное дело {member}")
        await self.db.create_case(member.guild.id,member.id,ch.id,self.now_iso())
        e=base_embed(f"📁 Личное дело • {member.display_name}",f"Владелец: {member.mention}\n\n1. Отправь сюда скрин/видео.\n2. Выбери тип активности.\n3. High Staff нажмёт **Засчитать** или **Отклонить**.\n\nВ статистику идут только подтверждённые отчёты.",0x6E56CF); e.set_thumbnail(url=member.display_avatar.url)
        await ch.send(content=f"{member.mention} {high.mention}",embed=e); return ch

    async def on_message(self,msg):
        if msg.author.bot or not msg.guild or not msg.attachments: return
        case=await self.db.get_case_by_channel(msg.guild.id,msg.channel.id)
        if not case: return
        urls=[]
        for a in msg.attachments:
            ct=(a.content_type or "").lower()
            if ct.startswith("image/") or ct.startswith("video/") or a.filename.lower().endswith(MEDIA_EXTS): urls.append(a.url)
        if not urls: return
        sid=await self.db.create_activity(msg.guild.id,case["member_id"],msg.channel.id,msg.id,urls,self.now_iso())
        if not sid: return
        from .views import ActivityClassifyView
        e=base_embed(f"📎 Активность #{sid}",f"Участник: <@{case['member_id']}>\nОтправил: {msg.author.mention}\nВложений: **{len(urls)}**\n[Открыть исходное сообщение]({msg.jump_url})",0xD5A43A)
        e.add_field(name="Тип",value="❔ Не выбран",inline=True); e.add_field(name="Баллы",value="—",inline=True); e.add_field(name="Статус",value="🟡 Нужно выбрать тип",inline=False)
        review=await msg.reply(embed=e,view=ActivityClassifyView(self),mention_author=False); await self.db.update_activity(sid,review_message_id=review.id)

    async def send_or_update_leaderboard(self,guild):
        c=await self.db.get_config(guild.id); rows=await self.db.leaderboard(guild.id,10); medals=["🥇","🥈","🥉"]; lines=[]
        for i,r in enumerate(rows): lines.append(f"{medals[i] if i<3 else f'`#{i+1}`'} <@{r['recruiter_id']}> — **{r['accepted_count']}** принято" + (f" · {r['rejected_count']} отказов" if r['rejected_count'] else ""))
        e=base_embed("🏆 Лидерборд рекрутеров","\n".join(lines) if lines else "Пока нет данных.",0xE5B64B); ch=guild.get_channel(c.get("leaderboard_channel_id") or 0)
        if not isinstance(ch,discord.TextChannel): return None
        mid=c.get("leaderboard_message_id")
        if mid:
            try: m=await ch.fetch_message(mid); await m.edit(embed=e); return m
            except discord.DiscordException: pass
        m=await ch.send(embed=e); await self.db.set_config(guild.id,leaderboard_message_id=m.id); return m

    async def update_vacation_status(self,guild):
        c=await self.db.get_config(guild.id); rows=await self.db.active_vacations(guild.id); today=date.today(); lines=[]
        for r in rows:
            end=date.fromisoformat(r["end_date"]); lines.append(f"🌴 <@{r['member_id']}> — до **{end.strftime('%d.%m.%Y')}** · **{max((end-today).days,0)} дн.**")
        e=base_embed("🌴 Кто сейчас в отпуске","\n".join(lines) if lines else "Сейчас активных отпусков нет.",0x3BAA72); ch=guild.get_channel(c.get("vacation_status_channel_id") or 0)
        if not isinstance(ch,discord.TextChannel): return None
        mid=c.get("vacation_status_message_id")
        if mid:
            try: m=await ch.fetch_message(mid); await m.edit(embed=e); return m
            except discord.DiscordException: pass
        m=await ch.send(embed=e); await self.db.set_config(guild.id,vacation_status_message_id=m.id); return m

    async def inactive_members(self,guild,days):
        rows=await self.db.last_activity_for_cases(guild.id); vacations={x["member_id"] for x in await self.db.active_vacations(guild.id)}; now=datetime.now(timezone.utc); out=[]
        for r in rows:
            if r["member_id"] in vacations: continue
            m=guild.get_member(r["member_id"])
            if not m: continue
            raw=r["last_activity"] or r["case_created_at"]; dt=datetime.fromisoformat(raw); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc); d=int((now-dt).total_seconds()/86400)
            if d>=days: out.append((m,d,r["last_activity"]))
        return sorted(out,key=lambda x:x[1],reverse=True)

    async def update_inactivity_report(self,guild):
        c=await self.db.get_config(guild.id); days=int(os.getenv("INACTIVITY_DAYS_DEFAULT","3")); rows=await self.inactive_members(guild,days); lines=[f"⚠️ {m.mention} — **{d} дн.**" for m,d,_ in rows[:30]]
        e=base_embed(f"📉 Контроль неактива • {days}+ дней","\n".join(lines) if lines else "✅ Участников с таким неактивом нет.",0xD64045 if lines else 0x3BAA72); e.set_footer(text="Одобренный отпуск автоматически исключает участника из неактива.")
        ch=guild.get_channel(c.get("inactivity_report_channel_id") or 0)
        if not isinstance(ch,discord.TextChannel): return None
        mid=c.get("inactivity_report_message_id")
        if mid:
            try: m=await ch.fetch_message(mid); await m.edit(embed=e); return m
            except discord.DiscordException: pass
        m=await ch.send(embed=e); await self.db.set_config(guild.id,inactivity_report_message_id=m.id); return m

    async def expire_vacations(self,guild):
        c=await self.db.get_config(guild.id); today=date.today(); changed=False
        for r in await self.db.active_vacations(guild.id):
            if date.fromisoformat(r["end_date"])<today:
                await self.db.update_vacation(r["id"],status="expired",updated_at=self.now_iso()); m=guild.get_member(r["member_id"]); role=guild.get_role(c.get("vacation_role_id") or 0)
                if m and role:
                    try: await m.remove_roles(role,reason="Отпуск завершён")
                    except discord.DiscordException: pass
                changed=True
        if changed: await self.update_vacation_status(guild)

    @tasks.loop(hours=1)
    async def housekeeping(self):
        for g in self.guilds:
            try: await self.expire_vacations(g); await self.update_inactivity_report(g)
            except Exception as e: print(f"housekeeping[{g.id}]",e)

    @housekeeping.before_loop
    async def before_housekeeping(self): await self.wait_until_ready()
