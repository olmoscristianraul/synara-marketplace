import logging

from odoo import http
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerAssetsController(PhotographerPortalMixin, http.Controller):
    @http.route(['/mi/fotoapp/fotos/archivadas'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def photographer_archived_photos(self, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        Asset = request.env['tienda.foto.asset'].sudo()
        domain = [
            ('photographer_id', '=', partner.id),
            ('lifecycle_state', '=', 'archived')
        ]
        search_term = (request.params.get('search') or '').strip()
        if search_term:
            domain += ['|', '|',
                ('numero_dorsal', 'ilike', search_term),
                ('evento_id.name', 'ilike', search_term),
                ('album_ids.name', 'ilike', search_term)
            ]
        photos = Asset.search(domain, order='write_date desc')
        if request.httprequest.method == 'POST':
            action = post.get('action')
            photo = self._get_asset_for_partner(partner, int(post.get('photo_id')))
            if photo:
                if action == 'restore':
                    photo.sudo().action_publish()
                elif action == 'delete':
                    photo.sudo().unlink()
            return request.redirect('/mi/fotoapp/fotos/archivadas')
        values = {'partner': partner, 'photos': photos, 'active_menu': 'archived', 'search': search_term}
        return request.render('fotoapp.photographer_archived_photos', values)
