import type { Metadata } from "next";
import Link from "next/link";

import { PolicyPage, PolicySection } from "@/components/layout/policy-page";

export const metadata: Metadata = {
  title: "Authorized-use policy",
  description:
    "What ArtRestore Studio will and will not do, and what you are confirming when you upload.",
};

export default function AuthorizedUsePolicyPage() {
  return (
    <PolicyPage
      title="Authorized-use policy"
      version="2026-01-15"
      updated="15 January 2026"
      summary="This product exists for work you are entitled to do. This page is the plain statement of where that line sits, and how the software enforces it."
    >
      <PolicySection heading="What you confirm before anything is processed">
        <p>
          Every project requires one confirmation before an upload can be completed or a job can be
          queued: <strong>&ldquo;I own this image or have permission to edit it.&rdquo;</strong>
        </p>
        <p>
          That confirmation is stored as a dated record against your account and the project, with
          the version of this policy in force at the time. It is not a decorative checkbox: the API
          refuses to complete an upload or start a job without it.
        </p>
      </PolicySection>

      <PolicySection heading="What the cleanup tool is for">
        <ul className="flex flex-col gap-1.5">
          <li>Removing a burned-in date stamp from a photograph you took.</li>
          <li>Removing an obsolete overlay, badge or caption from an asset you made.</li>
          <li>Cleaning a client image you have been engaged and authorized to retouch.</li>
          <li>Removing your own draft marks from your own artwork.</li>
        </ul>
      </PolicySection>

      <PolicySection heading="What it refuses to do">
        <p>
          The following are detected in the processing pipeline. When a selection overlaps one of
          them, the run stops and tells you why. There is no setting, plan or support request that
          changes this.
        </p>
        <ul className="flex flex-col gap-1.5">
          <li>
            <strong>Artist signatures.</strong> Detected by the continuity of handwritten strokes
            rather than by darkness, so it works on painted and photographic surfaces.
          </li>
          <li>
            <strong>Copyright notices, credit lines and agency marks.</strong>
          </li>
          <li>
            <strong>Stock-provider and licensing watermarks</strong>, including tiled diagonal
            overlays.
          </li>
          <li>
            <strong>Content Credentials, C2PA manifests and other provenance labels.</strong>
          </li>
          <li>
            <strong>Invisible watermarks and forensic ownership markers.</strong> No attempt is made
            to detect, weaken or strip these, and metadata is preserved rather than removed.
          </li>
        </ul>
        <p>
          This product is not advertised or built as a way to bypass copyright, defeat provenance
          systems, evade AI-detection tooling, or conceal authorship. Those are not features that
          were left out; they are outcomes the design actively prevents.
        </p>
      </PolicySection>

      <PolicySection heading="Ambiguous regions, and why you are asked">
        <p>
          Some shapes are genuinely ambiguous. A date stamp in a bottom corner has the same geometry
          as a credit line, and a diagonally patterned artwork has some of the same signal as a tiled
          watermark. Guessing in either direction would be wrong: refusing would break legitimate
          work, and proceeding would risk erasing attribution.
        </p>
        <p>
          So the app pauses and asks you to state explicitly that the region is not attribution
          content. That statement is recorded. High-confidence detections — a clear signature, a
          clear tiled licensing watermark — are refused outright and cannot be acknowledged away.
        </p>
      </PolicySection>

      <PolicySection heading="Reconstructed timelapses">
        <p>
          The timelapse tool builds a <strong>plausible reconstruction</strong> of how a finished
          artwork might have been made. It does not recover the real process, and it never presents
          itself as doing so.
        </p>
        <ul className="flex flex-col gap-1.5">
          <li>
            Every exported video, GIF, poster frame and frame archive carries the reconstruction
            disclosure in its file metadata. This is written on every render and cannot be disabled.
          </li>
          <li>
            A visible end card reading &ldquo;Timelapse reconstructed from finished artwork.&rdquo;
            is enabled by default. You may switch the visible card off; the metadata stays.
          </li>
          <li>
            If you enable the optional brush cursor, the exported project file records that the
            cursor motion is simulated and is not a recording of real input.
          </li>
          <li>
            If you upload your own sketches or progress files, they are used as genuine keyframes in
            the order you provide, and are never replaced by generated stand-ins.
          </li>
        </ul>
        <p>
          Presenting a reconstruction as an original creation recording — to a client, a platform, a
          competition or an audience — is a misuse of this tool.
        </p>
      </PolicySection>

      <PolicySection heading="If a detection is wrong">
        <p>
          These detectors are heuristics. They will sometimes flag a mark that is genuinely yours to
          remove, and they will sometimes miss a low-contrast signature. Where the shape is
          ambiguous you can attest and continue. Where it is a high-confidence refusal, contact
          support with the details — the answer may be that the detector needs improving, and that is
          a change to the software rather than an exception granted to an account.
        </p>
        <p>
          See also the <Link href="/privacy">privacy policy</Link> and the{" "}
          <Link href="/terms">terms</Link>.
        </p>
      </PolicySection>
    </PolicyPage>
  );
}
