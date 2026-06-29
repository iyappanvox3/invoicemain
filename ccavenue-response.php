<?php
/**
 * CCAvenue Bridge File
 *
 * INSTRUCTIONS:
 * 1. Upload this file to your www.voxlom.com server root
 *    so it is accessible at: https://www.voxlom.com/ccavenue-response.php
 * 2. CCAvenue will POST the payment result here.
 * 3. This script forwards encResp to invoice.voxlom.com to complete processing.
 */

// Read the encrypted response from CCAvenue (comes as POST)
$encResp = isset($_POST['encResp']) ? trim($_POST['encResp']) : '';

if (empty($encResp)) {
    // No response received — redirect to failure page
    header("Location: https://invoice.voxlom.com/pay?payment_status=failed&error=no_response_from_ccavenue");
    exit;
}

// Forward the encResp to the invoice app on the subdomain
$target = "https://invoice.voxlom.com/ccavenue-response/?encResp=" . urlencode($encResp);

header("Location: " . $target);
exit;
?>
