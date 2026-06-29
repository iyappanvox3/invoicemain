import json
import base64
import os
import urllib.parse
from datetime import datetime
from django.http import JsonResponse, HttpResponseRedirect, HttpResponseNotFound, HttpResponseBadRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from .models import Order
from .utils import (
    send_payment_email, send_invoice_email,
    encrypt_ccavenue, decrypt_ccavenue
)

# Helpers for Config
def get_config():
    # Try to load from settings if provided, else fallback to config.json
    try:
        config_path = os.path.join(settings.BASE_DIR, 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                file_config = json.load(f)
                return file_config
    except Exception:
        pass
    
    return {
        "smtp_user": os.environ.get('SMTP_USER', getattr(settings, 'SMTP_USER', '')),
        "smtp_password": os.environ.get('SMTP_PASSWORD', getattr(settings, 'SMTP_PASSWORD', '')),
        "ccavenue_merchant_id": os.environ.get('CCAVENUE_MERCHANT_ID', getattr(settings, 'CCAVENUE_MERCHANT_ID', '')),
        "ccavenue_access_code": os.environ.get('CCAVENUE_ACCESS_CODE', getattr(settings, 'CCAVENUE_ACCESS_CODE', '')),
        "ccavenue_working_key": os.environ.get('CCAVENUE_WORKING_KEY', getattr(settings, 'CCAVENUE_WORKING_KEY', '')),
        "base_url": os.environ.get('BASE_URL', getattr(settings, 'BASE_URL', 'http://localhost:8000'))
    }

@csrf_exempt
@require_http_methods(["POST"])
def create_order(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        
        customer_email = data.get('customer_email', '').strip()
        if not customer_email:
            return JsonResponse({'status': 'error', 'message': 'Customer email is required.'}, status=400)
        
        items = data.get('items', [])
        if not items:
            return JsonResponse({'status': 'error', 'message': 'No items found in invoice.'}, status=400)

        config = get_config()
        smtp_user = config.get('smtp_user', '').strip()
        smtp_password = config.get('smtp_password', '').strip()

        if not smtp_user or not smtp_password:
            return JsonResponse({'status': 'error', 'message': 'SMTP not configured in config.json.'}, status=400)

        # Build order
        order = Order.objects.create(
            invoice_num=data.get('invoice_num', 'Invoice'),
            invoice_date=data.get('invoice_date', ''),
            customer_email=customer_email,
            items=items,
            subtotal=data.get('subtotal', 0),
            gst_type=data.get('gst_type', ''),
            gst_rate=data.get('gst_rate', 0),
            cgst=data.get('cgst', 0),
            sgst=data.get('sgst', 0),
            igst=data.get('igst', 0),
            total=data.get('total', 0),
            upi_id=data.get('upi_id', 'voxlomtmb@tmb'),
            status='pending'
        )

        site_base = config.get('base_url', 'http://localhost:8000').strip().rstrip('/')
        payment_url = f'{site_base}/pay?token={order.token}'

        # Send email (non-fatal: order is created regardless of email success)
        email_warning = None
        try:
            send_payment_email(smtp_user, smtp_password, customer_email, order.invoice_num, order.total, payment_url)
        except Exception as email_err:
            email_warning = f'Order created but email failed: {str(email_err)}'
            print(f'[WARN] Email send failed: {email_err}')

        response = {
            'status': 'success',
            'message': f'Payment link sent to {customer_email}' if not email_warning else f'Order created (email failed — copy link manually)',
            'payment_url': payment_url,
            'token': str(order.token)
        }
        if email_warning:
            response['email_warning'] = email_warning

        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error creating order: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def submit_details(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        token = data.get('token', '').strip()
        
        if not token:
            return JsonResponse({'status': 'error', 'message': 'Order token is required.'}, status=400)

        order = get_object_or_404(Order, token=token)

        company = data.get('company', '').strip()
        address = data.get('address', '').strip()
        city = data.get('city', '').strip()
        email = data.get('email', '').strip()

        if not company or not address or not city or not email:
            return JsonResponse({'status': 'error', 'message': 'Required billing details are missing.'}, status=400)

        # Update order details
        order.status = 'paid'
        order.billing_company = company
        order.billing_address = address
        order.billing_city = city
        order.billing_state = data.get('state', '').strip()
        order.billing_pin = data.get('pin', '').strip()
        order.billing_gst = data.get('gst', '').strip()
        order.billing_email = email
        order.save()

        config = get_config()
        smtp_user = config.get('smtp_user', '').strip()
        smtp_password = config.get('smtp_password', '').strip()

        if not smtp_user or not smtp_password:
            return JsonResponse({'status': 'error', 'message': 'SMTP not configured in config.json.'}, status=400)

        pdf_base64 = data.get('pdf_data', '').strip()
        if not pdf_base64:
            # Re-implementing the PDF generation logic from server.py would require xhtml2pdf in django
            # However, since the client usually sends pdf_base64 in the current flow, we will rely on it.
            # If server-side PDF generation is strictly needed here, we need to bring the HTML template logic here.
            # Since the original server.py had a big HTML blob, let's keep it simple for now and rely on the client or
            # the fact that `pdf_data` is usually provided by the frontend html2canvas/jsPDF.
            pass
            
        final_pdf_base64 = pdf_base64

        if final_pdf_base64:
            recipients = [email, smtp_user]
            send_invoice_email(smtp_user, smtp_password, recipients, order.invoice_num, final_pdf_base64)
            
            return JsonResponse({
                'status': 'success',
                'message': f'Invoice sent to {email} and copy sent to {smtp_user}'
            })
        else:
             return JsonResponse({'status': 'error', 'message': 'PDF data missing.'}, status=400)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error submitting details: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def send_email_view(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        pdf_base64 = data.get('pdf_data')
        recipients = data.get('recipients', [])
        invoice_num = data.get('invoice_num', 'Invoice')

        recipients = [r.strip() for r in recipients if r and r.strip()]

        if not pdf_base64:
            return JsonResponse({'status': 'error', 'message': 'Missing PDF attachment data.'}, status=400)
        if not recipients:
            return JsonResponse({'status': 'error', 'message': 'Please enter at least one recipient email address.'}, status=400)

        config = get_config()
        smtp_user = config.get('smtp_user', '').strip()
        smtp_password = config.get('smtp_password', '').strip()

        if not smtp_user or smtp_user == 'your-email@gmail.com':
            return JsonResponse({'status': 'error', 'message': 'Gmail address not configured.'}, status=400)

        send_invoice_email(smtp_user, smtp_password, recipients, invoice_num, pdf_base64)
        return JsonResponse({'status': 'success', 'message': f"Successfully sent invoice to: {', '.join(recipients)}"})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error sending email: {str(e)}'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def initiate_ccavenue(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        token = data.get('token', '').strip()

        if not token:
            return JsonResponse({'status': 'error', 'message': 'Order token is required.'}, status=400)

        order = get_object_or_404(Order, token=token)

        config = get_config()
        merchant_id = config.get('ccavenue_merchant_id', '').strip()
        access_code = config.get('ccavenue_access_code', '').strip()
        working_key = config.get('ccavenue_working_key', '').strip()

        if not merchant_id or not access_code or not working_key:
            return JsonResponse({'status': 'error', 'message': 'CCAvenue credentials not configured.'}, status=400)

        base_url = config.get('base_url', '').strip().rstrip('/')
        if not base_url:
            host = request.get_host()
            proto = request.scheme
            base_url = f"{proto}://{host}"

        redirect_url = f"{base_url}/ccavenue-response/"
        cancel_url = f"{base_url}/ccavenue-response/"

        params = {
            'merchant_id': merchant_id,
            'order_id': str(order.token),
            'amount': f"{float(order.total):.2f}",
            'currency': 'INR',
            'redirect_url': redirect_url,
            'cancel_url': cancel_url,
            'language': 'EN',
            'billing_email': order.customer_email,
            'integration_type': 'iframe_normal'
        }
        
        plain_text = urllib.parse.urlencode(params)
        encRequest = encrypt_ccavenue(plain_text, working_key)

        if not encRequest:
            return JsonResponse({'status': 'error', 'message': 'Encryption failed: encRequest is empty. Check the working key in config.json.'}, status=500)

        return JsonResponse({
            'status': 'success',
            'encRequest': encRequest,
            'access_code': access_code
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error initiating CCAvenue: {str(e)}'}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def ccavenue_response(request):
    try:
        encResp = request.POST.get('encResp', '').strip()

        if not encResp:
            return HttpResponseRedirect('/pay?payment_status=failed&error=no_response_payload')

        config = get_config()
        working_key = config.get('ccavenue_working_key', '').strip()

        decrypted_text = decrypt_ccavenue(encResp, working_key)
        response_dict = dict(urllib.parse.parse_qsl(decrypted_text))

        order_id = response_dict.get('order_id', '').strip()
        order_status = response_dict.get('order_status', '').strip()
        failure_message = response_dict.get('failure_message', '').strip()

        if not order_id:
            return HttpResponseRedirect('/pay?payment_status=failed&error=missing_order_id')

        try:
            order = Order.objects.get(token=order_id)
        except Order.DoesNotExist:
            return HttpResponseRedirect('/pay?payment_status=failed&error=order_not_found')

        if order_status == 'Success':
            order.payment_status = 'paid'
            order.ccavenue_tracking_id = response_dict.get('tracking_id', '')
            order.ccavenue_payment_mode = response_dict.get('payment_mode', '')
            order.save()
            return HttpResponseRedirect(f'/pay?token={order_id}&payment_status=success')
        else:
            err_msg = urllib.parse.quote(failure_message or f'Payment {order_status}')
            return HttpResponseRedirect(f'/pay?token={order_id}&payment_status=failed&error={err_msg}')

    except Exception as e:
        err_msg = urllib.parse.quote(str(e))
        return HttpResponseRedirect(f'/pay?payment_status=failed&error={err_msg}')

# GET Views
def test_payment(request):
    token = request.GET.get('token', '').strip()
    if not token:
        return HttpResponseBadRequest("Token is required")
        
    try:
        order = Order.objects.get(token=token)
    except Order.DoesNotExist:
        return HttpResponseNotFound("Order not found")
        
    order.payment_status = 'paid'
    order.save()
    return HttpResponseRedirect(f'/pay?token={token}&payment_status=success')

def pay_page(request):
    token = request.GET.get('token', '').strip()
    if not token:
        return HttpResponseBadRequest("Token is required")
        
    try:
        order = Order.objects.get(token=token)
    except Order.DoesNotExist:
        return HttpResponseNotFound("Order not found")

    order_dict = {
        'token': str(order.token),
        'invoice_num': order.invoice_num,
        'invoice_date': order.invoice_date,
        'customer_email': order.customer_email,
        'items': order.items,
        'subtotal': float(order.subtotal),
        'gst_type': order.gst_type,
        'gst_rate': float(order.gst_rate),
        'cgst': float(order.cgst),
        'sgst': float(order.sgst),
        'igst': float(order.igst),
        'total': float(order.total),
        'upi_id': order.upi_id,
        'status': order.status,
        'payment_status': order.payment_status,
    }

    # Instead of string replacement, we pass it to context.
    # In `pay.html`, we need to change __ORDER_DATA__ to {{ order_json|safe }}
    order_json = json.dumps(order_dict)
    
    return render(request, 'core/pay.html', {'order_json': order_json})

def invoice_page(request):
    return render(request, 'core/invoice.html')
