"""App Runner entry point; also usable with `python backend/start.py`."""

import os

import uvicorn


def main():
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
