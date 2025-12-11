import g4f
import asyncio
import sys
from g4f.client import AsyncClient

# --- НАСТРОЙКИ ---
CONCURRENT_LIMIT = 10  # Уменьшил для стабильности, 20 может вызывать баны по IP
TEST_PROMPT = "Answer with one word: is a tomato red or purple?" # Лучше на английском, больше моделей поймут
OUTPUT_FILE = "good_chat_providers.txt"
REQUEST_TIMEOUT = 20
# --- КОНЕЦ НАСТРОЕК ---

# Установка кодировки для Windows/Linux
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Инициализируем клиент один раз
client = AsyncClient()

async def test_provider(provider_cls, model_to_use: str):
    provider_name = provider_cls.__name__
    try:
        # Использование нового клиента G4F (аналог OpenAI API)
        response = await client.chat.completions.create(
            model=model_to_use,
            messages=[{"role": "user", "content": TEST_PROMPT}],
            provider=provider_cls,
            timeout=REQUEST_TIMEOUT # Таймаут может не поддерживаться клиентом напрямую, но оставим для совместимости
        )
        
        # Получаем контент ответа
        if response and response.choices:
            content = response.choices[0].message.content
            cleaned_response = content.strip().replace('\n', ' ').replace('\r', '') if content else None
            return provider_name, cleaned_response
            
        return provider_name, None
    except Exception:
        # Ошибки здесь ожидаемы для нерабочих провайдеров
        return provider_name, None

async def worker(provider, semaphore, file_handle, counters):
    async with semaphore:
        # Логика выбора модели
        model_list = getattr(provider, "models", [])
        
        # Берем первую модель или дефолтную
        if model_list and isinstance(model_list, list) and len(model_list) > 0:
            model_to_use = model_list[0]
        else:
            # Для многих провайдеров gpt-3.5 или gpt-4 являются дефолтными
            model_to_use = "gpt-3.5-turbo"

        # Тестируем
        try:
            # Обернем в wait_for для жесткого контроля таймаута (так как клиент может зависать)
            provider_name, response = await asyncio.wait_for(
                test_provider(provider, model_to_use), 
                timeout=REQUEST_TIMEOUT + 5
            )
        except asyncio.TimeoutError:
            provider_name, response = provider.__name__, None
        except Exception:
            provider_name, response = provider.__name__, None

        counters['completed'] += 1
        
        # Логика вывода и сохранения
        if response:
            counters['successful'] += 1
            # Простая проверка на адекватность (слово Red или красный)
            is_valid = len(response) < 100 # Просто чтоб не сохранять ошибки html 
            
            if is_valid:
                result_str = (
                    f"Provider: {provider_name}\n"
                    f"Model: {model_to_use}\n"
                    f"Response: {response}\n"
                    f"{'-'*30}\n"
                )
                file_handle.write(result_str)
                file_handle.flush()
                
                print(f"{' ' * 100}\r", end="")
                print(f"[+] GOOD: {provider_name:<20} | Model: {model_to_use:<15} | Ans: {response[:30]}")
        
        # Обновление статус-бара
        total = counters['total']
        current = counters['completed']
        success = counters['successful']
        print(f"Progress: {current}/{total} | Working: {success}", end='\r', flush=True)

async def main():
    # 1. Сбор провайдеров
    # В новых версиях лучше брать из __providers__ если есть, или фильтровать __map__
    if hasattr(g4f.Provider, '__providers__'):
         all_providers = g4f.Provider.__providers__
    else:
         all_providers = list(g4f.Provider.__map__.values())

    # 2. Фильтрация
    chat_providers = []
    ignored_names = [
        "GoogleSearch", "BingCreateImages", "GeminiPro", "OpenaiChat", 
        "NeedsAuth", "BaseProvider", "AsyncProvider", "AsyncGeneratorProvider"
    ]
    
    for p in all_providers:
        if not p: continue
        name = p.__name__
        
        # Пропускаем служебные классы и явно не чат-провайдеры
        if name in ignored_names:
            continue
        if getattr(p, 'working', False) is False: # Если провайдер помечен как нерабочий в g4f
            continue
        if getattr(p, 'needs_auth', False): # Пропускаем те, что требуют авторизации (cookies)
            continue
        if getattr(p, 'supports_image_generation', False): # Пропускаем генераторы картинок
            continue
            
        chat_providers.append(p)

    # Удаляем дубликаты
    chat_providers = list(set(chat_providers))
    total_providers = len(chat_providers)
    
    print(f"Providers found: {len(all_providers)}")
    print(f"Providers to test (Text Only): {total_providers}")
    print(f"Output file: {OUTPUT_FILE}\n")
    
    if not total_providers:
        print("No providers found to test.")
        return

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    counters = {'completed': 0, 'successful': 0, 'total': total_providers}
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- Scan Start ---\n\n")
        tasks = [worker(p, semaphore, f, counters) for p in chat_providers]
        await asyncio.gather(*tasks)

    print("\n\n" + "="*50)
    print(f"Done! Working providers: {counters['successful']}")
    print("="*50)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
