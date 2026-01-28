from pathlib import Path
from dotenv import load_dotenv

# Load .env from the same directory as this __main__.py file BEFORE importing local modules
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

from .main import main

if __name__ == "__main__":
    main()
