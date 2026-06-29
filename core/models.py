from django.db import models
from django.utils import timezone
import uuid

class Order(models.Model):
    token = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    invoice_num = models.CharField(max_length=100, default='Invoice')
    invoice_date = models.CharField(max_length=50, blank=True, null=True)
    customer_email = models.EmailField()
    items = models.JSONField(default=list)
    
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    gst_type = models.CharField(max_length=50, blank=True, null=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    cgst = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sgst = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    igst = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    upi_id = models.CharField(max_length=100, blank=True, null=True, default='voxlomtmb@tmb')
    status = models.CharField(max_length=50, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    
    # Billing details
    billing_company = models.CharField(max_length=200, blank=True, null=True)
    billing_address = models.TextField(blank=True, null=True)
    billing_city = models.CharField(max_length=100, blank=True, null=True)
    billing_state = models.CharField(max_length=100, blank=True, null=True)
    billing_pin = models.CharField(max_length=20, blank=True, null=True)
    billing_gst = models.CharField(max_length=50, blank=True, null=True)
    billing_email = models.EmailField(blank=True, null=True)
    
    # CCAvenue details
    payment_status = models.CharField(max_length=50, blank=True, null=True)
    ccavenue_tracking_id = models.CharField(max_length=100, blank=True, null=True)
    ccavenue_payment_mode = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.invoice_num} - {self.customer_email}"
