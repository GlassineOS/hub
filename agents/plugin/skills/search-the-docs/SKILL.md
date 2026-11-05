---
name: search-the-docs
description: Use before making a claim about how GlassineOS works, or when a change touches a design decision. Explains how to get good results from the docs search.
---

The `docs_search` tool searches the GlassineOS documentation by keywords and by meaning.

- Ask in plain words what you want to know, not just a keyword: "how do updates roll back
  if a deployment doesn't boot".
- Search twice with different words before you conclude something isn't documented.
- Results link to the page and heading. Cite the link when a finding rests on the docs.
- `docs_index_status` says whether the index is behind the docs repository. If it is, a very
  recent change may be missing: say so rather than assume.
- The docs say how things are meant to work, not where the code uses them. For that, if you have `code_search`, search the repositories' text:
  a FIFO path, a config key or a function name finds its users across repositories, with the commit of each copy. Search the docs first for the why, then the code for what's there.
