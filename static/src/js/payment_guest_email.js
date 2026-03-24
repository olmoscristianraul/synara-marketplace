/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';

const PaymentForm = publicWidget.registry.PaymentForm;

// Inject guest_email into the transaction payload sent to /shop/payment/transaction
PaymentForm.include({
    _prepareTransactionRouteParams() {
        const params = this._super(...arguments);
        const emailInput = document.getElementById('fotoapp_guest_email');
        const email = emailInput && emailInput.value ? emailInput.value.trim() : '';
        if (email) {
            params.guest_email = email;
        }
        return params;
    },
});
