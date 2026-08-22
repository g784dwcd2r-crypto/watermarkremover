import type { Metadata } from "next";
import Link from "next/link";

import { PolicyPage, PolicySection } from "@/components/layout/policy-page";

export const metadata: Metadata = {
  title: "Privacy policy",
  description:
    "What ArtRestore Studio stores, for how long, and what it never does with your images.",
};

export default function PrivacyPage() {
  return (
    <PolicyPage
      title="Privacy policy"
      version="2026-01-15"
      updated="15 January 2026"
      summary="A template privacy policy for a deployment of ArtRestore Studio. It describes what the software actually does; an operator running it must review it against their own jurisdiction and practices before publishing it."
    >
      <PolicySection heading="Your images are yours">
        <ul className="flex flex-col gap-1.5">
          <li>
            Uploads are private to your account by default. There is no public sharing feature.
          </li>
          <li>
            <strong>Your images are never used to train models.</strong> The inpainting and
            segmentation models this deployment uses are deployed by the operator; nothing you
            upload is added to a training set.
          </li>
          <li>Images are not sent to third-party services for processing.</li>
        </ul>
      </PolicySection>

      <PolicySection heading="Retention and deletion">
        <ul className="flex flex-col gap-1.5">
          <li>
            You choose automatic deletion after <strong>1, 7 or 30 days</strong>. The default is 7.
          </li>
          <li>
            Changing the setting re-dates work you have already uploaded, so shortening it takes
            effect on existing projects rather than only on new ones.
          </li>
          <li>Deleting a project removes its stored objects immediately, not on a later sweep.</li>
          <li>
            Deleting your account erases every project, file, export and consent record it holds.
          </li>
        </ul>
      </PolicySection>

      <PolicySection heading="How files are accessed">
        <ul className="flex flex-col gap-1.5">
          <li>Uploads and downloads use short-lived signed URLs, minted on demand.</li>
          <li>
            Transport is encrypted, and object storage is configured for server-side encryption.
          </li>
          <li>
            Signed URLs are never written to application logs. Storage keys appear in logs only as a
            truncated prefix, never in a form that could be reconstructed into a link.
          </li>
        </ul>
      </PolicySection>

      <PolicySection heading="What is logged">
        <p>
          Structured request logs record the method, path, status code and duration, plus a request
          identifier. They deliberately exclude:
        </p>
        <ul className="flex flex-col gap-1.5">
          <li>Image content, in any form.</li>
          <li>Mask data and editor state.</li>
          <li>Signed URLs and their signatures.</li>
          <li>Email addresses, which are redacted by the log formatter.</li>
          <li>Query strings, which can carry storage signatures.</li>
        </ul>
      </PolicySection>

      <PolicySection heading="What is stored about you">
        <ul className="flex flex-col gap-1.5">
          <li>Your email address, display name and a hashed password (Argon2id).</li>
          <li>
            Session records, storing only a hash of the session token — a database dump cannot be
            replayed as a login. No IP address or user-agent string is retained with a session.
          </li>
          <li>
            Consent records: what you confirmed, when, and under which policy version. These exist
            so the authorization trail is real rather than assumed.
          </li>
          <li>
            Project, asset, mask, job and export records. Asset rows store descriptions —
            dimensions, colour mode, whether provenance metadata is present — never image bytes.
          </li>
        </ul>
      </PolicySection>

      <PolicySection heading="Metadata and provenance">
        <p>
          EXIF, ICC colour profiles, XMP, IPTC and C2PA blocks are preserved and carried into every
          export. There is no strip-metadata mode. This is a deliberate design decision: stripping
          provenance is precisely the abuse this product refuses to assist with.
        </p>
      </PolicySection>

      <PolicySection heading="Your controls">
        <ul className="flex flex-col gap-1.5">
          <li>Export everything your account holds as JSON, at any time.</li>
          <li>Delete any project immediately.</li>
          <li>Delete your account, which erases all of it.</li>
          <li>Sign out of every session at once.</li>
        </ul>
        <p>
          Related: the <Link href="/authorized-use-policy">authorized-use policy</Link> and the{" "}
          <Link href="/terms">terms</Link>.
        </p>
      </PolicySection>

      <PolicySection heading="Operator note">
        <p>
          This is a template. A real deployment must add its legal entity, contact address, data
          protection contact, lawful bases for processing where applicable, sub-processor list, and
          any jurisdiction-specific rights and complaint routes before publishing it.
        </p>
      </PolicySection>
    </PolicyPage>
  );
}
