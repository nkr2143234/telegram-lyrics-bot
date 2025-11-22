import telebot
import lyricsgenius
import requests
import re
import sys
import os
from deep_translator import GoogleTranslator

TELEGRAM_TOKEN = "8329769044:AAFilq3rKfrJh8K7JWfH0k0MpWU2HhYLqZs"
GENIUS_TOKEN = "vJ8UJ8v6gHC2YrshS-G1X2uJ5vXo_CVA25p94O13BBXowqMWK3q-s4nrEExs_Yiu"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# НАСТРОЙКА GENIUS С ОБХОДОМ БЛОКИРОВКИ
genius = lyricsgenius.Genius(GENIUS_TOKEN)
genius.verbose = False
genius.remove_section_headers = True
genius.skip_non_songs = True
genius.excluded_terms = ["(Remix)", "(Live)"]

# ВАЖНЫЕ HEADERS ДЛЯ ОБХОДА 403 ОШИБКИ
genius._session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://genius.com/',
})

user_lyrics = {}
user_albums = {}


def clean_lyrics(lyrics):
    """Очистка оригинального текста от всей лишней информации"""
    if not lyrics:
        return ""

    lines = lyrics.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()

        if any(pattern in line for pattern in [
            'Contributor',
            'Contributors',
            'Lyrics',
            'cover of',
            're-produced by',
            'released on',
            'The song was',

        ]):
            continue

        if line and not line.isspace():
            cleaned_lines.append(line)

    cleaned = '\n'.join(cleaned_lines)

    cleaned = re.sub(r'\d+Embed$', '', cleaned)

    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip()


def clean_translation(translated_text, original_title, original_artist):
    """Очистка перевода от всей лишней информации"""
    lines = translated_text.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()

        if any(pattern in line for pattern in [
            'Contributor',
            'Contributors',
            'Translations',
            'Lyrics',
            'Текст песни',
            'Видео на',
            'describes',
            'Read More',
            'Подробнее',
            'On "',
            'He details',
            'laments about',
            'cover of',
            're-produced by',
            'released on',
            'The song was',
            'Песня была выпущена',
            'была выпущена',
            'Введение',
            'Introduction'
        ]):
            continue

        if line and not line.isspace():

            replacements = {
                '[Intro]': '🎵',
                '[Outro]': '🎵',
                '[Bridge]': '🎵',
                '[Chorus]': '🎵 ПРИПЕВ:',
                '[Refrain]': '🎵',
                '[Verse]': '🎵 КУПЛЕТ:',
                'Intro': '🎵',
                'Outro': '🎵',
                'Bridge': '🎵',
                'Chorus': '🎵 ПРИПЕВ:',
                'Refrain': '🎵',
                'Verse': '🎵 КУПЛЕТ:',
                'Введение': '',
                'Припев': '🎵 ПРИПЕВ:',
                'Куплет': '🎵 КУПЛЕТ:',
                'Мост': '🎵',
                'Рефрен': '🎵'
            }

            for eng, rus in replacements.items():
                line = line.replace(eng, rus)

            line = re.sub(r'\([^)]*[A-Z][a-z]+\)', '', line)
            line = re.sub(r'\([^)]*[а-яА-Я]+\)', '', line)

            cleaned_lines.append(line)

    cleaned = '\n'.join(cleaned_lines)

    cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return f"🎵 {original_title} - {original_artist}\n🇷🇺 *Перевод на русский:*\n\n❌ Не удалось очистить перевод"

    header = f"🎵 {original_title} - {original_artist}\n"
    header += "🇷🇺 *Перевод на русский:*\n\n"

    return header + cleaned


def translate_text(text, original_title, original_artist):
    """Перевод текста с очисткой"""
    try:
        if len(text) > 4000:
            text = text[:4000]

        translated = GoogleTranslator(source='auto', target='ru').translate(text)
        cleaned_translation = clean_translation(translated, original_title, original_artist)

        return cleaned_translation
    except Exception as e:
        return f"❌ Ошибка перевода: {str(e)}"


def create_main_keyboard():
    """Главное меню"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🎵 Поиск трека', '📀 Поиск альбома')
    return markup


def create_translate_keyboard():
    """Кнопка перевода для треков"""
    markup = telebot.types.InlineKeyboardMarkup()
    translate_btn = telebot.types.InlineKeyboardButton("🇷🇺 Перевести на русский", callback_data="translate_ru")
    markup.add(translate_btn)
    return markup


def create_album_keyboard(album_data, page=0):
    """Клавиатура для навигации по альбому"""
    markup = telebot.types.InlineKeyboardMarkup()

    tracks_per_page = 8
    start_idx = page * tracks_per_page
    end_idx = start_idx + tracks_per_page

    tracks = album_data['tracks']

    for i in range(start_idx, min(end_idx, len(tracks))):
        track = tracks[i]
        btn = telebot.types.InlineKeyboardButton(
            f"{i + 1}. {track['title'][:30]}",
            callback_data=f"album_track_{page}_{i}"
        )
        markup.add(btn)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"album_page_{page - 1}"))
    if end_idx < len(tracks):
        nav_buttons.append(telebot.types.InlineKeyboardButton("Вперед ➡️", callback_data=f"album_page_{page + 1}"))

    if nav_buttons:
        markup.row(*nav_buttons)

    markup.row(telebot.types.InlineKeyboardButton("🔍 Новый поиск", callback_data="new_search"))

    return markup


def create_track_navigation(album_data, current_track_index, page):
    """Навигация по трекам в альбоме"""
    markup = telebot.types.InlineKeyboardMarkup()
    tracks = album_data['tracks']

    nav_buttons = []
    if current_track_index > 0:
        nav_buttons.append(telebot.types.InlineKeyboardButton("⬅️ Предыдущий",
                                                              callback_data=f"album_track_{page}_{current_track_index - 1}"))

    nav_buttons.append(telebot.types.InlineKeyboardButton("📀 К альбому", callback_data=f"album_page_{page}"))

    if current_track_index < len(tracks) - 1:
        nav_buttons.append(telebot.types.InlineKeyboardButton("Следующий ➡️",
                                                              callback_data=f"album_track_{page}_{current_track_index + 1}"))

    markup.row(*nav_buttons)
    markup.row(telebot.types.InlineKeyboardButton("🇷🇺 Перевести",
                                                  callback_data=f"translate_album_track_{current_track_index}"))
    markup.row(telebot.types.InlineKeyboardButton("🔍 Новый поиск", callback_data="new_search"))

    return markup


def search_album(album_name):
    """Поиск альбома по названию"""
    try:
        # ДОБАВЛЕНЫ HEADERS ДЛЯ REQUESTS
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://genius.com/'
        }

        search_url = f"https://genius.com/api/search/album?q={requests.utils.quote(album_name)}"
        response = requests.get(search_url, timeout=10, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if data['response']['sections'] and data['response']['sections'][0]['hits']:
                album_hit = data['response']['sections'][0]['hits'][0]
                album_data = album_hit['result']

                print(f"Найден альбом: {album_data['name']} - {album_data['artist']['name']}")

                album_id = album_data['id']
                tracks_url = f"https://genius.com/api/albums/{album_id}/tracks"
                tracks_response = requests.get(tracks_url, timeout=10, headers=headers)

                if tracks_response.status_code == 200:
                    tracks_data = tracks_response.json()
                    tracks = []

                    for track in tracks_data['response']['tracks']:
                        tracks.append({
                            'title': track['song']['title'],
                            'artist': track['song']['artist_names'],
                            'url': track['song']['url']
                        })

                    print(f"Найдено треков: {len(tracks)}")

                    return {
                        'title': album_data['name'],
                        'artist': album_data['artist']['name'],
                        'release_date': album_data.get('release_date', 'Неизвестно'),
                        'tracks': tracks,
                        'success': True
                    }
                else:
                    print("Ошибка при получении треков")

        print("Альбом не найден в API")
        return {'success': False, 'error': 'Альбом не найден'}

    except Exception as e:
        print(f"Ошибка поиска альбома: {e}")
        return {'success': False, 'error': str(e)}


def search_album_fallback(album_name):
    """Альтернативный поиск альбома через поиск песен"""
    try:
        # ДОБАВЛЕНЫ HEADERS ДЛЯ REQUESTS
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://genius.com/'
        }

        search_url = f"https://genius.com/api/search/song?q={requests.utils.quote(album_name)}"
        response = requests.get(search_url, timeout=10, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if data['response']['sections'] and data['response']['sections'][0]['hits']:

                albums = {}

                for hit in data['response']['sections'][0]['hits'][:10]:
                    song_data = hit['result']
                    album_info = song_data.get('album', {})

                    if album_info and album_info.get('name'):
                        album_name = album_info['name']
                        if album_name not in albums:
                            albums[album_name] = {
                                'title': album_info['name'],
                                'artist': album_info.get('artist', {}).get('name', song_data['artist_names']),
                                'tracks': []
                            }

                        albums[album_name]['tracks'].append({
                            'title': song_data['title'],
                            'artist': song_data['artist_names'],
                            'url': song_data['url']
                        })

                if albums:
                    first_album = list(albums.values())[0]
                    print(f"Найден альбом через fallback: {first_album['title']}")
                    return {**first_album, 'success': True}

        return {'success': False, 'error': 'Альбом не найден'}

    except Exception as e:
        print(f"Ошибка fallback поиска: {e}")
        return {'success': False, 'error': str(e)}


@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """🎵 *Lyrics Finder Bot*

Я помогу найти тексты песен и альбомы!

*Что умею:*
• 🔍 Поиск текстов по названию
• 📀 Просмотр треков альбома
• 🇷🇺 Перевод текстов на русский

Выбери действие в меню ниже 👇"""
    bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=create_main_keyboard())


@bot.message_handler(func=lambda message: message.text == '🎵 Поиск трека')
def search_track_mode(message):
    msg = bot.send_message(message.chat.id, "🔍 *Режим поиска трека*\n\nВведите название песни и исполнителя:",
                           parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_track_search)


@bot.message_handler(func=lambda message: message.text == '📀 Поиск альбома')
def search_album_mode(message):
    msg = bot.send_message(message.chat.id, "📀 *Режим поиска альбома*\n\nВведите название альбома:",
                           parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_album_search)


def process_track_search(message):
    try:
        query = message.text.strip()
        if len(query) < 2:
            bot.send_message(message.chat.id, "❌ Слишком короткий запрос")
            return

        bot.send_chat_action(message.chat.id, 'typing')

        try:
            song = genius.search_song(query)
        except Exception as e:
            print(f"Genius API error: {e}")
            bot.send_message(message.chat.id, "❌ Ошибка доступа к Genius API. Попробуйте позже.")
            return

        if song:
            lyrics = clean_lyrics(song.lyrics)

            user_lyrics[message.chat.id] = {
                'lyrics': lyrics,
                'title': song.title,
                'artist': song.artist
            }

            if len(lyrics) > 3500:
                lyrics = lyrics[:3500] + "..."

            response = f"🎵 {song.title} - {song.artist}\n\n{lyrics}"
            bot.send_message(message.chat.id, response, reply_markup=create_translate_keyboard())
        else:
            bot.send_message(message.chat.id, f"❌ Не найдено: \"{query}\"")

    except Exception as e:
        bot.send_message(message.chat.id, f"😞 Ошибка: {str(e)}")


def process_album_search(message):
    try:
        query = message.text.strip()
        if len(query) < 2:
            bot.send_message(message.chat.id, "❌ Слишком короткий запрос")
            return

        bot.send_chat_action(message.chat.id, 'typing')

        album_result = search_album(query)

        if not album_result['success']:
            bot.send_message(message.chat.id, "🔄 Пробую альтернативный поиск...")
            album_result = search_album_fallback(query)

        if album_result['success']:

            user_albums[message.chat.id] = album_result

            album_info = f"📀 *{album_result['title']}* - {album_result['artist']}"
            if album_result.get('release_date'):
                album_info += f"\n📅 {album_result['release_date']}"
            album_info += f"\n🎵 {len(album_result['tracks'])} треков\n"

            bot.send_message(
                message.chat.id,
                album_info,
                parse_mode='Markdown',
                reply_markup=create_album_keyboard(album_result, 0)
            )
        else:
            bot.send_message(message.chat.id,
                             f"❌ Альбом не найден: \"{query}\"\n\nПопробуй уточнить название или искать конкретные треки.")

    except Exception as e:
        bot.send_message(message.chat.id, f"😞 Ошибка: {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data.startswith('album_page_'))
def handle_album_page(call):
    """Обработка перелистывания страниц альбома"""
    try:
        page = int(call.data.split('_')[2])
        chat_id = call.message.chat.id

        if chat_id in user_albums:
            album_data = user_albums[chat_id]

            bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=create_album_keyboard(album_data, page)
            )

        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data.startswith('album_track_'))
def handle_album_track(call):
    """Обработка выбора трека из альбома"""
    try:
        parts = call.data.split('_')
        page = int(parts[2])
        track_index = int(parts[3])
        chat_id = call.message.chat.id

        if chat_id in user_albums:
            album_data = user_albums[chat_id]
            track = album_data['tracks'][track_index]

            bot.send_message(chat_id, f"🔍 Ищу текст: {track['title']}")
            bot.send_chat_action(chat_id, 'typing')

            search_query = f"{track['title']} {track['artist']}"
            song = genius.search_song(search_query)

            if song:
                lyrics = clean_lyrics(song.lyrics)

                user_lyrics[chat_id] = {
                    'lyrics': lyrics,
                    'title': track['title'],
                    'artist': track['artist']
                }

                if len(lyrics) > 3500:
                    lyrics = lyrics[:3500] + "..."

                response = f"🎵 {track['title']} - {track['artist']}\n\n{lyrics}"

                bot.send_message(
                    chat_id,
                    response,
                    reply_markup=create_track_navigation(album_data, track_index, page)
                )
            else:
                bot.send_message(chat_id, f"❌ Текст трека не найден: {track['title']}")

        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data == "translate_ru")
def handle_translation(call):
    """Обработка перевода для обычного поиска"""
    try:
        chat_id = call.message.chat.id

        if chat_id not in user_lyrics:
            bot.answer_callback_query(call.id, "❌ Текст не найден для перевода")
            return

        bot.answer_callback_query(call.id, "🔄 Перевод...")
        bot.send_chat_action(chat_id, 'typing')

        user_data = user_lyrics[chat_id]
        original_text = user_data['lyrics']
        title = user_data['title']
        artist = user_data['artist']

        translated = translate_text(original_text, title, artist)

        if len(translated) > 4000:
            parts = [translated[i:i + 4000] for i in range(0, len(translated), 4000)]
            for part in parts:
                bot.send_message(chat_id, part, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, translated, parse_mode='Markdown')

    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Ошибка перевода")


@bot.callback_query_handler(func=lambda call: call.data.startswith('translate_album_track_'))
def handle_album_track_translation(call):
    """Обработка перевода для трека из альбома"""
    try:
        track_index = int(call.data.split('_')[3])
        chat_id = call.message.chat.id

        if chat_id in user_lyrics:
            bot.answer_callback_query(call.id, "🔄 Перевод...")
            bot.send_chat_action(chat_id, 'typing')

            user_data = user_lyrics[chat_id]
            original_text = user_data['lyrics']
            title = user_data['title']
            artist = user_data['artist']

            translated = translate_text(original_text, title, artist)

            if len(translated) > 4000:
                parts = [translated[i:i + 4000] for i in range(0, len(translated), 4000)]
                for part in parts:
                    bot.send_message(chat_id, part, parse_mode='Markdown')
            else:
                bot.send_message(chat_id, translated, parse_mode='Markdown')
        else:
            bot.answer_callback_query(call.id, "❌ Текст не найден")

    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Ошибка перевода")


@bot.callback_query_handler(func=lambda call: call.data == "new_search")
def handle_new_search(call):
    """Обработка кнопки нового поиска"""
    bot.send_message(call.message.chat.id, "🔍 Выбери тип поиска:", reply_markup=create_main_keyboard())
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Обработка остальных сообщений"""

    process_track_search(message)


if __name__ == "__main__":
    print("Бот запущен с улучшенным поиском альбомов!")
    
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        print(f"Ошибка: {e}")
        # Автоперезапуск через 10 секунд
        import time
        time.sleep(10)
        os.execv(sys.executable, ['python'] + sys.argv)
