from app import create_app
import database
app = create_app()
with app.app_context(): database.init_db()
print("Initialized PCCSMS database.")
