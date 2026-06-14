import os
import json
import tempfile
import sqlite3
import urllib.request
import yt_dlp
import time
import ssl

print("=== STARTING ===", flush=True)

BOT_TOKEN = "8981234358:AAHMZAirobfP_F-bt5WCY1LJxyRMW0E5OH8"
ADMIN_ID = 2104120716
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

DB_PATH = '/data/music.db'
os.makedirs('/data', exist_ok=True)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (video_id TEXT UNIQUE, title TEXT, file_id TEXT)''')
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

def search_youtube(query, max_results=5):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            return [{'video_id': e.get('id',''), 'title': e.get('title','')[:60]} 
                    for e in info.get('entries', []) if e]
    except:
        return []

def download_audio(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    temp_dir = tempfile.gettempdir()
    output = os.path.join(temp_dir, f"{video_id}.%(ext)s")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True, 'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return os.path.join(temp_dir, f"{video_id}.mp3")

def send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return api_call('sendMessage', params)

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

def save_file_id(video_id, title, file_id):
    cursor.execute('INSERT OR REPLACE INTO tracks (video_id, title, file_id) VALUES (?, ?, ?)', 
                   (video_id, title, file_id))
    conn.commit()

def process_update(update):
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        if user_id != ADMIN_ID:
            send_message(chat_id, "🔒 Приватний бот")
            return
        text = msg.get('text', '')
        if text.startswith('/start'):
            send_message(chat_id, "🎵 Бот готов!\n/s назва треку")
        elif text.startswith('/s'):
            query = text.replace('/s', '').strip()
            if not query:
                send_message(chat_id, "❌ /s назва треку")
                return
            send_message(chat_id, f"🔍 Шукаю: {query}")
            results = search_youtube(query)
            if not results:
                send_message(chat_id, "😔 Нічого не знайдено")
                return
            inline_keyboard = []
            for t in results:
                inline_keyboard.append([{'text': f"▶️ {t['title']}", 'callback_data': f"play_{t['video_id']}"}])
            send_message(chat_id, "🎶 Результати:", reply_markup={'inline_keyboard': inline_keyboard})
    elif 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        data = cb['data']
        api_call('answerCallbackQuery', {'callback_query_id': cb['id']})
        if data.startswith('play_'):
            video_id = data.replace('play_', '')
            file_id = get_file_id(video_id)
            if file_id:
                send_audio_by_id(chat_id, file_id)
            else:
                send_message(chat_id, "⬇️ Завантажую...")
                try:
                    mp3_path = download_audio(video_id)
                    result = send_audio_file(chat_id, mp3_path)
                    if result and result.get('ok'):
                        new_file_id = result['result']['audio']['file_id']
                        save_file_id(video_id, 'track', new_file_id)
                    os.remove(mp3_path)
                except Exception as e:
                    send_message(chat_id, f"❌ Помилка: {str(e)[:100]}")

def main():
    print("✅ Bot started", flush=True)
    offset = 0
    while True:
        try:
            updates = api_call('getUpdates', {'offset': offset, 'timeout': 30})
            if updates and updates.get('ok') and updates.get('result'):
                for upd in updates['result']:
                    offset = upd['update_id'] + 1
                    process_update(upd)
            time.sleep(1)
        except Exception as e:
            print(f"Loop error: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
