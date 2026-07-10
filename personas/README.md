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
  "split": "train|heldout"
}
```

The split is a deterministic threshold over `sha1(id)`. `pull` excludes both
heldout and low-substance rows unless their separate opt-in flags are provided.
Structure packs use schema `struct-v1` and proof class `corpus-measured`.

No real persona text belongs in this tracked README.
