import sys
print("Python path:")
for path in sys.path:
    print(f"  {path}")
    
print("\nTrying to import aiogram...")
try:
    import aiogram
    print(f"aiogram imported successfully from: {aiogram.__file__}")
    print(f"aiogram version: {aiogram.__version__}")
except ImportError as e:
    print(f"Import error: {e}")
    
print("\nTrying to import individual components...")
try:
    from aiogram import Bot
    print("Bot imported successfully")
except ImportError as e:
    print(f"Bot import error: {e}")
    
try:
    from aiogram import Dispatcher
    print("Dispatcher imported successfully")
except ImportError as e:
    print(f"Dispatcher import error: {e}")