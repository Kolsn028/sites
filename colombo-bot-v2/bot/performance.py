"""Combine refresh bursts and skip semantically identical panel edits."""
import asyncio
import functools
import discord


def embed_content(embed):
    value=embed.to_dict()
    value.pop('timestamp',None)
    # Discord adds transport metadata to images on received embeds.
    for key in ('image','thumbnail','author','footer'):
        if key in value:
            value[key]={k:v for k,v in value[key].items() if k not in ('proxy_url','proxy_icon_url','width','height')}
    return value


def component_content(value):
    if isinstance(value,dict):return {k:component_content(v) for k,v in value.items() if k!='id'}
    if isinstance(value,list):return [component_content(v) for v in value]
    return value


async def edit_if_changed(message, *, embed=None, **kwargs):
    same=embed is None or (len(message.embeds)==1 and embed_content(message.embeds[0])==embed_content(embed))
    if 'view' in kwargs:
        view=kwargs['view']
        same=same and component_content([c.to_dict() for c in message.components])==component_content(view.to_components() if view else [])
    if same:return message
    if embed is not None:kwargs['embed']=embed
    return await message.edit(**kwargs)


def coalesced_panel(func):
    @functools.wraps(func)
    async def wrapped(bot,guild):
        if not hasattr(bot,'_panel_tasks'):bot._panel_tasks={}
        key=(func.__name__,guild.id)
        state=bot._panel_tasks.get(key)
        if state is not None:
            state['revision']+=1
            return await asyncio.shield(state['task'])
        state={'revision':0}
        async def run():
            try:
                while True:
                    await asyncio.sleep(0.5)
                    revision=state['revision']
                    result=await func(bot,guild)
                    if revision==state['revision']:return result
            finally:
                bot._panel_tasks.pop(key,None)
        bot._panel_tasks[key]=state
        state['task']=asyncio.create_task(run())
        return await asyncio.shield(state['task'])
    return wrapped
