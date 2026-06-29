import http.server
import json
import smtplib
import uuid
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import base64
import hashlib
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from binascii import hexlify, unhexlify

PORT = int(os.environ.get("PORT", 8002))
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
ORDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.json")

# ── CCAvenue Cryptography Helpers ───────────────────────────────────────────


def get_aes_cipher(working_key, mode):
    key = hashlib.md5(working_key.encode("utf-8")).digest()
    iv = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f"
    return AES.new(key, mode, iv)


def encrypt_ccavenue(plain_text, working_key):
    try:
        cipher = get_aes_cipher(working_key, AES.MODE_CBC)
        padded_data = pad(plain_text.encode("utf-8"), AES.block_size)
        encrypted_data = cipher.encrypt(padded_data)
        return hexlify(encrypted_data).decode("utf-8")
    except Exception as e:
        print(f"Encryption error: {e}")
        return ""


def decrypt_ccavenue(encrypted_text, working_key):
    try:
        cipher = get_aes_cipher(working_key, AES.MODE_CBC)
        encrypted_bytes = unhexlify(encrypted_text)
        decrypted_data = cipher.decrypt(encrypted_bytes)
        return unpad(decrypted_data, AES.block_size).decode("utf-8")
    except Exception as e:
        print(f"Decryption error: {e}")
        return ""


# ── Helpers ─────────────────────────────────────────────────────────────────


def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return []
    with open(ORDERS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return []


def save_orders(orders):
    with open(ORDERS_FILE, "w") as f:
        json.dump(orders, f, indent=2)


def load_config():
    env_config = {
        "smtp_user": os.environ.get("SMTP_USER"),
        "smtp_password": os.environ.get("SMTP_PASSWORD"),
        "ccavenue_merchant_id": os.environ.get("CCAVENUE_MERCHANT_ID"),
        "ccavenue_access_code": os.environ.get("CCAVENUE_ACCESS_CODE"),
        "ccavenue_working_key": os.environ.get("CCAVENUE_WORKING_KEY"),
        "base_url": os.environ.get("BASE_URL"),
    }
    if all(env_config.values()):
        return env_config
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"
    )
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            try:
                file_config = json.load(f)
                for k, v in env_config.items():
                    if v is not None:
                        file_config[k] = v
                return file_config
            except:
                pass
    return env_config


# ── Handler ──────────────────────────────────────────────────────────────────


class CustomHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence default logging

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET  /pay?token=xxx  →  serve pay.html ───────────────────────────────
    def do_GET(self):
        if self.path.startswith("/pay"):
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            token = query_params.get("token", [""])[0].strip()

            orders = load_orders()
            order = next((o for o in orders if o["token"] == token), None)

            if not order:
                self.send_error_response(404, "Order not found or link expired.")
                return

            # Serve pay.html with order data injected
            pay_html_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "pay.html"
            )
            if not os.path.exists(pay_html_path):
                self.send_error_response(404, "pay.html not found.")
                return

            with open(pay_html_path, "r", encoding="utf-8") as f:
                html = f.read()

            # Inject order JSON into page
            order_json = json.dumps(order)
            html = html.replace("__ORDER_DATA__", order_json)

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        # Default file serving
        super().do_GET()

    def do_POST(self):

        # ── /create-order ────────────────────────────────────────────────────
        if self.path == "/create-order":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode("utf-8"))

                customer_email = data.get("customer_email", "").strip()
                invoice_num = data.get("invoice_num", "Invoice")
                items = data.get("items", [])
                subtotal = data.get("subtotal", 0)
                gst_type = data.get("gst_type", "")
                gst_rate = data.get("gst_rate", 0)
                cgst = data.get("cgst", 0)
                sgst = data.get("sgst", 0)
                igst = data.get("igst", 0)
                total = data.get("total", 0)
                invoice_date = data.get("invoice_date", "")
                upi_id = data.get("upi_id", "voxlomtmb@tmb")

                if not customer_email:
                    self.send_error_response(400, "Customer email is required.")
                    return
                if not items:
                    self.send_error_response(400, "No items found in invoice.")
                    return

                config = load_config()
                smtp_user = config.get("smtp_user", "").strip()
                smtp_password = config.get("smtp_password", "").strip()

                if not smtp_user or not smtp_password:
                    self.send_error_response(400, "SMTP not configured in config.json.")
                    return

                # Generate unique token
                token = str(uuid.uuid4()).replace("-", "")[:16]

                # Build order record
                order = {
                    "token": token,
                    "invoice_num": invoice_num,
                    "invoice_date": invoice_date,
                    "customer_email": customer_email,
                    "items": items,
                    "subtotal": subtotal,
                    "gst_type": gst_type,
                    "gst_rate": gst_rate,
                    "cgst": cgst,
                    "sgst": sgst,
                    "igst": igst,
                    "total": total,
                    "upi_id": upi_id,
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                }

                # Save order
                orders = load_orders()
                orders.append(order)
                save_orders(orders)

                # Build payment URL using base_url from config (public tunnel or production domain)
                site_base = (
                    config.get("base_url", "http://localhost:8002").strip().rstrip("/")
                )
                payment_url = f"{site_base}/pay?token={token}"

                # Send email to customer
                self.send_payment_email(
                    smtp_user,
                    smtp_password,
                    customer_email,
                    invoice_num,
                    total,
                    payment_url,
                )

                self.send_success_response(
                    {
                        "status": "success",
                        "message": f"Payment link sent to {customer_email}",
                        "payment_url": payment_url,
                        "token": token,
                    }
                )

            except Exception as e:
                self.send_error_response(500, f"Error creating order: {str(e)}")
            return

        # ── /submit-details ──────────────────────────────────────────────────
        if self.path == "/submit-details":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode("utf-8"))
                token = data.get("token", "").strip()
                company = data.get("company", "").strip()
                address = data.get("address", "").strip()
                city = data.get("city", "").strip()
                state = data.get("state", "").strip()
                pin = data.get("pin", "").strip()
                gst = data.get("gst", "").strip()
                email = data.get("email", "").strip()
                pdf_base64 = data.get("pdf_data", "").strip()

                if not token:
                    self.send_error_response(400, "Order token is required.")
                    return
                if not company or not address or not city or not email:
                    self.send_error_response(
                        400, "Required billing details are missing."
                    )
                    return

                orders = load_orders()
                order = next((o for o in orders if o["token"] == token), None)
                if not order:
                    self.send_error_response(404, "Order not found.")
                    return

                # Update order details
                order["status"] = "paid"
                order["billing"] = {
                    "company": company,
                    "address": address,
                    "city": city,
                    "state": state,
                    "pin": pin,
                    "gst": gst,
                    "email": email,
                }
                save_orders(orders)

                # Generate PDF invoice
                config = load_config()
                smtp_user = config.get("smtp_user", "").strip()
                smtp_password = config.get("smtp_password", "").strip()

                if not smtp_user or not smtp_password:
                    self.send_error_response(400, "SMTP not configured in config.json.")
                    return

                final_pdf_base64 = ""
                if pdf_base64:
                    final_pdf_base64 = pdf_base64
                else:
                    # Load bg.png and encode as base64
                    bg_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "bg.png"
                    )
                    bg_data_url = ""
                    if os.path.exists(bg_path):
                        with open(bg_path, "rb") as img_f:
                            bg_base64 = base64.b64encode(img_f.read()).decode("utf-8")
                            bg_data_url = f"data:image/png;base64,{bg_base64}"

                    # Generate HTML for items
                    items_rows = ""
                    for idx, item in enumerate(order.get("items", [])):
                        even_class = "even" if idx % 2 == 1 else ""
                        items_rows += f"""
                        <tr class="{even_class}">
                            <td class="align-center">{idx + 1}</td>
                            <td>{item.get('desc', '')}</td>
                            <td class="align-right">{float(item.get('price', 0)):.2f}</td>
                            <td class="align-center">{int(item.get('qty', 0))}</td>
                            <td class="align-right">{float(item.get('amount', 0)):.2f}</td>
                        </tr>
                        """

                    # Generate GST rows
                    gst_type = order.get("gst_type", "")
                    gst_rate = float(order.get("gst_rate", 0))
                    subtotal = float(order.get("subtotal", 0))
                    total = float(order.get("total", 0))
                    upi_id = order.get("upi_id", "voxlomomtmb@tmb")

                    gst_rows = ""
                    if gst_type == "CGST + SGST":
                        half_rate = gst_rate / 2
                        half_amount = (subtotal * (gst_rate / 100)) / 2
                        gst_rows = f"""
                        <tr class="total-row">
                            <td>CGST ({half_rate:.1f}%)</td>
                            <td class="align-right">INR {half_amount:.2f}</td>
                        </tr>
                        <tr class="total-row">
                            <td>SGST ({half_rate:.1f}%)</td>
                            <td class="align-right">INR {half_amount:.2f}</td>
                        </tr>
                        """
                    else:
                        igst_amount = subtotal * (gst_rate / 100)
                        gst_rows = f"""
                        <tr class="total-row">
                            <td>IGST ({gst_rate:.1f}%)</td>
                            <td class="align-right">INR {igst_amount:.2f}</td>
                        </tr>
                        """

                    html_content = f"""
                    <html>
                    <head>
                    <style>
                        @page {{
                            size: a4 portrait;
                            margin: 0;
                            @frame background {{
                                -pdf-frame-content: background-content;
                                left: 0;
                                top: 0;
                                width: 210mm;
                                height: 297mm;
                            }}
                            @frame content {{
                                left: 15mm;
                                top: 35mm;
                                width: 180mm;
                                height: 247mm;
                            }}
                        }}
                        body {{
                            font-family: Helvetica, Arial, sans-serif;
                            color: #2c3e50;
                            font-size: 10pt;
                            line-height: 1.4;
                        }}
                        #background-content {{
                            position: absolute;
                            left: 0;
                            top: 0;
                            width: 210mm;
                            height: 297mm;
                        }}
                        .header-table {{
                            width: 100%;
                            margin-bottom: 20px;
                        }}
                        .header-left {{
                            width: 60%;
                            text-align: left;
                        }}
                        .header-right {{
                            width: 40%;
                            text-align: right;
                            vertical-align: top;
                        }}
                        .title {{
                            font-size: 28pt;
                            font-weight: bold;
                            color: #1a5c3a;
                            margin: 0 0 10px 0;
                            text-transform: uppercase;
                            letter-spacing: 2px;
                        }}
                        .meta-item {{
                            font-size: 10pt;
                            margin-bottom: 4px;
                        }}
                        .meta-label {{
                            font-weight: bold;
                            color: #555;
                        }}
                        .meta-value {{
                            color: #111;
                        }}
                        .company-details {{
                            font-size: 9pt;
                            color: #555;
                            line-height: 1.3;
                        }}
                        .bill-to-title {{
                            font-size: 11pt;
                            font-weight: bold;
                            color: #be9428;
                            border-bottom: 1px solid #be9428;
                            padding-bottom: 3px;
                            margin-bottom: 6px;
                            text-transform: uppercase;
                        }}
                        .bill-to-details {{
                            font-size: 9.5pt;
                            line-height: 1.3;
                        }}
                        .items-table {{
                            width: 100%;
                            border-collapse: collapse;
                            margin-top: 25px;
                            margin-bottom: 20px;
                        }}
                        .items-table th {{
                            background-color: #1a5c3a;
                            color: #ffffff;
                            font-size: 9.5pt;
                            font-weight: bold;
                            text-transform: uppercase;
                            padding: 8px 10px;
                            border: none;
                        }}
                        .items-table td {{
                            padding: 8px 10px;
                            border-bottom: 1px solid #e0e0e0;
                            font-size: 9.5pt;
                        }}
                        .items-table tr.even {{
                            background-color: #fcfdfe;
                        }}
                        .align-center {{
                            text-align: center;
                        }}
                        .align-right {{
                            text-align: right;
                        }}
                        .bottom-table {{
                            width: 100%;
                            margin-top: 15px;
                        }}
                        .bottom-left {{
                            width: 55%;
                            vertical-align: top;
                        }}
                        .bottom-right {{
                            width: 45%;
                            vertical-align: top;
                        }}
                        .section-title {{
                            font-size: 9pt;
                            font-weight: bold;
                            color: #1a5c3a;
                            text-transform: uppercase;
                            margin-bottom: 6px;
                            letter-spacing: 1px;
                        }}
                        .payment-details {{
                            font-size: 8.5pt;
                            color: #555;
                            line-height: 1.4;
                            margin-bottom: 15px;
                        }}
                        .terms-box {{
                            font-size: 8pt;
                            color: #777;
                            line-height: 1.3;
                        }}
                        .totals-table {{
                            width: 100%;
                            border-collapse: collapse;
                        }}
                        .totals-table td {{
                            padding: 5px 10px;
                            font-size: 9.5pt;
                        }}
                        .total-row {{
                            color: #555;
                        }}
                        .total-highlight {{
                            font-size: 12pt;
                            font-weight: bold;
                            color: #1a5c3a;
                            background-color: #f4faf6;
                            border-top: 2px solid #1a5c3a;
                            border-bottom: 2px solid #1a5c3a;
                        }}
                        .total-highlight td {{
                            padding: 8px 10px;
                            font-size: 11pt;
                            font-weight: bold;
                        }}
                        .thank-you {{
                            margin-top: 30px;
                            text-align: center;
                            font-size: 12pt;
                            font-weight: bold;
                            color: #be9428;
                        }}
                        .website {{
                            text-align: center;
                            font-size: 9pt;
                            color: #888;
                            margin-top: 5px;
                        }}
                    </style>
                    </head>
                    <body>
                        <div id="background-content">
                            <img src="{bg_data_url}" width="210mm" height="297mm" />
                        </div>

                        <table class="header-table">
                            <tr>
                                <td class="header-left">
                                    <div class="title">Invoice</div>
                                    <div class="company-details">
                                        <strong>Voxlom Innovative Solution</strong><br>
                                        Kamarajar Tech Campus,<br>
                                        39/A, Gandhi East Street, Panagudi,<br>
                                        Tamil Nadu - 627108<br>
                                        GST: 33AAKCV0062G1ZK<br>
                                        Phone: +91 9092421284 | info@voxlom.com
                                    </div>
                                </td>
                                <td class="header-right">
                                    <div style="margin-top: 15px;">
                                        <div class="meta-item"><span class="meta-label">Invoice No:</span> <span class="meta-value">{order.get('invoice_num', 'Invoice')}</span></div>
                                        <div class="meta-item"><span class="meta-label">Invoice Date:</span> <span class="meta-value">{order.get('invoice_date', '')}</span></div>
                                    </div>
                                </td>
                            </tr>
                        </table>

                        <table class="header-table" style="margin-top: 10px;">
                            <tr>
                                <td style="width: 55%; vertical-align: top;">
                                    <div class="bill-to-title">Bill To</div>
                                    <div class="bill-to-details">
                                        <strong>{company}</strong><br>
                                        {address}<br>
                                        {city}, {state} - {pin}<br>
                                        GST: {gst}<br>
                                        Email: {email}
                                    </div>
                                </td>
                                <td style="width: 45%;"></td>
                            </tr>
                        </table>

                        <table class="items-table">
                            <thead>
                                <tr>
                                    <th class="align-center" style="width: 8%;">No</th>
                                    <th style="width: 50%;">Description</th>
                                    <th class="align-right" style="width: 15%;">Price</th>
                                    <th class="align-center" style="width: 12%;">Qty</th>
                                    <th class="align-right" style="width: 15%;">Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                {items_rows}
                            </tbody>
                        </table>

                        <table class="bottom-table">
                            <tr>
                                <td class="bottom-left">
                                    <div class="section-title">Payment Details</div>
                                    <div class="payment-details">
                                        <strong>Bank Name:</strong> State Bank of India<br>
                                        <strong>A/C Name:</strong> Voxlom Innovative Solution<br>
                                        <strong>A/C No:</strong> 1234567890123<br>
                                        <strong>IFSC Code:</strong> SBIN0001234<br>
                                        <strong>UPI ID:</strong> {upi_id}
                                    </div>

                                    <div class="section-title">Terms & Conditions</div>
                                    <div class="terms-box">
                                        1. Payment is due within 3 days from the invoice date.<br>
                                        2. Late payments may incur additional charges.<br>
                                        3. No refunds after project delivery.
                                    </div>
                                </td>
                                <td class="bottom-right">
                                    <table class="totals-table">
                                        <tr class="total-row">
                                            <td>SUB TOTAL</td>
                                            <td class="align-right">INR {subtotal:.2f}</td>
                                        </tr>
                                        {gst_rows}
                                        <tr class="total-highlight">
                                            <td>TOTAL</td>
                                            <td class="align-right">INR {total:.2f}</td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                        </table>

                        <div class="thank-you">Thank You</div>
                        <div class="website">www.voxlom.com</div>
                    </body>
                    </html>
                    """

                    # Render PDF using xhtml2pdf to bytes
                    from xhtml2pdf import pisa
                    import io

                    pdf_io = io.BytesIO()
                    pisa_status = pisa.CreatePDF(html_content, dest=pdf_io)
                    if pisa_status.err:
                        self.send_error_response(
                            500, f"Error generating PDF: {pisa_status.err}"
                        )
                        return

                    pdf_bytes = pdf_io.getvalue()
                    final_pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

                # Send invoice email to client and to the company email (smtp_user)
                recipients = [email, smtp_user]
                self.send_invoice_email(
                    smtp_user,
                    smtp_password,
                    recipients,
                    order.get("invoice_num", "Invoice"),
                    final_pdf_base64,
                )

                self.send_success_response(
                    {
                        "status": "success",
                        "message": f"Invoice sent to {email} and copy sent to {smtp_user}",
                    }
                )

            except Exception as e:
                self.send_error_response(500, f"Error submitting details: {str(e)}")
            return

        # ── /send-email (existing) ────────────────────────────────────────────
        if self.path == "/send-email":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode("utf-8"))
                pdf_base64 = data.get("pdf_data")
                recipients = data.get("recipients", [])
                invoice_num = data.get("invoice_num", "Invoice")

                recipients = [r.strip() for r in recipients if r and r.strip()]

                if not pdf_base64:
                    self.send_error_response(400, "Missing PDF attachment data.")
                    return
                if not recipients:
                    self.send_error_response(
                        400, "Please enter at least one recipient email address."
                    )
                    return

                config = load_config()
                smtp_user = config.get("smtp_user", "").strip()
                smtp_password = config.get("smtp_password", "").strip()

                if not smtp_user or smtp_user == "your-email@gmail.com":
                    self.send_error_response(
                        400, "Gmail address not configured in config.json."
                    )
                    return
                if not smtp_password or smtp_password == "xxxx-xxxx-xxxx-xxxx":
                    self.send_error_response(
                        400, "Gmail App Password not configured in config.json."
                    )
                    return

                self.send_invoice_email(
                    smtp_user, smtp_password, recipients, invoice_num, pdf_base64
                )
                self.send_success_response(
                    {
                        "status": "success",
                        "message": f"Successfully sent invoice to: {', '.join(recipients)}",
                    }
                )

            except smtplib.SMTPAuthenticationError:
                self.send_error_response(401, "SMTP Authentication Failed.")
            except Exception as e:
                self.send_error_response(500, f"Error sending email: {str(e)}")
            return

        # ── /initiate-ccavenue ────────────────────────────────────────────────
        if self.path == "/initiate-ccavenue":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode("utf-8"))
                token = data.get("token", "").strip()

                if not token:
                    self.send_error_response(400, "Order token is required.")
                    return

                orders = load_orders()
                order = next((o for o in orders if o["token"] == token), None)
                if not order:
                    self.send_error_response(404, "Order not found.")
                    return

                config = load_config()
                merchant_id = config.get("ccavenue_merchant_id", "").strip()
                access_code = config.get("ccavenue_access_code", "").strip()
                working_key = config.get("ccavenue_working_key", "").strip()

                if not merchant_id or not access_code or not working_key:
                    self.send_error_response(
                        400, "CCAvenue credentials not configured in config.json."
                    )
                    return

                # Use base_url from config (must be a public URL, e.g. localtunnel/ngrok)
                # so CCAvenue can POST the payment response back to us.
                base_url = config.get("base_url", "").strip().rstrip("/")
                if not base_url:
                    # Fallback: derive from request headers (works only if publicly reachable)
                    host = self.headers.get("Host", "localhost:8002")
                    proto = self.headers.get("X-Forwarded-Proto", "http")
                    base_url = f"{proto}://{host}"

                redirect_url = f"{base_url}/ccavenue-response"
                cancel_url = f"{base_url}/ccavenue-response"

                params = {
                    "merchant_id": merchant_id,
                    "order_id": order["token"],
                    "amount": f"{float(order['total']):.2f}",
                    "currency": "INR",
                    "redirect_url": redirect_url,
                    "cancel_url": cancel_url,
                    "language": "EN",
                    "billing_email": order["customer_email"],
                    "integration_type": "iframe_normal",
                }

                plain_text = urllib.parse.urlencode(params)
                encRequest = encrypt_ccavenue(plain_text, working_key)

                self.send_success_response(
                    {
                        "status": "success",
                        "encRequest": encRequest,
                        "access_code": access_code,
                    }
                )

            except Exception as e:
                self.send_error_response(500, f"Error initiating CCAvenue: {str(e)}")
            return

        # ── /ccavenue-response ────────────────────────────────────────────────
        if self.path == "/ccavenue-response":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                form_data = urllib.parse.parse_qs(post_data.decode("utf-8"))
                encResp = form_data.get("encResp", [""])[0].strip()

                if not encResp:
                    self.send_response(303)
                    self.send_header(
                        "Location",
                        "/pay?payment_status=failed&error=no_response_payload",
                    )
                    self.end_headers()
                    return

                config = load_config()
                working_key = config.get("ccavenue_working_key", "").strip()

                decrypted_text = decrypt_ccavenue(encResp, working_key)
                response_dict = dict(urllib.parse.parse_qsl(decrypted_text))

                order_id = response_dict.get("order_id", "").strip()
                order_status = response_dict.get("order_status", "").strip()
                failure_message = response_dict.get("failure_message", "").strip()

                if not order_id:
                    self.send_response(303)
                    self.send_header(
                        "Location", "/pay?payment_status=failed&error=missing_order_id"
                    )
                    self.end_headers()
                    return

                orders = load_orders()
                order = next((o for o in orders if o["token"] == order_id), None)

                if not order:
                    self.send_response(303)
                    self.send_header(
                        "Location", "/pay?payment_status=failed&error=order_not_found"
                    )
                    self.end_headers()
                    return

                if order_status == "Success":
                    order["payment_status"] = "paid"
                    order["ccavenue_tracking_id"] = response_dict.get("tracking_id", "")
                    order["ccavenue_payment_mode"] = response_dict.get(
                        "payment_mode", ""
                    )
                    save_orders(orders)

                    self.send_response(303)
                    self.send_header(
                        "Location", f"/pay?token={order_id}&payment_status=success"
                    )
                    self.end_headers()
                else:
                    self.send_response(303)
                    err_msg = urllib.parse.quote(
                        failure_message or f"Payment {order_status}"
                    )
                    self.send_header(
                        "Location",
                        f"/pay?token={order_id}&payment_status=failed&error={err_msg}",
                    )
                    self.end_headers()

            except Exception as e:
                self.send_response(303)
                err_msg = urllib.parse.quote(str(e))
                self.send_header(
                    "Location", f"/pay?payment_status=failed&error={err_msg}"
                )
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    # ── Email helpers ─────────────────────────────────────────────────────────

    def send_payment_email(
        self, smtp_user, smtp_password, recipient, invoice_num, total, payment_url
    ):
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(smtp_user, smtp_password)

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

    def send_invoice_email(self, user, password, recipients, invoice_num, pdf_base64):
        if "," in pdf_base64:
            pdf_base64 = pdf_base64.split(",")[1]
        pdf_data = base64.b64decode(pdf_base64)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(user, password)

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

    # ── Response helpers ──────────────────────────────────────────────────────

    def send_success_response(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def send_error_response(self, code, message):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "error", "message": message}).encode("utf-8")
        )


import socketserver


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Starting server on http://localhost:{PORT}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), CustomHandler)
    server.serve_forever()
