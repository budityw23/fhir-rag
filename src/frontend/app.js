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
    examples: [],

    async init() {
      await this.loadPatients();
      await this.loadSuggestions();
      // Suggestions describe the selected record, so they follow the picker.
      this.$watch("selectedPatient", () => this.loadSuggestions());
    },

    async loadSuggestions() {
      const query = this.selectedPatient
        ? `?patient_ref=${encodeURIComponent(this.selectedPatient)}`
        : "";
      try {
        const response = await fetch(`/api/suggestions${query}`);
        if (!response.ok) {
          throw new Error("Suggestions are unavailable.");
        }
        const payload = await response.json();
        this.examples = payload.suggestions || [];
      } catch {
        // Suggestions are a convenience; a failure here must not block asking.
        this.examples = [];
      }
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
