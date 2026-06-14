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

BOT_TOKEN = "8981234358:AAHMZAirobfP_F-bt5WCY1LJxyRMW0E5OH8"
ADMIN_IDS = [2104120716, 508881013]
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

DB_PATH = '/data/music.db'
os.makedirs('/data', exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (video_id TEXT UNIQUE, title TEXT, artist TEXT, file_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, user_id INTEGER, UNIQUE(name, user_id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS playlist_tracks (playlist_id INTEGER, video_id TEXT, title TEXT, artist TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, video_id TEXT, title TEXT, artist TEXT, UNIQUE(user_id, video_id))''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_state (user_id INTEGER UNIQUE, state TEXT, value TEXT)''')
conn.commit()

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

def search_music_piped(query, max_results=15):
    """Пошук через Piped API (проксі YouTube)"""
    results = []
    try:
        url = f"https://pipedapi.kavin.rocks/search?q={urllib.parse.quote(query)}&filter=music_songs"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            data = json.loads(resp.read())
            items = data.get('items', [])
            for item in items[:max_results]:
                vid = item.get('url', '').replace('/watch?v=', '')
                if vid:
                    results.append({
                        'video_id': vid,
                        'title': item.get('title', '')[:80],
                        'artist': item.get('uploaderName', '')[:50],
                        'duration': item.get('duration', 0),
                        'source': 'YouTube'
                    })
    except Exception as e:
        print(f"Piped search error: {e}", flush=True)
    
    return results

def download_audio_piped(video_id):
    """Завантаження через Piped"""
    url = f"https://pipedapi.kavin.rocks/streams/{video_id}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            data = json.loads(resp.read())
        
        # Шукаємо аудіо-трек
        audio_streams = [s for s in data.get('audioStreams', []) if s.get('quality')]
        if not audio_streams:
            # Якщо немає окремого аудіо — беремо відео
            video_streams = data.get('videoStreams', [])
            if video_streams:
                stream_url = video_streams[0].get('url', '')
            else:
                raise Exception("No streams found")
        else:
            stream_url = audio_streams[-1].get('url', '')  # Найкраща якість
        
        if not stream_url:
            raise Exception("Empty stream URL")
        
        # Завантажуємо через yt-dlp
        temp_dir = tempfile.gettempdir()
        file_hash = str(abs(hash(video_id)))
        output = os.path.join(temp_dir, f"{file_hash}.%(ext)s")
        final_path = os.path.join(temp_dir, f"{file_hash}.mp3")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'quiet': True, 'no_warnings': True,
            'socket_timeout': 30, 'retries': 3,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])
        
        return final_path
    
    except Exception as e:
        print(f"Piped download error: {e}", flush=True)
        raise e

# Використовуємо Piped як основні функції
search_youtube = search_music_piped
download_audio = download_audio_piped

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
    except:
        pass

def format_duration(seconds):
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f" {m}:{s:02d}"

def main_menu_keyboard():
    return {'inline_keyboard': [
        [{'text': '🔍  Пошук', 'callback_data': 'menu_search'}],
        [{'text': '📂  Плейлисти', 'callback_data': 'menu_playlists'}],
        [{'text': '❤️  Улюблене', 'callback_data': 'menu_favorites'}],
        [{'text': 'ℹ️  Допомога', 'callback_data': 'menu_help'}]
    ]}

def search_type_keyboard():
    return {'inline_keyboard': [
        [{'text': '🎵  За треком', 'callback_data': 'search_track'}],
        [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]
    ]}

def home_button():
    return [{'text': '🏠  Головне меню', 'callback_data': 'menu_main'}]

def back_button(data, text='⬅️  Назад'):
    return [{'text': text, 'callback_data': data}]

def show_main_menu(chat_id, message_id=None):
    text = "🎵 <b>Music Player</b>\n\nОбирай розділ:"
    kb = main_menu_keyboard()
    if message_id:
        edit_message(chat_id, message_id, text, kb)
    else:
        send_message(chat_id, text, kb)

def show_help(chat_id, message_id):
    text = "🎵 <b>Допомога</b>\n\n• Пошук\n• Плейлисти\n• Улюблене\n\n📱 iOS плеєр\n🔒 Приватний"
    edit_message(chat_id, message_id, text, {'inline_keyboard': [home_button()]})

def show_search_menu(chat_id, message_id):
    edit_message(chat_id, message_id, "🔍 <b>Пошук музики</b>\n\nОбери тип:", search_type_keyboard())

def show_search_prompt(chat_id, message_id, search_type, back_data, user_id):
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (user_id, f'search_{search_type}', ''))
    conn.commit()
    edit_message(chat_id, message_id, "🔍 <b>Пошук</b>\n\n✏️ Напиши назву:", {'inline_keyboard': [back_button(back_data), home_button()]})

def show_search_results(chat_id, results, query, search_type):
    if not results:
        send_message(chat_id, f"😔 Нічого не знайдено: <b>{query}</b>", main_menu_keyboard())
        return
    text = f"🎶 <b>Результати:</b> {query}\n\n"
    keyboard = {'inline_keyboard': []}
    for i, t in enumerate(results[:10]):
        dur = format_duration(t.get('duration', 0))
        text += f"{i+1}. {t['title'][:60]}{dur}\n   <i>{t['artist'][:40]}</i>\n"
        keyboard['inline_keyboard'].append([{'text': f"▶️ {t['title'][:50]}", 'callback_data': f"play_{t['video_id']}"}])
    keyboard['inline_keyboard'].append([{'text': '🔍  Новий пошук', 'callback_data': 'menu_search'}])
    keyboard['inline_keyboard'].append(home_button())
    send_message(chat_id, text, keyboard)

def show_playlists(chat_id, message_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ? ORDER BY name', (user_id,))
    playlists = cursor.fetchall()
    keyboard = {'inline_keyboard': []}
    if not playlists:
        text = "📂 <b>Плейлисти</b>\n\nНемає."
    else:
        text = "📂 <b>Плейлисти</b>\n\n"
        for pl in playlists:
            cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl[0],))
            count = cursor.fetchone()[0]
            text += f"• {pl[1]} ({count})\n"
            keyboard['inline_keyboard'].append([{'text': f"📁 {pl[1]}", 'callback_data': f"playlist_{pl[0]}_0"}])
    keyboard['inline_keyboard'].append([{'text': '➕  Створити', 'callback_data': 'create_playlist'}])
    keyboard['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, text, keyboard)

def show_create_playlist_prompt(chat_id, message_id, user_id):
    cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)',
                   (user_id, 'create_playlist', ''))
    conn.commit()
    edit_message(chat_id, message_id, "➕ <b>Новий плейлист</b>\n\n✏️ Напиши назву:", {'inline_keyboard': [back_button('menu_playlists'), home_button()]})

def show_playlist_tracks(chat_id, message_id, pl_id, page=0):
    cursor.execute('SELECT name FROM playlists WHERE id = ?', (pl_id,))
    pl = cursor.fetchone()
    if not pl:
        edit_message(chat_id, message_id, "❌", main_menu_keyboard())
        return
    name = pl[0]
    per_page = 5
    cursor.execute('SELECT video_id, title, artist FROM playlist_tracks WHERE playlist_id = ? LIMIT ? OFFSET ?', (pl_id, per_page, page*per_page))
    tracks = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?', (pl_id,))
    total = cursor.fetchone()[0]
    pages = max(1, (total + per_page - 1) // per_page)
    kb = {'inline_keyboard': []}
    txt = f"📁 <b>{name}</b>\n{page+1}/{pages}\n\n"
    for i, t in enumerate(tracks):
        txt += f"{page*per_page+i+1}. {t[1][:50]}\n"
        kb['inline_keyboard'].append([{'text': f"▶️ {t[1][:45]}", 'callback_data': f"play_{t[0]}"}])
    nav = []
    if page > 0: nav.append({'text': '⬅️', 'callback_data': f'playlist_{pl_id}_{page-1}'})
    nav.append({'text': '🔍', 'callback_data': f'search_in_pl_{pl_id}'})
    if page < pages - 1: nav.append({'text': '➡️', 'callback_data': f'playlist_{pl_id}_{page+1}'})
    if nav: kb['inline_keyboard'].append(nav)
    kb['inline_keyboard'].append([{'text': '🗑  Видалити', 'callback_data': f'delete_pl_{pl_id}'}])
    kb['inline_keyboard'].append(back_button('menu_playlists'))
    kb['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, txt, kb)

def show_favorites(chat_id, message_id, user_id):
    cursor.execute('SELECT video_id, title, artist FROM favorites WHERE user_id = ? ORDER BY title', (user_id,))
    favs = cursor.fetchall()
    kb = {'inline_keyboard': []}
    if not favs:
        txt = "❤️ <b>Улюблене</b>\n\nПусто."
    else:
        txt = f"❤️ <b>Улюблене</b> ({len(favs)})\n\n"
        for f in favs[:20]:
            txt += f"• {f[1][:50]}\n"
            kb['inline_keyboard'].append([{'text': f"▶️ {f[1][:45]}", 'callback_data': f"play_{f[0]}"}])
    kb['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, txt, kb)

def show_track_actions(chat_id, video_id, title, artist):
    kb = {'inline_keyboard': [
        [{'text': '▶️  Грати', 'callback_data': f'play_{video_id}'}, {'text': '❤️', 'callback_data': f'fav_{video_id}'}],
        [{'text': '📋  До плейлисту', 'callback_data': f'addtopl_{video_id}'}],
        home_button()
    ]}
    send_message(chat_id, f"🎵 <b>{title[:80]}</b>\n<i>{artist[:60]}</i>", kb)

def show_add_to_playlist(chat_id, message_id, video_id, user_id):
    cursor.execute('SELECT id, name FROM playlists WHERE user_id = ?', (user_id,))
    pls = cursor.fetchall()
    if not pls:
        api_call('answerCallbackQuery', {'callback_query_id': str(time.time()), 'text': 'Створи плейлист!', 'show_alert': True})
        return
    kb = {'inline_keyboard': []}
    for p in pls:
        kb['inline_keyboard'].append([{'text': f"📁 {p[1]}", 'callback_data': f'addto_{p[0]}_{video_id}'}])
    kb['inline_keyboard'].append(home_button())
    edit_message(chat_id, message_id, "📋 Обери:", kb)

def process_update(update):
    if 'callback_query' in update:
        cb = update['callback_query']
        cid = cb['message']['chat']['id']
        mid = cb['message']['message_id']
        data = cb['data']
        uid = cb['from']['id']
        if uid not in ADMIN_IDS:
            api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '🔒'})
            return
        api_call('answerCallbackQuery', {'callback_query_id': cb['id']})
        
        if data == 'menu_main': show_main_menu(cid, mid)
        elif data == 'menu_search': show_search_menu(cid, mid)
        elif data == 'menu_playlists': show_playlists(cid, mid, uid)
        elif data == 'menu_favorites': show_favorites(cid, mid, uid)
        elif data == 'menu_help': show_help(cid, mid)
        elif data == 'search_track': show_search_prompt(cid, mid, 'track', 'menu_search', uid)
        elif data == 'create_playlist': show_create_playlist_prompt(cid, mid, uid)
        elif data.startswith('playlist_'):
            p = data.split('_')
            show_playlist_tracks(cid, mid, int(p[1]), int(p[2]) if len(p) > 2 else 0)
        elif data.startswith('delete_pl_'):
            pid = int(data.replace('delete_pl_', ''))
            cursor.execute('DELETE FROM playlist_tracks WHERE playlist_id = ?', (pid,))
            cursor.execute('DELETE FROM playlists WHERE id = ? AND user_id = ?', (pid, uid))
            conn.commit()
            show_playlists(cid, mid, uid)
        elif data.startswith('search_in_pl_'):
            pid = int(data.replace('search_in_pl_', ''))
            cursor.execute('INSERT OR REPLACE INTO user_state (user_id, state, value) VALUES (?, ?, ?)', (uid, f'search_in_pl_{pid}', ''))
            conn.commit()
            edit_message(cid, mid, "🔍 Пошук\n\n✏️ Напиши:", {'inline_keyboard': [back_button(f'playlist_{pid}_0'), home_button()]})
        elif data.startswith('play_'):
            vid = data.replace('play_', '')
            fid = get_file_id(vid)
            if fid:
                send_audio_by_id(cid, fid)
                cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (vid,))
                t = cursor.fetchone()
                if t: show_track_actions(cid, vid, t[0], t[1])
            else:
                st = send_message(cid, "⬇️ Завантажую...")
                sid = st['result']['message_id'] if st and st.get('ok') else None
                try:
                    mp3 = download_audio(vid)
                    res = send_audio_file(cid, mp3)
                    if res and res.get('ok'):
                        nfid = res['result']['audio']['file_id']
                        title = res['result']['audio'].get('title', '?')
                        artist = res['result']['audio'].get('performer', '?')
                        save_track_info(vid, title, artist, nfid)
                        if sid: delete_message(cid, sid)
                        show_track_actions(cid, vid, title, artist)
                    elif sid: edit_message(cid, sid, "❌ Помилка", main_menu_keyboard())
                    os.remove(mp3)
                except Exception as e:
                    if sid: edit_message(cid, sid, f"❌ {str(e)[:100]}", main_menu_keyboard())
        elif data.startswith('addtopl_'): show_add_to_playlist(cid, mid, data.replace('addtopl_', ''), uid)
        elif data.startswith('addto_'):
            p = data.split('_')
            pid = int(p[1])
            vid = '_'.join(p[2:])
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (vid,))
            t = cursor.fetchone()
            if t:
                try:
                    cursor.execute('INSERT INTO playlist_tracks (playlist_id, video_id, title, artist) VALUES (?, ?, ?, ?)', (pid, vid, t[0], t[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '✅', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже є', 'show_alert': False})
        elif data.startswith('fav_'):
            vid = data.replace('fav_', '')
            cursor.execute('SELECT title, artist FROM tracks WHERE video_id = ?', (vid,))
            t = cursor.fetchone()
            if t:
                try:
                    cursor.execute('INSERT INTO favorites (user_id, video_id, title, artist) VALUES (?, ?, ?, ?)', (uid, vid, t[0], t[1]))
                    conn.commit()
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': '❤️', 'show_alert': False})
                except:
                    api_call('answerCallbackQuery', {'callback_query_id': cb['id'], 'text': 'Уже є', 'show_alert': False})
    elif 'message' in update:
        msg = update['message']
        cid = msg['chat']['id']
        uid = msg['from']['id']
        text = msg.get('text', '')
        if uid not in ADMIN_IDS:
            send_message(cid, "🔒")
            return
        if text == '/start': show_main_menu(cid)
        elif text == '/menu': show_main_menu(cid)
        else:
            cursor.execute('SELECT state FROM user_state WHERE user_id = ?', (uid,))
            row = cursor.fetchone()
            if row:
                state = row[0]
                if state in ['search_track', 'search_artist']:
                    stype = "track" if state == 'search_track' else "artist"
                    results = search_youtube(text, search_type=stype)
                    show_search_results(cid, results, text, stype)
                elif state == 'create_playlist':
                    name = text.strip()[:50]
                    try:
                        cursor.execute('INSERT INTO playlists (name, user_id) VALUES (?, ?)', (name, uid))
                        conn.commit()
                        send_message(cid, f"✅ {name}", main_menu_keyboard())
                    except:
                        send_message(cid, "❌ Назва існує", main_menu_keyboard())
                elif state.startswith('search_in_pl_'):
                    pid = int(state.replace('search_in_pl_', ''))
                    cursor.execute("SELECT video_id, title, artist FROM playlist_tracks WHERE playlist_id = ? AND title LIKE ? LIMIT 10", (pid, f'%{text}%'))
                    tracks = cursor.fetchall()
                    cursor.execute('SELECT name FROM playlists WHERE id = ?', (pid,))
                    pn = cursor.fetchone()[0]
                    kb = {'inline_keyboard': []}
                    txt = f"🔍 <b>{pn}</b>\n\n"
                    for t in tracks:
                        txt += f"• {t[1][:50]}\n"
                        kb['inline_keyboard'].append([{'text': f"▶️ {t[1][:45]}", 'callback_data': f"play_{t[0]}"}])
                    kb['inline_keyboard'].append(back_button(f'playlist_{pid}_0'))
                    kb['inline_keyboard'].append(home_button())
                    send_message(cid, txt, kb)
                cursor.execute('DELETE FROM user_state WHERE user_id = ?', (uid,))
                conn.commit()

health_app = Flask(__name__)

@health_app.route('/')
def health():
    return 'OK'

def start_health_server():
    health_app.run(host='0.0.0.0', port=10000)

def cleanup_temp_files():
    try:
        for f in os.listdir(tempfile.gettempdir()):
            if f.endswith('.mp3'):
                p = os.path.join(tempfile.gettempdir(), f)
                if time.time() - os.path.getmtime(p) > 3600:
                    os.remove(p)
    except:
        pass

def main():
    print("✅ Bot started", flush=True)
    api_call('deleteWebhook')
    time.sleep(1)
    updates = api_call('getUpdates', {'offset': -1, 'timeout': 1})
    offset = updates['result'][-1]['update_id'] + 1 if updates and updates.get('ok') and updates.get('result') else 0
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
