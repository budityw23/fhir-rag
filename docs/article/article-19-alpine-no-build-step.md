---
title: "90 Lines of Alpine.js and No Build Step"
published: false
tags: alpinejs, javascript, webdev, fastapi
series: "Grounded RAG over FHIR"
---

My frontend is one HTML file, one 90-line JavaScript file, and two vendored dependencies. There is no `package.json`, no bundler, no transpiler, and no `node_modules`. Editing the interface means editing a file and refreshing the browser.

For an interface that is a dropdown, a textarea, and a result panel, that is not a compromise. It is the correct amount of machinery.

## What the interface actually does

It is worth being precise about the requirements, because the requirements are what justify the choice:

Load a list of patients into a select. Load example questions for the selected patient, and reload them when the selection changes. Submit a question, show a loading state, render an answer with citations and a grounding verdict. Show errors without breaking.

That is the whole application. There is no routing, no client-side state that outlives a request, no optimistic updates, no offline behaviour, and no component reuse, because there is exactly one screen.

## The entire component

```javascript
// src/frontend/app.js
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
    ...
  };
}
```

A function returning an object. Properties are state, methods are behaviour, and Alpine makes the whole thing reactive when the DOM references it:

```html
<!-- src/frontend/index.html -->
<body x-data="fhirRagApp()" x-init="init()">
```

Ten state properties, four methods, one computed getter. There is no framework concept to learn beyond "this object is reactive".

## Where the reactivity shows up

The template reads like the state it renders:

```html
<!-- src/frontend/index.html -->
<select id="patient" x-model="selectedPatient" :disabled="loading">
  <option value="">All patients</option>
  <template x-for="patient in patients" :key="patient.id">
    <option :value="patient.id" x-text="patient.name + ' — ' + patient.id"></option>
  </template>
</select>
```

`x-model` two-way binds the select. `x-for` iterates. `:disabled="loading"` disables it during a request. The submit button does the same, with the label switching on the same flag:

```html
<button type="submit" :aria-busy="loading" :disabled="loading || !question.trim()">
  <span x-show="!loading">Ask the record</span>
  <span x-show="loading" x-cloak>Retrieving evidence</span>
</button>
```

`:aria-busy` is a Pico CSS convention that renders a spinner and is also the correct accessibility attribute, which is a nice case of the CSS framework and the accessibility requirement agreeing.

One React-shaped thing I do not have to think about: there is no dependency array. `$watch("selectedPatient", ...)` says what it does, and it fires when that value changes. That is the entire mental model.

## The submit handler

```javascript
// src/frontend/app.js
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
}
```

Guard against double submission, clear previous results, fetch, parse, assign, always clear the loading flag. Reading it top to bottom tells you what happens.

Two small defensive choices. `payload.confidence || "ungrounded"` defaults to the *least* trusting verdict if the field is missing, because a missing grounding verdict should never render as if the answer were verified. And the answer is cleared before the request rather than after, so a stale answer is never displayed next to a new question's spinner.

## Vendoring, and one bug worth knowing

Both dependencies are files in the repo:

```
src/frontend/vendor/alpine.min.js    54 KB
src/frontend/vendor/pico.min.css     83 KB
```

137 KB total, committed. No CDN, so the app works with no external network access, cannot break because someone else's CDN had an outage, and has no third-party request in a page that displays clinical data. In healthcare that last point is not a stylistic preference.

The one bug this setup produced was about script order. Alpine evaluates `x-data` during initialisation, so if `alpine.min.js` loads before `app.js`, `fhirRagApp` does not exist yet:

```
Uncaught ReferenceError: fhirRagApp is not defined
```

`app.js` must load first. For Alpine components defined in ordinary script files, **script order is part of the component contract**, and it is the first thing to check when an `x-data` method is reported as undefined.

## Serving it

FastAPI serves the static files directly, mounted at the root after the API routes:

```python
# src/api/main.py
frontend_dir = Path(__file__).parent.parent / "frontend"
application.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
```

`html=True` serves `index.html` for directory requests. Mount order matters: the API router is included first, so `/api/query` resolves to the route rather than to a missing file.

One container, one port, no CORS configuration, no separate frontend deploy. The tradeoff is that the frontend is baked into the image, so editing it needs a rebuild and a hard refresh. That has caught me out more than once, and it is the price of not having a dev server.

## Where this stops working

I would not defend this choice past a certain point, and the boundaries are clear enough to name.

**More than about three screens.** Alpine has no routing and no component composition worth the name. Two screens sharing a header is where you start writing your own abstractions, badly.

**State that outlives a request.** Alpine's state lives in one component. Anything shared across views wants a real store.

**A design system.** Repeated, parameterised components with variants are what component frameworks are for.

**A team.** A React codebase has conventions a new developer already knows. My Alpine file has conventions I invented, and the file being short is what makes that acceptable.

The honest read: at 90 lines this is obviously right, at 900 lines it is obviously wrong, and I do not know exactly where the line is. What I do know is that starting with the build pipeline would have meant maintaining it for the entire life of the project in exchange for nothing the user can see.

## The takeaway

Match the tooling to the interface, not to what you would reach for by default. A build step is not free: it is a dependency tree, a lockfile, a version to keep current, and a layer between the code you wrote and the code that runs.

For an interface this size, the whole thing is legible in one sitting, and that turns out to be worth more than anything a framework was going to give me.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
