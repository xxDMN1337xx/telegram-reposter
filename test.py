import g4f
import asyncio
import sys

# --- НАСТРОЙКИ ---
CONCURRENT_LIMIT = 20
TEST_PROMPT = "ответь одним словом, помидор красный или фиолетовый?"
OUTPUT_FILE = "good_chat_providers.txt"
# Таймаут на сам запрос внутри g4f
REQUEST_TIMEOUT = 30
# Общий, более строгий таймаут на всю задачу проверки одного провайдера
WORKER_TIMEOUT = 35 
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
        cleaned_response = response.strip().replace('\n', ' ').replace('\r', '') if response else None
        if cleaned_response:
            return provider_name, cleaned_response
        return provider_name, None
    except Exception as e:
        # Теперь мы можем видеть ошибку, если она произойдет внутри
        # print(f"[!] Ошибка у {provider_name}: {e}")
        return provider_name, None

async def worker(provider, semaphore, file_handle, counters):
    provider_name = provider.__name__
    async with semaphore:
        try:
            # Оборачиваем всю задачу в `wait_for` с общим таймаутом
            async with asyncio.timeout(WORKER_TIMEOUT):
                # ОТЛАДКА: Сообщаем, кого начали проверять
                # print(f"[*] Начинаю проверку: {provider_name}") 
                
                _, response = await test_provider(provider)

                counters['completed'] += 1
                
                total = counters['total']
                completed = counters['completed']
                successful = counters['successful']
                
                # Обновляем строку состояния
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

        except asyncio.TimeoutError:
            # Ловим ошибку общего таймаута
            counters['completed'] += 1
            print(f"{' ' * 80}\r", end="")
            print(f"[!] Таймаут: {provider_name} не ответил за {WORKER_TIMEOUT} сек.")
        except Exception:
            # Ловим любые другие непредвиденные ошибки на уровне worker
            counters['completed'] += 1
            print(f"{' ' * 80}\r", end="")
            print(f"[!] Критическая ошибка при работе с {provider_name}.")


async def main():
    all_known_providers = list(g4f.Provider.__map__.values())
    
    chat_providers = [
        p for p in all_known_providers if not getattr(p, 'supports_image_generation', False)
    ]

    total_providers = len(chat_providers)
    
    print(f"Найдено {len(all_known_providers)} провайдеров, из них {total_providers} являются текстовыми чатами.")
    print(f"Начинаю проверку (общий таймаут на провайдер: {WORKER_TIMEOUT} сек)...")
    
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
    elif sys.platform.startswith("linux"): # Для asyncio.timeout на Linux
        import uvloop
        uvloop.install()
    
    asyncio.run(main())
