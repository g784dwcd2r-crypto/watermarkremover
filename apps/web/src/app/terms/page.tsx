import type { Metadata } from "next";
import Link from "next/link";

import { PolicyPage, PolicySection } from "@/components/layout/policy-page";

export const metadata: Metadata = {
  title: "Terms of service",
  description: "The terms for using ArtRestore Studio.",
};

export default function TermsPage() {
  return (
    <PolicyPage
      title="Terms of service"
      version="2026-01-15"
      updated="15 January 2026"
      summary="A template set of terms for a deployment of ArtRestore Studio. An operator must review and complete it before relying on it."
    >
      <PolicySection heading="Your responsibilities">
        <ul className="flex flex-col gap-1.5">
          <li>
            You upload only images you own or have documented permission to edit, and you confirm
            this for every project.
          </li>
          <li>
            You upload only audio you hold the rights to use, if you add music to a timelapse.
          </li>
          <li>
            You do not use this service to remove attribution, defeat provenance systems, or
            misrepresent authorship. See the{" "}
            <Link href="/authorized-use-policy">authorized-use policy</Link>.
          </li>
          <li>
            You do not present a reconstructed timelapse as a recording of an original creation
            process.
          </li>
        </ul>
      </PolicySection>

      <PolicySection heading="What the service does and does not promise">
        <p>
          Image reconstruction is estimation. The software fills a selected region with plausible
          content derived from its surroundings; it does not recover what was underneath. Results on
          complex textures, large removals and fine structure vary, and some selections will not
          produce a usable result.
        </p>
        <p>
          Similarly, a reconstructed timelapse is a plausible sequence, not a record. No claim is
          made that it reflects how the artwork was actually produced.
        </p>
        <p>The service is provided as-is, without warranty of fitness for a particular purpose.</p>
      </PolicySection>

      <PolicySection heading="Accounts">
        <ul className="flex flex-col gap-1.5">
          <li>You are responsible for keeping your credentials secure.</li>
          <li>
            An operator may suspend an account that is being used to strip attribution or
            provenance.
          </li>
          <li>You may delete your account at any time; deletion is immediate and irreversible.</li>
        </ul>
      </PolicySection>

      <PolicySection heading="Content and ownership">
        <p>
          You retain all rights in what you upload and in what you export. The operator claims no
          licence over your images beyond what is required to store and process them at your
          request, and does not use them to train models.
        </p>
      </PolicySection>

      <PolicySection heading="Operator note">
        <p>
          This is a template. A real deployment must add its governing law, limitation of liability,
          payment and refund terms if any, acceptable-use enforcement process, notice periods for
          changes, and contact details.
        </p>
      </PolicySection>
    </PolicyPage>
  );
}
