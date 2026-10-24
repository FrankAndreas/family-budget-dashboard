"""What the AI gets from a receipt file (issue #56): an image, a PDF's text or pages, an e-mail's text."""

import base64
import io

import pytest
from PIL import Image

from files import eml, image_png, pdf_scanned, pdf_with_text

from app import receipt_files


def image_size(part):
    data = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    return Image.open(io.BytesIO(data)).size


def test_a_photo_is_shrunk_to_1600_px():
    parts = receipt_files.ai_content("image/png", image_png())
    assert len(parts) == 1 and parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert max(image_size(parts[0])) == 1600


def test_a_pdf_with_text_sends_its_text():
    parts = receipt_files.ai_content("application/pdf", pdf_with_text(["Migros Bern", "Brot 3.50", "Total 3.50"]))
    assert len(parts) == 1 and parts[0]["type"] == "text"
    assert "Brot 3.50" in parts[0]["text"]


def test_a_scanned_pdf_sends_its_pages_at_most_five():
    parts = receipt_files.ai_content("application/pdf", pdf_scanned(pages=7))
    assert len(parts) == 5 and all(p["type"] == "image_url" for p in parts)


def test_html_mail_without_scripts():
    data = eml(body_html="<html><script>steal()</script><p>Total CHF 12.50</p></html>")
    parts = receipt_files.ai_content("message/rfc822", data)
    assert parts[0]["type"] == "text"
    assert "12.50" in parts[0]["text"] and "steal" not in parts[0]["text"]


def test_plain_mail_text():
    parts = receipt_files.ai_content("message/rfc822", eml(body_text="Danke!\nKaffee 4.20\nTotal 4.20"))
    assert "Kaffee 4.20" in parts[0]["text"]


def test_mail_with_a_pdf_and_no_amounts_reads_the_pdf():
    data = eml(body_text="Ihre Quittung im Anhang.", attach_pdf=pdf_with_text(["Velo-Hose 79.90"]))
    parts = receipt_files.ai_content("message/rfc822", data)
    assert "Velo-Hose 79.90" in parts[0]["text"]


def test_empty_mail_is_unreadable():
    with pytest.raises(receipt_files.Unreadable):
        receipt_files.ai_content("message/rfc822", eml(body_text=""))


# Personal data the AI doesn't need is taken out of a text before it is sent (2026-10-24 review). Invented data.
FORWARDED = """Hallo, der Beleg.

---------- Forwarded message ---------
Von: Max Muster <max.muster@example.ch>
Date: Fri, 23 Oct 2026 at 10:12
Subject: Ihre Bestellung 4711
To: <familie@example.ch>
An: Erika Beispiel
Cc: Beispiel AG <info@example.ch>

Lieferadresse: Musterweg 1, 8000 Zürich, Tel. +41 79 123 45 67
Rückfragen: 044 123 45 67 oder 0041 44 123 45 67
Brot 3.50
Total 3.50
"""


def test_mail_text_leaves_out_addresses_phones_and_header_lines():
    [part] = receipt_files.ai_content("message/rfc822", eml(body_text=FORWARDED))
    text = part["text"]
    for personal in ("@", "Max Muster", "Erika Beispiel", "Beispiel AG", "79 123", "044 123", "44 123"):
        assert personal not in text
    assert "Ihre Bestellung 4711" in text
    assert "Brot 3.50" in text and "Total 3.50" in text


def test_pdf_text_leaves_out_addresses_and_phones():
    data = pdf_with_text(["Kontakt info@example.ch, 044 123 45 67", "Velo-Hose 79.90", "Total 79.90"])
    [part] = receipt_files.ai_content("application/pdf", data)
    assert "@" not in part["text"] and "123 45 67" not in part["text"]
    assert "Velo-Hose 79.90" in part["text"]
