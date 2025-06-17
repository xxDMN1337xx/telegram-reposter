import g4f
import asyncio
import sys

# --- НАСТРОЙКИ ---
CONCURRENT_LIMIT = 20
TEST_PROMPT = "ответь одним словом, помидор красный или фиолетовый?"
OUTPUT_FILE = "good_chat_providers.txt"
REQUEST_TIMEOUT = 30
# --- КОНЕЦ НАСТРОЕК ---

# Установка кодировки
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

async def test_provider(provider: g4f.Provider.BaseProvider):
    provider_name = provider.__name__
    try:
        response = await g4f.ChatCompletion.create_async(
            model=g4f.models.default,
            messages=[{"role": "user", "content": TEST_PROMPT}],
            provider=provider,
            timeout=REQUEST_TIMEOUT
        )
        # Очищаем ответ от переносов строк для более чистого вывода
        cleaned_response = response.strip().replace('\n', ' ').replace('\r', '') if response else None
        if cleaned_response:
            return provider_name, cleaned_response
        return provider_name, None
    except Exception:
        return provider_name, None

async def worker(provider, semaphore, file_handle, counters):
    async with semaphore:
        provider_name, response = await test_provider(provider)
        counters['completed'] += 1
        
        total = counters['total']
        completed = counters['completed']
        successful = counters['successful']
        status_line = f"[Проверено: {completed}/{total} | Успешно: {successful}]"
        
        if response:
            counters['successful'] += 1
            status_line = f"[Проверено: {completed}/{total} | Успешно: {counters['successful']}]"
            result_str = (
                f"Провайдер: {provider_name}\n"
                f"Ответ: {response}\n"
                f"{'-'*20}\n\n"
            )
            file_handle.write(result_str)
            file_handle.flush()
            print(f"{' ' * 80}\r", end="")
            print(f"[+] УСПЕХ: {provider_name:<25} | Ответ: {response}")

        print(status_line, end='\r', flush=True)

async def main():
    # 1. Получаем абсолютно всех известных провайдеров
    all_known_providers = list(g4f.Provider.__map__.values())
    
    # 2. ПРАВИЛЬНАЯ ФИЛЬТРАЦИЯ: ИСКЛЮЧАЕМ ПРОВАЙДЕРЫ ДЛЯ ИЗОБРАЖЕНИЙ
    # Мы оставляем провайдер (p), если у него НЕТ атрибута 'supports_image_generation',
    # или если этот атрибут равен False.
    chat_providers = [
        p for p in all_known_providers if not getattr(p, 'supports_image_generation', False)
    ]

    total_providers = len(chat_providers)
    
    print(f"Найдено {len(all_known_providers)} провайдеров, из них {total_providers} являются текстовыми чатами (или неизвестного типа).")
    print(f"Начинаю проверку...")
    print(f"Запускаю проверку (до {CONCURRENT_LIMIT} одновременных запросов)...")
    print(f"Результаты будут записываться в '{OUTPUT_FILE}' по мере их поступления.\n")
    
    # Если вдруг список оказался пуст, выходим
    if not total_providers:
        print("Не найдено ни одного подходящего провайдера для проверки.")
        return

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    counters = {'completed': 0, 'successful': 0, 'total': total_providers}
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- Начало проверки --- (Промпт: '{TEST_PROMPT}')\n\n")
        tasks = [
            worker(provider, semaphore, f, counters) for provider in chat_providers
        ]
        await asyncio.gather(*tasks)

    print("\n\n" + "="*50)
    print("Проверка завершена!")
    print(f"Рабочих чат-провайдеров найдено: {counters['successful']} из {total_providers}")
    print(f"Все результаты записаны в файл: '{OUTPUT_FILE}'")
    print("="*50)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
