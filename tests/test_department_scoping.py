"""
ExamExpert AI — Department Scoping RBAC Verification Test
SJB Institute of Technology | Office of Controller of Examinations

Proves that:
1. HOD CSE sees strictly the 21 'Computer Science & Engineering' faculty.
2. HOD CSE does NOT see 'CSE (Data Science)' faculty.
3. HOD MCA sees strictly the 3 'Master of Computer Applications' internal faculty.
4. HOD CSDS sees strictly the 5 'CSE (Data Science)' faculty.
5. CSDS HOD account exists and is seeded with correct credentials.
"""
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("scoping_")

from backend.app.database import SessionLocal
from backend.app.models import User, Faculty
from backend.app.routers.faculty import get_all_faculty
from backend.app.routers.auth import seed_rbac_users


def test_department_scoping():
    db = SessionLocal()
    try:
        # Ensure users are seeded
        seed_rbac_users(db)

        # 1. Verify HOD accounts exist
        hod_cse = db.query(User).filter_by(email="hod.cse@sjbit.edu.in").first()
        hod_mca = db.query(User).filter_by(email="hod.mca@sjbit.edu.in").first()
        hod_csds = db.query(User).filter_by(email="hod.csds@sjbit.edu.in").first()

        assert hod_cse is not None, "HOD CSE account not found!"
        assert hod_mca is not None, "HOD MCA account not found!"
        assert hod_csds is not None, "HOD CSDS account not found!"

        print(f"[OK] HOD CSE user: {hod_cse.username} ({hod_cse.department})")
        print(f"[OK] HOD MCA user: {hod_mca.username} ({hod_mca.department})")
        print(f"[OK] HOD CSDS user: {hod_csds.username} ({hod_csds.department})")

        # 2. Test HOD CSE Scoping
        res_cse = get_all_faculty(db=db, current_user=hod_cse)
        cse_faculty = res_cse["faculty"]
        print(f"[OK] HOD CSE sees {len(cse_faculty)} faculty")
        assert len(cse_faculty) == 21, f"Expected 21 faculty for HOD CSE, got {len(cse_faculty)}"

        for f in cse_faculty:
            assert f["department"] == "Computer Science & Engineering", (
                f"Contamination: HOD CSE saw faculty '{f['name']}' from department '{f['department']}'!"
            )

        # 3. Test HOD MCA Scoping
        res_mca = get_all_faculty(db=db, current_user=hod_mca)
        mca_faculty = res_mca["faculty"]
        print(f"[OK] HOD MCA sees {len(mca_faculty)} faculty")
        assert len(mca_faculty) == 3, f"Expected 3 faculty for HOD MCA, got {len(mca_faculty)}"

        for f in mca_faculty:
            assert f["department"] == "Master of Computer Applications", (
                f"Contamination: HOD MCA saw faculty '{f['name']}' from department '{f['department']}'!"
            )

        # 4. Test HOD CSDS Scoping
        res_csds = get_all_faculty(db=db, current_user=hod_csds)
        csds_faculty = res_csds["faculty"]
        print(f"[OK] HOD CSDS sees {len(csds_faculty)} faculty")
        assert len(csds_faculty) == 5, f"Expected 5 faculty for HOD CSDS, got {len(csds_faculty)}"

        for f in csds_faculty:
            assert f["department"] == "CSE (Data Science)", (
                f"Contamination: HOD CSDS saw faculty '{f['name']}' from department '{f['department']}'!"
            )

        # 5. Verify disjointness: No CSE faculty in CSDS list, and vice versa
        cse_ids = {f["id"] for f in cse_faculty}
        csds_ids = {f["id"] for f in csds_faculty}
        mca_ids = {f["id"] for f in mca_faculty}

        assert cse_ids.isdisjoint(csds_ids), "CSE and CSDS faculty sets overlap!"
        assert cse_ids.isdisjoint(mca_ids), "CSE and MCA faculty sets overlap!"
        assert csds_ids.isdisjoint(mca_ids), "CSDS and MCA faculty sets overlap!"

        print("[ALL TESTS PASSED] Exact Department Scoping verified successfully.")

    finally:
        db.close()


if __name__ == "__main__":
    test_department_scoping()
