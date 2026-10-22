"""Receipt files for tests (issue #56), made up here: the repo never holds real receipts."""

import io
from email.message import EmailMessage

from PIL import Image, ImageDraw


def image_png(text: str = "MIGROS 12.50", size=(2400, 1200)) -> bytes:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def pdf_with_text(lines: list[str]) -> bytes:
    """A one-page PDF with a text layer (what a shop's e-receipt looks like)."""
    stream = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def pdf_scanned(pages: int = 1) -> bytes:
    """A PDF of page images without a text layer (a scanned receipt)."""
    images = [Image.new("RGB", (600, 800), "white") for _ in range(pages)]
    out = io.BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:])
    return out.getvalue()


def eml(body_text=None, body_html=None, attach_pdf=None) -> bytes:
    message = EmailMessage()
    message["From"] = "shop@example.ch"
    message["To"] = "family@example.ch"
    message["Subject"] = "Ihre Quittung"
    if body_text is not None:
        message.set_content(body_text)
    if body_html is not None:
        if body_text is None:
            message.set_content(body_html, subtype="html")
        else:
            message.add_alternative(body_html, subtype="html")
    if attach_pdf is not None:
        if not message.is_multipart() and body_text is None and body_html is None:
            message.set_content("")
        message.add_attachment(attach_pdf, maintype="application", subtype="pdf", filename="quittung.pdf")
    return bytes(message)
