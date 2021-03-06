# Standard
import discord
import traceback
from discord import Interaction, app_commands, HTTPException, Forbidden
from discord.ext import commands, tasks
from datetime import time, timedelta
from datetime import datetime
from difflib import get_close_matches
from typing import Literal, Tuple

# Local
from utils.valorant.embed import Embed, notify_all_send
from utils.valorant.useful import json_read, json_save, get_skin, get_emoji_tier_by_bot, format_relative
from utils.valorant.local import InteractionLanguage, ResponseLanguage
from utils.valorant.db import DATABASE
from utils.valorant.endpoint import API_ENDPOINT
from utils.valorant.view import NotifyViewList, NotifyView
from utils.valorant.cache import create_json

class Notify(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.notifys.start()

    def cog_unload(self) -> None:
        self.notifys.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.db: DATABASE = self.bot.db
        self.endpoint: API_ENDPOINT = self.bot.endpoint

    async def get_endpoint_and_data(self, user_id: int) -> Tuple[API_ENDPOINT, dict]:
        data = await self.db.is_data(user_id)
        endpoint = self.endpoint
        await endpoint.activate(data)
        return endpoint, data

    async def send_notify(self) -> None:
        notify_users = self.db.get_user_is_notify()
        notify_data = json_read('notifys')
        
        for user_id in notify_users:
            try:
                # get guild language
                # guild_locale = [guild.preferred_locale for guild in self.bot.guilds if channel in guild.channels]
                # if not guild_locale: guild_locale = ['en-US']

                endpoint, data = await self.get_endpoint_and_data(int(user_id))
                offer = await endpoint.store_fetch_storefront()
                skin_offer_list = offer["SkinsPanelLayout"]["SingleItemOffers"]
                duration = offer["SkinsPanelLayout"]["SingleItemOffersRemainingDurationInSeconds"]

                author = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
                
                # language response
                try:
                    language = data['language']
                except KeyError:
                    language = 'th-TH'
                    
                response = ResponseLanguage('notify_send', language)

                user_skin_list = [skin for skin in notify_data if skin['id'] == str(user_id)]
                user_skin_list_uuid = [skin['uuid'] for skin in notify_data if skin['id'] == str(user_id)]

                if data['notify_mode'] == 'Specified':
                    skin_notify_list = list(set(skin_offer_list).intersection(set(user_skin_list_uuid)))
                    for noti in user_skin_list:
                        if noti['uuid'] in skin_notify_list:
                            uuid = noti['uuid']
                            channel = self.bot.get_channel(int(noti['channel_id']))
                            skin = get_skin(uuid)
                            name = skin['names'][language]
                            icon = skin['icon']
                            emoji = get_emoji_tier_by_bot(uuid, self.bot)
                            embed = Embed(f"{emoji} **{name}** is in your daily store!\nRemaining {format_relative(datetime.utcnow() + timedelta(seconds=duration))}", color=0xfd4554)
                            embed.set_thumbnail(url=icon)
                            view = NotifyView(user_id, uuid, name)
                            view.message = await channel.send(content=f'||{author.mention}||', embed=embed, view=view)
                
                elif data['notify_mode'] == 'All':
                    channel = self.bot.get_channel(int(data['notify_channel']))
                    embeds = notify_all_send(endpoint.player, offer, language, response, self.bot)
                    await channel.send(content=f'||{author.mention}||', embeds=embeds)
            
            except (KeyError, FileNotFoundError):
                print(f'{user_id} is not in notify list')
            except Forbidden:
                print("Bot don't have perm send notification message.")
                continue
            except HTTPException:
                print("Bot Can't send notification message.")
                continue
            except Exception as e:
                print(e)
                traceback.print_exception(type(e), e, e.__traceback__)
                continue

    @tasks.loop(time=time(hour=0, minute=0, second=10)) #utc 00:00:15
    async def notifys(self) -> None:
        __verify_time = datetime.utcnow()
        if __verify_time.hour == 0 and __verify_time.minute <= 10:
            await self.send_notify()
        
    @notifys.before_loop
    async def before_daily_send(self) -> None:
        await self.bot.wait_until_ready()
        print('Checking new store skins for notifys...')

    notify = app_commands.Group(name='notify', description='Notify commands')

    @notify.command(name='add', description='Set a notification when a specific skin is available on your store')
    @app_commands.describe(skin='The name of the skin you want to notify')
    async def notify_add(self, interaction: Interaction, skin: str) -> None:

        # language
        language = InteractionLanguage(interaction.locale)
        # response = ResponseLanguage(interaction.command.name, language)

        # check file if or not
        create_json('notifys', [])
        
        # get cache
        skindata = self.db.read_cache()

        # find skin
        skin_list = [skindata['skins'][x]['names'][language] for x in skindata['skins']] # get skin list
        skin_name = get_close_matches(skin, skin_list, 1) # get skin close match

        if skin_name:
            notify_data = json_read('notifys') 

            find_skin = [x for x in skindata['skins'] if skindata['skins'][x]['names'][language] == skin_name[0]]
            skin_uuid = find_skin[0]
            skin_source = skindata['skins'][skin_uuid]

            name = skin_source['names'][language]
            icon = skin_source['icon']
            uuid = skin_source['uuid']
            emoji = get_emoji_tier_by_bot(skin_uuid, self.bot)

            for skin in notify_data:
                if skin['id'] == str(interaction.user.id) and skin['uuid'] == skin_uuid:
                    raise RuntimeError(f'{emoji} **{name}** is already in your Notify')

            payload = {"id": str(interaction.user.id), "uuid": skin_uuid, "channel_id": interaction.channel.id}

            try:
                notify_data.append(payload)
                json_save('notifys', notify_data)
            except AttributeError:
                notify_data = [payload]
                json_save('notifys', notify_data)

            # check if user is notify is on
            userdata = json_read('users') 
            notify_mode = userdata.get('notify_mode')
            if notify_mode is None:
                userdata[str(interaction.user.id)]['notify_mode'] = 'Specified'
                json_save('users', userdata)

            embed = Embed(f'Successfully set an notify for the {emoji} **{name}**')
            embed.set_thumbnail(url=icon)

            view = NotifyView(interaction.user.id, uuid, name)
            await interaction.response.send_message(embed=embed, view=view)
            return

        raise RuntimeError("Not found skin")
    
    @notify.command(name='list', description='View skins you have set a for notification.')
    async def notify_list(self, interaction: Interaction) -> None:
        
        # language
        language = InteractionLanguage(interaction.locale)
        # response = ResponseLanguage(interaction.command.name, language)

        await self.db.is_data(interaction.user.id) # check if user is in db
        view = NotifyViewList(interaction)
        await view.start()

    @notify.command(name='mode', description='Change notification mode')
    @app_commands.describe(mode='Choose notification')
    async def notify_mode(self, interaction: Interaction, mode: Literal['Specified Skin','All Skin', 'Off']) -> None:
        
        # language
        language = InteractionLanguage(interaction.locale)
        # response = ResponseLanguage(interaction.command.name, language)
 
        await self.db.is_login(interaction.user.id) # check if user is logged in
        self.db.check_notify_list(interaction.user.id) # check total notify list
        self.db.change_notify_mode(interaction.user.id, mode, interaction.channel_id) # change notify mode

        embed = Embed(f'Successfully changed your notification mode to **{mode}**')
        if mode == 'Specified Skin':
            embed.set_image(url='https://i.imgur.com/RF6fHRY.png')
        elif mode == 'All Skin':
            embed.set_image(url='https://i.imgur.com/Gedqlzc.png')
        elif mode == 'Off':
            embed.description = 'Turn off notification mode'
        
        await interaction.response.send_message(embed=embed)
    
    @notify.command(name='test', description='Testing notification')
    async def notify_test(self, interaction: Interaction) -> None:

        # language
        # language = InteractionLanguage(interaction.locale)
        # response = ResponseLanguage(interaction.command.name, language)
        language = 'th-TH'
        response = ResponseLanguage('notify_send', language)

        await interaction.response.defer()

        # notify list
        notify_data = json_read('notifys')
        
        # get user data and offer
        endpoint, data = await self.get_endpoint_and_data(int(interaction.user.id))
        offer = await endpoint.store_fetch_storefront()

        # offer data
        duration = offer["SkinsPanelLayout"]["SingleItemOffersRemainingDurationInSeconds"]
        user_skin_list = [skin for skin in notify_data if skin['id'] == str(interaction.user.id)]
        
        if len(user_skin_list) == 0:
            raise RuntimeError("No skin set for notification")
        
        try:
            if data['notify_mode'] == 'Specified':
                for noti in user_skin_list:
                    uuid = noti['uuid']
                    channel = self.bot.get_channel(int(noti['channel_id']))
                    skin = get_skin(uuid)
                    name = skin['names'][language]
                    icon = skin['icon']
                    emoji = get_emoji_tier_by_bot(uuid, self.bot)
                    embed = Embed(f"{emoji} **{name}** is in your daily store!\nRemaining {format_relative(datetime.utcnow() + timedelta(seconds=duration))}", color=0xfd4554)
                    embed.set_thumbnail(url=icon)
                    view = NotifyView(interaction.user.id, uuid, name)
                    view.message = await channel.send(content=f'||{interaction.user.mention}||', embed=embed, view=view)
                    break
                await interaction.followup.send(Embed(f'Notification is working'))
            
            elif data['notify_mode'] == 'All':
                channel = self.bot.get_channel(int(data['notify_channel']))
                embeds = notify_all_send(endpoint.player, offer, language, response, self.bot)
                await channel.send(content=f'||{interaction.user.mention}||', embeds=embeds)
                await interaction.followup.send(embed=Embed(f'Notification is working'))

            else:
                await interaction.followup.send(embed=Embed(f"You're not turn on notification mode"))
        
        except (HTTPException, Forbidden):
            raise RuntimeError("Notification failed or bot don't have permission to send message")
        except Exception as e:
            print(e)
            raise RuntimeError("Notification failed")

async def setup(bot) -> None:
    await bot.add_cog(Notify(bot))