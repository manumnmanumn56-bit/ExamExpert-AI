// ExamExpert AI - Eligibility Engine, Semantic AI Matching & Conflict Auditing

/**
 * Statutory VTU / SJBIT Eligibility Verifier
 * Rule: Total teaching experience >= 10 years OR (Ph.D + teaching experience >= 5 years).
 */
function evaluateFacultyEligibility(faculty) {
  const qual = (faculty.qualification || "").toLowerCase();
  const hasPhD = qual.includes("ph.d") || qual.includes("phd");
  
  const expNum = parseFloat(faculty.experience);
  const isExpDisclosed = !isNaN(expNum) && faculty.experience !== "Not publicly disclosed";

  if (!isExpDisclosed) {
    return {
      status: "Cannot Verify",
      badgeClass: "badge-warning",
      isEligible: false,
      reason: "Experience not publicly disclosed in institutional records. Requires exam-cell physical verification."
    };
  }

  if (expNum >= 10) {
    return {
      status: "Qualified",
      badgeClass: "badge-success",
      isEligible: true,
      reason: `Meets statutory criterion: ${expNum} years total teaching experience (>= 10 yrs threshold).`
    };
  }

  if (hasPhD && expNum >= 5) {
    return {
      status: "Qualified",
      badgeClass: "badge-success",
      isEligible: true,
      reason: `Meets doctoral fast-track criterion: Holds Ph.D. with ${expNum} years teaching experience (>= 5 yrs threshold).`
    };
  }

  return {
    status: "Not Qualified",
    badgeClass: "badge-danger",
    isEligible: false,
    reason: `Below statutory threshold: ${expNum} years experience does not meet minimum 10 years (or 5 years with Ph.D).`
  };
}

/**
 * Multi-factor AI Matching Engine
 * Computes match score (0 - 100) and breakdown for a given course & faculty member.
 */
function calculateFacultyMatchScore(course, faculty) {
  // 1. Domain Expertise / Keyword Relevance (Max 40 pts)
  const expertiseText = (faculty.expertise || "").toLowerCase();
  const courseTitle = (course.title || "").toLowerCase();
  const courseCode = (course.code || "").toLowerCase();
  const keywords = course.keywords || [];

  let domainMatches = 0;
  keywords.forEach(kw => {
    if (expertiseText.includes(kw.toLowerCase())) {
      domainMatches++;
    }
  });

  // Direct title sub-string match check
  const titleWords = courseTitle.split(/\s+/).filter(w => w.length > 3);
  titleWords.forEach(w => {
    if (expertiseText.includes(w)) {
      domainMatches += 0.5;
    }
  });

  let domainScore = 0;
  if (keywords.length > 0) {
    domainScore = Math.min(40, Math.round((domainMatches / Math.max(1, keywords.length * 0.75)) * 40));
  } else {
    domainScore = 20;
  }

  // 2. Course Handling / Question Paper Setting Experience (Max 25 pts)
  let count = 0;
  if (faculty.type === "internal") {
    count = faculty.timesHandledCount || 0;
  } else {
    count = faculty.assumedTimesHandled || 0;
  }

  let handlingScore = 0;
  if (count >= 15) handlingScore = 25;
  else if (count >= 10) handlingScore = 22;
  else if (count >= 6) handlingScore = 18;
  else if (count >= 3) handlingScore = 14;
  else if (count >= 1) handlingScore = 10;
  else handlingScore = 4;

  // 3. Designation & Academic Seniority (Max 15 pts)
  const desig = (faculty.designation || "").toUpperCase();
  let seniorityScore = 8;
  if (desig.includes("HEAD") || desig.includes("HOD") || desig.includes("DIRECTOR") || desig.includes("DEAN")) {
    seniorityScore = 15;
  } else if (desig.includes("PROFESSOR") && !desig.includes("ASST") && !desig.includes("ASSOCIATE")) {
    seniorityScore = 14;
  } else if (desig.includes("ASSOCIATE")) {
    seniorityScore = 12;
  } else if (desig.includes("ASST") || desig.includes("ASSISTANT")) {
    seniorityScore = 9;
  }

  // 4. Overall Experience (Max 10 pts)
  const expNum = parseFloat(faculty.experience) || 0;
  let expScore = 0;
  if (expNum >= 20) expScore = 10;
  else if (expNum >= 15) expScore = 8;
  else if (expNum >= 10) expScore = 6;
  else if (expNum >= 5) expScore = 4;
  else expScore = 2;

  // 5. Statutory Eligibility Multiplier (Max 10 pts)
  const elig = evaluateFacultyEligibility(faculty);
  let eligScore = 0;
  if (elig.status === "Qualified") {
    eligScore = 10;
  } else if (elig.status === "Cannot Verify") {
    eligScore = 4;
  } else {
    eligScore = 0;
  }

  // Availability factor
  const isAvail = faculty.available !== false;
  if (!isAvail) {
    // Penalty for unavailable faculty
    eligScore = 0;
  }

  const totalScore = Math.min(100, domainScore + handlingScore + seniorityScore + expScore + eligScore);

  return {
    totalScore,
    breakdown: {
      domainScore,
      handlingScore,
      seniorityScore,
      expScore,
      eligScore
    },
    eligibility: elig,
    handlingCount: count,
    isAvailable: isAvail
  };
}

/**
 * Conflict Auditing Engine
 * Validates a proposed or existing allocation list against institutional rules:
 * - 50:50 Internal:External parity per paper
 * - Over-allocation (> 2 sets in the same cycle)
 * - Same external college clash
 * - Unqualified / Unavailable faculty allocation
 */
function auditAllocations(allocations, allFaculty) {
  const conflicts = [];
  const facultyAllocationCount = {};

  const facultyMap = {};
  allFaculty.forEach(f => {
    facultyMap[f.dbId] = f;
  });

  allocations.forEach((alloc, idx) => {
    const internalFaculty = facultyMap[alloc.internalSetterId];
    const externalFaculty = facultyMap[alloc.externalSetterId];
    const reserveFaculty = facultyMap[alloc.reserveSetterId];

    // Rule 1: Check 50:50 Parity
    const internalSets = alloc.internalSets || 1;
    const externalSets = alloc.externalSets || 1;
    const totalSets = internalSets + externalSets;
    if (internalSets !== externalSets) {
      conflicts.push({
        type: "RATIO_IMBALANCE",
        severity: "CRITICAL",
        courseCode: alloc.courseCode,
        courseTitle: alloc.courseTitle,
        message: `Statutory 50:50 violation for ${alloc.courseCode}: Internal sets (${internalSets}) vs External sets (${externalSets}). VTU requires exactly 50% Internal and 50% External.`
      });
    }

    // Rule 2: Ineligibility or Unavailable Internal Setter
    if (internalFaculty) {
      facultyAllocationCount[internalFaculty.dbId] = (facultyAllocationCount[internalFaculty.dbId] || 0) + 1;
      const elig = evaluateFacultyEligibility(internalFaculty);
      if (internalFaculty.available === false) {
        conflicts.push({
          type: "UNAVAILABLE_FACULTY",
          severity: "CRITICAL",
          courseCode: alloc.courseCode,
          courseTitle: alloc.courseTitle,
          facultyName: internalFaculty.name,
          message: `Internal Setter ${internalFaculty.name} is marked UNAVAILABLE / ON LEAVE.`
        });
      }
      if (elig.status === "Not Qualified") {
        conflicts.push({
          type: "INELIGIBLE_FACULTY",
          severity: "CRITICAL",
          courseCode: alloc.courseCode,
          courseTitle: alloc.courseTitle,
          facultyName: internalFaculty.name,
          message: `Internal Setter ${internalFaculty.name} does NOT meet statutory qualification criteria (${elig.reason}).`
        });
      }
    } else if (alloc.internalSetterId) {
      conflicts.push({
        type: "MISSING_SETTER",
        severity: "WARNING",
        courseCode: alloc.courseCode,
        courseTitle: alloc.courseTitle,
        message: `No Internal Setter assigned for ${alloc.courseCode}.`
      });
    }

    // Rule 3: Ineligibility or Unavailable External Setter
    if (externalFaculty) {
      facultyAllocationCount[externalFaculty.dbId] = (facultyAllocationCount[externalFaculty.dbId] || 0) + 1;
      const elig = evaluateFacultyEligibility(externalFaculty);
      if (externalFaculty.available === false) {
        conflicts.push({
          type: "UNAVAILABLE_FACULTY",
          severity: "CRITICAL",
          courseCode: alloc.courseCode,
          courseTitle: alloc.courseTitle,
          facultyName: externalFaculty.name,
          message: `External Setter ${externalFaculty.name} (${externalFaculty.college}) is marked UNAVAILABLE.`
        });
      }
      if (elig.status === "Not Qualified") {
        conflicts.push({
          type: "INELIGIBLE_FACULTY",
          severity: "CRITICAL",
          courseCode: alloc.courseCode,
          courseTitle: alloc.courseTitle,
          facultyName: externalFaculty.name,
          message: `External Setter ${externalFaculty.name} is NOT qualified (${elig.reason}).`
        });
      }
    } else if (alloc.externalSetterId) {
      conflicts.push({
        type: "MISSING_SETTER",
        severity: "WARNING",
        courseCode: alloc.courseCode,
        courseTitle: alloc.courseTitle,
        message: `No External Setter assigned for ${alloc.courseCode}.`
      });
    }

    // Rule 4: Institutional Clash Check
    // If scrutinizer or reserve is also from the same external institution as setter
    if (externalFaculty && alloc.scrutinizerId) {
      const scrutinizer = facultyMap[alloc.scrutinizerId];
      if (scrutinizer && scrutinizer.type === "external" && scrutinizer.college === externalFaculty.college) {
        conflicts.push({
          type: "INSTITUTION_CLASH",
          severity: "WARNING",
          courseCode: alloc.courseCode,
          courseTitle: alloc.courseTitle,
          message: `Both External Setter (${externalFaculty.name}) and Scrutinizer (${scrutinizer.name}) belong to the same institution: ${externalFaculty.college}. Recommended to diversify scrutiny.`
        });
      }
    }
  });

  // Rule 5: Over-Allocation Check (Max 2 papers per faculty)
  Object.keys(facultyAllocationCount).forEach(dbId => {
    const count = facultyAllocationCount[dbId];
    if (count > 2) {
      const f = facultyMap[dbId];
      conflicts.push({
        type: "OVER_ALLOCATION",
        severity: "CRITICAL",
        facultyName: f ? f.name : dbId,
        college: f ? f.college : "SJBIT",
        message: `Workload violation: ${f ? f.name : dbId} is assigned to ${count} exam papers (Permissible ceiling: 2 papers per session).`
      });
    }
  });

  return conflicts;
}
