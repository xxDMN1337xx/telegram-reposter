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

# Функция test_provider теперь принимает имя модели для использования
async def test_provider(provider: g4f.Provider.BaseProvider, model_to_use: str):
    provider_name = provider.__name__
    try:
        response = await g4f.ChatCompletion.create_async(
            model=model_to_use, # Используем переданную модель
            messages=[{"role": "user", "content": TEST_PROMPT}],
            provider=provider,
            timeout=REQUEST_TIMEOUT
        )
        cleaned_response = response.strip().replace('\n', ' ').replace('\r', '') if response else None
        if cleaned_response:
            return provider_name, cleaned_response
        return provider_name, None
    except Exception:
        return provider_name, None

async def worker(provider, semaphore, file_handle, counters):
    async with semaphore:
        # ====================================================================
        # ВАША ЛОГИКА ОПРЕДЕЛЕНИЯ МОДЕЛИ (ИНТЕГРИРОВАНА СЮДА)
        # ====================================================================
        # Используем getattr для безопасного получения списка моделей
        model_list = getattr(provider, "models", [])
        
        # Выбираем первую модель из списка, если он не пуст, иначе используем запасную
        if model_list and isinstance(model_list, list) and len(model_list) > 0:
            model_to_use = model_list[0]
        else:
            model_to_use = "gpt-3.5-turbo" # Запасной вариант, если список пуст или некорректен
        # ====================================================================

        # Передаем выбранную модель в функцию тестирования
        provider_name, response = await test_provider(provider, model_to_use)
        counters['completed'] += 1
        
        total, completed, successful = counters['total'], counters['completed'], counters['successful']
        status_line = f"[Проверено: {completed}/{total} | Успешно: {successful}]"
        
        if response:
            counters['successful'] += 1
            status_line = f"[Проверено: {completed}/{total} | Успешно: {counters['successful']}]"
            
            # Обновленный формат записи в файл с добавлением модели
            result_str = (
                f"Провайдер: {provider_name}\n"
                f"Модель: {model_to_use}\n"
                f"Ответ: {response}\n"
                f"{'-'*20}\n\n"
            )
            file_handle.write(result_str)
            file_handle.flush()
            
            # Очищаем строку и выводим расширенную информацию
            print(f"{' ' * 120}\r", end="")
            # Обновленный формат вывода в консоль
            print(f"[+] УСПЕХ: {provider_name:<25} | Модель: {model_to_use:<25} | Ответ: {response}")

        print(status_line, end='\r', flush=True)

async def main():
    all_known_providers = list(g4f.Provider.__map__.values())
    
    # Сохраняем надежную фильтрацию, которая отсеивает провайдеры для изображений
    chat_providers = [
        p for p in all_known_providers if not getattr(p, 'supports_image_generation', False)
    ]

    total_providers = len(chat_providers)
    
    print(f"Найдено {len(all_known_providers)} провайдеров. "
          f"После фильтрации осталось {total_providers} текстовых чатов.")
    print(f"Начинаю проверку...")
    print(f"Запускаю проверку (до {CONCURRENT_LIMIT} одновременных запросов)...")
    print(f"Результаты будут записываться в '{OUTPUT_FILE}' по мере их поступления.\n")
    
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
