"""Metadata and provenance handling.

Two rules drive this module:

1. **Provenance is preserved.** EXIF, ICC profiles, XMP, IPTC and C2PA/JUMBF
   blocks travel from the source image to every export. ArtRestore Studio has no
   "strip metadata" mode, because stripping provenance is exactly the abuse this
   product refuses to perform.
2. **Unsafe payloads are dropped.** Anything outside the permitted metadata set
   is discarded when the processing-safe representation is built.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

# Byte markers that indicate a Content Credentials / C2PA manifest.
_C2PA_MARKERS: tuple[bytes, ...] = (
    b"c2pa",
    b"jumb",
    b"urn:uuid:",
    b"contentauth",
    b"c2pa.assertions",
)

_XMP_PROVENANCE_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"contentauthenticity", re.IGNORECASE),
    re.compile(rb"c2pa", re.IGNORECASE),
    re.compile(rb"plus:\w*Licensor", re.IGNORECASE),
    re.compile(rb"xmpRights", re.IGNORECASE),
    re.compile(rb"dc:rights", re.IGNORECASE),
    re.compile(rb"Iptc4xmpExt:DigitalSourceType", re.IGNORECASE),
)

#: EXIF tags that carry authorship or rights information.
RIGHTS_EXIF_TAGS: tuple[str, ...] = ("Artist", "Copyright", "ImageDescription", "XPAuthor")


@dataclass(slots=True)
class ProvenanceReport:
    """What ownership/provenance signals an image carries."""

    has_c2pa: bool = False
    has_xmp_rights: bool = False
    has_iptc: bool = False
    exif_rights: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return bool(self.has_c2pa or self.has_xmp_rights or self.has_iptc or self.exif_rights)

    def to_dict(self) -> dict:
        return {
            "has_c2pa": self.has_c2pa,
            "has_xmp_rights": self.has_xmp_rights,
            "has_iptc": self.has_iptc,
            "exif_rights": self.exif_rights,
            "has_any": self.has_any,
            "notes": self.notes,
        }


def detect_provenance(data: bytes) -> ProvenanceReport:
    """Inspect raw image bytes for provenance and rights metadata.

    This is intentionally a *detector*, never a remover. The result is surfaced
    to the user and stored on the asset so exports can carry it forward.
    """
    report = ProvenanceReport()
    head = data[:262_144]  # manifests live near the start of the container

    for marker in _C2PA_MARKERS:
        if marker in head:
            report.has_c2pa = True
            report.notes.append(
                "Content Credentials / C2PA style manifest detected; it is preserved on export."
            )
            break

    for pattern in _XMP_PROVENANCE_PATTERNS:
        if pattern.search(head):
            report.has_xmp_rights = True
            report.notes.append("XMP rights metadata detected; it is preserved on export.")
            break

    if b"Photoshop 3.0\x00" in head or b"8BIM" in head:
        report.has_iptc = True
        report.notes.append("IPTC block detected; it is preserved on export.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            exif = image.getexif()
            for tag_id, value in exif.items():
                name = TAGS.get(tag_id, str(tag_id))
                if name in RIGHTS_EXIF_TAGS and value:
                    text = value.decode("utf-16-le", "ignore") if isinstance(value, bytes) else str(value)
                    text = text.replace("\x00", "").strip()
                    if text:
                        report.exif_rights[name] = text
    except Exception:  # noqa: BLE001 - metadata is best-effort, never fatal
        report.notes.append("EXIF block could not be parsed; it is copied through verbatim.")

    return report


def extract_preserved_metadata(data: bytes) -> dict:
    """Collect the metadata blocks that are carried into exports."""
    preserved: dict = {}
    try:
        with Image.open(io.BytesIO(data)) as image:
            info = image.info
            if info.get("exif"):
                preserved["exif"] = info["exif"]
            if info.get("icc_profile"):
                preserved["icc_profile"] = info["icc_profile"]
            xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
            if xmp:
                preserved["xmp"] = xmp.encode("utf-8") if isinstance(xmp, str) else xmp
            if info.get("dpi"):
                preserved["dpi"] = info["dpi"]
            if info.get("photoshop"):
                preserved["photoshop"] = info["photoshop"]
    except Exception:  # noqa: BLE001
        return preserved
    return preserved


def exif_orientation(data: bytes) -> int:
    """Return the EXIF orientation value (1 when absent)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            exif = image.getexif()
            return int(exif.get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001
        return 1


def apply_orientation(image: Image.Image) -> Image.Image:
    """Bake EXIF orientation into pixels.

    Pillow's ``exif_transpose`` rewrites the orientation tag to 1 while keeping
    the remaining EXIF entries, so rights metadata survives the correction.
    """
    corrected = ImageOps.exif_transpose(image)
    return corrected if corrected is not None else image


def describe_metadata(data: bytes) -> dict:
    """A JSON-serialisable metadata summary suitable for the Asset record.

    Only *descriptions* are stored in the database - never raw metadata blobs
    and never image content.
    """
    provenance = detect_provenance(data)
    preserved = extract_preserved_metadata(data)
    return {
        "provenance": provenance.to_dict(),
        "preserved_blocks": sorted(preserved.keys()),
        "orientation": exif_orientation(data),
    }
