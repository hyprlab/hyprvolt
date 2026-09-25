"""Development entrypoint: python run.py

Production runs gunicorn against ``hyprvolt:create_app()``; see the Dockerfile.
"""
from hyprvolt import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
