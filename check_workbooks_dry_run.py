from backend.app.database import SessionLocal
from backend.app.services.importer import preview_dataset_import

db = SessionLocal()
print("--- Dry-Run Preview on Real Workbooks ---")

def check_file(filepath, dtype):
    with open(filepath, "rb") as f:
        content = f.read()
    res = preview_dataset_import(db, content, filepath, dtype)
    print(f"[{dtype.upper()}] To Add={res['to_add_count']}, Duplicates={res['duplicates_count']}, Conflicts={res['conflicts_count']}, Rejected={res['rejected_count']}")
    if res.get("conflicts"):
        for c in res["conflicts"]:
            print(f"  Conflict in {c['identifier']}: {c['differences']}")
    return res

res_int = check_file("SJBIT college data internal faculty.xlsx", "internal")
res_ext = check_file("External Faculty college data.xlsx", "external")
res_syl = check_file("SJBIT_All_Academic_Years sylabus.xlsx", "syllabus")

db.close()
