import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@artrestore/ui";
import { Brush, FileCheck2, Film, ShieldCheck, Sparkles, Timer } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/components/layout/app-shell";
import { BeforeAfter } from "@/components/marketing/before-after";

const TOOLS = [
  {
    icon: Brush,
    title: "Authorized visible watermark cleanup",
    body:
      "Remove a date stamp, an obsolete overlay or a burned-in caption from an image you own or " +
      "have permission to edit. You paint the area, review what the app found, and approve it " +
      "before anything is processed.",
    href: "/projects/new?type=cleanup",
    action: "Clean an image",
  },
  {
    icon: Film,
    title: "Artwork timelapse reconstruction",
    body:
      "Turn your finished artwork into a process video for social media. The result is a " +
      "reconstruction, labelled as one in the file metadata and, by default, on screen.",
    href: "/projects/new?type=timelapse",
    action: "Create reconstructed timelapse",
  },
];

const AUDIENCES = [
  "Digital artists reconstructing the workflow of their own artwork",
  "Photographers cleaning authorized client images",
  "Designers removing obsolete overlays from their own assets",
  "Creators making process videos from their own finished work",
];

const REFUSALS = [
  "Artist signatures",
  "Copyright and credit lines",
  "Stock-agency and licensing watermarks",
  "Content Credentials and C2PA provenance",
  "Invisible watermarks and forensic ownership markers",
];

export default function LandingPage() {
  return (
    <AppShell>
      <section className="paper-texture -mx-4 mb-14 rounded-[var(--radius-xl)] px-4 py-12 sm:-mx-6 sm:px-10 sm:py-16">
        <div className="max-w-3xl">
          <Badge tone="primary" className="mb-4">
            <Sparkles className="size-3.5" aria-hidden="true" />
            For work you are entitled to do
          </Badge>
          <h1 className="font-serif text-4xl leading-[1.1] tracking-tight text-[var(--color-ink)] sm:text-5xl">
            Clean up your own images. Reconstruct your own process.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-[var(--color-ink-muted)]">
            ArtRestore Studio does two things well: it repairs overlays on images you have the right
            to edit, and it builds honestly-labelled process videos from your finished artwork. It
            will not help you erase someone&apos;s signature, strip a licensing watermark, or pass a
            reconstruction off as a recording.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg">
              <Link href="/projects/new?type=cleanup">Clean an image</Link>
            </Button>
            <Button asChild size="lg" variant="secondary">
              <Link href="/projects/new?type=timelapse">Create reconstructed timelapse</Link>
            </Button>
          </div>
          <p className="mt-4 text-sm text-[var(--color-ink-subtle)]">
            Every project starts with one confirmation:{" "}
            <span className="font-medium text-[var(--color-ink-muted)]">
              &ldquo;I own this image or have permission to edit it.&rdquo;
            </span>
          </p>
        </div>
      </section>

      <section aria-labelledby="demo-heading" className="mb-16">
        <h2
          id="demo-heading"
          className="font-serif text-2xl tracking-tight text-[var(--color-ink)]"
        >
          A date stamp on a backdrop you shot yourself
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          Drag the handle to compare. Both frames are generated procedurally by this repository, so
          the demonstration itself carries no third-party rights.
        </p>
        <div className="mt-6 grid gap-8 lg:grid-cols-2">
          <BeforeAfter
            beforeSrc="/demo/backdrop-datestamp.jpg"
            afterSrc="/demo/backdrop-clean.jpg"
            beforeLabel="With date stamp"
            afterLabel="Cleaned"
            caption="Fast Fill handles small marks on smooth backgrounds in a fraction of a second."
          />
          <BeforeAfter
            beforeSrc="/demo/canvas-texture-badge.jpg"
            afterSrc="/demo/canvas-texture-clean.jpg"
            beforeLabel="Obsolete badge"
            afterLabel="Texture restored"
            caption="Texture Restore rebuilds the weave instead of smearing it into a soft patch."
          />
        </div>
      </section>

      <section aria-labelledby="tools-heading" className="mb-16">
        <h2 id="tools-heading" className="sr-only">
          Tools
        </h2>
        <div className="grid gap-5 md:grid-cols-2">
          {TOOLS.map((tool) => (
            <Card key={tool.title}>
              <CardHeader>
                <tool.icon className="size-5 text-[var(--color-primary)]" aria-hidden="true" />
                <CardTitle as="h3">{tool.title}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">{tool.body}</p>
                <Button asChild variant="secondary" size="sm" className="self-start">
                  <Link href={tool.href}>{tool.action}</Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section
        aria-labelledby="limits-heading"
        className="mb-16 grid gap-6 rounded-[var(--radius-xl)] border border-[var(--color-line)] bg-[var(--color-paper-raised)] p-6 sm:p-8 lg:grid-cols-2"
      >
        <div>
          <h2
            id="limits-heading"
            className="flex items-center gap-2 font-serif text-2xl tracking-tight text-[var(--color-ink)]"
          >
            <ShieldCheck className="size-5 text-[var(--color-primary)]" aria-hidden="true" />
            What this app will not do
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-muted)]">
            These are enforced in the processing pipeline, not just written in a policy. When a
            selection overlaps one of them, the run stops and explains why.
          </p>
          <ul className="mt-4 flex flex-col gap-2">
            {REFUSALS.map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-[var(--color-ink)]">
                <span
                  aria-hidden="true"
                  className="mt-1.5 size-1.5 shrink-0 rounded-full bg-[var(--color-accent)]"
                />
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm text-[var(--color-ink-muted)]">
            Metadata is preserved by default. There is no strip-metadata mode, and a reconstructed
            timelapse is never described as an original recording.
          </p>
          <Button asChild variant="link" size="sm" className="mt-3 px-0">
            <Link href="/authorized-use-policy">Read the authorized-use policy</Link>
          </Button>
        </div>

        <div className="flex flex-col gap-5">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <FileCheck2 className="size-4 text-[var(--color-primary)]" aria-hidden="true" />
              Who it is for
            </h3>
            <ul className="mt-3 flex flex-col gap-2">
              {AUDIENCES.map((item) => (
                <li key={item} className="text-sm text-[var(--color-ink-muted)]">
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <Timer className="size-4 text-[var(--color-primary)]" aria-hidden="true" />
              Your files, briefly
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-muted)]">
              Uploads are private to your account, are never used to train models, and are deleted
              automatically after 1, 7 or 30 days — your choice, changeable at any time and applied
              to work you have already uploaded.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-6 rounded-[var(--radius-xl)] bg-[var(--color-primary)] px-6 py-10 text-center sm:px-10">
        <h2 className="font-serif text-2xl tracking-tight text-[var(--color-on-primary)]">
          Start with an image you own
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-[var(--color-on-primary)]/85">
          No exaggerated promises: difficult textures and large removals still take judgement, and
          the app tells you when a result is unlikely to hold up.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Button asChild variant="secondary" size="lg">
            <Link href="/register">Create an account</Link>
          </Button>
          <Button
            asChild
            size="lg"
            className="bg-[var(--color-primary-hover)] text-[var(--color-on-primary)]"
          >
            <Link href="/login">Log in</Link>
          </Button>
        </div>
      </section>
    </AppShell>
  );
}
