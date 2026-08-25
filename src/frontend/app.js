function fhirRagApp() {
  return {
    patients: [],
    selectedPatient: "",
    question: "",
    loading: false,
    error: "",
    answer: "",
    citations: [],
    confidence: "",
    examples: [
      "What is the latest HbA1c?",
      "What diabetes medications is this patient currently taking?",
      "Does this patient have any documented diabetic complications?",
    ],

    async init() {
      await this.loadPatients();
    },

    async loadPatients() {
      try {
        const response = await fetch("/api/patients");
        if (!response.ok) {
          throw new Error("Patient records are unavailable right now.");
        }
        this.patients = await response.json();
      } catch (error) {
        this.error = error.message || "Unable to load patient records.";
      }
    },

    async submitQuestion() {
      const question = this.question.trim();
      if (!question || this.loading) return;

      this.loading = true;
      this.error = "";
      this.answer = "";
      this.citations = [];
      this.confidence = "";

      try {
        const response = await fetch("/api/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            patient_ref: this.selectedPatient || null,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "The query could not be completed.");
        }
        this.answer = payload.answer;
        this.citations = payload.citations || [];
        this.confidence = payload.confidence || "ungrounded";
      } catch (error) {
        this.error = error.message || "The query could not be completed.";
      } finally {
        this.loading = false;
      }
    },

    get confidenceLabel() {
      return {
        grounded: "Grounded",
        partially_grounded: "Partially grounded",
        ungrounded: "Ungrounded",
      }[this.confidence] || "Evidence status unknown";
    },
  };
}
