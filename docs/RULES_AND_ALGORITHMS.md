# ExamExpert AI — Statutory Rules & Deterministic Matching Algorithms
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document details the statutory examination policies, statutory constraints, and the 9-level hierarchical deterministic ranking algorithm implemented by ExamExpert AI.

---

## 1. 9-Level Hierarchical Deterministic Matching Algorithm

The matching engine ranks eligible faculty candidates **without arbitrary numerical scores, random weights, or black-box algorithms**. Given a target examination course and pool of eligible candidates, candidates are ordered hierarchically by evaluating 9 deterministic criteria in strict precedence:

```
┌─────────────────────────────────────────────────────────────┐
│ Level 1: Exact Subject Experience                           │
│ (Prior handling of this specific course, sorted descending) │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 2: Specialization Keyword Match                       │
│ (Faculty specialization tag directly in course title)       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 3: Confirmed Related Curriculum Domain                │
│ (Only CONFIRMED mappings in shared curriculum domain)       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 4: Lower Combined Workload                            │
│ (Committed papers + Reserved ledger balance, ascending)     │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 5: Avoid Repeating Same Subject                       │
│ (Rotate away from setter who handled this subject last sem) │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 6: Higher Relevant Course Experience (Years)          │
│ (Documented years teaching this specific course, desc)      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 7: Higher Total Institutional Experience (Years)      │
│ (Total years of approved teaching service, descending)      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 8: Recorded Previous Paper-Setting Experience         │
│ (Historical papers set for SJBIT/VTU, strictly if recorded) │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Level 9: Final Deterministic Tie-Breaker                    │
│ (Ascending Faculty ID — ensures 100% reproducible ordering) │
└─────────────────────────────────────────────────────────────┘
```

### Explainability Guarantees
Every candidate returned by the matching engine includes an explicit `criteria_reason` string explaining the exact level at which they qualified, e.g.:
- `"Ranked #1 via Level 1 (Exact Subject Experience: Handled 'Programming in Python' 4 times; Combined Workload: 0/2 papers)"`
- `"Ranked #2 via Level 2 (Specialization Match: Specialization 'Data Science' aligns with course; Combined Workload: 1/2 papers)"`

---

## 2. Statutory Examination Policies

### 2.1 MCA 4-Semester Statutory Restriction Rule
Under Visvesvaraya Technological University (VTU) and SJBIT Autonomous regulations, the Master of Computer Applications (MCA) postgraduate program is strictly a 2-year (4-semester) degree. 
- **Enforcement:** The system strictly rejects any attempt to import, create, or allocate courses for the `MCA` department in Semesters `V`, `VI`, `VII`, or `VIII` with an explicit `400 Bad Request` statutory violation error.

### 2.2 Faculty Eligibility Criteria
To be deemed `Eligible` to set an Autonomous semester-end examination paper, a candidate must satisfy:
1. **Standard Teaching Experience:** Minimum 3.0 years of recognized collegiate teaching experience.
2. **PhD Fast-Track Exemption:** Candidates holding a verified doctoral degree (`Ph.D`, `PhD`, `Doctor of Philosophy`) qualify with a reduced minimum experience threshold of 1.0 year.
3. **External Institution Whitelist Governance:** External examiners must belong to an institution approved on the COE institutional whitelist. Unverified colleges are flagged as `Cannot Verify` or `Pending Verification`.

### 2.3 Workload Ledger & Capacity Ceiling
- **Maximum Workload:** Default limit of 2 question papers per faculty member per active academic cycle (`2025-26`).
- **Ledger States:**
  - `RESERVED`: Added when Admin generates recommendation. Prevents double-booking during review.
  - `COMMITTED`: Promoted upon HOD approval. Confirms formal allocation.
  - `RELEASED`: Deducted if allocation is rejected by HOD or cancelled by COE Admin.

---

## 3. Allocation Modes & Shortage Handling

1. **Balanced Mode (50:50 Split):**
   - For a standard requirement of 2 setters, selects 1 top-ranked internal SJBIT faculty member and 1 top-ranked external examiner.
2. **Internal Only Mode:**
   - Selects all required setters strictly from the internal faculty pool.
3. **External Only Mode:**
   - Selects all required setters strictly from the vetted external roster.
4. **Shortage Reallocation Protocol:**
   - If a mode requires external candidates but insufficient eligible external faculty exist (e.g. niche elective), the engine automatically backfills the deficit with the next highest-ranked eligible internal faculty member and documents the shortage rationale in the allocation order.
