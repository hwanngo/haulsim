"""
Database Configuration
Embedded DuckDB database. No server: the export path reads a single .duckdb file
(built by db/generate_seed.py). Override the location with DUCKDB_PATH.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
# Load from backend/.env (parent directory of core/)
env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)
load_dotenv(env_path)

# Repo root = backend/core -> backend -> root
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DUCKDB_PATH = os.getenv("DUCKDB_PATH", os.path.join(_REPO_ROOT, "db", "haulsim.duckdb"))
DB_CONFIG = {"path": DUCKDB_PATH}

# Main table name
TABLE_NAME = "amt_cycleprodinfo_handle"

# Paths from environment variables
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "../output")
EXECUTE_FILE_PATH = os.getenv("EXECUTE_FILE_PATH", "../executables")
REFERENCE_DATA_PATH = os.getenv("REFERENCE_DATA_PATH", "../reference_data")
# Temp directory for file processing (use short path to avoid Windows MAX_PATH limit)
TEMP_DIR = os.getenv("TEMP_DIR", "")
