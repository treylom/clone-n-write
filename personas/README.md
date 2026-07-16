# Persona registry data

This directory is the default data root for clone-n-write v2. Real exemplar
corpora and generated packs are local artifacts and are ignored by Git. Only
this schema note and the directory `.gitignore` are tracked.

Each persona has the following local layout:

```text
personas/<name>/
├── exemplars.jsonl
└── packs/
    ├── structure-threads.json
    └── structure-longform.json
```

Every line of `exemplars.jsonl` is one UTF-8 JSON object:

```json
{
  "schema_version": "registry-v1",
  "proof_class": "source-exemplar",
  "id": "stable opaque SHA-1 identifier",
  "ref": "source reference",
  "medium": "threads|longform",
  "genre": null,
  "grade": {"src": "auto", "score": 0.5},
  "substance": {"level": "ok|low", "reasons": []},
  "body": "cleaned source text",
  "chars": 123,
  "date": "source date or an empty string",
  "topic_keys": ["up to eight approximate noun-like tokens"],
  "skeleton": null,
  "split": "train|dev|final"
}
```

Splits are assigned deterministically (SHA1-based, topic-clustered so related
pieces stay on one side of an evaluation boundary). `pull` returns `train` rows
only by default; `dev` is for diagnostics, `final` is sealed for claims and no
row from it is returned without the explicit unseal opt-in. Low-substance rows
are likewise excluded unless their opt-in flag is provided.
Structure packs use schema `struct-v1` and proof class `corpus-measured`.

No real persona text belongs in this tracked README.
