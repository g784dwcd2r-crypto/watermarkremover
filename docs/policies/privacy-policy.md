# Privacy policy (template)

**Version 2026-01-15**

> This template describes what the software actually does. An operator running a
> deployment must review it against their own jurisdiction and practices, and
> complete the operator section, before publishing it. The same text is served to
> users at `/privacy`.

## Your images are yours

- Uploads are private to your account by default. There is no public sharing
  feature.
- **Your images are never used to train models.** The inpainting and segmentation
  models a deployment uses are deployed by its operator; nothing you upload is
  added to a training set.
- Images are not sent to third-party services for processing.

## Retention and deletion

- You choose automatic deletion after **1, 7 or 30 days**. The default is 7.
- Changing the setting re-dates work you have already uploaded, so shortening it
  takes effect on existing projects rather than only on new ones.
- Deleting a project removes its stored objects immediately, not on a later
  sweep.
- Deleting your account erases every project, file, export and consent record it
  holds.

## How files are accessed

- Uploads and downloads use short-lived signed URLs, minted on demand
  (5 minutes by default).
- Transport is encrypted, and object storage is configured for server-side
  encryption.
- Signed URLs are never written to application logs. Storage keys appear in logs
  only as a truncated prefix, never in a form that could be reconstructed into a
  link.

## What is logged

Structured request logs record the method, path, status code and duration, plus a
request identifier. They deliberately exclude:

- Image content, in any form.
- Mask data and editor state.
- Signed URLs and their signatures.
- Email addresses, which are redacted by the log formatter.
- Query strings, which can carry storage signatures.

## What is stored about you

- Your email address, display name and a hashed password (Argon2id).
- Session records storing only a **hash** of the session token — a database dump
  cannot be replayed as a login. No IP address or user-agent string is retained
  with a session.
- Consent records: what you confirmed, when, and under which policy version.
  These exist so the authorization trail is real rather than assumed.
- Project, asset, mask, job and export records. Asset rows store _descriptions_ —
  dimensions, colour mode, whether provenance metadata is present — never image
  bytes.

## Metadata and provenance

EXIF, ICC colour profiles, XMP, IPTC and C2PA blocks are preserved and carried
into every export. There is no strip-metadata mode. This is a deliberate design
decision: stripping provenance is precisely the abuse this product refuses to
assist with.

## Your controls

- Export everything your account holds as JSON, at any time
  (`GET /v1/account/export`).
- Delete any project immediately.
- Delete your account, which erases all of it.
- Sign out of every session at once.

## Operator section — complete before publishing

- [ ] Legal entity name and registered address
- [ ] Contact address for privacy enquiries, and a data protection contact where
      one is required
- [ ] Lawful bases for processing, where applicable
- [ ] Sub-processor list (hosting, object storage, email, error tracking)
- [ ] International transfer mechanisms, if any
- [ ] Jurisdiction-specific rights and the complaint route
- [ ] Whether object-storage versioning is enabled, and what that means for
      "immediate deletion"
- [ ] Log retention period
