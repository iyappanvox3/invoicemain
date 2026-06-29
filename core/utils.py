import smtplib
import base64
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from binascii import hexlify, unhexlify
from django.conf import settings

# ── CCAvenue Cryptography Helpers ───────────────────────────────────────────

def get_aes_cipher(working_key, mode):
    key = hashlib.md5(working_key.encode('utf-8')).digest()
    iv = b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f'
    return AES.new(key, mode, iv)

def encrypt_ccavenue(plain_text, working_key):
    """Encrypt plain_text with AES-CBC using working_key.
    Raises on failure so callers can surface a real error message."""
    cipher = get_aes_cipher(working_key, AES.MODE_CBC)
    padded_data = pad(plain_text.encode('utf-8'), AES.block_size)
    encrypted_data = cipher.encrypt(padded_data)
    enc = hexlify(encrypted_data).decode('utf-8')
    if not enc:
        raise ValueError("Encryption produced an empty result. Check the working key.")
    return enc

def decrypt_ccavenue(encrypted_text, working_key):
    try:
        cipher = get_aes_cipher(working_key, AES.MODE_CBC)
        encrypted_bytes = unhexlify(encrypted_text)
        decrypted_data = cipher.decrypt(encrypted_bytes)
        return unpad(decrypted_data, AES.block_size).decode('utf-8')
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""


# ── Email helpers ─────────────────────────────────────────────────────────

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT_SSL = 465
SMTP_PORT_TLS = 587

def _get_smtp_server(smtp_user, smtp_password):
    """Connect to Gmail SMTP. Tries port 465 (SSL) first, then 587 (STARTTLS).
    Render free tier blocks port 587, so SSL on 465 is the reliable option."""
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT_SSL, timeout=15)
        server.login(smtp_user, smtp_password)
        return server
    except Exception:
        pass
    # Fallback to STARTTLS on 587
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT_TLS, timeout=15)
    server.starttls()
    server.login(smtp_user, smtp_password)
    return server

def send_payment_email(smtp_user, smtp_password, recipient, invoice_num, total, payment_url):
    server = _get_smtp_server(smtp_user, smtp_password)

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = f"Payment Request – Invoice {invoice_num}"

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:30px;">
      <div style="max-width:520px;margin:auto;background:#fff;border-radius:10px;
                  padding:30px;box-shadow:0 4px 12px rgba(0,0,0,.1);">
        <h2 style="color:#1a5c3a;">Payment Request</h2>
        <p>You have a pending payment of <strong>₹{total}</strong>
           for Invoice <strong>{invoice_num}</strong>.</p>
        <p>Please click the button below to complete your payment and fill in your billing details:</p>
        <div style="text-align:center;margin:30px 0;">
          <a href="{payment_url}"
             style="background:#1a5c3a;color:#fff;padding:14px 32px;
                    border-radius:6px;text-decoration:none;font-size:16px;">
            Pay Now – ₹{total}
          </a>
        </div>
        <p style="font-size:12px;color:#888;">
          This link is unique to you. Please do not share it.
        </p>
      </div>
    </body></html>
    """

    msg.attach(MIMEText(html_body, "html"))
    server.sendmail(smtp_user, recipient, msg.as_string())
    server.quit()

def send_invoice_email(user, password, recipients, invoice_num, pdf_base64):
    if "," in pdf_base64:
        pdf_base64 = pdf_base64.split(",")[1]
    pdf_data = base64.b64decode(pdf_base64)

    server = _get_smtp_server(user, password)

    for recipient in recipients:
        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = recipient
        msg["Subject"] = f"Invoice {invoice_num} – Voxlom Innovative Solution"

        body = (
            f"Hi,\n\nPlease find attached the invoice {invoice_num} "
            f"from Voxlom Innovative Solution.\n\nThanks!"
        )
        msg.attach(MIMEText(body, "plain"))

        part = MIMEBase("application", "octet-stream")
        part.set_payload(pdf_data)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="Invoice-{invoice_num}.pdf"',
        )
        msg.attach(part)
        server.sendmail(user, recipient, msg.as_string())

    server.quit()
