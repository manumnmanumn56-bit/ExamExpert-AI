"""
ExamExpert AI — Test Database Isolation Helper
Ensures tests NEVER write to the production examexpert.db.
Copies examexpert.db to a temporary file, binds database engine to it,
and safely removes the temporary database upon test completion.
"""
import os
import shutil
import tempfile
import atexit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(BASE_DIR, "examexpert.db")


def create_isolated_test_db(name_prefix: str = "test_run_") -> str:
    """Creates a temporary isolated copy of examexpert.db and sets TEST_DATABASE_URL."""
    temp_dir = tempfile.gettempdir()
    temp_db_path = os.path.join(temp_dir, f"{name_prefix}{os.getpid()}_{os.urandom(4).hex()}.db")
    if os.path.exists(PROD_DB):
        shutil.copy2(PROD_DB, temp_db_path)
    
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{temp_db_path}"
    
    from backend.app import database
    database.rebind_engine(f"sqlite:///{temp_db_path}")
    
    def cleanup():
        try:
            database.engine.dispose()
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)
        except Exception:
            pass

    atexit.register(cleanup)
    return temp_db_path
