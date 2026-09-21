"""SQL operations for profiles; callers use named methods."""


class ProfilesRepository:
    async def member_events(self, guild_id, member_id):
        return await self._all('SELECT e.*,s.attended,s.seat,s.confirmed_by,s.confirmed_at FROM event_signups s\n        JOIN family_events e ON e.id=s.event_id WHERE e.guild_id=? AND s.member_id=?', (guild_id, member_id,))

    async def member_reports(self, guild_id, member_id):
        return await self._all('SELECT * FROM activity_submissions WHERE guild_id=? AND member_id=?', (guild_id, member_id,))

    async def member_contracts(self, guild_id, member_id):
        return await self._all("SELECT * FROM progress_requests WHERE guild_id=? AND member_id=? AND kind='contract'", (guild_id, member_id,))

    async def member_promotions(self, guild_id, member_id):
        return await self._all("SELECT * FROM progress_requests WHERE guild_id=? AND member_id=? AND kind IN ('promotion','tier_1','tier_2','tier_3')", (guild_id, member_id,))

    async def member_application_history(self, guild_id, member_id):
        return await self._all("SELECT * FROM applications WHERE guild_id=? AND applicant_id=? AND status IN ('accepted','rejected')", (guild_id, member_id,))

    async def request_rows(self,gid,member_id=None,pending=False,kind='all',page=0):
        # Owner filtering lives in every branch, never only in the UI.
        parts=[];args=[]
        specs=[('applications','application','applicant_id','thread_id','rejection_reason'),('vacations','vacation','member_id','thread_id','NULL'),('progress_requests',None,'member_id','thread_id','decision'),('activity_submissions','report','member_id','case_channel_id','note')]
        for table,label,owner,channel,reason in specs:
            category="kind" if label is None else "'"+label+"'"
            actor='COALESCE(assigned_to,handled_by)' if table=='applications' else 'handled_by'
            if table=='activity_submissions': actor='handled_by'
            where='guild_id=?';params=[gid]
            if member_id is not None: where+=f' AND {owner}=?';params.append(member_id)
            if pending: where+=" AND status IN ('pending','interview','return_pending','pending_review','pending_classification','applying')"
            parts.append(f'SELECT id,{category} kind,{owner} member_id,status,{channel} channel_id,{actor} actor,{reason} reason,created_at FROM {table} WHERE {where}')
            args+=params
        union=' UNION ALL '.join(parts)
        filter_sql='' if kind=='all' else ' WHERE kind=?'
        if kind!='all':args.append(kind)
        total=await self._one('SELECT COUNT(*) n FROM ('+union+')'+filter_sql,args)
        pages=max(1,(total['n']+7)//8);page=max(0,min(page,pages-1))
        rows=await self._all('SELECT * FROM ('+union+')'+filter_sql+' ORDER BY created_at DESC,kind,id DESC LIMIT 8 OFFSET ?',[*args,page*8])
        return rows,total['n'],page,pages

    async def set_profile_message(self, case_id, message_id):
        await self._write('UPDATE personal_cases SET profile_message_id=? WHERE id=?', (message_id, case_id))
