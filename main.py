from models import Server, session

from ctypes.util import find_library
import discord ## pip3 install git+...
import sys
import os
import aiohttp ## pip3 install aiohttp
import magic ## pip3 install python-magic
import asyncio
import json
import time
from configparser import SafeConfigParser


class BotClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super(BotClient, self).__init__(*args, **kwargs)

        self.color = 0xff3838

        self.MAX_SOUNDS = 15

        self.commands = {
            'ping' : self.ping,
            'help' : self.help,
            'info': self.info,
            'prefix' : self.change_prefix,
            'upload' : self.wait_for_file,
            'play' : self.play,
            'list' : self.list,
            'delete' : self.delete,
            'stop' : self.stop,
            'link' : self.link,
            'unlink' : self.unlink,
            'soundboard' : self.soundboard,
            'more' : self.more,
            'roles' : self.role
        }

        self.timeouts = {}

        self.config = SafeConfigParser()
        self.config.read('config.ini')


    async def get_sounds(self, guild):
        try:
            extra = 0

            patreon_server = self.get_guild(self.config.get('DEFAULT', 'patreon_server'))
            members = [p.id for p in patreon_server.members if not p.bot]

            voters = await self.get_voters()

            for member in guild.members:
                if member.id in members:
                    extra += 1

                if member.id in voters:
                    extra += 2

            return self.MAX_SOUNDS + extra

        except:
            return self.MAX_SOUNDS


    async def get_voters(self):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://discordbots.org/api/bots/votes', headers={'authorization' : self.config.get('tokens', 'discordbots'), 'content-type' : 'application/json'}) as resp:
                return [int(x['id']) for x in json.loads(await resp.text())]


    async def send(self):
        guild_count = len(self.guilds)
        member_count = len([x for x in self.get_all_members()])

        if self.config.get('TOKENS', 'discordbots'):

            session = aiohttp.ClientSession()
            dump = json.dumps({
                'server_count': len(client.guilds)
            })

            head = {
                'authorization': self.config.get('TOKENS', 'discordbots'),
                'content-type' : 'application/json'
            }

            url = 'https://discordbots.org/api/bots/stats'
            async with session.post(url, data=dump, headers=head) as resp:
                print('returned {0.status} for {1}'.format(resp, dump))

            session.close()


    async def on_ready(self):
        discord.opus.load_opus(find_library('opus'))

        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------------')
        await client.change_presence(activity=discord.Game(name='@{} info'.format(self.user.name)))


    async def on_guild_join(self, guild):
        await self.send()

        await self.welcome(guild)


    async def on_guild_remove(self, guild):
        await self.send()

        await self.cleanup()


    async def welcome(self, guild, *args):
        if isinstance(guild, discord.Message):
            guild = guild.guild

        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages and not channel.is_nsfw():
                await channel.send('Thank you for adding SoundFX! To begin, type `?info` to learn more.')
                break
            else:
                continue


    async def cleanup(self, *args):
        all_ids = [g.id for g in self.guilds]

        session.query(Server).filter(Server.id.notin_(all_ids)).delete(synchronize_session='fetch')

        session.commit()


    async def on_reaction_add(self, reaction, user):
        server = session.query(Server).filter_by(id=reaction.message.guild.id).first()

        if reaction.message.guild is None:
            return

        if user.bot or user.voice is None:
            return

        if reaction.message.author == self.user:
            if isinstance(reaction.emoji, discord.Emoji):
                for stripped, data in server.sounds.items():
                    if data['emoji'] is not None and (not isinstance(data['emoji'], str)) and data['emoji'][1] == reaction.emoji.id:
                        break # the combination of this break and the else following quits the flow if the reaction isnt stored for use
                else:
                    return

            else:
                for stripped, data in server.sounds.items():
                    if data['emoji'] == reaction.emoji:
                        break
                else:
                    return

            # method continues here
            await reaction.message.remove_reaction(reaction, user)
            await reaction.message.add_reaction(reaction.emoji)

            try:
                voice = await user.voice.channel.connect()
            except discord.errors.ClientException:
                voice = [v for v in self.voice_clients if v.channel.guild == reaction.message.guild][0]
                if voice.channel != user.voice.channel:
                    await voice.disconnect()
                    voice = await user.voice.channel.connect()

            if voice.is_playing():
                voice.stop()

            voice.play(discord.FFmpegPCMAudio(data['url']))


    async def on_message(self, message):

        if isinstance(message.channel, discord.DMChannel) or message.author.bot or message.content is None:
            return

        if session.query(Server).filter_by(id=message.guild.id).first() is None:
            s = Server(id=message.guild.id, prefix='?', sounds={}, roles=['off'],)
            session.add(s)
            session.commit()

        try:
            if await self.get_cmd(message):
                session.commit()

        except Exception as e:
            print(e)
            await message.channel.send('Internal exception detected in command, {}'.format(e))


    async def get_cmd(self, message):

        server = session.query(Server).filter_by(id=message.guild.id).first()
        prefix = server.prefix

        command = None

        if message.content[0:len(prefix)] == prefix:
            command = (message.content + ' ')[len(prefix):message.content.find(' ')]
            stripped = (message.content + ' ')[message.content.find(' '):].strip()

        elif self.user.id in map(lambda x: x.id, message.mentions) and len(message.content.split(' ')) > 1:
            command = message.content.split(' ')[1]
            stripped = (message.content + ' ').split(' ', 2)[-1].strip()

        if command is not None:
            self.timeouts[message.guild.id] = time.time()

            if command in self.commands.keys():
                await self.commands[command](message, stripped, server)
                return True

            elif '{} {}'.format(command, stripped).strip() in server.sounds.keys():
                await self.play(message, '{} {}'.format(command, stripped).strip(), server)

        return False


    async def change_prefix(self, message, stripped, server):

        if message.author.guild_permissions.manage_guild:

            if stripped:
                stripped += ' '
                new = stripped[:stripped.find(' ')]

                if len(new) > 5:
                    await message.channel.send('Prefix must be shorter than 5 characters')

                else:
                    server.prefix = new
                    await message.channel.send('Prefix changed to {}'.format(server.prefix))

            else:
                await message.channel.send('Please use this command as `{}prefix <prefix>`'.format(server.prefix))

        else:
            await message.channel.send('Please ensure you have the `manage guild` permission to run this command.')


    async def ping(self, message, stripped, server):
        t = message.created_at.timestamp()
        e = await message.channel.send('pong')
        delta = e.created_at.timestamp() - t

        await e.edit(content='Pong! {}ms round trip'.format(round(delta * 1000)))


    async def help(self, message, stripped, server):
        embed = discord.Embed(title='HELP', color=self.color, description=
        '''
`?help` : view this page

`?info` : view the info page

`?prefix <new prefix>` : change the prefix

`?upload <name>` : upload an MP3 or OGG to the name (will guide you through the process)

`?play <name>` : play back a saved sound

`?list` : view all sounds saved

`?delete <name>` : delete a sound

`?stop` : disconnect the bot from voice

`?link <name>` : link a reaction to a sound

`?unlink <name>` : unlink a sound-reaction pair

`?soundboard` : pull up all sounds with reaction pairs

`?roles` : set the roles that can use the bot

`?<soundname>` : alternative to `?play <soundname>`

All commands can be prefixed with a mention, e.g `@{} help`
        '''.format(self.user.name)
        )
        await message.channel.send(embed=embed)


    async def info(self, message, stripped, server):
        em = discord.Embed(title='INFO', color=self.color, description=
        '''\u200B
  Default prefix: `?`
  Reset prefix: `@{user} prefix ?`
  Help: `{p}help`

  **Welcome to SFX!**
  Developer: <@203532103185465344>
  Find me on https://discord.gg/v6YMfjj and on https://github.com/JellyWX :)

  Framework: `discord.py`
  Hosting provider: OVH

  *If you have enquiries about new features, please send to the discord server*
  *If you have enquiries about bot development for you or your server, please DM me*
        '''.format(user=self.user.name, p=server.prefix)
        )

        await message.channel.send(embed=em)

        await message.add_reaction('📬')


    async def more(self, message, stripped, server):
        em = discord.Embed(title='MORE', description=
        '''
2 ways you can get more sounds for your Discord server:

    - Join our server to keep up on the latest! https://discord.gg/v6YMfjj You will get **one** extra sound for each member that joins the server

    - Upvote our bot over on https://discordbots.org/bot/430384808200372245 You will get **two** extra sounds for each member that upvotes the bot
        ''')

        await message.channel.send(embed=em)


    async def role(self, message, stripped, server):
        if message.author.guild_permissions.manage_guild:

            if stripped == '@everyone':
                server.roles = ['off']

                await message.channel.send('Role blacklisting disabled.')

            elif len(message.role_mentions) > 0:
                roles = [x.id for x in message.role_mentions]

                server.roles = roles

                await message.channel.send('Roles set. Please note members with `Manage Server` permissions will be able to do sounds regardless of roles.')

            else:
                await message.channel.send('Please mention roles or `@everyone` to blacklist roles.')

        else:
            await message.channel.send('You must have permission `Manage Server` to perform this command.')


    async def cleanup(self):
        await self.wait_until_ready()
        while not client.is_closed():
            ids = []

            for guild_id, last_time in self.timeouts.copy().items():
                if time.time() - 300 >= last_time:
                    ids.append(guild_id)
                    del self.timeouts[guild_id]

            for vc in self.voice_clients:
                if len([m for m in vc.channel.members if not m.bot]) == 0 or vc.channel.guild.id in ids:
                    await vc.disconnect()

            await asyncio.sleep(15)


    async def wait_for_file(self, message, stripped, server):
        stripped = stripped.lower()

        if 'off' not in server.roles and not message.author.guild_permissions.manage_guild:
            for role in message.author.roles:
                if role.id in server.roles:
                    break
            else:
                await message.channel.send('You aren\'t allowed to do this. Please tell a moderator to do `{}roles` to set up permissions'.format(server.prefix))
                return

        if len(server.sounds) >= await self.get_sounds(message.guild) and stripped not in server.sounds.keys():
            await message.channel.send('Sorry, but the maximum is {} sounds per server (+{} for your server bonuses). You can either overwrite an existing sound name, use `{prefix}delete` to remove a sound or type `{prefix}more` to learn more ways to get sounds! https://discord.gg/v6YMfjj'.format(self.MAX_SOUNDS, await self.get_sounds(message.guild) - 14, prefix=server.prefix))

        elif stripped == '':
            await message.channel.send('Please provide a name for your sound in the command, e.g `?upload TERMINATION`')

        elif len(stripped) > 20:
            await message.channel.send('Please keep your names concise. You used {}/20 characters.'.format(len(stripped)))

        else:
            await message.channel.send('Saving as: `{}`. Send an MP3/OGG file <500KB or send any other message to cancel.'.format(stripped))

            msg = await self.wait_for('message', check=lambda x: x.author == message.author and x.channel == message.channel)

            if msg.attachments == [] or not msg.attachments[0].filename.lower().endswith(('mp3', 'ogg')):
                await message.channel.send('Please attach an MP3/OGG file following the `{}upload` command. Aborted.'.format(server.prefix))

            elif msg.attachments[0].size > 500000:
                await message.channel.send('Please only send MP3/OGG files that are under 500KB. If your file is an MP3, consider turning it to an OGG for more optimized file size.')

            else:
                async with aiohttp.ClientSession() as cs:
                    async with cs.get(msg.attachments[0].url) as request:
                        mime = magic.from_buffer(await request.read(), mime=True)

                if mime in ['audio/mpeg', 'audio/ogg']:
                    server.sounds[stripped] = {'url' : msg.attachments[0].url, 'emoji' : None}
                    response = await message.channel.send('Sound saved as `{name}`! Use `{prefix}play {name}` to play the sound. If you want to add a reaction binding, react to this message within 30 seconds. Please do not delete the file from discord.'.format(name=stripped, prefix=server.prefix))

                    try:
                        reaction, _ = await client.wait_for('reaction_add', timeout=30, check=lambda r, u: r.message.id == response.id and u == message.author)
                    except:
                        pass
                    else:
                        if isinstance(reaction.emoji, discord.Emoji):
                            if reaction.emoji.animated:
                                server.sounds[stripped]['emoji'] = ('a:' + reaction.emoji.name, reaction.emoji.id)
                            else:
                                server.sounds[stripped]['emoji'] = (reaction.emoji.name, reaction.emoji.id)
                        else:
                            server.sounds[stripped]['emoji'] = reaction.emoji

                        await message.channel.send('Reaction attached! React to any of my messages to bring up the sound.')

                else:
                    await message.channel.send('Please only upload MP3s or OGGs. If you *did* upload an MP3, it is likely corrupted or encoded wrongly. If it isn\'t, please send `file type {}` to us over on the SoundFX Discord'.format(mime))


    async def play(self, message, stripped, server):
        stripped = stripped.lower()

        if 'off' not in server.roles and not message.author.guild_permissions.manage_guild:
            for role in message.author.roles:
                if role.id in server.roles:
                    break
            else:
                await message.channel.send('You aren\'t allowed to do this. Please tell a moderator to do `{}roles` to set up permissions'.format(server.prefix))
                return

        if message.author.voice is None:
            await message.channel.send('You aren\'t in a voice channel.')

        elif stripped == '':
            await message.channel.send('You must specify the sound you wish to play. Use `{}list` to view all sounds.'.format(server.prefix))

        elif stripped not in server.sounds.keys():
            await message.channel.send('Sound `{}` could not be found. Use `{}list` to view all sounds'.format(stripped, server.prefix))

        else:
            if not message.author.voice.channel.permissions_for(message.guild.me).connect:
                await message.channel.send('No permissions to connect to channel.')

            else:
                try:
                    voice = await message.author.voice.channel.connect()
                except discord.errors.ClientException:
                    voice = [v for v in self.voice_clients if v.channel.guild == message.guild][0]
                    if voice.channel != message.author.voice.channel:
                        await voice.disconnect()
                        voice = await message.author.voice.channel.connect()

                if voice.is_playing():
                    voice.stop()

                voice.play(discord.FFmpegPCMAudio(server.sounds[stripped]['url']))


    async def stop(self, message, stripped, server):

        voice = [v for v in self.voice_clients if v.channel.guild == message.guild]
        if len(voice) == 0:
            await message.channel.send('Not connected to a VC!')
        else:
            await voice[0].disconnect()


    async def list(self, message, stripped, server):

        strings = []
        for name, data in server.sounds.items():
            string = name
            if data['emoji'] is None:
                pass
            elif isinstance(data['emoji'], str):
                string += ' ({})'.format(data['emoji'])
            else:
                string += ' (<:{0}:{1}>)'.format(*data['emoji'])

            strings.append(string)

        await message.channel.send('All sounds on server: {}'.format(', '.join(strings)))


    async def link(self, message, stripped, server):
        stripped = stripped.lower()

        if stripped == '':
            await message.channel.send('Please provide the name of the sound you wish to link to an emoji (e.g `?link HEADHUNTER`)')

        elif stripped in server.sounds.keys():
            response = await message.channel.send('Found sound. Please react to this message with the emoji you wish to use!')

            try:
                reaction, _ = await client.wait_for('reaction_add', timeout=120, check=lambda r, u: r.message.id == response.id and u == message.author)
            except:
                pass

            if isinstance(reaction.emoji, discord.Emoji):
                if reaction.emoji.animated:
                    server.sounds[stripped]['emoji'] = ('a:' + reaction.emoji.name, reaction.emoji.id)
                else:
                    server.sounds[stripped]['emoji'] = (reaction.emoji.name, reaction.emoji.id)
            else:
                server.sounds[stripped]['emoji'] = reaction.emoji

            await message.channel.send('Reaction attached! React to any of my messages to bring up the sound.')

        else:
            await message.channel.send('Couldn\'t find sound by name `{}`!'.format(stripped))


    async def unlink(self, message, stripped, server):
        stripped = stripped.lower()

        if stripped == '':
            await message.channel.send('Please provide the name of the sound you wish to unlink from its emoji (e.g `?unlink ULTRAKILL`)')

        elif stripped in server.sounds.keys():
            server.sounds[stripped]['emoji'] = None
            await message.channel.send('Unlinked `{}`'.format(stripped))

        else:
            await message.channel.send('Couldn\'t find sound by name `{}`!'.format(stripped))


    async def delete(self, message, stripped, server):
        stripped = stripped.lower()

        if 'off' not in server.roles and not message.author.guild_permissions.manage_guild:
            for role in message.author.roles:
                if role.id in server.roles:
                    break
            else:
                await message.channel.send('You aren\'t allowed to do this. Please tell a moderator to do `{}roles` to set up permissions'.format(server.prefix))
                return

        if stripped in server.sounds.keys():
            del server.sounds[stripped]
            await message.channel.send('Deleted `{}`. You have used {}/{} sounds.'.format(stripped, len(server.sounds), await self.get_sounds(message.guild)))
        else:
            await message.channel.send('Couldn\'t find sound by name {}. Use `{}list` to view all sounds.'.format(stripped, server.prefix))


    async def soundboard(self, message, stripped, server):

        strings = []
        emojis = []

        for name, data in server.sounds.items():
            if data['emoji'] is None:
                pass
            elif isinstance(data['emoji'], str):
                strings.append('`{}` : {}'.format(name, data['emoji']))
                emojis.append(data['emoji'])
            else:
                strings.append('`{}` : <:{}:{}>'.format(name, *data['emoji']))
                emojis.append(self.get_emoji(data['emoji'][1]))

        m = await message.channel.send(embed=discord.Embed(color=self.color, description='\n\n'.join(strings)))
        for e in emojis:
            await m.add_reaction(e)


client = BotClient()

try:

    client.loop.create_task(client.cleanup())
    client.run(client.config.get('TOKENS', 'bot'))
except Exception as e:
    print('Error detected. Restarting in 15 seconds.')
    print(sys.exc_info())
    time.sleep(15)

    os.execl(sys.executable, sys.executable, *sys.argv)
