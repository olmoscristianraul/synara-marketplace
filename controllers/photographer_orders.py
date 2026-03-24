import logging

from odoo import http
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerOrdersController(PhotographerPortalMixin, http.Controller):
    @http.route(['/mi/fotoapp/compras'], type='http', auth='user', website=True)
    def photographer_purchases(self, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        SaleOrder = request.env['sale.order'].sudo()
        orders = SaleOrder.search([
            ('partner_id', '=', request.env.user.partner_id.id),
            ('state', 'in', ['sale', 'done'])
        ], order='date_order desc', limit=50)
        values = {
            'partner': partner,
            'orders': orders,
            'active_menu': 'purchases',
        }
        return request.render('fotoapp.photographer_purchases', values)
