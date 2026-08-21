# Rendered canonical source navigation

LifeOS presents Projects and Areas as authenticated working views over the
canonical wiki. Each record includes its canonical root-relative Markdown path
and an **Open canonical note** action. The path and action identify the durable
source; they do not create a separate LifeOS copy of the record.

## Using the rendered source view

When no SilverBullet canonical-link base is configured, **Open canonical note**
opens LifeOS's authenticated rendered-source route:

```
/sources/wiki/<canonical-root-relative-path>.md
```

The route renders the current canonical Markdown after authentication. It is a
read-only navigation and inspection surface, not an editor or another wiki
product area. The shared LifeOS shell remains available while reading. A source
context band identifies the root-relative path, labels it **Canonical Markdown ·
read-only**, and provides a selectable path plus a **Copy path** control when
JavaScript clipboard access is available. If copying is unavailable, the path
remains selectable for manual copying. Its breadcrumb returns to the relevant
Projects or Areas entry point when that source type is known; otherwise it
provides a safe **LifeOS** root link. The Projects and Areas workflow views
remain the LifeOS entry points; there is no separate top-level Wiki or Context
surface.

The renderer intentionally supports a small escaped Markdown subset: headings,
paragraphs, ordered and unordered lists, fenced code blocks, wikilinks, and
Markdown links. It removes leading YAML frontmatter from the rendered body.
It is not a general-purpose Markdown renderer, so authoring assumptions should
remain with the canonical wiki rather than relying on LifeOS for full
SilverBullet rendering.

### In-wiki links

Rendered source keeps supported canonical navigation inside the authenticated
LifeOS route:

- Wiki links such as `[[01-Projects/Example/Index|Example]]` resolve to the
  matching canonical Markdown note.
- Relative Markdown links such as `[Notes](Notes.md)` resolve relative to the
  rendered note.
- Resolved internal targets are emitted as `/sources/wiki/...` links, including
  a fragment when one was supplied.

Targets are validated before a link is emitted. Missing or ambiguous targets,
targets that escape the wiki root, symlink-unsafe sources, non-Markdown files,
protocol-relative URLs, and unsafe URL schemes are shown as non-clickable text
with a diagnostic rather than an unsafe or broken anchor. `http`, `https`, and
`mailto` Markdown links are treated as external links and receive protective
`rel="noopener noreferrer"` attributes.

Before rendering, the source route validates that the requested canonical path
stays within the wiki root and rejects unavailable or symlink-unsafe sources.

The source route itself is authenticated. A direct request without a session is
rejected. An unavailable canonical source cannot be rendered; the Project or Area
view shows its diagnostic instead of an **Open canonical note** link.

## Canonical source guarantees

`/wiki` (the deployed mount of `/home/brian/wiki`) remains the durable authority
for LifeOS domain records. SQLite is a rebuildable projection, query index, and
audit cache, never a second writable source of truth. The source path shown in
the Project or Area view is the canonical location used to resolve the action.

The rendered view reads that source at request time. It does not promote the
rendered HTML, an API response, or a SQLite row into canonical content. Existing
source-first writes and optimistic `expected_hash` conflict handling remain the
write contract; an external wiki edit must not be silently overwritten.

## SilverBullet relationship and operator configuration

LifeOS does not replace SilverBullet and does not require SilverBullet to make
canonical source navigation available. The internal authenticated rendered view
is the default when no external base is configured.

An operator may set `LIFEOS_SILVERBULLET_BASE_URL` to a verified SilverBullet
base URL. When it is set, the **Open canonical note** action for Projects and
Areas (and the canonical-source resolution API) uses that base followed by the
URL-encoded canonical path without its `.md` suffix. For example, the canonical
path `01-Projects/Demo Project/Index.md` becomes:

```
<LIFEOS_SILVERBULLET_BASE_URL>/01-Projects/Demo%20Project/Index
```

Trailing slashes in the configured base are normalized. Configure the value only
when the resulting URL is reachable by the intended user and points to the same
canonical wiki mount. LifeOS does not verify SilverBullet availability or
authenticate that external service on its behalf.

This setting deliberately does not change links rendered inside the LifeOS
source view: supported in-wiki wikilinks and relative Markdown links continue
to use authenticated internal `/sources/wiki/...` navigation. Remove or leave
the variable unset to restore internal canonical-note actions.

## Operator checks

Before enabling an external base URL, verify that it serves the same canonical
wiki content and that a path containing spaces resolves with percent encoding.
After a deployment, sign in to LifeOS, open a Project and an Area, confirm the
displayed canonical path, and follow the canonical-note action. For internal
navigation, also verify a valid wikilink and relative `.md` link plus a known
invalid link diagnostic. Continue to run projection reconciliation separately;
valid navigation is not proof that the projection is aligned with source.