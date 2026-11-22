# ExamExpert AI — Start Server
import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
print("=" * 60)
print("  ExamExpert AI — SJB Institute of Technology")
print("  Office of the Controller of Examinations")
print("=" * 60)
print("\n  Starting server at: http://127.0.0.1:8000")
print("  Press Ctrl+C to stop.\n")
subprocess.run([sys.executable, "-m", "uvicorn", "backend.app.main:app",
                "--host", "127.0.0.1", "--port", "8000", "--reload"])
