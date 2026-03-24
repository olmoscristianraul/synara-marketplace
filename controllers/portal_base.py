import base64
import logging
from datetime import datetime

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class PhotographerPortalMixin:
    """Shared helpers for photographer portal controllers."""

    def _get_current_photographer(self):
        partner = request.env.user.partner_id
        if not partner or not partner.is_photographer:
            return None
        return partner

    def _ensure_photographer(self):
        partner = self._get_current_photographer()
        if not partner: 
            return None, request.render('fotoapp.gallery_photographer_required', {})
        return partner, None

    def _prepare_cover_image(self, uploaded_file, with_metadata=False):
        if not uploaded_file or not hasattr(uploaded_file, 'read'):
            return (False, 0) if with_metadata else False
        binary = uploaded_file.read()
        if not binary:
            return (False, 0) if with_metadata else False
        payload = base64.b64encode(binary)
        if with_metadata:
            return payload, len(binary)
        return payload

    def _parse_datetime(self, value):
        _logger.debug("Parsing datetime value: %s", value)
        if not value:
            return False
        formats = (
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %I:%M %p",
            "%d/%m/%Y %H:%M",
        )
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return fields.Datetime.to_datetime(value)
        except ValueError:
            return False

    def _get_event_for_partner(self, partner, event_id):
        return request.env['tienda.foto.evento'].sudo().search([
            ('id', '=', event_id),
            ('photographer_id', '=', partner.id),
        ], limit=1)

    def _get_album_for_partner(self, partner, album_id):
        return request.env['tienda.foto.album'].sudo().search([
            ('id', '=', album_id),
            ('photographer_id', '=', partner.id),
        ], limit=1)

    def _get_asset_for_partner(self, partner, asset_id):
        return request.env['tienda.foto.asset'].sudo().search([
            ('id', '=', asset_id),
            ('photographer_id', '=', partner.id),
        ], limit=1)
