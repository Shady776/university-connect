import sys
import os

# Create an empty __init__.py if not exists, just in case
if not os.path.exists('app/__init__.py'):
    with open('app/__init__.py', 'w') as f:
        pass

try:
    print("Attempting to import app...")
    import app
    print(f"App imported: {app}")
    
    print("Attempting to import app.schemas...")
    import app.schemas
    print(f"Schemas imported: {app.schemas}")
    
    print("Dir(app.schemas):")
    print(dir(app.schemas))
    
    from app.schemas import UserCreate
    print("UserCreate imported successfully")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
