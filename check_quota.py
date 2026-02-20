import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("📊 Информация о проекте:")
print(f"API ключ: {os.getenv('GEMINI_API_KEY')[:15]}...")

# Попробуем получить информацию о модели
try:
    model_info = genai.get_model('models/gemini-2.0-flash-lite')
    print(f"✅ Модель доступна: {model_info.name}")
    print(f"   Поддерживаемые методы: {model_info.supported_generation_methods}")
except Exception as e:
    print(f"❌ Ошибка: {e}")

# Простой тестовый запрос
try:
    model = genai.GenerativeModel('gemini-2.0-flash-lite')
    response = model.generate_content("Привет, это тестовый запрос")
    print("✅ Тестовый запрос выполнен успешно!")
    print(f"   Ответ: {response.text[:50]}...")
except Exception as e:
    print(f"❌ Ошибка при запросе: {e}")