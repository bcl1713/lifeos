# Canonical source navigation

LifeOS presents Projects and Areas as authenticated working views over the
canonical wiki. Each record includes its canonical root-relative Markdown path
and an **Open canonical note** action. The path and action identify the durable
source; they do not create a separate LifeOS copy of the record.

## Using the canonical source view

When no SilverBullet canonical-link base is configured, **Open canonical note**
opens LifeOS's authenticated source route:

```
/sources/wiki/<canonical-root-relative-path>.md
```

The route displays the current canonical file as escaped raw Markdown after
authentication. It is a read-only inspection surface, not an editor, a
Markdown renderer, or another wiki product area. Frontmatter and Markdown link
syntax are displayed as source text. The Projects and Areas workflow views
remain the LifeOS entry points; there is no separate top-level Wiki or Context
surface.

The source route validates the requested canonical source path against the wiki
root before reading it. It does not parse or navigate wikilinks or relative
Markdown links in the displayed text, diagnose targets referenced by that text,
or alter external-link attributes.

The source route itself is authenticated. A direct request without a session is
rejected. An unavailable canonical source cannot be viewed; the Project or Area
view shows its diagnostic instead of an **Open canonical note** link.

## Canonical source guarantees

`/wiki` (the deployed mount of `/home/brian/wiki`) remains the durable authority
for LifeOS domain records. SQLite is a rebuildable projection, query index, and
audit cache, never a second writable source of truth. The source path shown in
the Project or Area view is the canonical location used to resolve the action.

The source view reads that source at request time. It does not promote displayed
source text, an API response, or a SQLite row into canonical content. Existing
source-first writes and optimistic `expected_hash` conflict handling remain the
write contract; an external wiki edit must not be silently overwritten.

## SilverBullet relationship and operator configuration

LifeOS does not replace SilverBullet and does not require SilverBullet to make
canonical source navigation available. The internal authenticated source view
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

This setting deliberately affects only the canonical-note action. It does not
change the authenticated internal source view. Remove or leave the variable
unset to restore internal canonical-note actions.

## Operator checks

Before enabling an external base URL, verify that it serves the same canonical
wiki content and that a path containing spaces resolves with percent encoding.
After a deployment, sign in to LifeOS, open a Project and an Area, confirm the
displayed canonical path, and follow the canonical-note action. With no
external base configured, confirm that the authenticated source view shows the
current canonical source text. Continue to run projection reconciliation
separately; a reachable canonical-note action is not proof that the projection
is aligned with source.