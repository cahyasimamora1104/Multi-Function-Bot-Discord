# 🎯 Discord Bot dengan Music Player, Ticket System, dan Welcome System

Bot ini dibuat menggunakan **Python** dengan library **discord.py** versi 2.x. Fitur utama meliputi:

* ✅ **Welcome System** dengan custom message dan auto role
* ✅ **Ticket System** dengan kategori khusus dan tombol interaktif
* ✅ **Music Player** (YouTube) menggunakan **yt-dlp** + **FFmpeg**
* ✅ **Dashboard Admin** berbasis interaksi
* ✅ **Statistik Server** & Command Moderasi

---

## 📂 Struktur File

```
├── main.py             # File utama bot
├── requirements.txt    # Daftar dependensi Python
├── .env                # Token bot Discord (jangan dibagikan!)
```

---

## 🔧 Instalasi & Setup

### 1. **Clone Repository**

```bash
git clone https://github.com/username/nama-repo.git
cd nama-repo
```

### 2. **Buat Virtual Environment (Opsional)**

```bash
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows
```

### 3. **Install Dependensi**

```bash
pip install -r requirements.txt
```

Isi `requirements.txt`:

```
discord.py==2.3.2
yt-dlp==2025.01.12
aiosqlite==0.20.0
python-dotenv==1.0.1
```

---

## ⚙️ Konfigurasi Token

Buat file **.env** (sudah ada contoh pada repo):

```
DISCORD_BOT_TOKEN=MASUKKAN_TOKEN_DISCORD_ANDA
```

**Jangan share file `.env` ke publik!** Tambahkan ke `.gitignore` untuk keamanan.

---

## ▶️ Menjalankan Bot

Pastikan token sudah diatur, lalu jalankan:

```bash
python main.py
```

Jika token tidak ditemukan, bot akan memberikan error:

```
ValueError: Token bot tidak ditemukan. Pastikan Anda telah mengatur DISCORD_BOT_TOKEN di file .env
```

---

## ✅ Fitur Utama

### 👋 **Welcome System**

* Auto-kirim pesan ke channel tertentu saat member baru join
* Support **custom message** dengan placeholder:

  ```
  {user}, {username}, {guild}, {member_count}
  ```
* Auto-assign role yang dipilih admin

Command:

```
/set_welcome_message [teks]
```

### 🎫 **Ticket System**

* Buka ticket via tombol:

  * 🛒 **Beli**
  * 🆘 **Support**
* Auto-buat kategori jika belum ada
* Panel ticket dapat dipasang oleh admin:

```
/show_ticket
```

### 🎵 **Music Player**

* Putar musik YouTube di voice channel
* Command:

  ```
  /play [judul/URL]
  /skip
  /stop
  /queue
  ```

### 🛠️ **Admin Dashboard**

* Setup welcome & ticket melalui **menu interaktif**
* Perintah:

```
/dashboard
```

### 📊 **Statistik & Info**

* Lihat total member, open/closed ticket:

```
/stats
```

* Info pengaturan server:

```
/server_info
```

---

## 📌 Persyaratan Tambahan

* **FFmpeg** harus terinstall di sistem untuk fitur musik.

  * **Linux (Debian/Ubuntu)**:

    ```bash
    sudo apt install ffmpeg
    ```
  * **Windows**: Download dari [FFmpeg.org](https://ffmpeg.org/download.html) dan tambahkan ke PATH.

---

## 🗄 Database

Menggunakan **SQLite** dengan `aiosqlite`. File database otomatis dibuat:

```
bot_data.db
```

Tabel yang digunakan:

* `members` → Data member & jumlah pesan
* `tickets` → Data tiket
* `welcome_settings` → Pengaturan welcome
* `ticket_settings` → Pengaturan ticket

---

## 🚀 To-Do / Pengembangan Selanjutnya

* [ ] Fitur **auto close ticket** setelah waktu tertentu
* [ ] **Logging system** untuk semua aksi admin
* [ ] Kompatibilitas multi-server dengan setting UI lebih lengkap

---

### ⚠️ Catatan Keamanan

* **Jangan pernah commit file `.env` atau token bot ke repo publik!**
* Gunakan **environment variables** saat deploy di server.

---

📌 **Lisensi:** MIT
📌 **Dikembangkan dengan ❤️ oleh Homura Raito AKA Cahya Christian Ivan Marshall Simamora A.MD.Kom**

---

Apakah kamu mau saya **tambahkan contoh screenshot command bot dan outputnya di README** agar lebih menarik? Atau buat **badge (contoh: Python version, Discord.py version)** di bagian atas README?
