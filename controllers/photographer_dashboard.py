import logging

from odoo import http
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerDashboardController(PhotographerPortalMixin, http.Controller):
    @http.route(['/mi/fotoapp', '/mi/fotoapp/dashboard'], type='http', auth='user', website=True)
    def photographer_dashboard(self, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        Event = request.env['tienda.foto.evento'].sudo()
        Album = request.env['tienda.foto.album'].sudo()
        Asset = request.env['tienda.foto.asset'].sudo()
        events = Event.search([
            ('photographer_id', '=', partner.id)
        ], order='create_date desc', limit=10)
        stats = {
            'total_events': Event.search_count([('photographer_id', '=', partner.id)]),
            'published_events': Event.search_count([('photographer_id', '=', partner.id), ('estado', '=', 'publicado')]),
            'albums': Album.search_count([('photographer_id', '=', partner.id)]),
            'photos': Asset.search_count([('photographer_id', '=', partner.id)]),
        }
        storage_bytes = partner.total_storage_bytes or 0
        storage_mb = storage_bytes / (1024 * 1024) if storage_bytes else 0.0
        plan = partner.plan_id
        storage_limit_mb = 0
        if plan:
            storage_limit_mb = plan.storage_limit_mb or int((plan.storage_limit_gb or 0.0) * 1024)
        stats.update({
            'storage_mb': round(storage_mb, 2),
            'storage_limit_mb': storage_limit_mb,
            'commission_percent': plan.commission_percent if plan else 0.0,
            'plan_name': plan.name if plan else '',
        })
        values = {
            'partner': partner,
            'events': events,
            'stats': stats,
            'active_menu': 'dashboard',
        }
        return request.render('fotoapp.photographer_dashboard', values)
