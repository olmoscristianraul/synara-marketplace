import base64
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FotoappOrderPortalController(http.Controller):
    def _get_allowed_order(self, order_id):
        order = request.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return None
        user_partner = request.env.user.partner_id.commercial_partner_id
        if order.partner_id.commercial_partner_id != user_partner:
            return None
        return order

    def _prepare_photo_downloads(self, order):
        foto_lines = order.order_line.filtered(lambda line: line.foto_asset_id)
        assets = foto_lines.mapped('foto_asset_id')
        token_map = assets.ensure_download_token()
        downloads = []
        for asset in assets:
            token = token_map.get(asset.id)
            if not token:
                continue
            downloads.append({
                'asset': asset,
                'url': f"/fotoapp/download/{token}",
            })
        return downloads

    def _user_has_asset(self, asset):
        user_partner = request.env.user.partner_id.commercial_partner_id
        allowed_orders = asset.sale_order_line_ids.mapped('order_id').filtered(
            lambda order: order.partner_id.commercial_partner_id == user_partner and order.state in ('sale', 'done')
        )
        return bool(allowed_orders)

    @http.route(['/fotoapp/orders/<int:order_id>/downloads'], type='http', auth='user', website=True)
    def fotoapp_order_downloads(self, order_id, **kwargs):
        order = self._get_allowed_order(order_id)
        if not order:
            return request.not_found()
        downloads = self._prepare_photo_downloads(order)
        return request.render('fotoapp.order_download_page', {
            'order': order,
            'downloads': downloads,
        })

    @http.route(['/fotoapp/orders/<int:order_id>/summary'], type='http', auth='user', website=True)
    def fotoapp_order_summary_redirect(self, order_id, **kwargs):
        order = self._get_allowed_order(order_id)
        if not order:
            return request.not_found()
        request.session['sale_last_order_id'] = order.id
        request.session['sale_last_order_access_token'] = order.access_token
        return request.redirect('/shop/confirmation')

    @http.route(['/fotoapp/download/<string:token>'], type='http', auth='user', website=True)
    def fotoapp_download_photo(self, token, **kwargs):
        asset = request.env['tienda.foto.asset'].sudo().search([('download_token', '=', token)], limit=1)
        if not asset or not asset.imagen_original:
            return request.not_found()
        if not self._user_has_asset(asset):
            return request.not_found()
        binary = base64.b64decode(asset.imagen_original)
        filename = asset.name or f"foto_{asset.id}.jpg"
        headers = [
            ('Content-Type', 'image/jpeg'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ]
        asset.sudo().write({
            'download_count': asset.download_count + 1,
            'last_download_date': fields.Datetime.now(),
        })
        return request.make_response(binary, headers=headers)
