import asyncio
import random
import aiohttp
from datetime import date
from urllib.parse import quote
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import os

# =================== ТОКЕНЫ И ID ===================
TOKEN = "8561099909:AAGfrKVJ0QftjvGgx0kalGoV15zRYtYSnaw"
OPENROUTER_API_KEY = "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"
MAIN_USER_ID = 1398908364      # Матвей
SECOND_USER_ID = 1324090906    # Ангелина 
START_DATE = date(2025, 10, 23)

PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =================== GOOGLE GEMINI ===================
SYSTEM_PROMPT = """
Ты — романтичный и заботливый помощник для пары Матвея и Ангелины.
Твоя задача — помогать им выражать чувства, генерировать нежные и персонализированные комплименты и предлагать идеи для совместного досуга.
Будь креативным, но всегда очень вежливым и любящим.
"""

async def ask_gemini(prompt: str) -> str:
    """Отправляет запрос к OpenRouter (модель Gemini 2.0 Flash) и возвращает ответ."""
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await resp.text()
                    print(f"OpenRouter error {resp.status}: {error_text}")
                    return ""
    except Exception as e:
        print(f"Ошибка OpenRouter: {e}")
        return ""

# =================== ГЕОКОДИРОВАНИЕ ===================
async def geocode(place_name: str) -> tuple[float, float] | None:
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": place_name, "format": "json", "limit": 1}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers={"User-Agent": "CoupleBot/1.0"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        return float(data[0]["lat"]), float(data[0]["lon"])
        return None
    except Exception as e:
        print(f"Ошибка геокодирования: {e}")
        return None

# =================== FSM ===================
class WantWalk(StatesGroup):
    waiting_for_location = State()

class PlacesState(StatesGroup):
    places_list = State()

# =================== КЛАВИАТУРЫ ===================
def main_menu_kb(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💌 Комплимент", callback_data="compliment")],
        [InlineKeyboardButton(text="❤️ Хочу", callback_data="want_menu")],
        [InlineKeyboardButton(text="❓ Вопросы", callback_data="questions_menu")]
    ])

def questions_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Как дела?", callback_data="q_how_are_you")],
        [InlineKeyboardButton(text="Как настроение?", callback_data="q_mood")],
        [InlineKeyboardButton(text="Как самочувствие?", callback_data="q_health")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main")]
    ])

def want_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶 Погулять", callback_data="want_walk")],
        [InlineKeyboardButton(text="🏠 Посидеть дома", callback_data="want_stay_home")],
        [InlineKeyboardButton(text="🎲 Сходить куда-то", callback_data="want_go_out")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main")]
    ])

def walk_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_want_menu")]
    ])

def places_choice_kb():
    kb = []
    for i in range(1, 6):
        kb.append([InlineKeyboardButton(text=str(i), callback_data=f"choose_place_{i}")])
    kb.append([InlineKeyboardButton(text="Назад", callback_data="back_to_want_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# =================== ТЕКСТЫ ===================
def get_main_text(user_id: int):
    if user_id == SECOND_USER_ID:
        delta = date.today() - START_DATE
        return (f"Привет!\n"
                f"Чуть-чуть о нас:\n"
                f"Дата начала отношений: 23.10.2025\n"
                f"Дней в отношениях: {delta.days}")
    return "ПРИВЕТ"

def get_partner_name(user_id: int) -> str:
    return "Матвей" if user_id == MAIN_USER_ID else "Ангелина"

def get_target_id(user_id: int) -> int:
    return SECOND_USER_ID if user_id == MAIN_USER_ID else MAIN_USER_ID

# =================== /start ===================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    text = get_main_text(user_id)
    await message.answer(text, reply_markup=main_menu_kb(user_id))

# =================== КОМПЛИМЕНТ ===================
@dp.callback_query(F.data == "compliment")
async def send_compliment(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in (MAIN_USER_ID, SECOND_USER_ID):
        await callback.answer("Ты не в паре.", show_alert=True)
        return
    target = get_target_id(user_id)
    if user_id == MAIN_USER_ID:
        comp = random.choice([
            "Твои голубые глаза — как океан 💙",
            "Твоя улыбка освещает всё вокруг!",
            "Твои длинные светлые волосы — просто сказка ✨"
        ])
    else:
        comp = random.choice([
            "Ты самый заботливый и надёжный 💪",
            "Твой ум и чувство юмора покорили меня!",
            "Ты очень сильный и нежный 🧡"
        ])
    await bot.send_message(target, comp)
    await callback.answer("Комплимент отправлен! ❤️")

# =================== МЕНЮ ХОЧУ ===================
@dp.callback_query(F.data == "want_menu")
async def open_want_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("И что же ты хочешь?", reply_markup=want_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "want_stay_home")
async def stay_home(callback: CallbackQuery):
    user_id = callback.from_user.id
    name = get_partner_name(user_id)
    target = get_target_id(user_id)
    await bot.send_message(target, f"{name} хочет посидеть дома 🏠")
    await callback.answer("Сообщение отправлено!")

@dp.callback_query(F.data == "want_walk")
async def start_walk(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WantWalk.waiting_for_location)
    await callback.message.edit_text(
        "Где ты хочешь сегодня погулять?\nОтправь мне свою геопозицию через 📎 (скрепка → Геопозиция)",
        reply_markup=walk_back_kb()
    )
    await callback.answer()

@dp.message(WantWalk.waiting_for_location, F.location)
async def got_location(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    name = get_partner_name(user_id)
    target = get_target_id(user_id)
    lat = message.location.latitude
    lon = message.location.longitude
    await bot.send_location(target, latitude=lat, longitude=lon)
    await bot.send_message(target, f"{name} хочет погулять 📍")
    await state.clear()
    await message.answer("Место отправлено!", reply_markup=want_menu_kb())

@dp.callback_query(F.data == "back_to_want_menu", WantWalk.waiting_for_location)
async def cancel_walk(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("И что же ты хочешь?", reply_markup=want_menu_kb())
    await callback.answer()

# =================== СХОДИТЬ КУДА-ТО (ИИ) ===================
@dp.callback_query(F.data == "want_go_out")
async def generate_places(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in (MAIN_USER_ID, SECOND_USER_ID):
        await callback.answer("Ты не в паре.", show_alert=True)
        return
    await callback.answer("Генерирую интересные места...")
    await callback.message.edit_text("⏳ Генерирую интересные места на сегодня...")

    today_str = date.today().strftime('%d.%m.%Y')
    prompt = (
        f"Сегодня {today_str}. Предложи ровно 5 конкретных, реальных мест для прогулки сегодня **в городе Минске, Беларусь**. "
        "Это должны быть известные парки, кафе, набережные, скверы, кинотеатры или достопримечательности Минска. "
        "Пиши строго в формате: 1. Точное название места – краткое описание (1 предложение). "
        "Например: 1. Парк имени Горького – красивый парк с аттракционами и тенистыми аллеями. "
        "Названия должны быть точными, чтобы их можно было найти на карте Минска."
    )
    response = await ask_gemini(prompt)
    if not response:
        await callback.message.edit_text("Не удалось сгенерировать места. Попробуй ещё раз.", reply_markup=want_menu_kb())
        await callback.answer("Ошибка генерации", show_alert=True)
        return

    raw_places = []
    for line in response.strip().split('\n'):
        line = line.strip()
        if line and len(line) > 2 and line[0].isdigit() and '. ' in line[:4]:
            raw_places.append(line)
    if len(raw_places) < 1:
        raw_places = [response[:500]]
    raw_places = raw_places[:5]

    clean_places = []
    for p in raw_places:
        p = p.replace('**', '')
        if '. ' in p:
            p = p.split('. ', 1)[1]
        clean_places.append(p)

    places_with_coords = []
    for place in clean_places:
        search_name = place.split(' – ')[0] if ' – ' in place else place
        coords = await geocode(search_name)
        places_with_coords.append({
            "description": place,
            "lat": coords[0] if coords else None,
            "lon": coords[1] if coords else None
        })

    display_places = []
    for i, item in enumerate(places_with_coords, 1):
        place = item["description"]
        lat, lon = item["lat"], item["lon"]
        short = place.split(' – ')[0].strip() if ' – ' in place else place
        if lat is not None and lon is not None:
            url = f"https://yandex.ru/maps/?ll={lon},{lat}&z=15&text={quote(short)}"
        else:
            url = f"https://yandex.ru/maps/?text={quote(place)}"
        display_text = f"{i}. {place} <a href='{url}'>Нажми</a>"
        display_places.append(display_text)

    await state.set_state(PlacesState.places_list)
    await state.update_data(places=places_with_coords)

    text = "🌟 <b>Интересные места сегодня:</b>\n\n" + "\n\n".join(display_places)
    await callback.message.edit_text(text, reply_markup=places_choice_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("choose_place_"), PlacesState.places_list)
async def choose_place(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    places_data = data.get("places", [])
    idx = int(callback.data.split("_")[-1]) - 1
    if idx < 0 or idx >= len(places_data):
        await callback.answer("Неверный выбор", show_alert=True)
        return

    item = places_data[idx]
    chosen_text = item["description"]
    target = get_target_id(user_id)
    name = get_partner_name(user_id)

    await bot.send_message(target, f"{name} хочет посетить:\n\n{chosen_text}")

    lat, lon = item["lat"], item["lon"]
    if lat is not None and lon is not None:
        await bot.send_location(target, latitude=lat, longitude=lon)
    else:
        place_for_geo = chosen_text.split(' – ')[0] if ' – ' in chosen_text else chosen_text
        location = await geocode(place_for_geo)
        if location:
            await bot.send_location(target, latitude=location[0], longitude=location[1])
        else:
            await bot.send_message(target, "Не удалось определить местоположение, но место всё равно отличное!")

    await state.clear()
    await callback.message.edit_text("И что же ты хочешь?", reply_markup=want_menu_kb())
    await callback.answer("Место отправлено!")

@dp.callback_query(F.data == "back_to_want_menu", PlacesState.places_list)
async def back_from_places(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("И что же ты хочешь?", reply_markup=want_menu_kb())
    await callback.answer()

# =================== ВОПРОСЫ ===================
@dp.callback_query(F.data == "questions_menu")
async def open_questions(callback: CallbackQuery):
    await callback.message.edit_text("Тест 2", reply_markup=questions_menu_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("q_"))
async def send_question(callback: CallbackQuery):
    user_id = callback.from_user.id
    target = get_target_id(user_id)
    if callback.data == "q_how_are_you":
        text = "Как дела?"
    elif callback.data == "q_mood":
        text = "Как настроение?"
    elif callback.data == "q_health":
        text = "Как самочувствие?"
    else:
        return
    await bot.send_message(target, text)
    await callback.answer("Сообщение отправлено!")

# =================== НАЗАД В ГЛАВНОЕ МЕНЮ ===================
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    text = get_main_text(user_id)
    await callback.message.edit_text(text, reply_markup=main_menu_kb(user_id))
    await callback.answer()

# =================== WEBHOOK СЕРВЕР ===================
async def on_startup(bot: Bot):
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        print(f"Webhook set to {WEBHOOK_URL}/webhook")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Server started on port {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
