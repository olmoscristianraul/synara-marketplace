import requests
from dateutil.relativedelta import relativedelta

# -*- coding: utf-8 -*-
from odoo import fields, models, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_photographer = fields.Boolean(string='Es fotógrafo', default=True, tracking=True)
    photographer_bio = fields.Text(string='Biografía corta')
    portfolio_url = fields.Char(string='URL de portafolio')
    photographer_first_name = fields.Char(string='Nombre artístico')
    photographer_last_name = fields.Char(string='Apellido artístico')
    photo_reservoir_url = fields.Char(string='URL de reservorio de imágenes')
    phone_whatsapp = fields.Char(string='WhatsApp de contacto')
    instagram_account = fields.Char(string='Cuenta de Instagram')
    photographer_code = fields.Char(string='Código público', copy=False)
    onboarding_stage = fields.Selection([
        ('lead', 'Lead'),
        ('invited', 'Invitado'),
        ('pending_setup', 'Pendiente de setup'),
        ('ready', 'Listo para vender'),
    ], string='Etapa de onboarding', default='lead', tracking=True)
    watermark_image = fields.Image(
        string='Marca de agua',
        max_width=1024,
        max_height=1024,
        attachment=True,
        help='Imagen que se aplicará como marca de agua a las fotos de este fotógrafo.'
    )
    watermark_opacity = fields.Integer(
        string='Opacidad de marca de agua',
        default=60,
        help='Opacidad expresada en porcentaje (0-100).'
    )
    watermark_scale = fields.Float(
        string='Escala de marca de agua',
        default=0.3,
        help='Escala relativa frente a la imagen final (0-1).'
    )
    foto_event_ids = fields.One2many(
        comodel_name='tienda.foto.evento',
        inverse_name='photographer_id',
        string='Eventos fotográficos'
    )
    album_ids = fields.One2many(
        comodel_name='tienda.foto.album',
        inverse_name='photographer_id',
        string='Álbumes creados'
    )
    asset_ids = fields.One2many(
        comodel_name='tienda.foto.asset',
        inverse_name='photographer_id',
        string='Fotos subidas'
    )
    plan_subscription_ids = fields.One2many(
        comodel_name='sale.subscription',
        inverse_name='partner_id',
        string='Suscripciones',
        domain="[('fotoapp_is_photographer_plan', '=', True)]"
    )
    active_plan_subscription_id = fields.Many2one(
        comodel_name='sale.subscription',
        compute='_compute_active_subscription',
        string='Suscripción vigente',
        store=True,
        domain="[('fotoapp_is_photographer_plan', '=', True)]"
    )
    plan_id = fields.Many2one(
        comodel_name='fotoapp.plan',
        compute='_compute_active_subscription',
        string='Plan vigente',
        store=True
    )
    event_count = fields.Integer(string='Eventos publicados', compute='_compute_metrics', store=True)
    album_count = fields.Integer(string='Álbumes', compute='_compute_metrics', store=True)
    asset_count = fields.Integer(string='Fotos', compute='_compute_metrics', store=True)
    total_storage_bytes = fields.Integer(string='Almacenamiento usado', compute='_compute_metrics', store=True)
    company_currency_id = fields.Many2one('res.currency', string='Moneda compañía', related='company_id.currency_id', store=True, readonly=True)
    gross_sales_total = fields.Monetary(string='Ventas generadas', currency_field='company_currency_id', compute='_compute_metrics', store=True)
    statement_ids = fields.One2many('fotoapp.photographer.statement', 'partner_id', string='Liquidaciones')
    payout_preference = fields.Selection([
        ('mercadopago', 'Mercado Pago'),
        ('bank_transfer', 'Transferencia bancaria'),
        ('cash', 'Pago manual'),
    ], string='Método de pago preferido', default='mercadopago')
    payout_account = fields.Char(string='Cuenta de pago / CBU / Alias')
    bank_name_or_wallet = fields.Char(string='Banco o billetera')
    bank_alias = fields.Char(string='Alias bancario')
    cbu_cvu = fields.Char(string='CBU / CVU')
    fotoapp_next_photo_identifier = fields.Integer(
        string='Próximo identificador de foto',
        default=0,
        copy=False,
        help='Mantiene la secuencia interna para numerar fotos automáticamente.'
    )
    mp_user_id = fields.Char(string='MP User ID', copy=False, groups='base.group_system')
    mp_access_token = fields.Char(string='MP Access Token', groups='base.group_system')
    mp_refresh_token = fields.Char(string='MP Refresh Token', groups='base.group_system')
    mp_token_expires_at = fields.Datetime(string='MP Token expira', groups='base.group_system')
    mp_account_status = fields.Selection([
        ('not_connected', 'No conectado'),
        ('connected', 'Conectado'),
        ('error', 'Con error'),
    ], string='Estado Mercado Pago', default='not_connected', tracking=True)
    mp_account_email = fields.Char(string='Email Mercado Pago', groups='base.group_system')
    afip_cuit = fields.Char(string='CUIT / ID fiscal')
    afip_tax_condition = fields.Selection([
        ('ri', 'Responsable Inscripto'),
        ('mono', 'Monotributista'),
        ('exempt', 'Exento'),
        ('cf', 'Consumidor Final'),
    ], string='Condición frente a IVA', default='cf')
    afip_fiscal_address = fields.Char(string='Domicilio fiscal')
    afip_preferred_pos = fields.Char(string='Punto de venta preferido')

    def get_watermark_payload(self):
        self.ensure_one()
        return {
            'image': self.watermark_image,
            'opacity': min(max(self.watermark_opacity, 0), 100),
            'scale': min(max(self.watermark_scale, 0.05), 1.0),
        }

    @api.depends('plan_subscription_ids.state', 'plan_subscription_ids.plan_id')
    def _compute_active_subscription(self):
        active_states = {'trial', 'active', 'grace'}
        for partner in self:
            active_sub = partner.plan_subscription_ids.filtered(lambda sub: sub.state in active_states)[:1]
            partner.active_plan_subscription_id = active_sub.id if active_sub else False
            partner.plan_id = active_sub.plan_id.id if active_sub else False

    @api.depends('foto_event_ids', 'album_ids', 'asset_ids', 'asset_ids.file_size_bytes', 'asset_ids.sale_total_amount')
    def _compute_metrics(self):
        for partner in self:
            partner.event_count = len(partner.foto_event_ids)
            partner.album_count = len(partner.album_ids)
            partner.asset_count = len(partner.asset_ids)
            partner.total_storage_bytes = sum(partner.asset_ids.mapped('file_size_bytes'))
            partner.gross_sales_total = sum(partner.asset_ids.mapped('sale_total_amount'))

    def write(self, vals):
        watermark_fields = {'watermark_image', 'watermark_opacity', 'watermark_scale'}
        should_regenerate = bool(watermark_fields.intersection(vals.keys()))
        result = super().write(vals)
        if should_regenerate:
            self._regenerate_published_assets_watermark()
        if vals.get('is_photographer'):
            self.filtered('is_photographer')._ensure_default_photo_plan()
        return result

    def _regenerate_published_assets_watermark(self):
        Asset = self.env['tienda.foto.asset'].sudo()
        for partner in self:
            assets = Asset.search([
                ('photographer_id', '=', partner.id),
                ('lifecycle_state', '=', 'published'),
            ])
            if assets:
                assets.regenerate_watermark()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('is_photographer', True)
        partners = super().create(vals_list)
        partners.filtered('is_photographer')._ensure_default_photo_plan()
        return partners

    def _ensure_default_photo_plan(self): # Activa el plan freemium si el fotógrafo no tiene una suscripción activa
        SaleSubscription = self.env['sale.subscription']
        freemium_plan = self._get_fotoapp_plan('FREEMIUM')
        if not freemium_plan:
            return
        active_states = {'trial', 'active', 'grace'}
        for partner in self: # para cada fotógrafo sin suscripción activa se le asigna el plan freemium 
            existing = SaleSubscription.search([
                ('partner_id', '=', partner.id),
                ('state', 'in', list(active_states)),
                ('fotoapp_is_photographer_plan', '=', True),
            ], limit=1)
            if existing:
                continue
            partner._activate_photo_plan(freemium_plan)

    def _get_fotoapp_plan(self, code):
        Plan = self.env['fotoapp.plan']
        plan = Plan.search([('code', '=', code)], limit=1)
        return plan

    def _activate_photo_plan(self, plan, order=None): # Crea una suscripción para el plan indicado, vinculada al pedido si se proporciona, y la activa inmediatamente
        SaleSubscription = self.env['sale.subscription']
        today = fields.Date.context_today(self)
        note = order and f"Activado desde pedido #{order.name}" or False
        for partner in self:
            SaleSubscription.fotoapp_create_subscription(partner, plan, notes=note)

    def _mp_refresh_token_if_needed(self, force=False):
        IrConfig = self.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('fotoapp.mp_client_id')
        client_secret = IrConfig.get_param('fotoapp.mp_client_secret')
        for partner in self:
            if not partner.mp_refresh_token or not client_id or not client_secret:
                continue
            if not force and partner.mp_token_expires_at and partner.mp_token_expires_at > fields.Datetime.now():
                continue
            payload = {
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': partner.mp_refresh_token,
            }
            response = requests.post('https://api.mercadopago.com/oauth/token', data=payload, timeout=30)
            if response.ok:
                data = response.json()
                expires_in = data.get('expires_in') or 0
                partner.sudo().write({
                    'mp_access_token': data.get('access_token'),
                    'mp_refresh_token': data.get('refresh_token') or partner.mp_refresh_token,
                    'mp_token_expires_at': fields.Datetime.now() + relativedelta(seconds=max(expires_in - 60, 0)),
                    'mp_account_status': 'connected',
                })
            else:
                partner.sudo().write({'mp_account_status': 'error'})
