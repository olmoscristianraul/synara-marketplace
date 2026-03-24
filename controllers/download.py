# -*- coding: utf-8 -*-
import base64
import io
import zipfile
from datetime import datetime

from odoo import http, _, fields
from odoo.http import request


class FotoappDownloadController(http.Controller):
    @http.route([
        '/fotoapp/download/<string:token>',
        '/fotoapp/public_download/<string:token>',
    ], type='http', auth='none', website=False, csrf=False, sitemap=False)
    def download_zip(self, token, **kwargs):
        order = request.env['sale.order'].sudo().search([('download_token', '=', token)], limit=1)
        if not order or not order.download_token_expires_at:
            return request.make_response('Link de descarga inválido.', [('Content-Type', 'text/plain')], 404)
        if order.download_token_expires_at < fields.Datetime.now():
            return request.render('fotoapp.download_link_expired', {})
        assets = order.order_line.mapped('foto_asset_id')
        if not assets:
            return request.make_response('No hay fotos asociadas al pedido.', [('Content-Type', 'text/plain')], 404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for asset in assets:
                if not asset.imagen_original:
                    continue
                try:
                    data = base64.b64decode(asset.imagen_original)
                except Exception:
                    continue
                filename = asset.name or f"foto_{asset.id}"
                # Asegura extensión .jpg si no trae una
                if '.' not in filename.lower():
                    filename = f"{filename}.jpg"
                zf.writestr(filename, data)
        buf.seek(0)
        headers = [
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', f"attachment; filename=\"fotos_{order.name or 'pedido'}.zip\""),
        ]
        return request.make_response(buf.getvalue(), headers=headers)
