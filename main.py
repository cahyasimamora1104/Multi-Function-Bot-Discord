import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime
import os
from dotenv import load_dotenv
import asyncio
import yt_dlp

# =====================
# Load environment variables
# =====================
load_dotenv()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# =====================
# Helpers (ephemeral for hybrid)
# =====================
async def send_ephemeral(ctx: commands.Context, content: str = None, *, embed: discord.Embed | None = None):
    """Safely send ephemeral response if this is an interaction; else fall back to normal send."""
    try:
        if hasattr(ctx, 'interaction') and ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=True)
        elif hasattr(ctx, 'interaction') and ctx.interaction:
            await ctx.followup.send(content=content, embed=embed, ephemeral=True)
        else:
            await ctx.send(content=content, embed=embed)
    except Exception:
        # Fallback just in case
        await ctx.send(content=content, embed=embed)

# =====================
# Database setup - DIPERBAIKI
# =====================
async def init_db():
    async with aiosqlite.connect('bot_data.db') as db:
        # Members table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS members (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                joined_at TEXT,
                messages_sent INTEGER DEFAULT 0
            )
        ''')

        # Tickets table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                created_at TEXT,
                status TEXT DEFAULT 'open',
                category TEXT
            )
        ''')

        # Welcome settings table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS welcome_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message TEXT,
                role_id INTEGER
            )
        ''')

        # Ticket settings table - DIPERBAIKI dengan ALTER TABLE
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                category_id INTEGER
            )
        ''')

        # Cek jika kolom category_id belum ada di tabel lama
        try:
            await db.execute('SELECT category_id FROM ticket_settings LIMIT 1')
        except aiosqlite.OperationalError:
            # Jika kolom tidak ada, alter table
            await db.execute('ALTER TABLE ticket_settings ADD COLUMN category_id INTEGER')
            print("Added category_id column to ticket_settings table")

        await db.commit()

# =====================
# Music player setup (yt_dlp + FFmpeg)
# =====================
yt_dlp.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

# Only pass supported kwargs to FFmpegPCMAudio
ffmpeg_options = {
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
        return cls(source, data=data)

# =====================
# Music queue system (per-guild)
# =====================
class QueueState:
    def __init__(self):
        self.queues: dict[int, list[YTDLSource]] = {}
        self.text_channels: dict[int, int] = {}  # guild_id -> last text channel id where /play used

    def get_queue(self, guild_id: int) -> list:
        return self.queues.setdefault(guild_id, [])

    def clear_queue(self, guild_id: int):
        self.queues[guild_id] = []

    def set_text_channel(self, guild_id: int, channel_id: int):
        self.text_channels[guild_id] = channel_id

    def get_text_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = self.text_channels.get(guild.id)
        if cid:
            return guild.get_channel(cid)
        # fallback: first text channel
        return next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

music_state = QueueState()

# =====================
# Bot Events
# =====================
@bot.event
async def on_ready():
    print(f'{bot.user} telah online!')
    await init_db()
    try:
        bot.add_view(TicketOptionsView())
        bot.add_view(CloseTicketView())
        await bot.tree.sync()
        print("Slash commands synced successfully!")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")

# Welcome system dengan database
@bot.event
async def on_member_join(member: discord.Member):
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute(
            'INSERT OR IGNORE INTO members (user_id, username, joined_at) VALUES (?, ?, ?)',
            (member.id, str(member), datetime.now().isoformat())
        )
        cursor = await db.execute(
            'SELECT channel_id, message, role_id FROM welcome_settings WHERE guild_id = ?',
            (member.guild.id,)
        )
        welcome_settings = await cursor.fetchone()
        await db.commit()

    if welcome_settings:
        channel_id, welcome_message, role_id = welcome_settings
        # Send welcome
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                message = (welcome_message or "🎉 Selamat datang {user} di {guild}!")
                # Template placeholders
                message = (message
                           .replace('{user}', member.mention)
                           .replace('{username}', member.name)
                           .replace('{guild}', member.guild.name)
                           .replace('{member_count}', str(member.guild.member_count)))

                embed = discord.Embed(title="Selamat Datang!", description=message, color=discord.Color.green())
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="Member #", value=member.guild.member_count)
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass
        # Give role
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto welcome role")
                except Exception:
                    pass

# =====================
# Ticket system dengan kategori khusus - DIPERBAIKI
# =====================
class TicketOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🛒 Beli", style=discord.ButtonStyle.primary, custom_id="persistent_ticket_beli")
    async def ticket_beli(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "beli")

    @discord.ui.button(label="🆘 Support", style=discord.ButtonStyle.secondary, custom_id="persistent_ticket_support")
    async def ticket_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "support")

    async def create_ticket(self, interaction: discord.Interaction, category_type: str):
        await interaction.response.defer(ephemeral=True)

        # Cek existing ticket
        async with aiosqlite.connect('bot_data.db') as db:
            cursor = await db.execute(
                'SELECT channel_id FROM tickets WHERE user_id = ? AND status = "open"',
                (interaction.user.id,)
            )
            open_ticket = await cursor.fetchone()

        if open_ticket:
            channel = interaction.guild.get_channel(open_ticket[0])
            if channel:
                await interaction.followup.send(
                    f"❌ Kamu sudah memiliki ticket yang terbuka! Silakan gunakan {channel.mention}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send("❌ Kamu sudah memiliki ticket yang terbuka!", ephemeral=True)
            return

        # Dapatkan kategori dari database - DIPERBAIKI query
        async with aiosqlite.connect('bot_data.db') as db:
            cursor = await db.execute(
                'SELECT category_id FROM ticket_settings WHERE guild_id = ?',
                (interaction.guild.id,)
            )
            category_setting = await cursor.fetchone()

        category_id = category_setting[0] if category_setting else None

        if category_id:
            category = interaction.guild.get_channel(category_id)
            if not category or not isinstance(category, discord.CategoryChannel):
                category = await self.create_ticket_category(interaction.guild)
                async with aiosqlite.connect('bot_data.db') as db:
                    await db.execute(
                        'UPDATE ticket_settings SET category_id = ? WHERE guild_id = ?',
                        (category.id, interaction.guild.id)
                    )
                    await db.commit()
        else:
            category = await self.create_ticket_category(interaction.guild)
            async with aiosqlite.connect('bot_data.db') as db:
                await db.execute(
                    'INSERT OR REPLACE INTO ticket_settings (guild_id, category_id) VALUES (?, ?)',
                    (interaction.guild.id, category.id)
                )
                await db.commit()

        # Setup permissions untuk ticket channel
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, manage_channels=True)
        }

        try:
            ticket_channel = await interaction.guild.create_text_channel(
                f"{category_type}-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Saya tidak memiliki izin untuk membuat channel!", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Error membuat channel: {str(e)}", ephemeral=True)
            return

        # Simpan ke database
        async with aiosqlite.connect('bot_data.db') as db:
            await db.execute(
                'INSERT INTO tickets (user_id, channel_id, created_at, category) VALUES (?, ?, ?, ?)',
                (interaction.user.id, ticket_channel.id, datetime.now().isoformat(), category_type)
            )
            await db.commit()

        # Kirim embed
        if category_type == "beli":
            title = "🛒 Ticket Pembelian"
            description = f"Halo {interaction.user.mention}! Silakan jelaskan apa yang ingin Anda beli."
            color = discord.Color.green()
        else:
            title = "🆘 Ticket Support"
            description = f"Halo {interaction.user.mention}! Silakan jelaskan masalah Anda."
            color = discord.Color.blue()

        embed = discord.Embed(title=title, description=description, color=color)
        embed.add_field(name="Dibuat oleh", value=interaction.user.mention, inline=True)
        embed.add_field(name="Waktu", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.set_footer(text=f"Ticket ID: {ticket_channel.id}")

        view = CloseTicketView()
        try:
            await ticket_channel.send(embed=embed, view=view)
            await interaction.followup.send(f"✅ Ticket berhasil dibuat! {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"✅ Ticket dibuat di {ticket_channel.mention}, tapi ada error mengirim embed: {str(e)}",
                ephemeral=True
            )

    async def create_ticket_category(self, guild: discord.Guild):
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True, manage_messages=True)
        }
        category = await guild.create_category("🎫 Tickets", overwrites=overwrites)
        return category

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Tutup Ticket", style=discord.ButtonStyle.danger, custom_id="persistent_close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        async with aiosqlite.connect('bot_data.db') as db:
            await db.execute('UPDATE tickets SET status = "closed" WHERE channel_id = ?', (interaction.channel.id,))
            await db.commit()
        try:
            await interaction.channel.delete()
        except discord.Forbidden:
            await interaction.followup.send("❌ Saya tidak memiliki izin untuk menghapus channel ini!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error menghapus channel: {str(e)}", ephemeral=True)

# =====================
# Dashboard & Setup Commands
# =====================
@bot.hybrid_command(name="dashboard", description="Panel kontrol admin untuk mengatur bot")
@commands.has_permissions(administrator=True)
async def dashboard(ctx: commands.Context):
    embed = discord.Embed(title="🛠️ Admin Dashboard", description="Pilih opsi di bawah untuk mengatur bot:", color=discord.Color.blue())
    view = DashboardView()
    await send_ephemeral(ctx, embed=embed)
    # For non-interaction fallback, also send the view
    if not (hasattr(ctx, 'interaction') and ctx.interaction):
        await ctx.send(embed=embed, view=view)

class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="🎫 Setup Ticket", style=discord.ButtonStyle.primary)
    async def setup_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🎫 Setup Ticket System", description="Pilih channel untuk panel ticket:", color=discord.Color.blue())
        text_channels = [channel for channel in interaction.guild.text_channels]
        if not text_channels:
            await interaction.response.send_message("❌ Tidak ada text channel yang tersedia!", ephemeral=True)
            return

        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Pilih channel untuk panel ticket...", min_values=1, max_values=1)
        for channel in text_channels[:25]:
            select.add_option(label=f"#{channel.name}", value=str(channel.id), description=f"Channel: {channel.name}")

        async def select_callback(inner_interaction: discord.Interaction):
            channel_id = int(select.values[0])
            channel = inner_interaction.guild.get_channel(channel_id)
            if channel:
                panel = discord.Embed(title="🎫 Ticket System", description="Klik tombol di bawah untuk membuka ticket:", color=discord.Color.blue())
                view_panel = TicketOptionsView()
                await channel.send(embed=panel, view=view_panel)
                async with aiosqlite.connect('bot_data.db') as db:
                    await db.execute('INSERT OR REPLACE INTO ticket_settings (guild_id, channel_id) VALUES (?, ?)', (inner_interaction.guild.id, channel_id))
                    await db.commit()
                await inner_interaction.response.edit_message(content=f"✅ Panel ticket berhasil dipasang di {channel.mention}!", embed=None, view=None)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="👋 Setup Welcome", style=discord.ButtonStyle.secondary)
    async def setup_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="👋 Setup Welcome System", description="Pilih channel untuk welcome message:", color=discord.Color.green())
        text_channels = [channel for channel in interaction.guild.text_channels]
        if not text_channels:
            await interaction.response.send_message("❌ Tidak ada text channel yang tersedia!", ephemeral=True)
            return

        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Pilih channel untuk welcome...", min_values=1, max_values=1)
        for channel in text_channels[:25]:
            select.add_option(label=f"#{channel.name}", value=str(channel.id), description=f"Channel: {channel.name}")

        async def select_callback(inner_interaction: discord.Interaction):
            channel_id = int(select.values[0])
            channel = inner_interaction.guild.get_channel(channel_id)
            if channel:
                # Lanjut ke pemilihan role
                embed_role = discord.Embed(title="👋 Pilih Role untuk Member Baru", description="Pilih role yang akan diberikan ke member baru:", color=discord.Color.green())
                roles = [role for role in inner_interaction.guild.roles if not role.is_default()][:25]
                if not roles:
                    await inner_interaction.response.send_message("❌ Tidak ada role yang tersedia!", ephemeral=True)
                    return

                role_view = discord.ui.View()
                role_select = discord.ui.Select(placeholder="Pilih role...", min_values=1, max_values=1)
                for role in roles:
                    role_select.add_option(label=role.name, value=str(role.id), description=f"Role: {role.name}")

                async def role_callback(role_interaction: discord.Interaction):
                    role_id = int(role_select.values[0])
                    role = role_interaction.guild.get_role(role_id)
                    if role:
                        async with aiosqlite.connect('bot_data.db') as db:
                            await db.execute('INSERT OR REPLACE INTO welcome_settings (guild_id, channel_id, role_id) VALUES (?, ?, ?)', (role_interaction.guild.id, channel_id, role_id))
                            await db.commit()
                        embed_done = discord.Embed(title="✅ Welcome System Setup Complete", description="Pengaturan welcome berhasil disimpan!", color=discord.Color.green())
                        embed_done.add_field(name="Channel", value=channel.mention, inline=True)
                        embed_done.add_field(name="Role", value=role.mention, inline=True)
                        await role_interaction.response.edit_message(embed=embed_done, view=None)

                role_select.callback = role_callback
                role_view.add_item(role_select)
                await inner_interaction.response.edit_message(embed=embed_role, view=role_view)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.edit_message(embed=embed, view=view)

# =====================
# Welcome: set custom message command
# =====================
@bot.hybrid_command(name="set_welcome_message", description="Set teks welcome kustom dengan placeholder {user}, {username}, {guild}, {member_count}")
@commands.has_permissions(administrator=True)
@app_commands.describe(message="Teks welcome. Contoh: Selamat datang {user} di {guild}! Kamu member ke-{member_count}.")
async def set_welcome_message(ctx: commands.Context, *, message: str):
    async with aiosqlite.connect('bot_data.db') as db:
        # Pastikan ada row; gunakan existing channel/role jika ada
        cursor = await db.execute('SELECT channel_id, role_id FROM welcome_settings WHERE guild_id = ?', (ctx.guild.id,))
        row = await cursor.fetchone()
        channel_id = row[0] if row else None
        role_id = row[1] if row else None
        await db.execute('INSERT OR REPLACE INTO welcome_settings (guild_id, channel_id, message, role_id) VALUES (?, ?, ?, ?)', (ctx.guild.id, channel_id, message, role_id))
        await db.commit()

    await send_ephemeral(ctx, "✅ Pesan welcome berhasil diatur!")

# =====================
# Command untuk menggunakan kategori khusus - DIPERBAIKI
# =====================
@bot.hybrid_command(name="set_ticket_category", description="Set kategori khusus untuk ticket")
@commands.has_permissions(administrator=True)
@app_commands.describe(category_id="ID kategori untuk ticket (kosongkan untuk buat baru)")
async def set_ticket_category(ctx: commands.Context, category_id: str | None = None):
    if category_id:
        try:
            category = ctx.guild.get_channel(int(category_id))
            if not category or not isinstance(category, discord.CategoryChannel):
                await send_ephemeral(ctx, "❌ ID kategori tidak valid!")
                return
        except ValueError:
            await send_ephemeral(ctx, "❌ Format ID tidak valid!")
            return
    else:
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True, manage_messages=True)
        }
        category = await ctx.guild.create_category("🎫 Tickets", overwrites=overwrites)

    async with aiosqlite.connect('bot_data.db') as db:
        cursor = await db.execute('SELECT guild_id FROM ticket_settings WHERE guild_id = ?', (ctx.guild.id,))
        existing = await cursor.fetchone()
        if existing:
            await db.execute('UPDATE ticket_settings SET category_id = ? WHERE guild_id = ?', (category.id, ctx.guild.id))
        else:
            await db.execute('INSERT INTO ticket_settings (guild_id, category_id) VALUES (?, ?)', (ctx.guild.id, category.id))
        await db.commit()

    await ctx.send(f"✅ Kategori ticket diset ke {category.mention}!")

# =====================
# Ticket listing & panel show
# =====================
@bot.hybrid_command(name="mytickets", description="Lihat ticket yang masih terbuka")
async def mytickets(ctx: commands.Context):
    async with aiosqlite.connect('bot_data.db') as db:
        cursor = await db.execute('SELECT channel_id, category, created_at FROM tickets WHERE user_id = ? AND status = "open"', (ctx.author.id,))
        open_tickets = await cursor.fetchall()

    if open_tickets:
        embed = discord.Embed(title="🎫 Ticket Anda yang Masih Terbuka", color=discord.Color.blue())
        for channel_id, category, created_at in open_tickets:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                embed.add_field(name=f"{'🛒' if category == 'beli' else '🆘'} {category.capitalize()}", value=f"Channel: {channel.mention}\nDibuat: <t:{int(datetime.fromisoformat(created_at).timestamp())}:R>", inline=False)
        await send_ephemeral(ctx, embed=embed)
    else:
        await send_ephemeral(ctx, "❌ Anda tidak memiliki ticket yang terbuka.")

@bot.hybrid_command(name="show_ticket", description="Tampilkan panel ticket ke channel tertentu")
@commands.has_permissions(administrator=True)
@app_commands.describe(channel="Channel untuk menampilkan panel ticket")
async def show_ticket(ctx: commands.Context, channel: discord.TextChannel):
    embed = discord.Embed(title="🎫 Ticket System", description="Klik tombol di bawah untuk membuka ticket:", color=discord.Color.blue())
    view = TicketOptionsView()
    await channel.send(embed=embed, view=view)
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute('INSERT OR REPLACE INTO ticket_settings (guild_id, channel_id) VALUES (?, ?)', (ctx.guild.id, channel.id))
        await db.commit()
    await ctx.send(f"✅ Panel ticket berhasil ditampilkan di {channel.mention}!")

@bot.hybrid_command(name="server_info", description="Lihat pengaturan server")
async def server_info(ctx: commands.Context):
    embed = discord.Embed(title="⚙️ Server Information", description="Pengaturan yang aktif di server ini:", color=discord.Color.blue())
    async with aiosqlite.connect('bot_data.db') as db:
        cursor = await db.execute('SELECT channel_id, role_id, message FROM welcome_settings WHERE guild_id = ?', (ctx.guild.id,))
        welcome_settings = await cursor.fetchone()
        cursor = await db.execute('SELECT channel_id, category_id FROM ticket_settings WHERE guild_id = ?', (ctx.guild.id,))
        ticket_settings = await cursor.fetchone()

    if welcome_settings:
        w_channel_id, w_role_id, w_message = welcome_settings
        if w_channel_id:
            channel = ctx.guild.get_channel(w_channel_id)
            role = ctx.guild.get_role(w_role_id) if w_role_id else None
            if channel:
                text = f"Channel: {channel.mention}\nRole: {role.mention if role else 'Tidak ada'}"
                if w_message:
                    text += f"\nMessage: {w_message[:100]}{'...' if len(w_message) > 100 else ''}"
                embed.add_field(name="👋 Welcome System", value=text, inline=False)

    if ticket_settings:
        t_channel_id, category_id = ticket_settings
        if t_channel_id:
            channel = ctx.guild.get_channel(t_channel_id)
            if channel:
                embed.add_field(name="🎫 Ticket Panel", value=f"Channel: {channel.mention}", inline=False)
        if category_id:
            category = ctx.guild.get_channel(category_id)
            if isinstance(category, discord.CategoryChannel):
                embed.add_field(name="🎫 Ticket Category", value=f"Kategori: {category.mention}", inline=False)

    if not welcome_settings and not ticket_settings:
        embed.description = "Belum ada pengaturan yang diatur untuk server ini."

    await ctx.send(embed=embed)

# =====================
# Music Commands (Fixed error + autoplay queue)
# =====================
async def _after_playback(error: Exception | None, guild_id: int):
    # This runs in the player thread; schedule coroutine on bot loop
    try:
        awaitable = play_next_by_guild_id(guild_id)
        asyncio.run_coroutine_threadsafe(awaitable, bot.loop)
    except Exception:
        pass

@bot.hybrid_command(name="play", description="Memutar musik dari YouTube")
@app_commands.describe(query="URL atau nama lagu")
async def play(ctx: commands.Context, *, query: str):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ Anda harus berada di voice channel terlebih dahulu!")
        return

    voice_channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client

    if voice_client and voice_client.is_connected():
        if voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)
    else:
        try:
            voice_client = await voice_channel.connect()
        except Exception as e:
            await ctx.send(f"❌ Error connecting to voice channel: {str(e)}")
            return

    # Remember last text channel used for this guild
    music_state.set_text_channel(ctx.guild.id, ctx.channel.id)

    # Defer interaction to avoid timeouts
    try:
        if hasattr(ctx, 'defer'):
            await ctx.defer()
    except Exception:
        pass

    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        queue = music_state.get_queue(ctx.guild.id)

        if voice_client.is_playing():
            queue.append(player)
            embed = discord.Embed(title="🎵 Added to Queue", description=f"**{player.title}** ditambahkan ke queue (Posisi: #{len(queue)})", color=discord.Color.green())
            await ctx.send(embed=embed)
        else:
            def after_cb(error):
                # schedule next track
                asyncio.run_coroutine_threadsafe(play_next_by_guild_id(ctx.guild.id), bot.loop)
            voice_client.play(player, after=after_cb)
            embed = discord.Embed(title="🎵 Now Playing", description=f"**{player.title}**", color=discord.Color.blue())
            await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

async def play_next_by_guild_id(guild_id: int):
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    queue = music_state.get_queue(guild.id)
    voice_client = guild.voice_client
    if not voice_client:
        music_state.clear_queue(guild.id)
        return
    if queue and not voice_client.is_playing():
        next_player = queue.pop(0)
        def after_cb(error):
            asyncio.run_coroutine_threadsafe(play_next_by_guild_id(guild.id), bot.loop)
        try:
            voice_client.play(next_player, after=after_cb)
        except Exception:
            # Skip problematic track and move on
            await play_next_by_guild_id(guild.id)
            return
        # Announce now playing
        text_channel = music_state.get_text_channel(guild)
        if text_channel:
            embed = discord.Embed(title="🎵 Now Playing", description=f"**{next_player.title}**", color=discord.Color.blue())
            try:
                await text_channel.send(embed=embed)
            except Exception:
                pass

@bot.hybrid_command(name="stop", description="Menghentikan musik")
async def stop(ctx: commands.Context):
    voice_client = ctx.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_connected()):
        voice_client.stop()
        music_state.clear_queue(ctx.guild.id)
        try:
            await voice_client.disconnect()
        except Exception:
            pass
        await ctx.send("⏹️ Musik dihentikan")
    else:
        await ctx.send("❌ Tidak ada musik yang sedang diputar!")

@bot.hybrid_command(name="skip", description="Skip musik saat ini")
async def skip(ctx: commands.Context):
    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏭️ Musik diskip")
        await play_next_by_guild_id(ctx.guild.id)
    else:
        await ctx.send("❌ Tidak ada musik yang sedang diputar!")

@bot.hybrid_command(name="queue", description="Menampilkan queue musik")
async def queue_cmd(ctx: commands.Context):
    queue = music_state.get_queue(ctx.guild.id)
    if queue:
        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.purple())
        for i, player in enumerate(queue[:10], 1):
            embed.add_field(name=f"#{i}", value=player.title, inline=False)
        if len(queue) > 10:
            embed.set_footer(text=f"Dan {len(queue) - 10} lagu lainnya...")
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Queue kosong!")

# =====================
# Moderation commands
# =====================
@bot.hybrid_command(name="ban", description="Ban member dari server")
@commands.has_permissions(ban_members=True)
@app_commands.describe(member="Member yang akan di-ban", reason="Alasan ban")
async def ban(ctx: commands.Context, member: discord.Member, reason: str = "Tidak ada alasan"):
    try:
        await member.ban(reason=reason)
        embed = discord.Embed(title="✅ Banned", description=f"{member.mention} telah di-ban dari server.", color=discord.Color.red())
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ Saya tidak memiliki izin untuk ban member ini!")

@bot.hybrid_command(name="kick", description="Kick member dari server")
@commands.has_permissions(kick_members=True)
@app_commands.describe(member="Member yang akan di-kick", reason="Alasan kick")
async def kick(ctx: commands.Context, member: discord.Member, reason: str = "Tidak ada alasan"):
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(title="✅ Kicked", description=f"{member.mention} telah di-kick dari server.", color=discord.Color.orange())
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ Saya tidak memiliki izin untuk kick member ini!")

# =====================
# Info commands
# =====================
@bot.hybrid_command(name="stats", description="Lihat statistik server")
async def stats(ctx: commands.Context):
    async with aiosqlite.connect('bot_data.db') as db:
        cursor = await db.execute('SELECT COUNT(*) FROM members')
        total_members = await cursor.fetchone()
        cursor = await db.execute('SELECT COUNT(*) FROM tickets WHERE status = "open"')
        open_tickets = await cursor.fetchone()
        cursor = await db.execute('SELECT COUNT(*) FROM tickets WHERE status = "closed"')
        closed_tickets = await cursor.fetchone()

    embed = discord.Embed(title="📊 Server Statistics", color=discord.Color.gold())
    embed.add_field(name="👥 Total Members", value=total_members[0], inline=True)
    embed.add_field(name="🎫 Open Tickets", value=open_tickets[0], inline=True)
    embed.add_field(name="✅ Closed Tickets", value=closed_tickets[0], inline=True)
    embed.add_field(name="🏢 Server Created", value=ctx.guild.created_at.strftime("%Y-%m-%d"), inline=True)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="help", description="Menampilkan semua command")
async def help_command(ctx: commands.Context):
    embed = discord.Embed(title="🤖 Bot Commands Help", description="Berikut adalah semua command yang tersedia:", color=discord.Color.blue())
    embed.add_field(name="🎵 Music Commands", value="• `/play [query]` - Putar musik\n• `/stop` - Stop musik\n• `/skip` - Skip lagu\n• `/queue` - Lihat antrian", inline=False)
    embed.add_field(name="🎫 Ticket Commands", value="• Klik tombol `Beli`/`Support` - Buat ticket\n• `/mytickets` - Lihat ticket Anda\n• `/set_ticket_category` - Set kategori (Admin)\n• `/show_ticket` - Pasang panel", inline=False)
    embed.add_field(name="👋 Welcome", value="• `/set_welcome_message [teks]` - Set pesan welcome (support placeholder {user}, {username}, {guild}, {member_count})", inline=False)
    embed.add_field(name="🛠️ Moderation Commands", value="• `/ban [user] [reason]` - Ban member\n• `/kick [user] [reason]` - Kick member", inline=False)
    embed.add_field(name="📊 Info Commands", value="• `/stats` - Statistik server\n• `/server_info` - Info pengaturan\n• `/dashboard` - Admin dashboard\n• `/help` - Bantuan", inline=False)
    await ctx.send(embed=embed)

# =====================
# Event untuk message counter
# =====================
@bot.event
async def on_message(message: discord.Message):
    if not message.author.bot:
        async with aiosqlite.connect('bot_data.db') as db:
            await db.execute('INSERT OR IGNORE INTO members (user_id, username, joined_at) VALUES (?, ?, ?)', (message.author.id, str(message.author), datetime.now().isoformat()))
            await db.execute('UPDATE members SET messages_sent = messages_sent + 1 WHERE user_id = ?', (message.author.id,))
            await db.commit()
    await bot.process_commands(message)

# =====================
# Jalankan bot
# =====================
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        raise ValueError("Token bot tidak ditemukan. Pastikan Anda telah mengatur DISCORD_BOT_TOKEN di file .env")
    bot.run(token)
