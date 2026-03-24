import logging

from odoo import http, fields
from odoo.http import request
from odoo.tools import html2plaintext

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerEventsController(PhotographerPortalMixin, http.Controller):
    @http.route(['/mi/fotoapp/eventos'], type='http', auth='user', website=True)
    def photographer_event_list(self, estado=None, search=None, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        Event = request.env['tienda.foto.evento'].sudo()
        base_domain = [('photographer_id', '=', partner.id)]
        state_filter = estado if estado in {'borrador', 'publicado', 'archivado'} else False
        if state_filter:
            base_domain.append(('estado', '=', state_filter))
        search_term = (search or '').strip()
        if search_term:
            base_domain += ['|', ('name', 'ilike', search_term), ('categoria_id.name', 'ilike', search_term)]
        events = Event.search(base_domain, order='fecha desc, create_date desc')
        stats = {
            'all': Event.search_count([('photographer_id', '=', partner.id)]),
            'borrador': Event.search_count([('photographer_id', '=', partner.id), ('estado', '=', 'borrador')]),
            'publicado': Event.search_count([('photographer_id', '=', partner.id), ('estado', '=', 'publicado')]),
            'archivado': Event.search_count([('photographer_id', '=', partner.id), ('estado', '=', 'archivado')]),
        }
        values = {
            'partner': partner,
            'events': events,
            'active_menu': 'events',
            'state_filter': state_filter or 'all',
            'search': search_term,
            'stats': stats,
        }
        return request.render('fotoapp.photographer_event_list', values)

    @http.route(['/mi/fotoapp/eventos/nuevo'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def photographer_event_create(self, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        category_domain = [
            ('estado', '=', 'publicado'),
            ('display_on_homepage', '=', True),
            ('website_published', '=', True),
        ]
        categories = request.env['tienda.foto.categoria'].sudo().search(category_domain, order='name')
        countries = request.env['res.country'].sudo().search([], order='name')
        values = {
            'partner': partner,
            'categories': categories,
            'countries': countries,
            'errors': [],
            'active_menu': 'events_new',
            'default': {
                'name': post.get('name', ''),
                'fecha': post.get('fecha', ''),
                'ciudad': post.get('ciudad', ''),
                'estado_provincia': post.get('estado_provincia', ''),
                'pais_id': post.get('pais_id'),
                'categoria_id': post.get('categoria_id'),
                'descripcion': (post.get('descripcion') or '').strip(),
            }
            
        }

        if request.httprequest.method == 'POST':
            name = (post.get('name') or '').strip()
            categoria_id_raw = post.get('categoria_id')
            categoria_id = int(categoria_id_raw) if categoria_id_raw else False
            fecha = self._parse_datetime(post.get('fecha'))
            cover = self._prepare_cover_image(post.get('image_cover'))
            if not name:
                values['errors'].append('El nombre del evento es obligatorio.')
            if not categoria_id:
                values['errors'].append('Debes seleccionar una categoría.')
            elif categoria_id not in categories.ids:
                values['errors'].append('La categoría seleccionada ya no está disponible.')
            if not fecha:
                values['errors'].append('Debes indicar una fecha válida.')
            if not values['errors']:
                vals = {
                    'name': name,
                    'categoria_id': categoria_id,
                    'fecha': fields.Datetime.to_string(fecha),
                    'ciudad': post.get('ciudad'),
                    'estado_provincia': post.get('estado_provincia'),
                    'pais_id': int(post.get('pais_id')) if post.get('pais_id') else False,
                    'descripcion': post.get('descripcion'),
                    'photographer_id': partner.id,
                    'website_published': False,
                    'estado': 'borrador',
                }
                if cover:
                    vals['image_cover'] = cover
                event = request.env['tienda.foto.evento'].sudo().create(vals)
                return request.redirect(f"/mi/fotoapp/evento/{event.id}")
        return request.render('fotoapp.photographer_event_create', values)

    @http.route(['/mi/fotoapp/evento/<int:event_id>'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def photographer_event_detail(self, event_id, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        event = self._get_event_for_partner(partner, event_id)
        if not event:
            return request.not_found()
        category_domain = [
            ('estado', '=', 'publicado'),
            ('display_on_homepage', '=', True),
            ('website_published', '=', True),
        ]
        categories = request.env['tienda.foto.categoria'].sudo().search(category_domain, order='name')
        countries = request.env['res.country'].sudo().search([], order='name')
        albums = request.env['tienda.foto.album'].sudo().search([
            ('event_id', '=', event.id)
        ], order='create_date desc')
        album_error = request.session.pop('fotoapp_album_error', False)
        values = {
            'partner': partner,
            'event': event,
            'albums': albums,
            'categories': categories,
            'countries': countries,
            'errors': [],
            'album_error': album_error,
            'active_menu': 'events',
        }

        if request.httprequest.method == 'POST':
            action = post.get('action') or 'update_event'
            redirect_url = f"/mi/fotoapp/evento/{event.id}"
            if action == 'update_event':
                fecha = self._parse_datetime(post.get('fecha'))
                categoria_id_raw = post.get('categoria_id')
                categoria_id = int(categoria_id_raw) if categoria_id_raw else False
                if not categoria_id:
                    values['errors'].append('Selecciona una categoría.')
                elif categoria_id not in categories.ids:
                    values['errors'].append('La categoría seleccionada ya no está disponible.')
                if not fecha:
                    values['errors'].append('Ingresa una fecha válida.')
                values['event_description_plain'] = post.get('descripcion', '').strip()
                if not values['errors']:
                    update_vals = {
                        'name': (post.get('name') or '').strip(),
                        'fecha': fields.Datetime.to_string(fecha),
                        'ciudad': post.get('ciudad'),
                        'estado_provincia': post.get('estado_provincia'),
                        'pais_id': int(post.get('pais_id')) if post.get('pais_id') else False,
                        'descripcion': post.get('descripcion'),
                        'categoria_id': categoria_id,
                    }
                    cover = self._prepare_cover_image(post.get('image_cover'))
                    if cover:
                        update_vals['image_cover'] = cover
                    event.sudo().write(update_vals)
                else:
                    return request.render('fotoapp.photographer_event_detail', values)
            elif action == 'publish_event':
                event.sudo().action_publicar()
            elif action == 'archive_event':
                event.sudo().action_archivar()
            elif action == 'delete_event':
                event.sudo().unlink()
                return request.redirect('/mi/fotoapp')
            return request.redirect(redirect_url)

        return request.render('fotoapp.photographer_event_detail', values)

    @http.route(['/mi/fotoapp/evento/<int:event_id>/album/nuevo'], type='http', auth='user', website=True, methods=['POST'])
    def photographer_album_create(self, event_id, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        event = self._get_event_for_partner(partner, event_id)
        if not event:
            return request.not_found()
        name = (post.get('name') or '').strip()
        if not name:
            request.session['fotoapp_album_error'] = 'El nombre del álbum es obligatorio.'
        else:
            vals = {
                'name': name,
                'event_id': event.id,
                'partner_id': post.get('partner_id') or False,
                'customer_email': post.get('customer_email'),
            }
            request.env['tienda.foto.album'].sudo().create(vals)
        return request.redirect(f"/mi/fotoapp/evento/{event.id}")
