# -*- coding: utf-8 -*-
import base64

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

SAMPLE_IMAGE = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc```\x00\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@tagged('post_install', '-at_install')
class TestPhotoLifecycle(TransactionCase):
    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('fotoapp.asset_archive_days', 30)
        icp.set_param('fotoapp.asset_delete_days', 15)
        self.photographer = self.env['res.partner'].create({
            'name': 'Test Photographer',
            'is_photographer': True,
        })
        self.category = self.env['tienda.foto.categoria'].create({
            'name': 'Test Category',
            'estado': 'publicado',
            'website_published': True,
        })
        self.event = self.env['tienda.foto.evento'].create({
            'name': 'Test Event',
            'fecha': fields.Datetime.now(),
            'categoria_id': self.category.id,
            'photographer_id': self.photographer.id,
        })

    def _create_photo(self):
        return self.env['tienda.foto.asset'].create({
            'evento_id': self.event.id,
            'precio': 10.0,
            'imagen_original': SAMPLE_IMAGE,
            'name': 'Sample',
        })

    def test_archive_after_inactivity(self):
        asset = self._create_photo()
        inactive_since = fields.Datetime.now() - relativedelta(days=31)
        asset.write({'publicada_por_ultima_vez': inactive_since})

        self.env['tienda.foto.asset'].cron_manage_photo_lifecycle()
        asset.flush()
        asset.refresh()

        self.assertEqual(asset.lifecycle_state, 'archived')

    def test_delete_after_archived(self):
        asset = self._create_photo()
        asset.action_archive()
        archived_since = fields.Datetime.now() - relativedelta(days=16)
        asset.write({'archived_at': archived_since})

        self.env['tienda.foto.asset'].cron_manage_photo_lifecycle()

        self.assertFalse(asset.exists())
