from src.api.suggestions import MAX_SUGGESTIONS, build_suggestions


def _condition(name: str, code: str = "SNOMED: 1") -> str:
    return f"Condition: {name} ({code}).\nStatus: active."


def test_names_conditions_explicitly_and_strips_snomed_qualifiers():
    suggestions = build_suggestions(
        [_condition("Childhood asthma (disorder)")], ["Condition"]
    )
    assert "Childhood asthma" in suggestions[0]
    # The "(disorder)" qualifier is noise in a UI chip.
    assert "(disorder)" not in suggestions[0]


def test_excludes_repeated_administrative_conditions():
    suggestions = build_suggestions(
        [
            _condition("Medication review due (situation)"),
            _condition("Childhood asthma (disorder)"),
        ],
        ["Condition"],
    )
    joined = " ".join(suggestions)
    assert "Medication review" not in joined
    assert "Childhood asthma" in joined


def test_suggests_hba1c_only_for_a_diabetic_record():
    diabetic = build_suggestions([_condition("Diabetes mellitus type 2 (disorder)")], [])
    pediatric = build_suggestions([_condition("Childhood asthma (disorder)")], [])
    assert any("HbA1c" in item for item in diabetic)
    # The bug this endpoint exists to fix: offering HbA1c to a patient who has
    # no glucose data at all.
    assert not any("HbA1c" in item for item in pediatric)


def test_resource_driven_questions_survive_a_multi_condition_patient():
    suggestions = build_suggestions(
        [
            _condition("Childhood asthma (disorder)"),
            _condition("Atopic dermatitis (disorder)"),
            _condition("Perennial allergic rhinitis (disorder)"),
        ],
        ["AllergyIntolerance", "Immunization"],
    )
    assert any("allergies are documented" in item for item in suggestions)


def test_only_offers_resource_questions_the_patient_has_records_for():
    suggestions = build_suggestions([], ["MedicationRequest"])
    joined = " ".join(suggestions)
    assert "medications" in joined.lower()
    assert "immunization" not in joined.lower()


def test_falls_back_to_generic_questions_for_an_empty_record():
    suggestions = build_suggestions([], [])
    assert suggestions
    assert all(isinstance(item, str) and item for item in suggestions)


def test_never_exceeds_the_display_cap_and_stays_unique():
    suggestions = build_suggestions(
        [
            _condition("Diabetes mellitus type 2 (disorder)"),
            _condition("Childhood asthma (disorder)"),
            _condition("Hypertension (disorder)"),
            _condition("Obesity (disorder)"),
        ],
        ["AllergyIntolerance", "Immunization", "MedicationRequest", "Procedure"],
    )
    assert len(suggestions) <= MAX_SUGGESTIONS
    assert len(set(suggestions)) == len(suggestions)


def test_ignores_rows_that_are_not_renderable_conditions():
    suggestions = build_suggestions(["", "not a condition line"], ["Condition"])
    assert suggestions  # falls back rather than raising


def test_ranks_clinical_diagnoses_ahead_of_social_determinants():
    # Synthea lists social findings as active Conditions, often most recently.
    suggestions = build_suggestions(
        [
            _condition("Limited social contact (finding)"),
            _condition("Unemployed (finding)"),
            _condition("Diabetes mellitus type 2 (disorder)"),
        ],
        ["Condition"],
    )
    assert "Diabetes mellitus type 2" in suggestions[0]
    # Social findings are not phrased as diagnoses when a real one exists.
    assert "Unemployed" not in suggestions[0]
    assert "Limited social contact" not in suggestions[0]


def test_falls_back_to_social_findings_when_nothing_clinical_exists():
    suggestions = build_suggestions([_condition("Unemployed (finding)")], ["Condition"])
    assert "Unemployed" in suggestions[0]


def test_keeps_recency_order_within_a_rank():
    suggestions = build_suggestions(
        [
            _condition("Ischemic heart disease (disorder)"),
            _condition("Gout (disorder)"),
        ],
        ["Condition"],
    )
    assert suggestions[0].index("Ischemic heart disease") < suggestions[0].index("Gout")
