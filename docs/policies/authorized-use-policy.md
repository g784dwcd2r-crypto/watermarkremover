# Authorized-use policy

**Version 2026-01-15**

This product exists for work you are entitled to do. This is the plain statement
of where that line sits, and how the software enforces it. The same text is
served to users at `/authorized-use-policy`.

## What you confirm before anything is processed

Every project requires one confirmation before an upload can be completed or a
job can be queued:

> **I own this image or have permission to edit it.**

That confirmation is stored as a dated record against the account and the
project, with the version of this policy in force at the time. It is not a
decorative checkbox: the API refuses to complete an upload or start a job
without it.

## What the cleanup tool is for

- Removing a burned-in date stamp from a photograph you took.
- Removing an obsolete overlay, badge or caption from an asset you made.
- Cleaning a client image you have been engaged and authorized to retouch.
- Removing your own draft marks from your own artwork.

## What it refuses to do

The following are detected in the processing pipeline. When a selection overlaps
one of them, the run stops and explains why. There is no setting, plan or support
request that changes this.

- **Artist signatures.** Detected by the continuity of handwritten strokes rather
  than by darkness, so it works on painted and photographic surfaces.
- **Copyright notices, credit lines and agency marks.**
- **Stock-provider and licensing watermarks,** including tiled diagonal overlays.
- **Content Credentials, C2PA manifests and other provenance labels.**
- **Invisible watermarks and forensic ownership markers.** No attempt is made to
  detect, weaken or strip these, and metadata is preserved rather than removed.

This product is not advertised or built as a way to bypass copyright, defeat
provenance systems, evade AI-detection tooling, or conceal authorship. Those are
not features that were left out; they are outcomes the design actively prevents.

## Ambiguous regions, and why you are asked

Some shapes are genuinely ambiguous. A date stamp in a bottom corner has the same
geometry as a credit line, and a diagonally patterned artwork has some of the same
signal as a tiled watermark. Guessing in either direction would be wrong: refusing
would break legitimate work, and proceeding would risk erasing attribution.

So the app pauses and asks you to state explicitly that the region is not
attribution content. That statement is recorded. High-confidence detections — a
clear signature, a clear tiled licensing watermark — are refused outright and
cannot be acknowledged away.

## Reconstructed timelapses

The timelapse tool builds a **plausible reconstruction** of how a finished
artwork might have been made. It does not recover the real process, and it never
presents itself as doing so.

- Every exported video, GIF, poster frame and frame archive carries the
  reconstruction disclosure in its file metadata. This is written on every render
  and cannot be disabled.
- A visible end card reading _"Timelapse reconstructed from finished artwork."_
  is enabled by default. You may switch the visible card off; the metadata stays.
- If you enable the optional brush cursor, the exported project file records that
  the cursor motion is simulated and is not a recording of real input.
- If you upload your own sketches or progress files, they are used as genuine
  keyframes in the order you provide, and are never replaced by generated
  stand-ins.

Presenting a reconstruction as an original creation recording — to a client, a
platform, a competition or an audience — is a misuse of this tool.

## If a detection is wrong

These detectors are heuristics. They will sometimes flag a mark that is genuinely
yours to remove, and they will sometimes miss a low-contrast signature. Where the
shape is ambiguous you can attest and continue. Where it is a high-confidence
refusal, contact support with the details — the answer may be that the detector
needs improving, and that is a change to the software rather than an exception
granted to an account.

See also the [privacy policy](privacy-policy.md) and the [terms](terms.md).
