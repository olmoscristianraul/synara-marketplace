# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models, _
from odoo.exceptions import ValidationError

FREEMIUM_CODE = 'FREEMIUM'
SUBSCRIPTION_BLUEPRINT_XMLID = 'fotoapp.fotoapp_subscription_template'


class FotoappPlan(models.Model):
    _name = 'fotoapp.plan'
    _description = 'Planes de suscripción FotoApp'
    _order = 'sequence, monthly_fee desc, id'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True, copy=False)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(string='Descripción interna')
    website_description = fields.Html(string='Descripción para la web')
    billing_interval = fields.Selection([
        ('monthly', 'Mensual'),
        ('quarterly', 'Trimestral'),
        ('yearly', 'Anual'),
    ], string='Intervalo de facturación', default='monthly')
    monthly_fee = fields.Monetary(string='Precio mensual', required=True)
    yearly_fee = fields.Monetary(string='Precio anual')
    setup_fee = fields.Monetary(string='Cargo inicial')
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Moneda',
        required=True,
        default=lambda self: self._default_currency()
    )
    photo_limit = fields.Integer(string='Límite de fotos', help='0 significa ilimitado.')
    album_limit = fields.Integer(string='Límite de álbumes', help='0 significa ilimitado.')
    event_limit = fields.Integer(string='Límite de eventos', help='0 significa ilimitado.')
    storage_limit_gb = fields.Float(string='[Deprecated] Límite almacen (GB)', help='Usar storage_limit_mb', default=0.0)
    storage_limit_mb = fields.Integer(string='Límite de almacenamiento (MB)', help='0 significa ilimitado.')
    featured_event_limit = fields.Integer(string='Eventos destacados incluidos')
    download_bundle_limit = fields.Integer(string='Descargas full-res incluidas', help='0 significa ilimitado.')
    autopublish_enabled = fields.Boolean(string='Autopublicación disponible', default=True)
    proofing_enabled = fields.Boolean(string='Herramientas de proofing', default=True)
    private_gallery_enabled = fields.Boolean(string='Galería privada', default=True)
    advanced_watermark_enabled = fields.Boolean(string='Marca de agua avanzada', default=True)
    api_access_enabled = fields.Boolean(string='API / Integraciones', default=False)
    commission_percent = fields.Float(string='Comisión estándar (%)', default=22.0)
    transaction_fee_percent = fields.Float(string='Fee por transacción (%)', default=3.0)
    payout_delay_days = fields.Integer(string='Días de espera para pago', default=7)
    mercadopago_plan_code = fields.Char(string='Código plan Mercado Pago')
    notes = fields.Text(string='Notas internas')
    subscription_ids = fields.One2many(
        'sale.subscription',
        'plan_id',
        string='Suscripciones',
        domain="[('fotoapp_is_photographer_plan', '=', True)]"
    )
    subscription_count = fields.Integer(string='Suscripciones activas', compute='_compute_subscription_count')
    product_template_id = fields.Many2one('product.template', string='Producto asociado', copy=False)
    product_variant_id = fields.Many2one('product.product', string='Variante ecommerce', copy=False)
    subscription_template_id = fields.Many2one(
        'sale.subscription.template',
        string='Plantilla de suscripción OCA',
        help='Plantilla usada al crear suscripciones OCA vinculadas a este plan.'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company.id,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Diario de facturación',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_subscription_journal_id(),
        help='Diario de ventas que usará la suscripción al generar facturas.'
    )
    income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de ingresos',
        domain="[('internal_group', '=', 'income')]",
        default=lambda self: self._default_income_account_id(),
        help='Cuenta de ingresos que forzará el producto asociado al plan.'
    )
    tax_ids = fields.Many2many(
        'account.tax',
        'fotoapp_plan_tax_rel',
        'plan_id',
        'tax_id',
        string='Impuestos de venta',
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_tax_ids(),
    )
    is_freemium = fields.Boolean(
        string='Plan Freemium',
        help='Marca este plan como Freemium para evitar generación de deudas.',
        default=False,
    )
    cover_image = fields.Image(
        string='Portada para website',
        max_width=1920,
        max_height=1080,
        help='Imagen utilizada en la landing pública de planes.'
    )
    website_published = fields.Boolean(string='Publicado en website', default=True)

    _sql_constraints = [
        ('plan_code_unique', 'unique(code)', 'El código del plan debe ser único.'),
    ]

    def _default_currency(self):
        ars = self.env.ref('base.ARS', raise_if_not_found=False)
        if not ars:
            ars = self.env['res.currency'].search([('name', '=', 'ARS')], limit=1)
        if ars and not ars.active:
            ars.sudo().write({'active': True})
        return ars.id if ars else self.env.company.currency_id.id

    @api.depends('subscription_ids.state')
    def _compute_subscription_count(self):
        active_states = {'trial', 'active', 'grace'}
        for plan in self:
            plan.subscription_count = len(plan.subscription_ids.filtered(lambda sub: sub.state in active_states))

    @api.constrains('commission_percent', 'transaction_fee_percent')
    def _check_percentages(self):
        for plan in self:
            if plan.commission_percent < 0 or plan.transaction_fee_percent < 0:
                raise ValidationError(_('Los porcentajes no pueden ser negativos.'))
            if plan.commission_percent > 100 or plan.transaction_fee_percent > 100:
                raise ValidationError(_('Los porcentajes no pueden superar 100%.'))

    @api.constrains('photo_limit', 'album_limit', 'event_limit', 'storage_limit_gb')
    def _check_positive_limits(self):
        for plan in self:
            numeric_limits = [plan.photo_limit, plan.album_limit, plan.event_limit]
            if any(limit < 0 for limit in numeric_limits if limit is not None):
                raise ValidationError(_('Los límites no pueden ser negativos.'))
            if plan.storage_limit_gb and plan.storage_limit_gb < 0:
                raise ValidationError(_('El almacenamiento no puede ser negativo.'))

    def get_limit_payload(self):
        self.ensure_one()
        return {
            'photo': self.photo_limit,
            'album': self.album_limit,
            'event': self.event_limit,
            'storage_mb': self.storage_limit_mb or int((self.storage_limit_gb or 0.0) * 1024),
            'featured': self.featured_event_limit,
            'download_bundle': self.download_bundle_limit,
        }

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._ensure_plan_products()
        return plans

    def write(self, vals):
        res = super().write(vals)
        self._ensure_plan_products()
        return res

    def _ensure_plan_products(self):
        for plan in self:
            plan._sync_plan_product()
            plan._sync_plan_template()

    def _sync_plan_product(self):
        self.ensure_one()
        ProductTemplate = self.env['product.template'].sudo()
        product_vals = self._prepare_plan_product_vals()
        if not self.product_template_id: # Crear el producto si no existe
            template = ProductTemplate.create(product_vals)
            self.product_template_id = template.id
            self.product_variant_id = template.product_variant_id.id
            template.fotoapp_plan_id = self.id
        else: # Actualizar el producto existente
            self.product_template_id.write(product_vals)
            if self.product_variant_id:
                self.product_variant_id.write({'list_price': self.monthly_fee})
            self.product_template_id.fotoapp_plan_id = self.id

    def _prepare_plan_product_vals(self):
        self.ensure_one()
        ProductTemplate = self.env['product.template']
        tax_ids = self._get_plan_tax_ids()
        tax_commands = [(6, 0, tax_ids)] if tax_ids else [(5, 0, 0)]
        vals = {
            'name': self.name,
            'sale_ok': True, #sirve para vender el producto en el ecommerce
            'purchase_ok': False, 
            'invoice_policy': 'order', #facturar al hacer el pedido
            'list_price': self.monthly_fee,
            'description_sale': _('%s · Plan mensual para fotógrafos') % self.name,
            'fotoapp_plan_id': self.id,
            'website_published': True,
            'company_id': self.company_id.id,
            'subscribable': True,
            'subscription_template_id': self.subscription_template_id.id if self.subscription_template_id else False,
            'taxes_id': tax_commands,
            'property_account_income_id': self.income_account_id.id if self.income_account_id else False,
        }
        if 'detailed_type' in ProductTemplate._fields:
            vals['detailed_type'] = 'service'
        else:
            vals['type'] = 'service'
        return vals

    def _sync_plan_template(self):
        self.ensure_one()
        Template = self.env['sale.subscription.template'].sudo()
        blueprint = self._get_blueprint_template()
        template = self.subscription_template_id
        requires_clone = template and blueprint and template.id == blueprint.id
        if not template or requires_clone:
            template = Template.create(self._prepare_subscription_template_vals())
            template.fotoapp_plan_id = self.id
            self.subscription_template_id = template.id
        else:
            template.write(self._prepare_subscription_template_vals())
            template.fotoapp_plan_id = self.id
        if self.product_template_id:
            self.product_template_id.sudo().write({
                'subscription_template_id': template.id,
                'subscribable': True,
            })

    def _get_subscription_template(self):
        self.ensure_one()
        template = self.subscription_template_id
        if template:
            return template
        return self._get_blueprint_template()

    def is_freemium_plan(self):
        self.ensure_one()
        if self.is_freemium:
            return True
        return self.code == FREEMIUM_CODE

    def _prepare_subscription_template_vals(self):
        self.ensure_one()
        interval_type, interval_count = self._get_subscription_interval_payload()
        return {
            'name': _('Suscripción %(plan)s (%(company)s)') % {
                'plan': self.name,
                'company': self.company_id.display_name,
            },
            'code': self.code,
            'description': self.description or '',
            'recurring_rule_type': interval_type,
            'recurring_interval': interval_count,
            'recurring_rule_boundary': 'unlimited',
            'recurring_rule_count': interval_count,
            'invoicing_mode': 'invoice',
        }

    def _get_subscription_interval_payload(self):
        self.ensure_one()
        mapping = {
            'monthly': ('months', 1),
            'quarterly': ('months', 3),
            'yearly': ('months', 12),
        }
        return mapping.get(self.billing_interval or 'monthly', ('months', 1))

    def _get_blueprint_template(self):
        return self.env.ref(SUBSCRIPTION_BLUEPRINT_XMLID, raise_if_not_found=False)

    @api.model
    def _default_subscription_journal_id(self):
        company = self.env.company
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id),
        ], limit=1)
        return journal.id if journal else False

    @api.model
    def _default_income_account_id(self):
        company = self.env.company
        account = getattr(company, 'account_sale_income_account_id', False)
        return account.id if account else False

    @api.model
    def _default_tax_ids(self):
        company = self.env.company
        tax = getattr(company, 'account_sale_tax_id', False)
        return tax.ids if tax else []

    def _get_plan_tax_ids(self):
        self.ensure_one()
        if self.tax_ids:
            return self.tax_ids.ids
        company = self.company_id or self.env.company
        tax = getattr(company, 'account_sale_tax_id', False)
        return tax.ids if tax else []

    def _get_billing_relativedelta(self):
        _, interval = self._get_subscription_interval_payload()
        return relativedelta(months=interval)

    def _prepare_subscription_line_commands(self):
        self.ensure_one()
        product = self.product_variant_id
        if not product:
            return []
        return [Command.create({
            'product_id': product.id,
            'product_uom_qty': 1.0,
        })]
