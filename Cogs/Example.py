import asyncio
import discord
import random
import datetime
import subprocess
from   discord.ext import commands
from   Cogs import Settings
from   Cogs import DisplayName
from   Cogs import Nullify
from   Cogs import downloader
import youtube_dl
import functools

if not discord.opus.is_loaded():
	# the 'opus' library here is opus.dll on windows
	# or libopus.so on linux in the current directory
	# you should replace this with the location the
	# opus library is located in and with the proper filename.
	# note that on windows this DLL is automatically provided for you
	discord.opus.load_opus('opus')

class Example:

	def __init__(self, bot, settings):
		self.bot = bot
		self.settings = settings

	@commands.command()
	async def add(self, ctx, left : int, right : int):
		"""Adds two numbers together."""
		await ctx.channel.send(left + right)

	@commands.command()
	async def roll(self, ctx, dice : str):
		"""Rolls a dice in NdN format."""
		try:
			rolls, limit = map(int, dice.split('d'))
		except Exception:
			await ctx.channel.send('Format has to be in NdN!')
			return

		result = ', '.join(str(random.randint(1, limit)) for r in range(rolls))
		await ctx.channel.send(result)

	@commands.command(description='For when you wanna settle the score some other way')
	async def choose(self, ctx, *choices : str):
		"""Chooses between multiple choices."""
		msg = random.choice(choices)
		msg = Nullify.clean(msg)
		await ctx.channel.send(msg)

	@commands.command(pass_context=True)
	async def joined(self, ctx, *, member : str = None):
		"""Says when a member joined."""

		# Check if we're suppressing @here and @everyone mentions
		if self.settings.getServerStat(ctx.message.guild, "SuppressMentions").lower() == "yes":
			suppress = True
		else:
			suppress = False
		
		if member is None:
			member = ctx.message.author
			
		if type(member) is str:
			memberName = member
			member = DisplayName.memberForName(memberName, ctx.message.guild)
			if not member:
				msg = 'I couldn\'t find *{}*...'.format(memberName)
				# Check for suppress
				if suppress:
					msg = Nullify.clean(msg)
				await ctx.channel.send(msg)
				return

		await ctx.channel.send('*{}* joined *{}*'.format(DisplayName.name(member), member.joined_at.strftime("%Y-%m-%d %I:%M %p")))

class VoiceEntry:
	def __init__(self, message, player, title, duration, ctx):
		self.requester = message.author
		self.channel = message.channel
		self.player = player
		self.title = title
		self.duration = duration
		self.ctx = ctx

	def __str__(self):
		fmt = '*{}* requested by *{}*'.format(self.title, DisplayName.name(self.requester))
		seconds = self.duration
		if seconds:
			hours = seconds // 3600
			minutes = (seconds % 3600) // 60
			seconds = seconds % 60
			fmt = fmt + ' [length: {:02d}h:{:02d}m:{:02d}s]'.format(round(hours), round(minutes), round(seconds))
		return fmt

class VoiceState:
	def __init__(self, bot, settings):
		self.current = None
		self.voice = None
		self.bot = bot
		self.play_next_song = asyncio.Event()
		self.playlist = []
		self.repeat = False
		self.votes = []
		self.audio_player = self.bot.loop.create_task(self.audio_player_task())
		self.start_time = datetime.datetime.now()
		self.total_playing_time = datetime.datetime.now() - datetime.datetime.now()
		self.is_paused = False
		self.settings = settings

	def is_playing(self):
		if self.voice is None or self.current is None:
			return False

		player = self.voice
		return not player.is_paused() and player.is_playing()

	@property
	def player(self):
		return self.current.player

	def skip(self):
		self.votes = []
		if self.voice.is_playing():
			self.voice.stop()

	def toggle_next(self, error):
		if error:
			print("Error and shit... Should probably handle this one day.")
		self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

	async def audio_player_task(self):
		while True:

			self.play_next_song.clear()

			if len(self.playlist) <= 0:
				await asyncio.sleep(1)
				continue


			self.start_time = datetime.datetime.now()
			self.current = await self.create_youtube_entry(self.playlist[0]["ctx"], self.playlist[0]["raw_song"], self.playlist[0]['song'], self.playlist[0]['duration'])


			#Check if youtube-dl found the song
			if self.current == False:
				del self.playlist[0]
				continue
				
			
			seconds = self.playlist[0]["duration"]
			hours = seconds // 3600
			minutes = (seconds % 3600) // 60
			seconds = seconds % 60

			self.votes = []
			self.votes.append({ 'user' : self.current.requester, 'value' : 'keep' })
			await self.current.channel.send('Now playing *{}* - [{:02d}h:{:02d}m:{:02d}s] - requested by *{}*'.format(self.playlist[0]["song"], round(hours), round(minutes), round(seconds), DisplayName.name(self.playlist[0]['requester'])))

			await self.play_next_song.wait()
			self.total_playing_time = datetime.datetime.now() - datetime.datetime.now()
			if self.repeat:
				self.playlist.append(self.playlist[0])
			del self.playlist[0]


	async def create_youtube_entry(self, ctx, song: str, title: str, duration):

		opts = {
			'buffersize': '20000000',
			'f': 'bestaudio',
			'default_search': 'auto',
			'quiet': True
		}
		volume = self.settings.getServerStat(ctx.message.guild, "Volume")
		defVolume = self.settings.getServerStat(ctx.message.guild, "DefaultVolume")
		if volume:
			volume = float(volume)
		else:
			if defVolume:
				volume = float(self.settings.getServerStat(ctx.message.guild, "DefaultVolume"))
			else:
				# No volume or default volume in settings - go with 60%
				volume = 0.6

		try:
			
			# Create a rewrite player because why not...
			# PS - Look at all these shitty attempts?!
			#
			# audioProc = subprocess.Popen( [ "youtube-dl", "-q", "-o", "-", song ], stdout=subprocess.PIPE )
			# before_args = "-reconnect_streamed 1"
			# audioProc = subprocess.Popen( "youtube-dl -o - \"" + song + "\"", shell=True, stdout=subprocess.PIPE )
			# ffsource = discord.FFmpegPCMAudio(audioProc.stdout, before_options=before_args, pipe=True)
			# audioProc = subprocess.Popen( "youtube-dl -o - \"" + song + "\" | ffmpeg -i pipe:0 -ac 2 -f s16le -ar 48000 pipe:1 -reconnect_streamed 1", stdout=subprocess.PIPE, shell=True )
			#
			# VICTORY!
			#
			audioProc = subprocess.Popen( "ffmpeg -hide_banner -loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -i \"" + song + "\" -ac 2 -f s16le -ar 48000 pipe:1", stdout=subprocess.PIPE, shell=True )
			rawAudio = discord.PCMAudio(audioProc.stdout)
			volumeSource = discord.PCMVolumeTransformer(rawAudio)
			#
			# ffsource = discord.FFmpegPCMAudio(song, before_options=before_args, pipe=True)
			# volumeSource = discord.PCMVolumeTransformer(ffsource)
			self.voice.play(volumeSource, after=self.toggle_next)

		except Exception as e:
			fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'.format(type(e).__name__, e)
			await ctx.channel.send(fmt)
			return False
		else:
			#self.voice.volume = volume
			self.voice.source.volume = volume
			entry = VoiceEntry(ctx.message, self.voice, title, duration, ctx)
			return entry

class Music:
	"""Voice related commands.

	Works in multiple servers at once.
	"""
	def __init__(self, bot, settings):
		self.bot = bot
		self.voice_states = {}
		self.settings = settings
		self.downloader = downloader.Downloader()

	def get_voice_state(self, server):
		state = self.voice_states.get(server.id)
		if state is None:
			state = VoiceState(self.bot, self.settings)
			self.voice_states[server.id] = state

		return state

	async def create_voice_client(self, channel):
		voice = await channel.connect()
		state = self.get_voice_state(channel.guild)
		state.voice = voice

	def __unload(self):
		for state in self.voice_states.values():
			try:
				state.audio_player.cancel()
				if state.voice:
					self.bot.loop.create_task(state.voice.disconnect())
			except:
				pass

	async def _user_in_voice(self, ctx):
		# Check if we're in a voice channel
		# voiceChannel = self.bot.voice_client_in(ctx.message.guild)
		voiceChannel = None
		for client in self.bot.voice_clients:
			if client.guild == ctx.guild:
				# Found it?
				voiceChannel = client.channel

		if not voiceChannel:
			# We're not in a voice channel
			return None

		channel = ctx.message.channel
		author  = ctx.message.author
		server  = ctx.message.guild

		# Check if user is admin
		isAdmin = ctx.message.author.permissions_in(ctx.message.channel).administrator
		if not isAdmin:
			checkAdmin = self.settings.getServerStat(ctx.message.guild, "AdminArray")
			for role in ctx.message.author.roles:
				for aRole in checkAdmin:
					# Get the role that corresponds to the id
					if str(aRole['ID']) == str(role.id):
						isAdmin = True
		if isAdmin:
			return True
		
		# Here, user is not admin - make sure they're in the voice channel
		# Check if the user in question is in a voice channel
		if ctx.message.author in voiceChannel.members:
			return True
		# If we're here - we're not admin, and not in the same channel, deny
		return False


	@commands.command(pass_context=True, no_pm=True)
	async def join(self, ctx, *, channel : discord.VoiceChannel):
		"""Joins a voice channel."""
		try:
			await self.create_voice_client(channel)
		except discord.ClientException:
			await ctx.channel.send('Already in a voice channel...')
		except discord.InvalidArgument:
			await ctx.channel.send('This is not a voice channel...')
		else:
			await ctx.channel.send('Ready to play audio in ' + channel.name)

	@commands.command(pass_context=True, no_pm=True)
	async def summon(self, ctx):
		"""Summons the bot to join your voice channel."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return

		state = self.get_voice_state(ctx.message.guild)

		if state.is_playing():
			await ctx.channel.send('I\`m already playing in a channel, Join me there instead! :D')
			return

		summoned_channel = ctx.message.author.voice.channel
		if summoned_channel is None:
			await ctx.channel.send('You are not in a voice channel.')
			return False

		if state.voice is None:
			state.voice = await summoned_channel.connect() # self.bot.join_voice_channel(summoned_channel)
		else:
			await state.voice.move_to(summoned_channel)

		return True

	@commands.command(pass_context=True, no_pm=True)
	async def play(self, ctx, *, song : str = None):
		"""Plays a song.

		If there is a song currently in the queue, then it is
		queued until the next song is done playing.

		This command automatically searches as well from YouTube.
		The list of supported sites can be found here:
		https://rg3.github.io/youtube-dl/supportedsites.html
		"""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return

		if song == None:
			await ctx.channel.send('Sweet.  I will *totally* add nothing to my list.  Thanks for the *superb* musical suggestion...')
			return

		state = self.get_voice_state(ctx.message.guild)
		
		if state.voice is None:
			success = await ctx.invoke(self.summon)
			if not success:
				return

		#await state.songs.put(entry)

		opts = {
			'buffersize': '20000000',
			'f': 'bestaudio',
			'default_search': 'auto',
			'quiet': True
		}

		song = song.strip('<>')

		#info = await self.bot.loop.run_in_executor(None, func)
		info = await self.downloader.extract_info(self.bot.loop, song, download=False, process=False)

		if info.get('url', '').startswith('ytsearch'):
			info = await self.downloader.extract_info(
				self.bot.loop,
				song,
				download=False,
				process=True,    # ASYNC LAMBDAS WHEN
				retry_on_error=True
			)
			if not info:
				return
			if not all(info.get('entries', [])):
				# empty list, no data
				return
			song = info['entries'][0]['webpage_url']
			info = await self.downloader.extract_info(self.bot.loop, song, download=False, process=False)

		if "entries" in info:
			info = info['entries'][0]
		
		seconds = info.get('duration')
		hours = seconds // 3600
		minutes = (seconds % 3600) // 60
		seconds = seconds % 60
		
		# state.playlist.append({ 'song': info.get('title'), 'duration': info.get('duration'), 'ctx': ctx, 'requester': ctx.message.author, 'raw_song': song})
		state.playlist.append({ 'song': info.get('title'), 'duration': info.get('duration'), 'ctx': ctx, 'requester': ctx.message.author, 'raw_song': info['formats'][len(info['formats'])-1]['url']})
		await ctx.channel.send('Enqueued - *{}* - [{:02d}h:{:02d}m:{:02d}s] - requested by *{}*'.format(info.get('title'), round(hours), round(minutes), round(seconds), DisplayName.name(ctx.message.author)))

	
	@commands.command(pass_context=True, no_pm=True)
	async def repeat(self, ctx, *, repeat = None):
		"""Checks or sets whether to repeat or not."""
		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return

		state = self.get_voice_state(ctx.message.guild)

		if repeat == None:
			# Just checking
			if state.repeat:
				await ctx.channel.send('Repeat is currently **on**.')
			else:
				await ctx.channel.send('Repeat is currently **off**.')
			return
		elif repeat.lower() == "on" or repeat.lower() == "yes" or repeat.lower() == "true":
			# Trying to enable repeat
			if state.repeat:
				await ctx.channel.send('Repeat will remain **on**.')
			else:
				state.repeat = True
				await ctx.channel.send('Repeat is now **on**.')
			return
		elif repeat.lower() == "off" or repeat.lower() == "no" or repeat.lower() == "false":
			# Trying to disable repeat
			if not state.repeat:
				await ctx.channel.send('Repeat will remain **off**.')
			else:
				state.repeat = False
				await ctx.channel.send('Repeat is now **off**.')
			return
		else:
			# No working variable - let's just output repeat status
			if state.repeat:
				await ctx.channel.send('Repeat is currently **on**.')
			else:
				await ctx.channel.send('Repeat is currently **off**.')
			return


	@commands.command(pass_context=True, no_pm=True)
	async def willrepeat(self, ctx):
		"""Displays whether or not repeat is active."""
		# Check user credentials
		state = self.get_voice_state(ctx.message.guild)
		if state.repeat:
			await ctx.channel.send('Repeat is currently **on**.')
		else:
			await ctx.channel.send('Repeat is currently **off**.')



	@commands.command(pass_context=True, no_pm=True)
	async def volume(self, ctx, value = None):
		"""Sets the volume of the currently playing song."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return
		
		if not value == None:
			# We have a value, let's make sure it's valid
			try:
				value = int(value)
			except Exception:
				await ctx.channel.send('Volume must be an integer.')
				return

		state = self.get_voice_state(ctx.message.guild)
		if state.is_playing():
			player = state.voice
			if value == None:
				# No value - output current volume
				await ctx.channel.send('Current volume is {:.0%}'.format(player.source.volume))
				return
			if value < 0:
				value = 0
			if value > 100:
				value = 100
			player.source.volume = value / 100
			self.settings.setServerStat(ctx.message.guild, "Volume", player.source.volume)
			await ctx.channel.send('Set the volume to {:.0%}'.format(player.source.volume))
		else:
			# Not playing anything
			await ctx.channel.send('Not playing anything right now...')
			return

	@commands.command(pass_context=True, no_pm=True)
	async def pause(self, ctx):
		"""Pauses the currently played song."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		state = self.get_voice_state(ctx.message.guild)
		if state.voice.is_playing():
			player = state.voice
			player.pause()
			state.total_playing_time += (datetime.datetime.now() - state.start_time)
			state.is_paused = True

	@commands.command(pass_context=True, no_pm=True)
	async def resume(self, ctx):
		"""Resumes the currently played song."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		state = self.get_voice_state(ctx.message.guild)
		if state.voice.is_paused():
			player = state.voice
			player.resume()
			state.start_time = datetime.datetime.now()
			state.is_paused = False


	@commands.command(pass_context=True, no_pm=True)
	async def stop(self, ctx):
		"""Stops playing audio and leaves the voice channel.

		This also clears the queue.
		"""

		channel = ctx.message.channel
		author  = ctx.message.author
		server  = ctx.message.guild

		# Check for role requirements
		requiredRole = self.settings.getServerStat(server, "RequiredStopRole")
		if requiredRole == "":
			#admin only
			isAdmin = ctx.message.author.permissions_in(ctx.message.channel).administrator
			if not isAdmin:
				checkAdmin = self.settings.getServerStat(ctx.message.guild, "AdminArray")
				for role in ctx.message.author.roles:
					for aRole in checkAdmin:
						# Get the role that corresponds to the id
						if str(aRole['ID']) == str(role.id):
							isAdmin = True
			if not isAdmin:
				await channel.send('You do not have sufficient privileges to access this command.')
				return
		else:
			#role requirement
			hasPerms = False
			for role in author.roles:
				if str(role.id) == str(requiredRole):
					hasPerms = True
			if not hasPerms:
				await channel.send('You do not have sufficient privileges to access this command.')
				return

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		server = ctx.message.guild
		state = self.get_voice_state(server)

		self.settings.setServerStat(ctx.message.guild, "Volume", None)

		if state.is_playing():
			player = state.voice
			player.stop()

		try:
			state.audio_player.cancel()
			del self.voice_states[server.id]
			state.playlist = []
			state.repeat = False
			await state.voice.disconnect()
		except:
			pass

	@commands.command(pass_context=True, no_pm=True)
	async def skip(self, ctx):
		"""Vote to skip a song. The song requester can automatically skip."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		state = self.get_voice_state(ctx.message.guild)
		if not state.voice.is_playing():
			await ctx.channel.send('Not playing anything right now...')
			return

		# Get song requester
		state = self.get_voice_state(ctx.message.guild)
		requester = state.playlist[0]['requester']
		requesterAdmin = requester.permissions_in(ctx.message.channel).administrator
		if not requesterAdmin:
			checkAdmin = self.settings.getServerStat(ctx.message.guild, "AdminArray")
			for role in requester.roles:
				for aRole in checkAdmin:
					# Get the role that corresponds to the id
					if str(aRole['ID']) == str(role.id):
						requesterAdmin = True


		# Check if user is admin
		isAdmin = ctx.message.author.permissions_in(ctx.message.channel).administrator
		if not isAdmin:
			checkAdmin = self.settings.getServerStat(ctx.message.guild, "AdminArray")
			for role in ctx.message.author.roles:
				for aRole in checkAdmin:
					# Get the role that corresponds to the id
					if str(aRole['ID']) == str(role.id):
						isAdmin = True
		if isAdmin:
			# Check if the requester is also an admin
			if not requesterAdmin:
				# Auto skip.
				await ctx.channel.send('My *Admin-Override* module is telling me to skip.')
				state.skip()
				return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			vote["value"] = 'skip'
		else:
			state.votes.append({ 'user': ctx.message.author, 'value': 'skip' })
		
		result = await self._vote_stats(ctx)

		if(result["total_skips"] >= result["total_keeps"]):
			await ctx.channel.send('Looks like skips WINS! sorry guys, skipping the song...')
			state.skip()
		# if voter == state.current.requester:
		# 	await ctx.channel.send('Requester requested skipping...')
		# 	state.skip()
		# elif voter.id not in state.skip_votes:
		# 	state.skip_votes.add(voter.id)
		# 	total_votes = len(state.skip_votes)
		# 	if total_votes >= 3:
		# 		await ctx.channel.send('Skip vote passed, skipping the song...')
		# 		state.skip()
		# 	else:
		# 		await ctx.channel.send('Skip vote added, currently at [{}/3]'.format(total_votes))
		# else:
		# 	await ctx.channel.send('You have already voted to skip this.')

	# @commands.command(pass_context=True, no_pm=True)
	# async def keep(self, ctx):
	# 	"""Vote to keep a song. The song requester can automatically skip.
	# 	"""

	@commands.command(pass_context=True, no_pm=True)
	async def keep(self, ctx):
		"""Vote to keep a song."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		state = self.get_voice_state(ctx.message.guild)
		if not state.is_playing():
			await ctx.channel.send('Not playing anything right now...')
			return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			vote["value"] = 'keep'
		else:
			state.votes.append({ 'user': ctx.message.author, 'value': 'keep' })
		
		await self._vote_stats(ctx)

	
	@commands.command(pass_context=True, no_pm=True)
	async def unvote(self, ctx):
		"""Remove your song vote."""
		state = self.get_voice_state(ctx.message.guild)
		if not state.is_playing():
			await ctx.channel.send('Not playing anything right now...')
			return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			for voted in state.votes:
				if(ctx.message.author == voted["user"]):
					# Found our vote - remove it
					state.votes.remove(voted)
		else:
			await ctx.channel.send('Your non-existent vote has been removed.')

		result = await self._vote_stats(ctx)

		if(result["total_skips"] >= result["total_keeps"]):
			await ctx.channel.send('Looks like skips WINS! sorry guys, skipping the song...')
			state.skip()
		
	
	@commands.command(pass_context=True, no_pm=True)
	async def vote_stats(self, ctx):
		return await self._vote_stats(ctx)

	async def _vote_stats(self, ctx):
		state = self.get_voice_state(ctx.message.guild)
		total_skips = 0
		total_keeps = 0
		for vote in state.votes:
			XP = self.settings.getUserStat(vote["user"], ctx.message.guild, "XP")
			if vote["value"] == 'skip':
				total_skips = total_skips + XP
			else:
				total_keeps = total_keeps + XP
		
		await ctx.channel.send('**Total Votes**:\nKeeps Score: *{}*\nSkips Score : *{}*'.format(total_keeps, total_skips))

		return {'total_skips': total_skips, 'total_keeps': total_keeps}

	async def has_voted(self, user , votes):

		for vote in votes:
			if(user == vote["user"]):
				return vote

		return False


	@commands.command(pass_context=True, no_pm=True)
	async def playing(self, ctx):
		"""Shows info about currently playing."""

		state = self.get_voice_state(ctx.message.guild)
		if state.voice == None or not state.voice.is_playing():
			await ctx.channel.send('Not playing anything.')
		else:
			diff_time = state.total_playing_time  + (datetime.datetime.now() - state.start_time)

			if state.is_paused:
				diff_time = state.total_playing_time

			seconds = diff_time.total_seconds()
			hours = seconds // 3600
			minutes = (seconds % 3600) // 60
			seconds = seconds % 60

			#percent = diff_time.total_seconds() / state.current.player.duration * 100
			dSeconds = state.playlist[0]["duration"]
			percent = diff_time.total_seconds() / dSeconds * 100

			await ctx.channel.send('Now playing - *{}* [at {:02d}h:{:02d}m:{:02d}s] - {}%'.format(state.playlist[0]["song"],round(hours), round(minutes), round(seconds), round(percent, 2)))


	@commands.command(pass_context=True, no_pm=True)
	async def playlist(self, ctx):
		"""Shows current songs in the playlist."""
		state = self.get_voice_state(ctx.message.guild)
		if len(state.playlist) <= 0:
						await ctx.channel.send('No songs in the playlist')
						return
		# Get our length
		totalSongs = len(state.playlist)
		if totalSongs > 15:
			playlist_string  = '**__Current Playlist (showing 1-15 out of {}):__**\n\n'.format(totalSongs)
		else:
			playlist_string  = '**__Current Playlist (1-{}):__**\n\n'.format(totalSongs)
		#playlist_string += '```Markdown\n'
		count = 1
		total_seconds = 0
		for i in state.playlist:
			if count > 15:
				break

			seconds = i["duration"]
			total_seconds += seconds
			hours = seconds // 3600
			minutes = (seconds % 3600) // 60
			seconds = seconds % 60

			playlist_string += '{}. *{}* - [{:02d}h:{:02d}m:{:02d}s] - requested by *{}*\n'.format(count, str(i["song"]),round(hours), round(minutes), round(seconds), DisplayName.name(i['requester']))
			count = count + 1
		#playlist_string += '```'
		hours = total_seconds // 3600
		minutes = (total_seconds % 3600) // 60
		seconds = total_seconds % 60
		playlist_string  += '\n**Total Time: **[{:02d}h:{:02d}m:{:02d}s]'.format(round(hours), round(minutes), round(seconds))
		if state.repeat:
			playlist_string += '\nRepeat is **on**'

		await ctx.channel.send(playlist_string)


	@commands.command(pass_context=True, no_pm=True)
	async def removesong(self, ctx, idx : int = None):
		"""Removes a song in the playlist by the index."""

		# Check user credentials
		userInVoice = await self._user_in_voice(ctx)
		if userInVoice == False:
			await ctx.channel.send('You\'ll have to join the same voice channel as me to use that.')
			return
		elif userInVoice == None:
			await ctx.channel.send('I\'m not in a voice channel.  Use the `{}summon`, `{}join [channel]` or `{}play [song]` commands to start playing something.'.format(ctx.prefix, ctx.prefix, ctx.prefix))
			return

		channel = ctx.message.channel
		author  = ctx.message.author
		server  = ctx.message.guild

		canRemove = False
		# Check for role requirements
		requiredRole = self.settings.getServerStat(server, "RequiredStopRole")
		if requiredRole == "":
			#admin only
			isAdmin = author.permissions_in(channel).administrator
			if isAdmin:
				canRemove = True
		else:
			#role requirement
			hasPerms = False
			for role in author.roles:
				if str(role.id) == str(requiredRole):
					hasPerms = True
			if hasPerms:
				canRemove = True

		if idx == None:
			await ctx.channel.send('Umm... Okay.  I successfully removed *0* songs from the playlist.  That\'s what you wanted, right?')
			return

		if not type(idx) == int:
			await ctx.channel.send('Indexes need to be integers, yo.')
			return

		idx = idx - 1
		state = self.get_voice_state(ctx.message.guild)
		if idx < 0 or idx >= len(state.playlist):
			await ctx.channel.send('Invalid song index, please refer to `{}playlist` for the song index.'.format(ctx.prefix))
			return
		current = state.playlist[idx]
		if idx == 0:
			await ctx.channel.send('Cannot delete currently playing song, use `{}skip` instead'.format(ctx.prefix))
			return
		if not current['requester'].id == ctx.message.author.id:
			# Not the owner of the song - check if we *can* delete
			if not canRemove:
				await channel.send('You do not have sufficient privileges to remove *other* users\' songs.')
				return
		await ctx.channel.send('Deleted *{}* from playlist'.format(str(current["song"])))
		del state.playlist[idx]
