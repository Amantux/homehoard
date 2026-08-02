"""Development entrypoint: ``python run.py``."""
from app import create_app
from app.settings import load_settings

app = create_app()

if __name__ == "__main__":
    # Same registry the app resolved from, so `python run.py` and gunicorn
    # cannot disagree about the port.
    settings = load_settings()
    app.run(host="0.0.0.0", port=settings.PORT, debug=settings.DEBUG)
