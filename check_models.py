import google.generativeai as genai
import os
from dotenv import load_dotenv

# Загружаем ключ из .env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print(f"🔑 Используется ключ: {api_key[:15]}...")
print("-" * 50)

# Настраиваем Gemini
genai.configure(api_key=api_key)

print("📋 МОДЕЛИ, ДОСТУПНЫЕ ДЛЯ generateContent:")
print("-" * 50)

# Получаем список всех моделей
try:
    models = genai.list_models()
    
    found = False
    for model in models:
        # Проверяем, поддерживает ли модель generateContent
        if 'generateContent' in model.supported_generation_methods:
            print(f"✅ {model.name}")
            print(f"   Описание: {model.display_name}")
            print(f"   Поддерживает: {model.supported_generation_methods}")
            print("-" * 30)
            found = True
    
    if not found:
        print("❌ Нет доступных моделей для generateContent!")
        
except Exception as e:
    print(f"❌ Ошибка при получении списка моделей: {e}")