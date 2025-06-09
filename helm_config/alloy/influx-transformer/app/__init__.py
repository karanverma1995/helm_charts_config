from flask import Flask
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=3)  # Adjust max_workers as necessary

def create_app():
    app = Flask(__name__)

    # Import routes and register them
    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
