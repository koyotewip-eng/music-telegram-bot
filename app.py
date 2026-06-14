import os
import json
import tempfile
import sqlite3
import urllib.request
import urllib.parse
import yt_dlp
import time
import ssl
import threading
from flask import Flask

print("=== STARTING ===", flush=True)

# ===== НАЛАШТУВАННЯ =====
BOT_TOKEN = "8981234358:AAHMZAirobfP_F-bt5WCY1LJxyRMW0E5OH8"
ADMIN_IDS = [2104120716, 508881013]
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Cookies для YouTube
COOKIES_RAW = "APISID=6lq2xTKRyDqX7yyw/AQowjf-gmcILKItxs; SAPISID=H1i1QJwoc_e-Ssej/AKAi8a-McoHTo32uG; __Secure-1PAPISID=H1i1QJwoc_e-Ssej/AKAi8a-McoHTo32uG; __Secure-3PAPISID=H1i1QJwoc_e-Ssej/AKAi8a-McoHTo32uG; SID=g.a000_AhEoweiy-VOhvczD0d3hgh57Fzad1L4ERmJPPHXWDN6mXtNwsirFVbA1VA-zn69kY2UAwACgYKASYSARcSFQHGX2Mij2CKNcwuu9ilU1T9Q2tuwRoVAUF8yKqGK42Aucx9qtN2CXDvcdg30076; SIDCC=AKEyXzUMJlIlDPWhw0UGjzvKk5-ZAjM59mgEImqLcObQdTZYNbI_eBCZwK9TK6aDSBNffXuaRQ; PREF=f6=40000000&tz=Europe.Berlin"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# ===== БАЗА ДАНИХ =====
DB_PATH = '/data/music.db'
os.makedirs('/data', exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (
    video_id TEXT UNIQUE,
    title TEXT,
    artist TEXT,
    file_id TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    user_id INTEGER,
    UNIQUE(name, user_id)
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER,
    video_id TEXT,
    title TEXT,
    artist TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER,
    video_id TEXT,
    title TEXT,
    artist TEXT,
    UNIQUE(user_id, video_id)
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS user_state (
    user_id INTEGER UNIQUE,
    state TEXT,
    value TEXT
)''')

conn.commit()

# ===== API FUNCTIONS =====

def api_call(method, params=None):
    url = f"{BASE_URL}/{method}"
    try:
        if params:
            data = json.dumps(params).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"API error: {e}", flush=True)
        return None

def _write_cookies(path):
    with open(path, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")
        for cookie in COOKIES_RAW.split('; '):
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

def search_youtube(query, max_results=15, search_type="track"):
    """Пошук YouTube з cookies"""
    all_results = []
    
    cookies_path = os.path.join(tempfile.gettempdir(), f"cookies_{hash(query)}.txt")
    _write_cookies(cookies_path)
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    
    try:
        yt_query = f"ytsearch{max_results}:{query}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_query, download=False)
            for e in info.get('entries', []):
                if e and e.get('duration', 0) > 10:
                    all_results.append({
                        'video_id': e.get('id', ''),
                        'title': e.get('title', '')[:80],
                        'artist': e.get('channel', '')[:50],
                        'duration': e.get('duration', 0),
                        'source': 'YouTube'
                    })
        print(f"Found {len(all_results)} results for: {query}", flush=True)
    except Exception as e:
        print(f"Search error: {e}", flush=True)
    
    try:
        os.remove(cookies_path)
    except:
        pass
    
    return all_results[:15]

def download_audio(video_id):
    """Завантаження з cookies"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    temp_dir = tempfile.gettempdir()
    file_hash = str(abs(hash(url)))
    output = os.path.join(temp_dir, f"{file_hash}.%(ext)s")
    final_path = os.path.join(temp_dir, f"{file_hash}.mp3")
    
    cookies_path = os.path.join(temp_dir, f"cookies_{file_hash}.txt")
    _write_cookies(cookies_path)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True,
        'no_warnings': True,
        'cookiefile': cookies_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'socket_timeout': 30,
        'retries': 3,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    try:
        os.remove(cookies_path)
    except:
        pass
    
    return final_path

def send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return api_call('sendMessage', params)

def edit_message(chat_id, message_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return api_call('editMessageText', params)

def delete_message(chat_id, message_id):
    return api_call('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})

def send_audio_file(chat_id, file_path):
    url = f"{BASE_URL}/sendAudio"
    with open(file_path, 'rb') as f:
        data = f.read()
    boundary = '----Boundary7MA4YWxkTrZu0gW'
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="music.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
    ).encode('utf-8') + data + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=60, context=ssl_ctx) as resp:
        return json.loads(resp.read())

def send_audio_by_id(chat_id, file_id):
    return api_call('sendAudio', {'chat_id': chat_id, 'audio': file_id})

def get_file_id(video_id):
    cursor.execute('SELECT file_id FROM tracks WHERE video_id = ?', (video_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def save_track_info(video_id, title, artist, file_id):
    try:
        cursor.execute('INSERT OR REPLACE INTO tracks (video_id, title, artist, file_id) VALUES (?, ?, ?, ?)',
                       (video_id, title, artist, file_id))
        conn.commit()
    except Exception as e:
        print(f"DB error: {e}", flush=True)

def format_duration(seconds):
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f" {m}:{s:02d}"

# ===== KEYBOARDS =====

def main_menu_keyboard():
    return {'inline_keyboard': [
        [{'text': '🔍  Пошук', 'callback_data': 'menu_search'}],
        [{'text': '📂  Плейлисти', 'callback_data': 'menu_playlists'}],
        [{'text': '❤️  Улюблене', 'callback_data': 'menu_favorites'}],
        [{'text': 'ℹ️  Допомога', 'callback_data': 'menu_help'}]
    ]}

def search_type_keyboard():
    return {'inline_keyboard': [
        [{'text': '🎵  За треком', 'callback_data': 'search_track'},
         {'text': '🎤  За артистом', 'callback_data': 'search_artist'}],
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}

def home_button():
    return [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]

def back_button(data, text='⬅️  Назад'):
    return [{'text': text, 'callback_data': data}]

# ===== SCREEN HANDLERS =====

def show_main_menu(chat_id, message_id=None):
    text = "🎵 <b>Music Player</b>\n\nОбирай розділ:"
    kb = main_menu_keyboard()
    if message_id:
        return edit_message(chat_id, message_id, text, kb)
    else:
        return send_message(chat_id, text, kb)

def show_help(chat_id, message_id):
    text = (
        "🎵 <b>Допомога</b>\n\n"
        "• <b>Пошук</b> — знайти трек або артиста\n"
        "• <b>Плейлисти</b> — твої збірки треків\n"
        "• <b>Улюблене</b> — збережені треки\n\n"
        "📱 <i>Працює в фоновому режимі</i>\n"
        "🎧 <i>Нативний плеєр iOS</i>\n"
        "🔒 <i>Приватний бот</i>"
    )
    kb = {'inline_keyboard': [home_button()]}
    edit_message(chat_id, message_id, text, kb)

def show_search_menu(chat_id, message_id):
    text = "🔍 <b>Пошук музики</b>\n\nОбери тип пошуку:"
    edit_message(chat_id, message_id, text, search_type_keyboard())

def show_search_prompt(chat_id, message_id, search_type, back_data, user_id):
    type_text = "трек" if search_type == "track" else "артиста"
    text = f"🔍 <b>Пошук за {type_text}ом</b>\n\n✏️ Напиши назву в чат:"
    
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (user_id, f'search_{search_type}', ''))
    conn.commit()
    
    kb = {'inline_keyboard': [
        back_button(back_data, '↩️  Назад до вибору'),
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    edit_message(chat_id, message_id, text, kb)

def show_search_results(chat_id, results, search_query, search_type):
    type_text = "треком" if search_type == "track" else "артистом"
    
    if not results:
        send_message(chat_id, f"😔 Нічого не знайдено за {type_text}: <b>{search_query}</b>", main_menu_keyboard())
        return
    
    text = f"🎶 <b>Результати за {type_text}:</b> {search_query}\n\n"
    keyboard = {'inline_keyboard': []}
    
    for i, t in enumerate(results[:10]):
        dur = format_duration(t.get('duration', 0))
        source = t.get('source', '')
        text += f"{i+1}. {t['title'][:60]}{dur}\n   <i>{t['artist'][:40]}</i>  [{source}]\n"
        keyboard['inline_keyboard'].append([{
            'text': f"▶️ {t['title'][:50]}",
            'callback_data': f"play_{t['video_id']}"
        }])
    
    keyboard['inline_keyboard'].append([{'text': '🔍  Новий пошук', 'callback_data': 'menu_search'}])
    keyboard['inline_keyboard'].append(home_button())
    
    send_message(chat_id, text, keyboard)

def show_playlists(chat_id, message_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ? ORDER BY name', (user_id,))
    playlists = cursor.fetchall()
    
    keyboard = {'inline_keyboard': []}
    
    if not playlists:
        text = "📂 <b>Плейлисти</b>\n\nУ тебе ще немає плейлистів."
    else:
        text = "📂 <b>Плейлисти</b>\n\nОбери плейлист:\n"
        for pl in playlists:
            cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl[0],))
            count = cursor.fetchone()[0]
            text += f"• {pl[1]} ({count} треків)\n"
            keyboard['inline_keyboard'].append([{
                'text': f"📁 {pl[1]}",
                'callback_data': f"playlist_{pl[0]}_0"
            }])
    
    keyboard['inline_keyboard'].append([{'text': '➕  Створити плейлист', 'callback_data': 'create_playlist'}])
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, text, keyboard)

def show_create_playlist_prompt(chat_id, message_id, user_id):
    text = "➕ <b>Новий плейлист</b>\n\n✏️ Напиши назву в чат:"
    
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (user_id, 'create_playlist', ''))
    conn.commit()
    
    kb = {'inline_keyboard': [
        back_button('menu_playlists', '↩️  До плейлистів'),
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    edit_message(chat_id, message_id, text, kb)

def show_playlist_tracks(chat_id, message_id, pl_id, page=0):
    cursor.execute('SELECT name FROM playlists WHERE id = ?', (pl_id,))
    pl_row = cursor.fetchone()
    if not pl_row:
        edit_message(chat_id, message_id, "❌ Плейлист не знайдено", main_menu_keyboard())
        return
    pl_name = pl_row[0]
    
    per_page = 5
    offset = page * per_page
    
    cursor.execute('SELECT pt.video_id, pt.title, pt.artist FROM playlist_tracks pt WHERE pt.playlist_id = ? LIMIT ? OFFSET ?',
                   (pl_id, per_page, offset))
    tracks = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl_id,))
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    keyboard = {'inline_keyboard': []}
    
    if not tracks and page == 0:
        text = f"📁 <b>{pl_name}</b>\n\nПлейлист пустий.\nЗнайди треки через 🔍 Пошук."
    else:
        text = f"📁 <b>{pl_name}</b>\nСтор. {page+1}/{total_pages}\n\n"
        for i, t in enumerate(tracks):
            num = offset + i + 1
            text += f"{num}. {t[1][:60]}\n   <i>{t[2][:40]}</i>\n"
            keyboard['inline_keyboard'].append([{
                'text': f"▶️ {t[1][:50]}",
                'callback_data': f"play_{t[0]}"
            }])
    
    nav = []
    if page > 0:
        nav.append({'text': '⬅️', 'callback_data': f'playlist_{pl_id}_{page-1}'})
    nav.append({'text': '🔍', 'callback_data': f'search_in_pl_{pl_id}'})
    if page < total_pages - 1:
        nav.append({'text': '➡️', 'callback_data': f'playlist_{pl_id}_{page+1}'})
    if nav:
        keyboard['inline_keyboard'].append(nav)
    
    keyboard['inline_keyboard'].append([{'text': '🗑  Видалити плейлист', 'callback_data': f'delete_pl_{pl_id}'}])
    keyboard['inline_keyboard'].append(back_button('menu_playlists', '↩️  До плейлистів'))
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, text, keyboard)

def show_favorites(chat_id, message_id, user_id):
    cursor.execute('SELECT video_id, title, artist FROM favorites WHERE user_id = ? ORDER BY title', (user_id,))
    favs = cursor.fetchall()
    
    keyboard = {'inline_keyboard': []}
    
    if not favs:
        text = "❤️ <b>Улюблене</b>\n\nПоки що пусто.\nНатисни ❤️ біля треку, щоб додати."
    else:
        text = f"❤️ <b>Улюблене</b> ({len(favs)} треків)\n\n"
        for i, f in enumerate(favs[:20]):
            text += f"{i+1}. {f[1][:50]}\n   <i>{f[2][:30]}</i>\n"
            keyboard['inline_keyboard'].append([{
                'text': f"▶️ {f[1][:45]}",
                'callback_data': f"play_{f[0]}"
            }])
    
    keyboard['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, text, keyboard)

def show_track_actions(chat_id, video_id, title, artist):
    text = f"🎵 <b>{title[:80]}</b>\n<i>{artist[:60]}</i>\n\nОбери дію:"
    kb = {'inline_keyboard': [
        [{'text': '▶️  Грати', 'callback_data': f'play_{video_id}'},
         {'text': '❤️', 'callback_data': f'fav_{video_id}'}],
        [{'text': '📋  Додати до плейлисту', 'callback_data': f'addtopl_{video_id}'}],
        [{'text': '🔍  Новий пошук', 'callback_data': 'menu_search'}],
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    send_message(chat_id, text, kb)

def show_add_to_playlist(chat_id, message_id, video_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ? ORDER BY name', (user_id,))
    playlists = cursor.fetchall()
    
    if not playlists:
        api_call('answerCallbackQuery', {
            'callback_query_id': str(time.time()),
            'text': 'Спочатку створи плейлист!',
            'show_alert': True
        })
        return
    
    keyboard = {'inline_keyboard': []}
    for pl in playlists:
        keyboard['inline_keyboard'].append([{
            'text': f"📁 {pl[1]}",
            'callback_data': f'addto_{pl[0]}_{video_id}'
        }])
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, "📋 <b>Обери плейлист:</b>", keyboard)

# ===== MAIN PROCESSOR =====

def process_update(update):
    if 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        message_id = cb['message']['message_id']
        data = cb['data']
        user_id = cb['from']['id']
        
        if user_id not in ADMIN_IDS:
            api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '🔒 Приватний бот'})
            return
        
        api_call('answerCallbackQuery', {'callback_query_id': cb['id']})
        
        if data == 'menu_main':
            show_main_menu(chat_id, message_id)
        elif data == 'menu_search':
            show_search_menu(chat_id, message_id)
        elif data == 'menu_playlists':
            show_playlists(chat_id, message_id, user_id)
        elif data == 'menu_favorites':
            show_favorites(chat_id, message_id, user_id)
        elif data == 'menu_help':
            show_help(chat_id, message_id)
        elif data == 'search_track':
            show_search_prompt(chat_id, message_id, 'track', 'menu_search', user_id)
        elif data == 'search_artist':
            show_search_prompt(chat_id, message_id, 'artist', 'menu_search', user_id)
        elif data == 'create_playlist':
            show_create_playlist_prompt(chat_id, message_id, user_id)
        elif data.startswith('playlist_'):
            parts = data.split('_')
            pl_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 0
            show_playlist_tracks(chat_id, message_id, pl_id, page)
        elif data.startswith('delete_pl_'):
            pl_id = int(data.replace('delete_pl_', ''))
            cursor.execute('DELETE FROM playlist_tracks WHERE playlist_id = ?', (pl_id,))
            cursor.execute('DELETE FROM playlists WHERE id = ? AND user_id = ?', (pl_id, user_id))
            conn.commit()
            show_playlists(chat_id, message_id, user_id)
        elif data.startswith('search_in_pl_'):
            pl_id = int(data.replace('search_in_pl_', ''))
            cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                          (user_id, f'search_in_pl_{pl_id}', ''))
            conn.commit()
            text = "🔍 <b>Пошук у плейлисті</b>\n\n✏️ Напиши назву треку:"
            kb = {'inline_keyboard': [
                back_button(f'playlist_{pl_id}_0', '↩️  До плейлисту'),
                [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
            ]}
            edit_message(chat_id, message_id, text, kb)
        elif data.startswith('play_'):
            video_id = data.replace('play_', '')
            file_id = get_file_id(video_id)
            if file_id:
                result = send_audio_by_id(chat_id, file_id)
                if result and result.get('ok'):
                    cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
                    track = cursor.fetchone()
                    if track:
                        show_track_actions(chat_id, video_id, track[0], track[1])
            else:
                status_msg = send_message(chat_id, "⬇️ <b>Завантажую...</b>")
                status_id = status_msg['result']['message_id'] if status_msg and status_msg.get('ok') else None
                try:
                    mp3_path = download_audio(video_id)
                    result = send_audio_file(chat_id, mp3_path)
                    if result and result.get('ok'):
                        new_file_id = result['result']['audio']['file_id']
                        title = result['result']['audio'].get('title', 'Невідомий трек')
                        artist = result['result']['audio'].get('performer', 'Невідомий артист')
                        save_track_info(video_id, title, artist, new_file_id)
                        if status_id:
                            delete_message(chat_id, status_id)
                        show_track_actions(chat_id, video_id, title, artist)
                    else:
                        if status_id:
                            edit_message(chat_id, status_id, "❌ Помилка завантаження", main_menu_keyboard())
                    os.remove(mp3_path)
                except Exception as e:
                    if status_id:
                        edit_message(chat_id, status_id, f"❌ Помилка: {str(e)[:100]}", main_menu_keyboard())
        elif data.startswith('addtopl_'):
            video_id = data.replace('addtopl_', '')
            show_add_to_playlist(chat_id, message_id, video_id, user_id)
        elif data.startswith('addto_'):
            parts = data.split('_')
            pl_id = int(parts[1])
            video_id = '_'.join(parts[2:])
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
            track = cursor.fetchone()
            if track:
                try:
                    cursor.execute('INSERT INTO playlist_tracks (playlist_id, video_id, title, artist) VALUES (?, ?, ?, ?)',
                                  (pl_id, video_id, track[0], track[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '✅ Додано!', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже в плейлисті', 'show_alert': False})
        elif data.startswith('fav_'):
            video_id = data.replace('fav_', '')
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
            track = cursor.fetchone()
            if track:
                try:
                    cursor.execute('INSERT INTO favorites (user_id, video_id, title, artist) VALUES (?, ?, ?, ?)',
                                  (user_id, video_id, track[0], track[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '❤️ Додано!', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже в улюблених', 'show_alert': False})
    
    elif 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        text = msg.get('text', '')
        
        if user_id not in ADMIN_IDS:
            send_message(chat_id, "🔒 Приватний бот")
            return
        
        if text == '/start':
            show_main_menu(chat_id)
            return
        if text == '/menu':
            show_main_menu(chat_id)
            return
        
        cursor.execute('SELECT state FROM user_state WHERE user_id = ?', (user_id,))
        state_row = cursor.fetchone()
        
        if state_row:
            state = state_row[0]
            
            if state in ['search_track', 'search_artist']:
                search_type = "track" if state == 'search_track' else "artist"
                type_text = "треком" if search_type == "track" else "артистом"
                send_message(chat_id, f"🔍 Шукаю за {type_text}: <b>{text}</b>...")
                results = search_youtube(text, search_type=search_type)
                show_search_results(chat_id, results, text, search_type)
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()
            
            elif state == 'create_playlist':
                name = text.strip()[:50]
                try:
                    cursor.execute('INSERT INTO playlists (name, user_id) VALUES (?, ?)', (name, user_id))
                    conn.commit()
                    send_message(chat_id, f"✅ Плейлист <b>{name}</b> створено!", main_menu_keyboard())
                except:
                    send_message(chat_id, "❌ Плейлист із такою назвою вже є", main_menu_keyboard())
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()
            
            elif state.startswith('search_in_pl_'):
                pl_id = int(state.replace('search_in_pl_', ''))
                cursor.execute('''SELECT pt.video_id, pt.title, pt.artist FROM playlist_tracks pt 
                                 WHERE pt.playlist_id = ? AND pt.title LIKE ? LIMIT 10''',
                              (pl_id, f'%{text}%'))
                tracks = cursor.fetchall()
                cursor.execute('SELECT name FROM playlists WHERE id = ?', (pl_id,))
                pl_name = cursor.fetchone()[0]
                keyboard = {'inline_keyboard': []}
                if not tracks:
                    result_text = f"🔍 <b>{pl_name}</b>\n\nНічого не знайдено."
                else:
                    result_text = f"🔍 <b>{pl_name}</b>\n\nЗнайдено:\n"
                    for i, t in enumerate(tracks):
                        result_text += f"{i+1}. {t[1][:50]}\n   <i>{t[2][:30]}</i>\n"
                        keyboard['inline_keyboard'].append([{
                            'text': f"▶️ {t[1][:45]}",
                            'callback_data': f"play_{t[0]}"
                        }])
                keyboard['inline_keyboard'].append(back_button(f'playlist_{pl_id}_0', '↩️  До плейлисту'))
                keyboard['inline_keyboard'].append(home_button())
                send_message(chat_id, result_text, keyboard)
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()

# ===== HEALTH SERVER =====

health_app = Flask(__name__)

@health_app.route('/')
def health():
    return 'OK'

def start_health_server():
    health_app.run(host='0.0.0.0', port=10000)

# ===== MAIN LOOP =====

def cleanup_temp_files():
    try:
        temp_dir = tempfile.gettempdir()
        for f in os.listdir(temp_dir):
            if f.endswith('.mp3') or f.endswith('.txt'):
                filepath = os.path.join(temp_dir, f)
                try:
                    if time.time() - os.path.getmtime(filepath) > 3600:
                        os.remove(filepath)
                except:
                    pass
    except:
        pass

def main():
    print("✅ Bot started", flush=True)
    
    api_call('deleteWebhook')
    time.sleep(1)
    
    updates = api_call('getUpdates', {'offset': -1, 'timeout': 1})
    if updates and updates.get('ok') and updates.get('result') and len(updates['result']) > 0:
        offset = updates['result'][-1]['update_id'] + 1
    else:
        offset = 0
    
    print(f"Offset: {offset}", flush=True)
    last_cleanup = time.time()
    
    while True:
        try:
            updates = api_call('getUpdates', {'offset': offset, 'timeout': 30})
            if updates and updates.get('ok') and updates.get('result'):
                for upd in updates['result']:
                    offset = upd['update_id'] + 1
                    process_update(upd)
            if time.time() - last_cleanup > 3600:
                cleanup_temp_files()
                last_cleanup = time.time()
            time.sleep(1)
        except Exception as e:
            print(f"Loop error: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    time.sleep(2)
    main()    UNIQUE(name, user_id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER, video_id TEXT, title TEXT, artist TEXT,
    FOREIGN KEY(playlist_id) REFERENCES playlists(id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER, video_id TEXT, title TEXT, artist TEXT,
    UNIQUE(user_id, video_id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_state 
    (user_id INTEGER UNIQUE, state TEXT, value TEXT)''')
conn.commit()

# ===== API FUNCTIONS =====

def api_call(method, params=None):
    url = f"{BASE_URL}/{method}"
    try:
        if params:
            data = json.dumps(params).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"API error: {e}", flush=True)
        return None

def _write_cookies(path):
    with open(path, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")
        for cookie in COOKIES_RAW.split('; '):
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                f.write(f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")

def search_youtube(query, max_results=15, search_type="track"):
    """Пошук YouTube з cookies"""
    all_results = []
    
    cookies_path = os.path.join(tempfile.gettempdir(), f"cookies_{hash(query)}.txt")
    _write_cookies(cookies_path)
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': cookies_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    
    try:
        yt_query = f"ytsearch{max_results}:{query}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_query, download=False)
            for e in info.get('entries', []):
                if e and e.get('duration', 0) > 10:
                    all_results.append({
                        'video_id': e.get('id', ''),
                        'title': e.get('title', '')[:80],
                        'artist': e.get('channel', '')[:50],
                        'duration': e.get('duration', 0),
                        'source': 'YouTube'
                    })
        print(f"Found {len(all_results)} results for: {query}", flush=True)
    except Exception as e:
        print(f"Search error: {e}", flush=True)
    
    try:
        os.remove(cookies_path)
    except:
        pass
    
    return all_results[:15]

def download_audio(video_id):
    """Завантаження з cookies"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    temp_dir = tempfile.gettempdir()
    file_hash = str(abs(hash(url)))
    output = os.path.join(temp_dir, f"{file_hash}.%(ext)s")
    final_path = os.path.join(temp_dir, f"{file_hash}.mp3")
    
    cookies_path = os.path.join(temp_dir, f"cookies_{file_hash}.txt")
    _write_cookies(cookies_path)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True,
        'no_warnings': True,
        'cookiefile': cookies_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'socket_timeout': 30,
        'retries': 3,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    try:
        os.remove(cookies_path)
    except:
        pass
    
    return final_path

def send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return api_call('sendMessage', params)

def edit_message(chat_id, message_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return api_call('editMessageText', params)

def delete_message(chat_id, message_id):
    return api_call('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})

def send_audio_file(chat_id, file_path):
    url = f"{BASE_URL}/sendAudio"
    with open(file_path, 'rb') as f:
        data = f.read()
    boundary = '----Boundary7MA4YWxkTrZu0gW'
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="music.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
    ).encode('utf-8') + data + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=60, context=ssl_ctx) as resp:
        return json.loads(resp.read())

def send_audio_by_id(chat_id, file_id):
    return api_call('sendAudio', {'chat_id': chat_id, 'audio': file_id})

def get_file_id(video_id):
    cursor.execute('SELECT file_id FROM tracks WHERE video_id = ?', (video_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def save_track_info(video_id, title, artist, file_id):
    try:
        cursor.execute('INSERT OR REPLACE INTO tracks (video_id, title, artist, file_id) VALUES (?, ?, ?, ?)',
                       (video_id, title, artist, file_id))
        conn.commit()
    except Exception as e:
        print(f"DB error: {e}", flush=True)

def format_duration(seconds):
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f" {m}:{s:02d}"

# ===== KEYBOARDS =====

def main_menu_keyboard():
    return {'inline_keyboard': [
        [{'text': '🔍  Пошук', 'callback_data': 'menu_search'}],
        [{'text': '📂  Плейлисти', 'callback_data': 'menu_playlists'}],
        [{'text': '❤️  Улюблене', 'callback_data': 'menu_favorites'}],
        [{'text': 'ℹ️  Допомога', 'callback_data': 'menu_help'}]
    ]}

def search_type_keyboard():
    return {'inline_keyboard': [
        [{'text': '🎵  За треком', 'callback_data': 'search_track'},
         {'text': '🎤  За артистом', 'callback_data': 'search_artist'}],
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}

def home_button():
    return [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]

def back_button(data, text='⬅️  Назад'):
    return [{'text': text, 'callback_data': data}]

# ===== SCREEN HANDLERS =====

def show_main_menu(chat_id, message_id=None):
    text = "🎵 <b>Music Player</b>\n\nОбирай розділ:"
    kb = main_menu_keyboard()
    if message_id:
        return edit_message(chat_id, message_id, text, kb)
    else:
        return send_message(chat_id, text, kb)

def show_help(chat_id, message_id):
    text = (
        "🎵 <b>Допомога</b>\n\n"
        "• <b>Пошук</b> — знайти трек або артиста\n"
        "• <b>Плейлисти</b> — твої збірки треків\n"
        "• <b>Улюблене</b> — збережені треки\n\n"
        "📱 <i>Працює в фоновому режимі</i>\n"
        "🎧 <i>Нативний плеєр iOS</i>\n"
        "🔒 <i>Приватний бот</i>"
    )
    kb = {'inline_keyboard': [home_button()]}
    edit_message(chat_id, message_id, text, kb)

def show_search_menu(chat_id, message_id):
    text = "🔍 <b>Пошук музики</b>\n\nОбери тип пошуку:"
    edit_message(chat_id, message_id, text, search_type_keyboard())

def show_search_prompt(chat_id, message_id, search_type, back_data):
    type_text = "трек" if search_type == "track" else "артиста"
    text = f"🔍 <b>Пошук за {type_text}ом</b>\n\n✏️ Напиши назву в чат:"
    
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (ADMIN_IDS[0], f'search_{search_type}', ''))
    conn.commit()
    
    kb = {'inline_keyboard': [
        back_button(back_data, '↩️  Назад до вибору'),
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    edit_message(chat_id, message_id, text, kb)

def show_search_results(chat_id, results, search_query, search_type):
    type_text = "треком" if search_type == "track" else "артистом"
    
    if not results:
        send_message(chat_id, f"😔 Нічого не знайдено за {type_text}: <b>{search_query}</b>", main_menu_keyboard())
        return
    
    text = f"🎶 <b>Результати за {type_text}:</b> {search_query}\n\n"
    keyboard = {'inline_keyboard': []}
    
    for i, t in enumerate(results[:10]):
        dur = format_duration(t.get('duration', 0))
        source = t.get('source', '')
        text += f"{i+1}. {t['title'][:60]}{dur}\n   <i>{t['artist'][:40]}</i>  [{source}]\n"
        keyboard['inline_keyboard'].append([{
            'text': f"▶️ {t['title'][:50]}",
            'callback_data': f"play_{t['video_id']}"
        }])
    
    keyboard['inline_keyboard'].append([{'text': '🔍  Новий пошук', 'callback_data': 'menu_search'}])
    keyboard['inline_keyboard'].append(home_button())
    
    send_message(chat_id, text, keyboard)

def show_playlists(chat_id, message_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ? ORDER BY name', (user_id,))
    playlists = cursor.fetchall()
    
    keyboard = {'inline_keyboard': []}
    
    if not playlists:
        text = "📂 <b>Плейлисти</b>\n\nУ тебе ще немає плейлистів."
    else:
        text = "📂 <b>Плейлисти</b>\n\nОбери плейлист:\n"
        for pl in playlists:
            cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl[0],))
            count = cursor.fetchone()[0]
            text += f"• {pl[1]} ({count} треків)\n"
            keyboard['inline_keyboard'].append([{
                'text': f"📁 {pl[1]}",
                'callback_data': f"playlist_{pl[0]}_0"
            }])
    
    keyboard['inline_keyboard'].append([{'text': '➕  Створити плейлист', 'callback_data': 'create_playlist'}])
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, text, keyboard)

def show_create_playlist_prompt(chat_id, message_id):
    text = "➕ <b>Новий плейлист</b>\n\n✏️ Напиши назву в чат:"
    
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (ADMIN_IDS[0], 'create_playlist', ''))
    conn.commit()
    
    kb = {'inline_keyboard': [
        back_button('menu_playlists', '↩️  До плейлистів'),
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    edit_message(chat_id, message_id, text, kb)

def show_playlist_tracks(chat_id, message_id, pl_id, page=0):
    cursor.execute('SELECT name FROM playlists WHERE id = ?', (pl_id,))
    pl_row = cursor.fetchone()
    if not pl_row:
        edit_message(chat_id, message_id, "❌ Плейлист не знайдено", main_menu_keyboard())
        return
    pl_name = pl_row[0]
    
    per_page = 5
    offset = page * per_page
    
    cursor.execute('SELECT pt.video_id, pt.title, pt.artist FROM playlist_tracks pt WHERE pt.playlist_id = ? LIMIT ? OFFSET ?',
                   (pl_id, per_page, offset))
    tracks = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl_id,))
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    keyboard = {'inline_keyboard': []}
    
    if not tracks and page == 0:
        text = f"📁 <b>{pl_name}</b>\n\nПлейлист пустий.\nЗнайди треки через 🔍 Пошук."
    else:
        text = f"📁 <b>{pl_name}</b>\nСтор. {page+1}/{total_pages}\n\n"
        for i, t in enumerate(tracks):
            num = offset + i + 1
            text += f"{num}. {t[1][:60]}\n   <i>{t[2][:40]}</i>\n"
            keyboard['inline_keyboard'].append([{
                'text': f"▶️ {t[1][:50]}",
                'callback_data': f"play_{t[0]}"
            }])
    
    nav = []
    if page > 0:
        nav.append({'text': '⬅️', 'callback_data': f'playlist_{pl_id}_{page-1}'})
    nav.append({'text': '🔍', 'callback_data': f'search_in_pl_{pl_id}'})
    if page < total_pages - 1:
        nav.append({'text': '➡️', 'callback_data': f'playlist_{pl_id}_{page+1}'})
    if nav:
        keyboard['inline_keyboard'].append(nav)
    
    keyboard['inline_keyboard'].append([{'text': '🗑  Видалити плейлист', 'callback_data': f'delete_pl_{pl_id}'}])
    keyboard['inline_keyboard'].append(back_button('menu_playlists', '↩️  До плейлистів'))
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, text, keyboard)

def show_favorites(chat_id, message_id, user_id):
    cursor.execute('SELECT video_id, title, artist FROM favorites WHERE user_id = ? ORDER BY title', (user_id,))
    favs = cursor.fetchall()
    
    keyboard = {'inline_keyboard': []}
    
    if not favs:
        text = "❤️ <b>Улюблене</b>\n\nПоки що пусто.\nНатисни ❤️ біля треку, щоб додати."
    else:
        text = f"❤️ <b>Улюблене</b> ({len(favs)} треків)\n\n"
        for i, f in enumerate(favs[:20]):
            text += f"{i+1}. {f[1][:50]}\n   <i>{f[2][:30]}</i>\n"
            keyboard['inline_keyboard'].append([{
                'text': f"▶️ {f[1][:45]}",
                'callback_data': f"play_{f[0]}"
            }])
    
    keyboard['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, text, keyboard)

def show_track_actions(chat_id, video_id, title, artist):
    text = f"🎵 <b>{title[:80]}</b>\n<i>{artist[:60]}</i>\n\nОбери дію:"
    kb = {'inline_keyboard': [
        [{'text': '▶️  Грати', 'callback_data': f'play_{video_id}'},
         {'text': '❤️', 'callback_data': f'fav_{video_id}'}],
        [{'text': '📋  Додати до плейлисту', 'callback_data': f'addtopl_{video_id}'}],
        [{'text': '🔍  Новий пошук', 'callback_data': 'menu_search'}],
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}
    send_message(chat_id, text, kb)

def show_add_to_playlist(chat_id, message_id, video_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ? ORDER BY name', (user_id,))
    playlists = cursor.fetchall()
    
    if not playlists:
        api_call('answerCallbackQuery', {
            'callback_query_id': str(time.time()),
            'text': 'Спочатку створи плейлист!',
            'show_alert': True
        })
        return
    
    keyboard = {'inline_keyboard': []}
    for pl in playlists:
        keyboard['inline_keyboard'].append([{
            'text': f"📁 {pl[1]}",
            'callback_data': f'addto_{pl[0]}_{video_id}'
        }])
    keyboard['inline_keyboard'].append(home_button())
    
    edit_message(chat_id, message_id, "📋 <b>Обери плейлист:</b>", keyboard)

# ===== MAIN PROCESSOR =====

def process_update(update):
    if 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        message_id = cb['message']['message_id']
        data = cb['data']
        user_id = cb['from']['id']
        
        if user_id not in ADMIN_IDS:
            api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '🔒 Приватний бот'})
            return
        
        api_call('answerCallbackQuery', {'callback_query_id': cb['id']})
        
        if data == 'menu_main':
            show_main_menu(chat_id, message_id)
        elif data == 'menu_search':
            show_search_menu(chat_id, message_id)
        elif data == 'menu_playlists':
            show_playlists(chat_id, message_id, user_id)
        elif data == 'menu_favorites':
            show_favorites(chat_id, message_id, user_id)
        elif data == 'menu_help':
            show_help(chat_id, message_id)
        elif data == 'search_track':
            show_search_prompt(chat_id, message_id, 'track', 'menu_search')
        elif data == 'search_artist':
            show_search_prompt(chat_id, message_id, 'artist', 'menu_search')
        elif data == 'create_playlist':
            show_create_playlist_prompt(chat_id, message_id)
        elif data.startswith('playlist_'):
            parts = data.split('_')
            pl_id = int(parts[1])
            page = int(parts[2]) if len(parts) > 2 else 0
            show_playlist_tracks(chat_id, message_id, pl_id, page)
        elif data.startswith('delete_pl_'):
            pl_id = int(data.replace('delete_pl_', ''))
            cursor.execute('DELETE FROM playlist_tracks WHERE playlist_id = ?', (pl_id,))
            cursor.execute('DELETE FROM playlists WHERE id = ? AND user_id = ?', (pl_id, user_id))
            conn.commit()
            show_playlists(chat_id, message_id, user_id)
        elif data.startswith('search_in_pl_'):
            pl_id = int(data.replace('search_in_pl_', ''))
            cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                          (user_id, f'search_in_pl_{pl_id}', ''))
            conn.commit()
            text = "🔍 <b>Пошук у плейлисті</b>\n\n✏️ Напиши назву треку:"
            kb = {'inline_keyboard': [
                back_button(f'playlist_{pl_id}_0', '↩️  До плейлисту'),
                [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
            ]}
            edit_message(chat_id, message_id, text, kb)
        elif data.startswith('play_'):
            video_id = data.replace('play_', '')
            file_id = get_file_id(video_id)
            if file_id:
                result = send_audio_by_id(chat_id, file_id)
                if result and result.get('ok'):
                    cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
                    track = cursor.fetchone()
                    if track:
                        show_track_actions(chat_id, video_id, track[0], track[1])
            else:
                status_msg = send_message(chat_id, "⬇️ <b>Завантажую...</b>")
                status_id = status_msg['result']['message_id'] if status_msg and status_msg.get('ok') else None
                try:
                    mp3_path = download_audio(video_id)
                    result = send_audio_file(chat_id, mp3_path)
                    if result and result.get('ok'):
                        new_file_id = result['result']['audio']['file_id']
                        title = result['result']['audio'].get('title', 'Невідомий трек')
                        artist = result['result']['audio'].get('performer', 'Невідомий артист')
                        save_track_info(video_id, title, artist, new_file_id)
                        if status_id:
                            delete_message(chat_id, status_id)
                        show_track_actions(chat_id, video_id, title, artist)
                    else:
                        if status_id:
                            edit_message(chat_id, status_id, "❌ Помилка завантаження", main_menu_keyboard())
                    os.remove(mp3_path)
                except Exception as e:
                    if status_id:
                        edit_message(chat_id, status_id, f"❌ Помилка: {str(e)[:100]}", main_menu_keyboard())
        elif data.startswith('addtopl_'):
            video_id = data.replace('addtopl_', '')
            show_add_to_playlist(chat_id, message_id, video_id, user_id)
        elif data.startswith('addto_'):
            parts = data.split('_')
            pl_id = int(parts[1])
            video_id = '_'.join(parts[2:])
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
            track = cursor.fetchone()
            if track:
                try:
                    cursor.execute('INSERT INTO playlist_tracks (playlist_id, video_id, title, artist) VALUES (?, ?, ?, ?)',
                                  (pl_id, video_id, track[0], track[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '✅ Додано!', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже в плейлисті', 'show_alert': False})
        elif data.startswith('fav_'):
            video_id = data.replace('fav_', '')
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (video_id,))
            track = cursor.fetchone()
            if track:
                try:
                    cursor.execute('INSERT INTO favorites (user_id, video_id, title, artist) VALUES (?, ?, ?, ?)',
                                  (user_id, video_id, track[0], track[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '❤️ Додано!', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже в улюблених', 'show_alert': False})
    
    elif 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        text = msg.get('text', '')
        
        if user_id not in ADMIN_IDS:
            send_message(chat_id, "🔒 Приватний бот")
            return
        
        if text == '/start':
            show_main_menu(chat_id)
            return
        if text == '/menu':
            show_main_menu(chat_id)
            return
        
        cursor.execute('SELECT state FROM user_state WHERE user_id = ?', (user_id,))
        state_row = cursor.fetchone()
        
        if state_row:
            state = state_row[0]
            
            if state in ['search_track', 'search_artist']:
                search_type = "track" if state == 'search_track' else "artist"
                type_text = "треком" if search_type == "track" else "артистом"
                send_message(chat_id, f"🔍 Шукаю за {type_text}: <b>{text}</b>...")
                results = search_youtube(text, search_type=search_type)
                show_search_results(chat_id, results, text, search_type)
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()
            
            elif state == 'create_playlist':
                name = text.strip()[:50]
                try:
                    cursor.execute('INSERT INTO playlists (name, user_id) VALUES (?, ?)', (name, user_id))
                    conn.commit()
                    send_message(chat_id, f"✅ Плейлист <b>{name}</b> створено!", main_menu_keyboard())
                except:
                    send_message(chat_id, "❌ Плейлист із такою назвою вже є", main_menu_keyboard())
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()
            
            elif state.startswith('search_in_pl_'):
                pl_id = int(state.replace('search_in_pl_', ''))
                cursor.execute('''SELECT pt.video_id, pt.title, pt.artist FROM playlist_tracks pt 
                                 WHERE pt.playlist_id = ? AND pt.title LIKE ? LIMIT 10''',
                              (pl_id, f'%{text}%'))
                tracks = cursor.fetchall()
                cursor.execute('SELECT name FROM playlists WHERE id = ?', (pl_id,))
                pl_name = cursor.fetchone()[0]
                keyboard = {'inline_keyboard': []}
                if not tracks:
                    result_text = f"🔍 <b>{pl_name}</b>\n\nНічого не знайдено."
                else:
                    result_text = f"🔍 <b>{pl_name}</b>\n\nЗнайдено:\n"
                    for i, t in enumerate(tracks):
                        result_text += f"{i+1}. {t[1][:50]}\n   <i>{t[2][:30]}</i>\n"
                        keyboard['inline_keyboard'].append([{
                            'text': f"▶️ {t[1][:45]}",
                            'callback_data': f"play_{t[0]}"
                        }])
                keyboard['inline_keyboard'].append(back_button(f'playlist_{pl_id}_0', '↩️  До плейлисту'))
                keyboard['inline_keyboard'].append(home_button())
                send_message(chat_id, result_text, keyboard)
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (user_id,))
                conn.commit()

# ===== HEALTH SERVER =====

health_app = Flask(__name__)

@health_app.route('/')
def health():
    return 'OK'

def start_health_server():
    health_app.run(host='0.0.0.0', port=10000)

# ===== MAIN LOOP =====

def cleanup_temp_files():
    try:
        temp_dir = tempfile.gettempdir()
        for f in os.listdir(temp_dir):
            if f.endswith('.mp3') or f.endswith('.txt'):
                filepath = os.path.join(temp_dir, f)
                try:
                    if time.time() - os.path.getmtime(filepath) > 3600:
                        os.remove(filepath)
                except:
                    pass
    except:
        pass

def main():
    print("✅ Bot started", flush=True)
    
    api_call('deleteWebhook')
    time.sleep(1)
    
    updates = api_call('getUpdates', {'offset': -1, 'timeout': 1})
    if updates and updates.get('ok') and updates.get('result') and len(updates['result']) > 0:
        offset = updates['result'][-1]['update_id'] + 1
    else:
        offset = 0
    
    print(f"Offset: {offset}", flush=True)
    last_cleanup = time.time()
    
    while True:
        try:
            updates = api_call('getUpdates', {'offset': offset, 'timeout': 30})
            if updates and updates.get('ok') and updates.get('result'):
                for upd in updates['result']:
                    offset = upd['update_id'] + 1
                    process_update(upd)
            if time.time() - last_cleanup > 3600:
                cleanup_temp_files()
                last_cleanup = time.time()
            time.sleep(1)
        except Exception as e:
            print(f"Loop error: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    time.sleep(2)
    main()
