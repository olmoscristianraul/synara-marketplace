# -*- coding: utf-8 -*-
from odoo import _, http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class MarketplaceCheckout(WebsiteSale):
    """Override cart validation to enforce single-seller carts."""

    def _check_cart(self, order_sudo):
        redir = super()._check_cart(order_sudo)
        if redir:
            return redir
        return self._marketplace_validate_single_seller(order_sudo)

    def _marketplace_validate_single_seller(self, order_sudo):
        """Ensure all marketplace products in the cart belong to the same seller."""
        if not order_sudo or not order_sudo.order_line:
            return None
        seller_lines = order_sudo.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id.marketplace_seller_id
        )
        if not seller_lines:
            return None
        sellers = seller_lines.mapped('product_id.product_tmpl_id.marketplace_seller_id')
        if len(set(sellers.ids)) > 1:
            request.session['website_sale_cart_warning'] = _(
                'No está permitido comprar productos de varios vendedores en un mismo pedido. '
                'Por favor, separá los pedidos.'
            )
            return request.redirect('/shop/cart')
        return None
