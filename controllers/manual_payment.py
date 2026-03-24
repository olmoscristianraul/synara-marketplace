# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request


class FotoappManualPaymentController(http.Controller):
    def _get_cart(self):
        """Return the current cart as sudoed sale.order or False."""
        order = request.website.sale_get_order()
        return order.sudo() if order else False

    def _redirect_with_warning(self, message, target="/shop/cart"):
        request.session['website_sale_cart_warning'] = message
        return request.redirect(target)

    def _get_cart_photographer(self, order):
        photo_lines = order.order_line.filtered(lambda line: line.foto_photographer_id)
        photographers = photo_lines.mapped('foto_photographer_id')
        if len(photographers) > 1:
            return None, True
        photographer = photographers[:1] if photographers else False
        return photographer, False

    @http.route(['/fotoapp/payment/manual'], type='http', auth='public', website=True, methods=['POST'])
    def manual_payment(self, **kwargs):
        order = self._get_cart()
        if not order or not order.order_line:
            return self._redirect_with_warning(_('Tu carrito está vacío. Agregá fotos para continuar.'))

        photographer, has_multiple = self._get_cart_photographer(order)
        if has_multiple:
            return self._redirect_with_warning(_('No está permitido agregar fotos de varios fotógrafos al carrito. Separá los carritos por favor.'))
        if not photographer:
            return self._redirect_with_warning(_('No encontramos un fotógrafo asociado al carrito. Volvé a la galería para elegir fotos.'))

        def _safe(value):
            return value or _('No informado')

        whatsapp = photographer.phone_whatsapp or photographer.mobile or photographer.phone
        alias = photographer.bank_alias or photographer.payout_account
        values = {
            'photographer': photographer,
            'contact_name': _safe(photographer.name),
            'instagram': _safe(photographer.instagram_account),
            'whatsapp': _safe(whatsapp),
            'cbu_cvu': _safe(photographer.cbu_cvu),
            'alias': _safe(alias),
            'gallery_url': '/galeria',
        }
        return request.render('fotoapp.manual_payment_contact', values)
