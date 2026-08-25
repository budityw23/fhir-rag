# Diabetics Validation Questions

Clinical Q&A validation dataset for the FHIR RAG system.
50 questions covering Type 1 and Type 2 Diabetes across 10 categories.

> Source for `eval/questions.json` (Phase 5). Each question maps to expected
> FHIR resource types, clinical codes, and answer keywords for automated scoring.

---

## Categories

| Category | Count | Focus |
|----------|-------|-------|
| `diagnosis` | 6 | Diabetes type, onset, status |
| `hba1c_monitoring` | 6 | HbA1c values, trends, glycemic control |
| `medications` | 7 | Metformin, insulin, dosage, adherence |
| `complications` | 5 | Retinopathy, neuropathy, nephropathy, cardiovascular |
| `vitals_labs` | 5 | Glucose, BMI, blood pressure, lipid panel |
| `care_plan` | 4 | Management plans, goals, self-management |
| `cross_resource` | 6 | Multi-resource reasoning, correlations |
| `temporal` | 5 | Time-based trends, progression, timelines |
| `preventive` | 3 | Screenings, foot exams, eye exams |
| `negative` | 3 | Questions the system should NOT be able to answer |

---

## Question Format

Each entry follows this schema (maps directly to `eval/questions.json`):

```json
{
  "id": "DM-001",
  "question": "...",
  "patient_ref": "Patient/{id}",
  "category": "diagnosis",
  "expected_resource_types": ["Condition"],
  "expected_codes": [{"system": "SNOMED", "code": "44054006", "display": "Diabetes mellitus type 2"}],
  "expected_answer_contains": ["type 2", "diabetes"],
  "diabetes_type": "type2"
}
```

---

## Diagnosis (6 questions)

### DM-001
- **Question:** "What type of diabetes does this patient have?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `44054006` (Type 2 DM) or SNOMED `46635009` (Type 1 DM)
- **Expected Answer Contains:** ["diabetes", "type 1" or "type 2"]
- **Diabetes Type:** both

### DM-002
- **Question:** "When was this patient first diagnosed with diabetes?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `44054006` or `46635009`
- **Expected Answer Contains:** ["diagnosed", "onset", date value]
- **Diabetes Type:** both

### DM-003
- **Question:** "What is the current clinical status of this patient's diabetes?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `44054006` or `46635009`
- **Expected Answer Contains:** ["active" or "resolved" or "inactive"]
- **Diabetes Type:** both

### DM-004
- **Question:** "Does this patient have any prediabetes or impaired glucose tolerance history?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `15777000` (Prediabetes)
- **Expected Answer Contains:** ["prediabetes" or "impaired glucose tolerance" or "insufficient data"]
- **Diabetes Type:** type2

### DM-005
- **Question:** "What conditions does this patient have related to metabolic syndrome?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `44054006`, `38341003` (Hypertension), `55822004` (Hyperlipidemia)
- **Expected Answer Contains:** ["diabetes", "hypertension" or "blood pressure", "cholesterol" or "lipid"]
- **Diabetes Type:** type2

### DM-006
- **Question:** "Is this patient's diabetes classified as insulin-dependent?"
- **Category:** `diagnosis`
- **Expected Resource Types:** `Condition`, `MedicationRequest`
- **Expected Codes:** SNOMED `46635009` (Type 1 DM), RxNorm insulin codes
- **Expected Answer Contains:** ["type 1" or "insulin-dependent" or "insulin"]
- **Diabetes Type:** type1

---

## HbA1c Monitoring (6 questions)

### DM-007
- **Question:** "What is this patient's most recent HbA1c result?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4` (Hemoglobin A1c)
- **Expected Answer Contains:** ["HbA1c" or "A1c", percentage value]
- **Diabetes Type:** both

### DM-008
- **Question:** "Is this patient's diabetes well-controlled based on their HbA1c?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** ["HbA1c" or "A1c", "controlled" or "uncontrolled", percentage value]
- **Diabetes Type:** both

### DM-009
- **Question:** "How many HbA1c tests has this patient had in the past two years?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** [numeric count, "HbA1c"]
- **Diabetes Type:** both

### DM-010
- **Question:** "What was this patient's highest recorded HbA1c value?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** ["highest" or "maximum", "HbA1c", percentage value]
- **Diabetes Type:** both

### DM-011
- **Question:** "Has this patient's HbA1c been above 9% at any point?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** ["HbA1c", "9%" or "above" or "below"]
- **Diabetes Type:** both

### DM-012
- **Question:** "When was this patient's last HbA1c test performed?"
- **Category:** `hba1c_monitoring`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** ["HbA1c", date value]
- **Diabetes Type:** both

---

## Medications (7 questions)

### DM-013
- **Question:** "What diabetes medications is this patient currently taking?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm `860975` (Metformin) or insulin RxNorm codes
- **Expected Answer Contains:** ["Metformin" or "insulin" or "medication", "active"]
- **Diabetes Type:** both

### DM-014
- **Question:** "What is the current dosage of Metformin prescribed to this patient?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm `860975` (Metformin 500mg) or `861004` (Metformin 1000mg)
- **Expected Answer Contains:** ["Metformin", "mg", dosage value]
- **Diabetes Type:** type2

### DM-015
- **Question:** "Has this patient's diabetes medication been changed in the past year?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm diabetes medication codes
- **Expected Answer Contains:** ["medication", "changed" or "started" or "stopped" or "no changes"]
- **Diabetes Type:** both

### DM-016
- **Question:** "Is this patient on insulin therapy? If so, what type?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm `311040` (Insulin Glargine) or `311041` (Insulin Lispro) or other insulin codes
- **Expected Answer Contains:** ["insulin" or "not on insulin", type if applicable]
- **Diabetes Type:** both

### DM-017
- **Question:** "What non-insulin diabetes medications has this patient been prescribed?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm `860975` (Metformin), `897122` (Glipizide), `1598392` (Canagliflozin)
- **Expected Answer Contains:** ["Metformin" or other oral diabetes medications]
- **Diabetes Type:** type2

### DM-018
- **Question:** "List all active prescriptions for this patient related to diabetes management."
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm diabetes-related codes (antidiabetics, statins, ACE inhibitors)
- **Expected Answer Contains:** [medication names, "active"]
- **Diabetes Type:** both

### DM-019
- **Question:** "When was this patient first started on diabetes medication?"
- **Category:** `medications`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm diabetes medication codes
- **Expected Answer Contains:** [date value, medication name]
- **Diabetes Type:** both

---

## Complications (5 questions)

### DM-020
- **Question:** "Does this patient have any documented diabetic complications?"
- **Category:** `complications`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `422034002` (Diabetic retinopathy), `230572002` (Diabetic neuropathy), `127013003` (Diabetic nephropathy)
- **Expected Answer Contains:** ["retinopathy" or "neuropathy" or "nephropathy" or "no complications"]
- **Diabetes Type:** both

### DM-021
- **Question:** "Has this patient been diagnosed with diabetic retinopathy?"
- **Category:** `complications`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `422034002` (Diabetic retinopathy)
- **Expected Answer Contains:** ["retinopathy", "diagnosed" or "no" or "insufficient data"]
- **Diabetes Type:** both

### DM-022
- **Question:** "Does this patient show signs of diabetic kidney disease?"
- **Category:** `complications`
- **Expected Resource Types:** `Condition`, `Observation`
- **Expected Codes:** SNOMED `127013003` (Diabetic nephropathy), LOINC `14959-1` (Microalbumin/creatinine ratio)
- **Expected Answer Contains:** ["nephropathy" or "kidney" or "microalbumin" or "no evidence"]
- **Diabetes Type:** both

### DM-023
- **Question:** "Has this patient had any episodes of diabetic ketoacidosis?"
- **Category:** `complications`
- **Expected Resource Types:** `Condition`, `Encounter`
- **Expected Codes:** SNOMED `420422005` (Diabetic ketoacidosis)
- **Expected Answer Contains:** ["ketoacidosis" or "DKA" or "no episodes"]
- **Diabetes Type:** type1

### DM-024
- **Question:** "What cardiovascular conditions does this patient have in the context of their diabetes?"
- **Category:** `complications`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `53741008` (Coronary heart disease), `38341003` (Hypertension)
- **Expected Answer Contains:** ["cardiovascular" or "heart" or "hypertension" or "coronary"]
- **Diabetes Type:** both

---

## Vitals and Labs (5 questions)

### DM-025
- **Question:** "What are this patient's most recent fasting blood glucose levels?"
- **Category:** `vitals_labs`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `1558-6` (Fasting glucose)
- **Expected Answer Contains:** ["glucose", "mg/dL" or value, date]
- **Diabetes Type:** both

### DM-026
- **Question:** "What is this patient's current BMI?"
- **Category:** `vitals_labs`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `39156-5` (BMI)
- **Expected Answer Contains:** ["BMI", numeric value]
- **Diabetes Type:** both

### DM-027
- **Question:** "What are this patient's recent lipid panel results?"
- **Category:** `vitals_labs`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `2093-3` (Total cholesterol), `2085-9` (HDL), `2089-1` (LDL), `2571-8` (Triglycerides)
- **Expected Answer Contains:** ["cholesterol" or "LDL" or "HDL" or "triglycerides"]
- **Diabetes Type:** both

### DM-028
- **Question:** "What is this patient's latest blood pressure reading?"
- **Category:** `vitals_labs`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `85354-9` (Blood pressure panel)
- **Expected Answer Contains:** ["blood pressure" or "systolic" or "diastolic", "mmHg"]
- **Diabetes Type:** both

### DM-029
- **Question:** "What is this patient's most recent serum creatinine and eGFR?"
- **Category:** `vitals_labs`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `2160-0` (Creatinine), `33914-3` (eGFR)
- **Expected Answer Contains:** ["creatinine" or "eGFR", numeric value]
- **Diabetes Type:** both

---

## Care Plan (4 questions)

### DM-030
- **Question:** "What is the current diabetes care plan for this patient?"
- **Category:** `care_plan`
- **Expected Resource Types:** `CarePlan`
- **Expected Codes:** SNOMED `698360004` (Diabetes self-management plan)
- **Expected Answer Contains:** ["care plan" or "management", "diabetes"]
- **Diabetes Type:** both

### DM-031
- **Question:** "What self-management goals have been set for this patient's diabetes?"
- **Category:** `care_plan`
- **Expected Resource Types:** `CarePlan`
- **Expected Codes:** SNOMED `698360004`
- **Expected Answer Contains:** ["goal" or "target", "diabetes" or "glucose" or "HbA1c"]
- **Diabetes Type:** both

### DM-032
- **Question:** "What activities or interventions are included in this patient's diabetes care plan?"
- **Category:** `care_plan`
- **Expected Resource Types:** `CarePlan`
- **Expected Codes:** SNOMED `698360004`, `386463000` (Prescribing), `413473000` (Counseling)
- **Expected Answer Contains:** ["activity" or "intervention", "diet" or "exercise" or "monitoring" or "medication"]
- **Diabetes Type:** both

### DM-033
- **Question:** "Is this patient enrolled in any diabetes education programs?"
- **Category:** `care_plan`
- **Expected Resource Types:** `CarePlan`, `Procedure`
- **Expected Codes:** SNOMED `6143009` (Diabetic education)
- **Expected Answer Contains:** ["education" or "program" or "insufficient data"]
- **Diabetes Type:** both

---

## Cross-Resource Reasoning (6 questions)

### DM-034
- **Question:** "How has this patient's HbA1c changed since starting Metformin?"
- **Category:** `cross_resource`
- **Expected Resource Types:** `Observation`, `MedicationRequest`
- **Expected Codes:** LOINC `4548-4`, RxNorm `860975`
- **Expected Answer Contains:** ["HbA1c", "Metformin", trend or values]
- **Diabetes Type:** type2

### DM-035
- **Question:** "What medications were prescribed during this patient's most recent diabetes-related encounter?"
- **Category:** `cross_resource`
- **Expected Resource Types:** `Encounter`, `MedicationRequest`
- **Expected Codes:** SNOMED `185347001` (Encounter), RxNorm medication codes
- **Expected Answer Contains:** [medication names, encounter date]
- **Diabetes Type:** both

### DM-036
- **Question:** "Summarize this patient's complete diabetes history including diagnosis, medications, and lab results."
- **Category:** `cross_resource`
- **Expected Resource Types:** `Condition`, `MedicationRequest`, `Observation`
- **Expected Codes:** SNOMED `44054006` or `46635009`, LOINC `4548-4`, RxNorm medication codes
- **Expected Answer Contains:** ["diabetes", "diagnosed", medication name, "HbA1c"]
- **Diabetes Type:** both

### DM-037
- **Question:** "Are this patient's current medications appropriate given their latest lab results?"
- **Category:** `cross_resource`
- **Expected Resource Types:** `MedicationRequest`, `Observation`
- **Expected Codes:** RxNorm medication codes, LOINC lab codes
- **Expected Answer Contains:** [medication names, lab values, clinical correlation]
- **Diabetes Type:** both

### DM-038
- **Question:** "What procedures has this patient undergone related to their diabetes management?"
- **Category:** `cross_resource`
- **Expected Resource Types:** `Procedure`, `Condition`
- **Expected Codes:** SNOMED procedure codes (eye exams, foot exams)
- **Expected Answer Contains:** ["procedure" or "exam", description]
- **Diabetes Type:** both

### DM-039
- **Question:** "What is the relationship between this patient's BMI trend and their diabetes control?"
- **Category:** `cross_resource`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `39156-5` (BMI), LOINC `4548-4` (HbA1c)
- **Expected Answer Contains:** ["BMI", "HbA1c" or "glucose", trend or correlation]
- **Diabetes Type:** type2

---

## Temporal (5 questions)

### DM-040
- **Question:** "Show this patient's HbA1c trend over the past two years."
- **Category:** `temporal`
- **Expected Resource Types:** `Observation`
- **Expected Codes:** LOINC `4548-4`
- **Expected Answer Contains:** ["HbA1c", multiple date-value pairs, "trend"]
- **Diabetes Type:** both

### DM-041
- **Question:** "What changes in diabetes medication have occurred over the past year?"
- **Category:** `temporal`
- **Expected Resource Types:** `MedicationRequest`
- **Expected Codes:** RxNorm diabetes medication codes
- **Expected Answer Contains:** [medication names, dates, "started" or "stopped" or "changed" or "no changes"]
- **Diabetes Type:** both

### DM-042
- **Question:** "When did this patient's diabetes complications first appear?"
- **Category:** `temporal`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED complication codes
- **Expected Answer Contains:** ["onset" or "diagnosed", complication name, date]
- **Diabetes Type:** both

### DM-043
- **Question:** "How long has this patient been living with diabetes?"
- **Category:** `temporal`
- **Expected Resource Types:** `Condition`
- **Expected Codes:** SNOMED `44054006` or `46635009`
- **Expected Answer Contains:** ["diagnosed", duration or date, "diabetes"]
- **Diabetes Type:** both

### DM-044
- **Question:** "Timeline of all diabetes-related events for this patient in the last 12 months."
- **Category:** `temporal`
- **Expected Resource Types:** `Condition`, `Observation`, `MedicationRequest`, `Encounter`, `Procedure`
- **Expected Codes:** Various diabetes-related codes
- **Expected Answer Contains:** [chronological events with dates]
- **Diabetes Type:** both

---

## Preventive Screenings (3 questions)

### DM-045
- **Question:** "When was this patient's last diabetic eye examination?"
- **Category:** `preventive`
- **Expected Resource Types:** `Procedure`
- **Expected Codes:** SNOMED `36228007` (Ophthalmic examination), `252779009` (Fundoscopy)
- **Expected Answer Contains:** ["eye exam" or "retinal" or "ophthalmic", date]
- **Diabetes Type:** both

### DM-046
- **Question:** "Has this patient had a diabetic foot examination in the past year?"
- **Category:** `preventive`
- **Expected Resource Types:** `Procedure`
- **Expected Codes:** SNOMED `401191002` (Diabetic foot examination)
- **Expected Answer Contains:** ["foot exam" or "foot examination", date or "no record"]
- **Diabetes Type:** both

### DM-047
- **Question:** "Is this patient up to date on recommended diabetic screenings?"
- **Category:** `preventive`
- **Expected Resource Types:** `Procedure`, `Observation`
- **Expected Codes:** Various screening codes (eye, foot, kidney, lipid)
- **Expected Answer Contains:** ["screening" or "exam", "up to date" or "overdue" or listing of screenings]
- **Diabetes Type:** both

---

## Negative / Boundary (3 questions)

### DM-048
- **Question:** "What insulin pump model is this patient using?"
- **Category:** `negative`
- **Expected Resource Types:** none (not in FHIR data)
- **Expected Codes:** none
- **Expected Answer Contains:** ["insufficient data" or "not available"]
- **Diabetes Type:** both
- **Notes:** FHIR MedicationRequest does not capture device model. System should acknowledge data limitation.

### DM-049
- **Question:** "What did the patient eat for breakfast before their last glucose test?"
- **Category:** `negative`
- **Expected Resource Types:** none
- **Expected Codes:** none
- **Expected Answer Contains:** ["insufficient data" or "not available"]
- **Diabetes Type:** both
- **Notes:** Dietary information is not captured in standard FHIR resources.

### DM-050
- **Question:** "What is this patient's continuous glucose monitor average for the past week?"
- **Category:** `negative`
- **Expected Resource Types:** none (CGM data typically not in Synthea bundles)
- **Expected Codes:** none
- **Expected Answer Contains:** ["insufficient data" or "not available"]
- **Diabetes Type:** both
- **Notes:** CGM data is not generated by Synthea. System should correctly identify data gap.

---

## Code Reference Table

Common FHIR codes used across questions:

| System | Code | Display |
|--------|------|---------|
| SNOMED | 44054006 | Diabetes mellitus type 2 |
| SNOMED | 46635009 | Diabetes mellitus type 1 |
| SNOMED | 15777000 | Prediabetes |
| SNOMED | 422034002 | Diabetic retinopathy |
| SNOMED | 230572002 | Diabetic neuropathy |
| SNOMED | 127013003 | Diabetic nephropathy |
| SNOMED | 420422005 | Diabetic ketoacidosis |
| SNOMED | 38341003 | Hypertension |
| SNOMED | 55822004 | Hyperlipidemia |
| SNOMED | 698360004 | Diabetes self-management plan |
| LOINC | 4548-4 | Hemoglobin A1c |
| LOINC | 1558-6 | Fasting glucose |
| LOINC | 39156-5 | Body mass index |
| LOINC | 2093-3 | Total cholesterol |
| LOINC | 2085-9 | HDL cholesterol |
| LOINC | 2089-1 | LDL cholesterol |
| LOINC | 2571-8 | Triglycerides |
| LOINC | 85354-9 | Blood pressure panel |
| LOINC | 2160-0 | Serum creatinine |
| LOINC | 33914-3 | eGFR |
| LOINC | 14959-1 | Microalbumin/creatinine ratio |
| RxNorm | 860975 | Metformin 500 MG |
| RxNorm | 861004 | Metformin 1000 MG |
| RxNorm | 311040 | Insulin Glargine |
| RxNorm | 311041 | Insulin Lispro |
| RxNorm | 897122 | Glipizide |
| RxNorm | 1598392 | Canagliflozin |
