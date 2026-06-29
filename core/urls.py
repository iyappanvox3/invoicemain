from django.urls import path
from . import views

urlpatterns = [
    path('', views.invoice_page, name='invoice_page'),
    path('pay/', views.pay_page, name='pay_page'),
    path('pay', views.pay_page, name='pay_page_no_slash'),
    path('create-order/', views.create_order, name='create_order'),
    path('create-order', views.create_order, name='create_order_no_slash'),
    path('submit-details/', views.submit_details, name='submit_details'),
    path('submit-details', views.submit_details, name='submit_details_no_slash'),
    path('send-email/', views.send_email_view, name='send_email'),
    path('send-email', views.send_email_view, name='send_email_no_slash'),
    path('initiate-ccavenue/', views.initiate_ccavenue, name='initiate_ccavenue'),
    path('initiate-ccavenue', views.initiate_ccavenue, name='initiate_ccavenue_no_slash'),
    path('ccavenue-response/', views.ccavenue_response, name='ccavenue_response'),
    path('ccavenue-response', views.ccavenue_response, name='ccavenue_response_no_slash'),
    path('test-payment/', views.test_payment, name='test_payment'),
]
