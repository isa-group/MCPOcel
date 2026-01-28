from pathlib import Path
from dotenv import load_dotenv
from .cli import main

if __name__ == "__main__":
    # Load .env from the same directory as this __main__.py file
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)
    main()
