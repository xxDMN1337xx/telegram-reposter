async def check_with_gpt(text: str, client) -> str:
    clean_text = sanitize_input(text.replace('"', "'").replace("
", " "))

    prompt = (
        "Ты ассистент, помогающий отбирать посты для Telegram-канала по арбитражу трафика.

"
        "Тебе НЕЛЬЗЯ допускать к публикации следующие типы постов:
"
        "- личные посты (о жизни, мотивации, погоде, мнения, размышления, философия)
"
        "- общая реклама и нецелевые офферы
"
        "- любые бесполезные и ни о чём тексты, без конкретных действий, результатов или данных
"
        "- интервью, подкасты, беседы, видеоинтервью
"
        "- розыгрыши, конкурсы, призы, подарки
"
        "- посты про вечеринки, конференции, собрания, митапы, тусовки и сходки
"
        "- лонгриды или колонки без конкретики: без связок, инструментов, цифр или кейсов
"
        "- жалобы, наблюдения, история развития рынка, «эволюция контента» и т.д.

"
        "Публиковать можно ТОЛЬКО если пост содержит:
"
        "- конкретную пользу для арбитражников: кейсы, схемы, инсайты, цифры, советы, таблицы
"
        "- конкретные связки, источники трафика, подходы, платформы, сравнение офферов
"
        "- полезные инструменты, спай, автоматизацию, API, скрипты, парсеры, настройки
"
        "- обзоры или новости об ИИ-инструментах (SkyReels, Scira, Sora, ChatGPT, MidJourney, Runway и т.д.)
"
        "- новости по платформам, трекерам, банам, обновлениям, платёжкам и т.д.

"
        "Если в тексте нет конкретной пользы — считай его бесполезным.
"
        "Не будь мягким. Отсеивай всё, что не даст выгоды арбитражнику.

"
        f"Анализируй текст поста:
\"{clean_text}\"

"
        "Ответь **одним словом**, выбери только из: реклама, бесполезно, полезно."
    )

    total = len(fallback_providers)

    async def call_provider(provider, index):
        try:
            # Сначала пробуем без model
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        g4f.ChatCompletion.create,
                        provider=provider,
                        messages=[{"role": "user", "content": prompt}]
                    ),
                    timeout=30
                )
            except Exception:
                # Если не сработало — пробуем с model="gpt-3.5"
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            g4f.ChatCompletion.create,
                            provider=provider,
                            model="gpt-3.5",
                            messages=[{"role": "user", "content": prompt}]
                        ),
                        timeout=30
                    )
                except Exception:
                    # Если не сработало вообще — пропускаем провайдера
                    return None

            result = (response or "").strip().lower()
            result = re.sub(r'[^а-яА-Я]', '', result)
            if result in ['реклама', 'бесполезно', 'полезно']:
                await client.send_message(CHANNEL_TRASH, escape_markdown_v2(f"{index+1}/{total} ✅ {provider.__name__}: {result}"), parse_mode='markdown_v2')
                return result
            else:
                await client.send_message(CHANNEL_TRASH, escape_markdown_v2(f"{index+1}/{total} ⚠️ {provider.__name__} странный ответ: '{result}'"), parse_mode='markdown_v2')
        except Exception as e:
            await client.send_message(CHANNEL_TRASH, escape_markdown_v2(f"{index+1}/{total} ❌ {provider.__name__} ошибка: {str(e)[:100]}"), parse_mode='markdown_v2')
        return None

    tasks = [call_provider(p, i) for i, p in enumerate(fallback_providers)]
    raw_results = await asyncio.gather(*tasks)

    summary = {"полезно": 0, "реклама": 0, "бесполезно": 0}
    for result in raw_results:
        if result in summary:
            summary[result] += 1

    total_valid = sum(summary.values())

    if total_valid == 0:
        await client.send_message(CHANNEL_TRASH, escape_markdown_v2("❌ Ни один GPT-провайдер не дал ответ. Повтор через 30 минут."), parse_mode='markdown_v2')
        await asyncio.sleep(1800)
        return await check_with_gpt(text, client)

    await client.send_message(CHANNEL_TRASH, escape_markdown_v2(f"📊 Сводка: {summary}"), parse_mode='markdown_v2')

    if summary["полезно"] > (summary["реклама"] + summary["бесполезно"]):
        return "полезно"
    else:
        return "мусор"


async def handle_message(event, client):
    # Только для каналов (чаты, супергруппы и лички игнорируются)
    if not getattr(event, "is_channel", False):
        return

    load_filter_words()

    if event.poll or event.voice or event.video_note:
        return

    message_text = event.message.text or ""
    if not message_text.strip():
        return

    if len(message_text) > 2000:
        await client.send_message(CHANNEL_TRASH, escape_markdown_v2(f"⚠️ Сообщение обрезано до 2000 символов (было {len(message_text)})"), parse_mode='MarkdownV2')

    normalized = normalize_text(message_text)
    if filter_words.intersection(normalized):
        return

    result = await check_with_gpt(message_text, client)

    messages_to_forward = [event.message]
    if event.message.grouped_id:
        async for msg in client.iter_messages(event.chat_id, min_id=event.message.id - 10, max_id=event.message.id + 10):
            if msg.grouped_id == event.message.grouped_id and msg.id != event.message.id:
                messages_to_forward.append(msg)
    messages_to_forward.sort(key=lambda m: m.id)

    # --- Определение источника ---
    if event.message.fwd_from and getattr(event.message.fwd_from.from_id, 'channel_id', None):
        channel_id = event.message.fwd_from.from_id.channel_id
        try:
            orig_chat = await client.get_entity(channel_id)
            if hasattr(orig_chat, "username") and orig_chat.username:
                source_url = f"https://t.me/{orig_chat.username}"
            else:
                source_url = f"Канал: {getattr(orig_chat, 'title', 'Без названия')} (ID: {channel_id})"
        except Exception as e:
            source_url = f"Неизвестный канал (ID: {channel_id})"
    else:
        chat = await event.get_chat()
        if hasattr(chat, "username") and chat.username:
            source_url = f"https://t.me/{chat.username}"
        else:
            source_url = f"Канал: {getattr(chat, 'title', 'Без названия')} (ID: {chat.id})"

    target_channel = CHANNEL_GOOD if result == "полезно" else CHANNEL_TRASH

    media_files = []
    full_text = ""

    for msg in messages_to_forward:
        if msg.media:
            media_files.append(msg.media)
        if msg.text:
            full_text += msg.text.strip() + "\n"

    if full_text.strip():
        text_parts = split_text(full_text.strip(), SPLIT_LEN)
        text_parts[-1] = text_parts[-1] + f"\n\nИсточник: {source_url}"
    else:
        text_parts = [f"Источник: {source_url}"]

    if media_files:
        caption, rest_parts = split_caption_and_text(text_parts[0], CAPTION_LEN, SPLIT_LEN)
        try:
            await client.send_file(
                target_channel,
                file=media_files,
                caption=escape_markdown_v2(caption),
                force_document=False,
                parse_mode='MarkdownV2'
            )
            for part in rest_parts + text_parts[1:]:
                await client.send_message(target_channel, escape_markdown_v2(part), parse_mode='MarkdownV2')
        except Exception as e:
            print(f"[!] Ошибка отправки медиа: {e}")
    else:
        for part in text_parts:
            await client.send_message(target_channel, escape_markdown_v2(part), parse_mode='MarkdownV2')

    print(f"[OK] Копия с источника: {source_url}")

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        await handle_message(event, client)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
