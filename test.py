import g4f
import asyncio
import sys
from g4f.client import AsyncClient

# --- НАСТРОЙКИ ---
CONCURRENT_LIMIT = 15       # Количество потоков
TEST_PROMPT = "Answer with one word: is a tomato red or purple?"
OUTPUT_FILE = "good_chat_providers.txt"
REQUEST_TIMEOUT = 25        # Таймаут чуть побольше для медленных
# --- КОНЕЦ НАСТРОЕК ---

# Настройка кодировки
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Инициализируем клиент
client = AsyncClient()

async def test_provider(provider_cls, model_to_use: str):
    provider_name = provider_cls.__name__
    try:
        # Пытаемся отправить запрос
        response = await client.chat.completions.create(
            model=model_to_use,
            messages=[{"role": "user", "content": TEST_PROMPT}],
            provider=provider_cls,
        )
        
        if response and response.choices:
            content = response.choices[0].message.content
            if content:
                # Очистка от лишних пробелов
                return provider_name, content.strip()
        return provider_name, None

    except Exception:
        # Любая ошибка (сеть, не тот тип провайдера, бан) = провал
        return provider_name, None

async def worker(provider, semaphore, file_handle, counters):
    async with semaphore:
        # --- ЛОГИКА ВЫБОРА МОДЕЛИ ---
        # Мы пытаемся угадать модель. Если у провайдера есть список - берем первую.
        # Если нет - пробуем самые популярные стандарты, которые поддерживают почти все.
        model_list = getattr(provider, "models", [])
        
        if model_list and isinstance(model_list, list) and len(model_list) > 0:
            model_to_use = model_list[0]
        else:
            model_to_use = "gpt-3.5-turbo" # Самый универсальный вариант

        # --- ТЕСТ ---
        provider_name = provider.__name__
        response = None
        
        try:
            # Жесткий таймаут снаружи, чтобы не зависать на "мертвых" провайдерах
            provider_name, response = await asyncio.wait_for(
                test_provider(provider, model_to_use), 
                timeout=REQUEST_TIMEOUT
            )
        except Exception:
            # Игнорируем ошибки таймаута и прочие
            pass

        counters['completed'] += 1

        # --- ПРОВЕРКА РЕЗУЛЬТАТА ---
        if response:
            # Простейшая проверка: ответ должен быть коротким (так как мы просили одно слово)
            # и не содержать явного HTML мусора
            if len(response) < 300 and "<!DOCTYPE" not in response:
                counters['successful'] += 1
                
                # Запись в файл
                result_str = (
                    f"Provider: {provider_name}\n"
                    f"Model: {model_to_use}\n"
                    f"Response: {response}\n"
                    f"{'-'*30}\n"
                )
                file_handle.write(result_str)
                file_handle.flush()
                
                # Вывод в консоль (зеленым цветом, если поддерживает терминал, или просто текстом)
                print(f"{' ' * 100}\r", end="")
                print(f"[+] НАЙДЕН: {provider_name:<25} | Ответ: {response[:40]}")

        # Обновление прогресса
        print(f"Обработано: {counters['completed']}/{counters['total']} | Найдено рабочих: {counters['successful']}", end='\r', flush=True)

async def main():
    # 1. Получаем ВСЕХ провайдеров без разбора
    if hasattr(g4f.Provider, '__providers__'):
         all_raw_providers = g4f.Provider.__providers__
    else:
         all_raw_providers = list(g4f.Provider.__map__.values())

    providers_to_test = []
    
    # Исключаем только технические базовые классы, которые нельзя запустить
    technical_classes = ["BaseProvider", "AsyncProvider", "AsyncGeneratorProvider", "ProviderUtils"]

    for p in all_raw_providers:
        if p and p.__name__ not in technical_classes:
            providers_to_test.append(p)

    # Удаляем дубликаты
    providers_to_test = list(set(providers_to_test))
    total = len(providers_to_test)

    print(f"Всего загружено провайдеров из g4f: {total}")
    print("Запускаю режим полной проверки (без фильтров).")
    print("В консоли могут появляться ошибки от нетекстовых провайдеров - это нормально.")
    print("-" * 50)

    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    counters = {'completed': 0, 'successful': 0, 'total': total}

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- FULL SCAN RESULT ---\n\n")
        tasks = [worker(p, semaphore, f, counters) for p in providers_to_test]
        await asyncio.gather(*tasks)

    print("\n\n" + "="*50)
    print(f"Готово. Рабочих провайдеров: {counters['successful']}")
    print(f"Результат сохранен в: {OUTPUT_FILE}")
    print("="*50)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
