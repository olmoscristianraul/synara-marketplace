# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

class MarketplaceWebsiteSale(WebsiteSale):

    def _shop_get_query_url_kwargs(self, category, search, min_price, max_price, **post):
        """Include custom kwargs in the query URL so they persist during pagination."""
        result = super()._shop_get_query_url_kwargs(category, search, min_price, max_price, **post)
        seller_id = post.get('seller_id')
        if seller_id:
            result['seller_id'] = seller_id
        return result

    def _get_search_domain(self, search, category, attrib_values, search_in_description=True):
        """Add seller filtering to the search domain."""
        domain = super()._get_search_domain(search, category, attrib_values, search_in_description)
        seller_id = request.params.get('seller_id')
        if seller_id:
            try:
                seller_id = int(seller_id)
                domain.append(('marketplace_seller_id', '=', seller_id))
            except (ValueError, TypeError):
                pass
        return domain

    @http.route()
    def shop(self, page=0, category=None, search='', ppg=False, **post):
        """Inject marketplace sellers into the shop context for the sidebar filter."""
        response = super().shop(page, category, search, ppg, **post)
        if response.qcontext:
            # We fetch all marketplace sellers to display in the UI filter
            sellers = request.env['res.partner'].sudo().search([
                ('is_marketplace_seller', '=', True),
            ])
            response.qcontext['marketplace_sellers'] = sellers
            
            selected_seller_id = request.params.get('seller_id')
            try:
                response.qcontext['selected_seller_id'] = int(selected_seller_id) if selected_seller_id else 0
            except (ValueError, TypeError):
                response.qcontext['selected_seller_id'] = 0
                
        return response
