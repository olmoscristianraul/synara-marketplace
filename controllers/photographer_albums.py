import logging
import os

from odoo import http, _
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerAlbumsController(PhotographerPortalMixin, http.Controller):
    @http.route(['/mi/fotoapp/album/<int:album_id>'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def photographer_album_detail(self, album_id, **post):
        partner, denied = self._ensure_photographer() # acá nos aseguramos de que sea fotógrafo
        if not partner:
            return denied
        album = self._get_album_for_partner(partner, album_id)
        if not album:
            return request.not_found()
        if request.httprequest.method == 'POST' and (post.get('action') == 'delete_album'):
            event_id = album.event_id.id
            album.sudo().unlink()
            return request.redirect(f"/mi/fotoapp/evento/{event_id}")
        success_message = request.session.pop('fotoapp_album_success', False)
        values = {
            'partner': partner,
            'album': album,
            'photos': album.asset_ids,
            'errors': [],
            'active_menu': 'events',
            'album_success': success_message,
        }
        if request.httprequest.method == 'POST':
            action = post.get('action')
            should_redirect = True
            if action == 'update_album':
                is_private = 'is_private' in post
                # Treat privacy switch as visibility toggle for homepage listings
                next_state = 'draft' if is_private else 'published' # aca decimos que si es privado va a borrador, sino publicado
                album.sudo().write({
                    'name': (post.get('name') or '').strip(),
                    'is_private': is_private,
                    'download_limit': int(post.get('download_limit') or 0),
                    'state': next_state,
                })
            elif action == 'publish_album':
                album.sudo().action_publish()
            elif action == 'archive_album':
                album.sudo().action_archive()
            elif action == 'upload_photo':
                files = request.httprequest.files.getlist('image_files')
                price_raw = post.get('price')
                try:
                    precio = float(price_raw or 0.0)
                except ValueError:
                    precio = 0.0
                    values['errors'].append('El precio debe ser numérico.')
                if not files:
                    values['errors'].append('Seleccioná al menos una imagen para subir.')
                if not values['errors']:
                    Asset = request.env['tienda.foto.asset'].sudo()
                    created = 0
                    skipped = 0
                    subscription = album.event_id.plan_subscription_id or partner.active_plan_subscription_id
                    limit_reached = False
                    for upload in files:
                        image, size_bytes = self._prepare_cover_image(upload, with_metadata=True)
                        if not image:
                            skipped += 1
                            continue
                        if subscription and size_bytes and not subscription.can_store_bytes(size_bytes):
                            limit_mb = subscription.plan_id.storage_limit_mb or int((subscription.plan_id.storage_limit_gb or 0.0) * 1024)
                            values['errors'].append(_(
                                'Alcanzaste el límite de almacenamiento de tu plan (%s MB). Eliminá fotos o actualizá tu plan para seguir subiendo.'
                            ) % limit_mb)
                            limit_reached = True
                            break
                        file_name = self._extract_upload_file_name(upload)
                        asset_vals = {
                            'evento_id': album.event_id.id,
                            'precio': precio,
                            'imagen_original': image,
                            'name': file_name,
                            'album_ids': [(4, album.id)],
                            'file_size_bytes': size_bytes,
                        }
                        Asset.create(asset_vals)
                        created += 1
                    if limit_reached and not created:
                        should_redirect = False
                    elif not created:
                        values['errors'].append('No se pudo procesar ninguna imagen. Verificá los archivos seleccionados e intentá nuevamente.')
                        should_redirect = False
                    else:
                        if skipped:
                            request.session['fotoapp_album_success'] = f"Se subieron {created} fotos correctamente. {skipped} archivos fueron descartados por estar vacíos o corruptos."
                        else:
                            request.session['fotoapp_album_success'] = f"Se subieron {created} fotos correctamente."
                else:
                    should_redirect = False
            elif action in {'archive_photo', 'publish_photo'}:
                photo_id = int(post.get('photo_id')) if post.get('photo_id') else False
                photo = self._get_asset_for_partner(partner, photo_id)
                if photo:
                    if action == 'archive_photo':
                        photo.sudo().action_archive()
                    else:
                        photo.sudo().action_publish()
            elif action == 'update_photo_price':
                photo_id = int(post.get('photo_id')) if post.get('photo_id') else False
                photo = self._get_asset_for_partner(partner, photo_id)
                price_raw = post.get('photo_price')
                try:
                    new_price = float(price_raw or 0.0)
                except (TypeError, ValueError):
                    new_price = 0.0
                    values['errors'].append('El precio debe ser numérico.')
                if not photo:
                    values['errors'].append('No se pudo encontrar la foto para actualizar el precio.')
                elif new_price <= 0:
                    values['errors'].append('El precio debe ser mayor a cero.')
                else:
                    photo.sudo().write({'precio': new_price})
                    request.session['fotoapp_album_success'] = 'Precio actualizado correctamente.'
                if values['errors']:
                    should_redirect = False
            elif action == 'update_photo_name':
                photo_id = int(post.get('photo_id')) if post.get('photo_id') else False
                photo = self._get_asset_for_partner(partner, photo_id)
                new_name = (post.get('photo_name') or '').strip()
                if not photo:
                    values['errors'].append('No se encontró la foto para actualizar el nombre.')
                elif not new_name:
                    values['errors'].append('El nombre no puede estar vacío.')
                else:
                    photo.sudo().write({'name': new_name})
                    request.session['fotoapp_album_success'] = 'Nombre actualizado correctamente.'
                if values['errors']:
                    should_redirect = False
            if should_redirect:
                return request.redirect(f"/mi/fotoapp/album/{album.id}")
            values['photos'] = album.asset_ids
        return request.render('fotoapp.photographer_album_detail', values)

    def _extract_upload_file_name(self, upload):
        filename = getattr(upload, 'filename', '') or ''
        if not filename:
            return False
        basename = os.path.basename(filename)
        cleaned = basename.strip()
        return cleaned[:120] if cleaned else False
