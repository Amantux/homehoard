"""Development entrypoint: ``python run.py``."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("HBOX_PORT", "7745"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("HBOX_DEBUG") == "1")
